from copy import deepcopy
from contextlib import ExitStack
import json
from datetime import date
import unittest
from unittest.mock import Mock, patch
import frappe
from mat_reco.material_reconfiguration.services import mcp_compensation_service as api
from mat_reco.material_reconfiguration.services import mcp_action_preview as actions
from mat_reco.material_reconfiguration.services import repack_draft_service as repack
from mat_reco.material_reconfiguration.tests.test_mcp_compensation_geometry import sheet, need


class Document(frappe._dict):
    def __init__(self, tree=None):
        super().__init__(name="MCP",docstatus=0,mcp_mode="Retour Terrain",company="CO",source_item="RAW",
            source_warehouse="WH",target_warehouse="OUT",kerf_mm=0,allow_rotation=1,
            result_json="{}",effective_result_json=json.dumps(tree or {"nodes":[sheet()]}),
            material_plan_incidents=[],mcp_stock_candidate=[],simulation_lines=[],modified="v1")
        self.flags=frappe._dict()
        self.previous=None
    def as_dict(self):
        return {k:v for k,v in self.items() if k not in ("previous","flags") and not callable(v)}
    def get_doc_before_save(self):return self.previous
    def is_new(self):return False
    def set(self,key,value):self[key]=value
    def append(self,key,value):
        row=frappe._dict(value);self.setdefault(key,[]).append(row);return row
    def _build_summary_from_tree(self,tree):return {"planned_piece_count":sum(c["node_type"]=="finished_good" for n in tree["nodes"] for c in n["children"])}
    def _apply_summary_to_fields(self,summary):self.summary_json=json.dumps(summary)


def fail(message,*args,**kwargs):raise frappe.ValidationError(message)


class TestPersistence(unittest.TestCase):
    def setUp(self):
        self.throw=patch.object(frappe,"throw",side_effect=fail);self.throw.start();self.addCleanup(self.throw.stop)
    def compensated(self):
        result=api.propose_compensation({"nodes":[sheet()]},[need()],seed="v1")
        tree=result["effective_tree"];tree["compensation_events"]=[{"id":"event","placements":result["placements"]}]
        doc=Document(tree);doc.previous=Document(tree);return doc,result

    def test_h_reload_preserves_geometry_and_journal(self):
        doc,result=self.compensated();before=json.loads(doc.effective_result_json)
        with patch.object(api,"submitted_receipts",return_value=(set(),set())):
            self.assertTrue(api.preserve_compensated_plan(doc))
            saved=json.loads(doc.effective_result_json)
            self.assertEqual(saved["nodes"],before["nodes"])
            self.assertEqual(saved["compensation_events"],before["compensation_events"])
            reloaded=Document(saved);reloaded.previous=Document(saved)
            api.preserve_compensated_plan(reloaded)
            self.assertEqual(json.loads(reloaded.effective_result_json),saved)
        self.assertTrue(doc.effective_mcp_sheets)

    def test_e_new_destroy_and_second_compensation_have_distinct_identity(self):
        doc,result=self.compensated();replacement=result["placements"][0]
        doc.material_plan_incidents.append(frappe._dict(plan_node_id=replacement["id"],incident_action="Destroy",is_active=1))
        with patch.object(api,"submitted_receipts",return_value=(set(),set())):api.preserve_compensated_plan(doc)
        tree=json.loads(doc.effective_result_json)
        needs=api.reconcile_requirements([need()],tree["nodes"],doc.material_plan_incidents)
        self.assertEqual(needs["summary"]["to_compensate"],1)
        # A different future source can cover the failed replacement without reuse.
        tree["nodes"].append({**sheet(),"id":"SN2","serial_no":"SN2"})
        second=api.propose_compensation(tree,needs["compensation_requirements"],seed="v2")
        self.assertNotEqual(second["placements"][0]["id"],replacement["id"])
        self.assertIn(replacement["id"],second["placements"][0]["broken_operation_ids"])
        self.assertEqual(tree["compensation_events"],[{"id":"event","placements":result["placements"]}])

    def test_cannot_change_confirmed_geometry_or_remove_incidents(self):
        doc,_=self.compensated();doc.effective_result_json="{}"
        with self.assertRaises(frappe.ValidationError):api.preserve_compensated_plan(doc)
        doc,_=self.compensated();doc.previous.material_plan_incidents=[frappe._dict(plan_node_id="x",is_active=1)]
        with self.assertRaises(frappe.ValidationError):api.preserve_compensated_plan(doc)

    def test_submitted_output_cannot_be_destroyed(self):
        doc,result=self.compensated();replacement=result["placements"][0]
        doc.material_plan_incidents.append(frappe._dict(plan_node_id=replacement["id"],incident_action="Destroy",is_active=1))
        with patch.object(api,"submitted_receipts",return_value=({replacement["id"]},set())):
            with self.assertRaises(frappe.ValidationError):api.preserve_compensated_plan(doc)

    def test_historical_mcp_keeps_old_save_path(self):
        doc=Document();doc.previous=Document()
        self.assertFalse(api.preserve_compensated_plan(doc))

    def test_submit_blocks_missing_and_keeps_planning_compatibility(self):
        doc=Document()
        with patch.object(api,"get_requirements_for_doc",return_value={"summary":{"to_compensate":1},"warnings":[]}):
            with self.assertRaises(frappe.ValidationError):api.validate_compensation_coverage(doc)
        doc.mcp_mode="Planification"
        with patch.object(api,"get_requirements_for_doc",side_effect=AssertionError("Historical planning must not change")):
            api.validate_compensation_coverage(doc)

    def test_g_repack_inputs_and_outputs_skip_submitted_serials(self):
        doc,result=self.compensated();tree=json.loads(doc.effective_result_json)
        for n in tree["nodes"]:n["item_code"]="RAW"
        se=Document();se.items=[]
        cp=result["placements"][0]["id"]
        with ExitStack() as stack:
            stack.enter_context(patch.object(api,"submitted_receipts",return_value=({cp},{"SN"})))
            stock_check=stack.enter_context(patch.object(repack,"_ensure_input_serial_exists"))
            stack.enter_context(patch.object(repack,"_set_item_uom_fields"))
            repack._build_input_rows(se,doc,tree["nodes"])
            repack._build_output_rows(se,doc,tree["nodes"])
        stock_check.assert_not_called()
        self.assertFalse(any(cp in (r.get("serial_no") or "") for r in se["items"]))
        self.assertFalse(any(r.get("s_warehouse") for r in se["items"]))
        self.assertTrue(se["items"]) # remaining leftovers, neither the consumed input nor CP

    def test_i_mcp_version_conflict_rolls_back(self):
        doc=Document();doc.as_dict=Mock(return_value={"modified":"v2"})
        with ExitStack() as stack:
            db=stack.enter_context(patch.object(frappe,"db",Mock()))
            stack.enter_context(patch.object(api,"_compensation_doc",return_value=doc))
            result=api.apply_compensation.__wrapped__("MCP","proposal",{"modified":"v1","signature":"old"})
        self.assertFalse(result["valid"])
        db.rollback.assert_called_once_with(save_point="mcp_compensation")

    def test_i_stock_conflict_rolls_back_without_appending_inputs(self):
        doc=Document();version=actions._document_version(doc)
        preview={"proposal_id":"changed","stock_candidates":[],"effective_tree":{"nodes":[sheet()]}}
        with ExitStack() as stack:
            db=stack.enter_context(patch.object(frappe,"db",Mock()))
            stack.enter_context(patch.object(api,"_compensation_doc",return_value=doc))
            stack.enter_context(patch.object(api,"_preview",return_value=preview))
            result=api.apply_compensation.__wrapped__("MCP","old",version)
        self.assertFalse(result["valid"]);self.assertEqual(doc.mcp_stock_candidate,[])
        db.rollback.assert_called_once()

    def test_real_return_terrain_planner_leaves_destroyed_need_for_confirmation(self):
        from mat_reco.material_reconfiguration.services.cutting_plan_service import generate_return_terrain_cutting_plan
        from mat_reco.material_reconfiguration.tests.test_mcp_compensation_service import piece
        good=piece("p");good.update(x=0,y=0,length_mm=800,width_mm=600,thickness_mm=6)
        free=dict(id="left",node_type="leftover",x=800,y=0,length_mm=1200,width_mm=1000)
        waste=dict(id="bottom",node_type="waste",x=0,y=600,length_mm=800,width_mm=400)
        nodes=[sheet(2000,1000,[good,free,waste])]
        doc=Document({"nodes":nodes});doc.material_plan_incidents=[frappe._dict(plan_node_id="p",incident_action="Destroy",is_active=1)]
        bins=[dict(serial_no="SN",item_code="RAW",length_mm=2000,width_mm=1000,area_mm2=2000000,thickness_mm=6)]
        out=generate_return_terrain_cutting_plan(plan_name="MCP",demands=[need()],bins=bins,existing_tree={"nodes":nodes},mcp_doc=doc,plan_missing_pieces=False)
        result=api.reconcile_requirements([need()],out["tree"]["nodes"],doc.material_plan_incidents)
        self.assertEqual(result["summary"]["to_compensate"],1)
        self.assertFalse(any(c["node_type"]=="finished_good" for n in out["tree"]["nodes"] for c in n["children"]))
        proposed=api.propose_compensation(out["tree"],result["compensation_requirements"],seed="new")
        # Add source thickness like the authoritative API snapshot does.
        if not proposed["placements"]:
            out["tree"]["nodes"][0]["thickness_mm"]=6
            proposed=api.propose_compensation(out["tree"],result["compensation_requirements"],seed="new")
        self.assertEqual(len(proposed["placements"]),1)

    def test_dates_from_real_commercial_context_serialize(self):
        doc,result=self.compensated()
        tree=result["effective_tree"]
        tree["compensation_events"]=[{"id":"event","source_context":{"delivery_date":date(2026,10,14)}}]
        doc.flags.compensation_tree=tree
        api.preserve_compensated_plan(doc)
        self.assertEqual(json.loads(doc.effective_result_json)["compensation_events"][0]["source_context"]["delivery_date"],"2026-10-14")

    def test_successful_application_records_server_journal_and_saves_once(self):
        doc=Document();doc.previous=Document();version=actions._document_version(doc)
        proposal=api.propose_compensation({"nodes":[sheet()]},[need()],seed="v1")
        proposal.update(proposal_id="hash",document_version=version,options={"strategy":"automatic","selected_sources":[],"override_reason":""},stock_candidates=[])
        persisted=[]
        def save():
            api.preserve_compensated_plan(doc)
            persisted.append(json.loads(doc.effective_result_json))
        doc.save=Mock(side_effect=save)
        with ExitStack() as stack:
            stack.enter_context(patch.object(frappe,"db",Mock()))
            stack.enter_context(patch.object(frappe,"session",frappe._dict(user="operator")))
            stack.enter_context(patch.object(frappe.utils,"now",return_value="2026-10-14 10:00:00"))
            stack.enter_context(patch.object(api,"_compensation_doc",return_value=doc))
            stack.enter_context(patch.object(api,"_preview",side_effect=lambda *args:deepcopy(proposal)))
            stack.enter_context(patch.object(api,"_validate_locked_sources"))
            stack.enter_context(patch.object(api,"get_requirements_for_doc",return_value={"summary":{"to_compensate":0},"warnings":[]}))
            loader=Mock();loader.__wrapped__=Mock(return_value={"valid":True,"effective_tree":proposal["effective_tree"],"document_version":version})
            stack.enter_context(patch.object(actions,"load_mcp_effective_plan",loader))
            result=api.apply_compensation.__wrapped__("MCP","hash",version)
        self.assertTrue(result["applied"]);doc.save.assert_called_once()
        self.assertEqual(persisted[0]["compensation_events"][0]["id"],"hash")
        self.assertEqual(doc.mcp_stock_candidate,[])

    def test_save_error_rolls_back_atomic_application(self):
        doc=Document();version=actions._document_version(doc)
        proposal=api.propose_compensation({"nodes":[sheet()]},[need()],seed="v1")
        proposal.update(proposal_id="hash",document_version=version,options={},stock_candidates=[])
        doc.save=Mock(side_effect=RuntimeError("Database failure"))
        with ExitStack() as stack:
            db=stack.enter_context(patch.object(frappe,"db",Mock()))
            stack.enter_context(patch.object(frappe,"session",frappe._dict(user="operator")))
            stack.enter_context(patch.object(frappe.utils,"now",return_value="2026-10-14"))
            stack.enter_context(patch.object(api,"_compensation_doc",return_value=doc))
            stack.enter_context(patch.object(api,"_preview",side_effect=lambda *args:deepcopy(proposal)))
            stack.enter_context(patch.object(api,"_validate_locked_sources"))
            with self.assertRaises(RuntimeError):api.apply_compensation.__wrapped__("MCP","hash",version)
        db.rollback.assert_called_once_with(save_point="mcp_compensation")

    def test_current_locked_stock_consumed_is_rejected(self):
        doc=Document()
        source=dict(serial_no="STOCK",item_code="RAW",length_mm=1200,width_mm=1000,thickness_mm=6)
        preview={"effective_tree":{"nodes":[]},"used_stock_sources":[source],"placements":[]}
        actual=frappe._dict(status="Consumed",company="CO",warehouse="WH")
        with patch.object(frappe,"db",Mock(sql=Mock(return_value=[actual]))):
            with self.assertRaises(ValueError):api._validate_locked_sources(doc,preview)

    def test_historical_serial_thickness_falls_back_to_item(self):
        serial=frappe._dict(item_code="RAW",custom_dimension_thickness_mm=0)
        item=frappe._dict(custom_thickness_mm=10);item.has_permission=Mock(return_value=True)
        with patch.object(frappe,"get_doc",return_value=item):self.assertEqual(api._source_thickness(serial),10)
