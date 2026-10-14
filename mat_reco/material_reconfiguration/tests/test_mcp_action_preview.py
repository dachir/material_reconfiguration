"""LOT 1 tests: real incident/Single engines; persistence and permissions mocked."""
from copy import deepcopy
import json
import unittest
from unittest.mock import Mock, patch

import frappe
from mat_reco.material_reconfiguration.services import mcp_action_preview as api


def fixture():
    return [{"id":"sheet","serial_no":"SN","node_type":"input_serial","length_mm":1800,"width_mm":1500,
             "children":[{"id":"piece","node_type":"finished_good","x":0,"y":0,"length_mm":1500,"width_mm":1000,"piece_item_code":"FG"},
                         {"id":"left","node_type":"leftover","x":0,"y":1000,"length_mm":1500,"width_mm":500},
                         {"id":"red","node_type":"waste","x":1500,"y":0,"length_mm":300,"width_mm":1500}]}]


def action(kind,source,targets=None,**parameters):
    return {"action":kind,"source_node_id":source,"target_node_ids":targets or [],"parameters":parameters}


def doc(nodes=None):
    value = frappe._dict(name="MCP-TEST",docstatus=0,mcp_mode="Retour Terrain",modified="2026-10-13 10:00:00",
                         result_json=json.dumps({"nodes":nodes or fixture()}),material_plan_incidents=[])
    value.check_permission=Mock()
    value.has_permission=Mock(return_value=True)
    value.save=Mock(side_effect=AssertionError("Preview must not save"))
    value.insert=Mock(side_effect=AssertionError("Preview must not insert"))
    return value


class TestGeometryPreview(unittest.TestCase):
    def test_destroy_keeps_footprint_but_excludes_stock(self):
        original=fixture();nodes,rows=api.preview_intentions(original,[action("Destroy","red")])
        red=next(n for n in nodes[0]["children"] if n["id"]=="red")
        self.assertEqual(red["node_type"],"destroyed")
        self.assertEqual(red["include_in_repack"],0)
        self.assertEqual(red["effective_area_mm2"],0)
        self.assertEqual(rows[0]["include_in_repack"],0)
        self.assertEqual(api._validate_nodes(nodes),api._validate_nodes(original))
        self.assertEqual(original,fixture())

    def test_resize_uses_historical_destroyed_complements(self):
        nodes,rows=api.preview_intentions(fixture(),[action("Resize","piece",length_mm=1000,width_mm=800)])
        self.assertEqual(rows[0]["new_area_mm2"],800000)
        self.assertEqual(len([n for n in nodes[0]["children"] if n["node_type"]=="destroyed"]),2)
        self.assertEqual(len({n["id"] for n in nodes[0]["children"]}),len(nodes[0]["children"]))
        self.assertEqual(api._validate_nodes(nodes),{"SN":2700000})
        for l,w in [(0,800),(2000,800),(1000,float("nan"))]:
            with self.assertRaises(ValueError):api.preview_intentions(fixture(),[action("Resize","piece",length_mm=l,width_mm=w)])

    def test_consecutive_resize_then_destroy_replays_without_duplicate_ids(self):
        nodes,rows=api.preview_intentions(fixture(),[action("Resize","piece",length_mm=1000,width_mm=800),action("Resize","piece",length_mm=800,width_mm=600),action("Destroy","piece")])
        self.assertEqual(len(rows),3)
        self.assertEqual(api._validate_nodes(nodes),{"SN":2700000})
        self.assertEqual(next(n for n in nodes[0]["children"] if n["id"]=="piece")["node_type"],"destroyed")

    def test_partial_merge_anchors_first_source_and_serializes_residuals(self):
        original=fixture();original[0]["children"][2]["node_type"]="leftover"
        # Change input iteration order; the selected source remains authoritative.
        original[0]["children"].reverse()
        nodes,rows=api.preview_intentions(original,[action("Merge","left",["red"])])
        output=next(n for n in nodes[0]["children"] if n["id"]=="left__merged")
        self.assertEqual((output["length_mm"],output["width_mm"]),(1800,500))
        self.assertEqual(json.loads(rows[0]["remarks"])["residual_rects"],[{"x":1500.0,"y":0.0,"length_mm":300.0,"width_mm":1000.0}])
        self.assertEqual(api._validate_nodes(nodes),{"SN":2700000})
        self.assertEqual(sum(n["node_type"]=="finished_good" for n in nodes[0]["children"]),1)
        with self.assertRaises(ValueError):api.preview_intentions(original,[action("Merge","red",["left"])])

    def test_waste_source_can_recover_into_the_selected_leftover(self):
        nodes,rows=api.preview_intentions(fixture(),[action("Merge","red",["left"])])
        out=next(n for n in nodes[0]["children"] if n["id"]=="red__merged")
        self.assertEqual((out["length_mm"],out["width_mm"]),(1800,500))
        self.assertEqual(api._validate_nodes(nodes),{"SN":2700000})
        self.assertEqual(rows[0]["plan_node_id"],"red")

    def test_merge_multiple_regions_and_subsequent_operation(self):
        original=[{"id":"s","serial_no":"SN","length_mm":1500,"width_mm":1000,"children":[{"id":str(i),"node_type":"leftover","x":500*i,"y":0,"length_mm":500,"width_mm":1000} for i in range(3)]}]
        nodes,rows=api.preview_intentions(original,[action("Merge","1",["0","2"]),action("Resize","1__merged",length_mm=1200,width_mm=800)])
        self.assertEqual(rows[0]["affected_node_ids_json"],'["1", "0", "2"]')
        self.assertEqual(api._validate_nodes(nodes),{"SN":1500000})

    def test_single_is_one_output_and_preserves_finished_good_in_hole(self):
        nodes,rows=api.preview_intentions(fixture(),[action("Single","left",["red"])])
        out=next(n for n in nodes[0]["children"] if n["geometry_type"]=="single")
        self.assertEqual(out["id"],"left__single")
        self.assertEqual(out["removed_length_mm"],1500)
        self.assertEqual(out["removed_width_mm"],1000)
        self.assertEqual(out["effective_area_mm2"],1200000)
        self.assertEqual(len(nodes[0]["children"]),2)
        self.assertEqual(rows[0]["incident_action"],"Single")
        self.assertEqual(api._validate_nodes(nodes),{"SN":2700000})

    def test_single_rejects_gaps_and_two_physical_sheets(self):
        gap=fixture();gap[0]["children"][2]["x"]+=100
        with self.assertRaises(ValueError):api.preview_intentions(gap,[action("Single","left",["red"])])
        two=fixture();red=two[0]["children"].pop();two.append({"id":"other","serial_no":"OTHER","length_mm":1800,"width_mm":1500,"children":[red]})
        with self.assertRaisesRegex(ValueError,"plaque physique"):api.preview_intentions(two,[action("Single","left",["red"])])

    def test_move_into_waste_same_sheet_swing(self):
        base=fixture();base[0]["children"][0].update(length_mm=200,width_mm=800)
        nodes,rows=api.preview_intentions(base,[action("Move","piece",["red"])])
        piece=next(n for n in nodes[0]["children"] if n["id"]=="piece")
        self.assertEqual(piece["x"],1500)
        self.assertEqual(rows[0]["move_case"],"swing")
        self.assertEqual(api._validate_nodes(nodes),api._validate_nodes(base))

    def test_move_inter_sheet_swap(self):
        base=[{"id":"s1","serial_no":"S1","length_mm":500,"width_mm":500,"children":[{"id":"p","node_type":"finished_good","length_mm":500,"width_mm":500}]},
              {"id":"s2","serial_no":"S2","length_mm":500,"width_mm":500,"children":[{"id":"zone","node_type":"leftover","length_mm":500,"width_mm":500}]}]
        nodes,rows=api.preview_intentions(base,[action("Move","p",["zone"])])
        self.assertEqual(rows[0]["move_case"],"swap")
        self.assertEqual(nodes[1]["children"][0]["id"],"p")
        self.assertEqual(api._validate_nodes(nodes),api._validate_nodes(base))

    def test_move_rejects_oversize_outside_and_historical_cutout(self):
        base=fixture();base[0]["children"][0].update(length_mm=200,width_mm=800)
        for intent in [action("Move","piece",["red"],target_x_mm=1700),action("Move","piece",["left"]),action("Move","left",["red"])]:
            with self.assertRaises(ValueError):api.preview_intentions(base,[intent])
        base[0]["children"].append({"id":"hole","node_type":"destroyed","x":1500,"y":0,"length_mm":100,"width_mm":100,"__preexisting_cutout":1})
        with self.assertRaises(ValueError):api.preview_intentions(base,[action("Move","piece",["red"])])

    def test_overlap_invalid_numbers_and_duplicate_targets_are_rejected(self):
        base=fixture();base[0]["children"][2]["x"]=1400
        with self.assertRaisesRegex(ValueError,"Chevauchement"):api.preview_intentions(base,[action("Destroy","red")])
        with self.assertRaises(ValueError):api.preview_intentions(fixture(),[action("Merge","left",["red","red"])])
        with self.assertRaises(ValueError):api.preview_intentions(fixture(),[action("Destroy","red",["left"])])


class TestPreviewAPI(unittest.TestCase):
    def setUp(self):
        self.previous_flags=getattr(frappe.local,"flags",None)
        frappe.local.flags=frappe._dict(in_test=True)

    def tearDown(self):
        if self.previous_flags is None:
            del frappe.local.flags
        else:
            frappe.local.flags=self.previous_flags

    def test_api_has_no_writes_and_does_not_trust_client_dimensions(self):
        document=doc();before=deepcopy(document)
        with patch.object(frappe,"get_doc",return_value=document),patch.object(frappe,"new_doc",side_effect=AssertionError("No new documents")):
            version=api.load_mcp_effective_plan("MCP-TEST")["document_version"]
            result=api.preview_mcp_action("MCP-TEST","Merge","left",'["red"]',{},[],version)
        self.assertTrue(result["valid"],result["errors"])
        self.assertFalse(result["document_modified"])
        document.save.assert_not_called();document.insert.assert_not_called()
        for key in ("result_json","effective_result_json","material_plan_incidents","modified"):
            self.assertEqual(document.get(key),before.get(key))
        document.check_permission.assert_any_call("read");document.check_permission.assert_any_call("write")

    def test_conflict_missing_version_and_submitted_document(self):
        document=doc()
        with patch.object(frappe,"get_doc",return_value=document):
            version=api.load_mcp_effective_plan("MCP-TEST")["document_version"]
            document.modified="2026-10-13 11:00:00"
            result=api.preview_mcp_action("MCP-TEST","Destroy","red",document_version=version)
            self.assertTrue(result["conflict"]);self.assertFalse(result["document_modified"])
            self.assertFalse(api.preview_mcp_action("MCP-TEST","Destroy","red")["valid"])
            document.docstatus=1
            self.assertFalse(api.preview_mcp_action("MCP-TEST","Destroy","red",document_version=version)["valid"])
            self.assertFalse(api.load_mcp_effective_plan("MCP-TEST")["editable"])

    def test_permissions_propagate_and_planification_is_readonly(self):
        document=doc();document.check_permission.side_effect=frappe.PermissionError("denied")
        with patch.object(frappe,"get_doc",return_value=document):
            with self.assertRaises(frappe.PermissionError):api.load_mcp_effective_plan("MCP-TEST")
        document.check_permission.side_effect=lambda permission: (_ for _ in ()).throw(frappe.PermissionError("denied")) if permission=="write" else None
        with patch.object(frappe,"get_doc",return_value=document):
            with self.assertRaises(frappe.PermissionError):api.preview_mcp_action("MCP-TEST","Destroy","red",document_version={})
        document.check_permission.side_effect=None;document.mcp_mode="Planification"
        with patch.object(frappe,"get_doc",return_value=document):
            self.assertFalse(api.load_mcp_effective_plan("MCP-TEST")["editable"])
            self.assertFalse(api.preview_mcp_action("MCP-TEST","Destroy","red",document_version={})["valid"])

    def test_saved_resolved_incidents_are_not_replayed(self):
        base=fixture();resolved,_=api.preview_intentions(base,[action("Destroy","red")]);document=doc()
        document.effective_result_json=json.dumps({"nodes":resolved,"return_terrain_resolved":True})
        document.material_plan_incidents=[frappe._dict(incident_action="Destroy",plan_node_id="red",is_active=1)]
        with patch.object(frappe,"get_doc",return_value=document):
            result=api.load_mcp_effective_plan("MCP-TEST")
        self.assertEqual(result["effective_nodes"],resolved)

    def test_pending_intentions_are_revalidated_and_failure_leaves_no_partial_write(self):
        document=doc()
        with patch.object(frappe,"get_doc",return_value=document):
            version=api.load_mcp_effective_plan("MCP-TEST")["document_version"]
            result=api.preview_mcp_action("MCP-TEST","Resize","piece",parameters={"length_mm":2000,"width_mm":1000},pending_incidents=[action("Destroy","red")],document_version=version)
            self.assertFalse(result["valid"])
            self.assertEqual(result["effective_nodes"],[])
            self.assertEqual(document.material_plan_incidents,[])
            self.assertEqual(json.loads(document.result_json)["nodes"],fixture())



class TestPrepareIncidents(unittest.TestCase):
    setUp=TestPreviewAPI.setUp
    tearDown=TestPreviewAPI.tearDown
    def test_prepare_single_uses_remarks_schema_and_no_save(self):
        original=doc();version=api._document_version(original)
        expected,rows=api.preview_intentions(fixture(),[action('Single','left',['red'])])
        class Probe:
            def __init__(self):self.rows=[];self.before_save=Mock()
            def append(self,field,row):self.rows.append((field,row))
        probe=Probe()
        with patch.object(api,'_load_doc',return_value=original),patch.object(api,'_effective_tree',side_effect=[{'nodes':fixture()},{'nodes':expected}]),patch.object(frappe,'get_doc',return_value=probe):
            original.as_dict=lambda:dict(original)
            result=api.prepare_mcp_incidents('MCP-TEST',[action('Single','left',['red'])],version)
        self.assertTrue(result['valid']);self.assertEqual(result['incidents'][0]['incident_action'],'Single')
        self.assertEqual(json.loads(result['incidents'][0]['remarks']),{'removed_length_mm':1500,'removed_width_mm':1000})
        self.assertEqual(probe.rows[0][0],'material_plan_incidents');probe.before_save.assert_called_once();original.save.assert_not_called()

    def test_prepare_refuses_result_lost_by_historical_save_and_stale_version(self):
        original=doc();original.as_dict=lambda:dict(original)
        class Probe:
            def append(self,*args):pass
            def before_save(self):pass
        with patch.object(api,'_load_doc',return_value=original),patch.object(api,'_effective_tree',return_value={'nodes':fixture()}),patch.object(frappe,'get_doc',return_value=Probe()):
            result=api.prepare_mcp_incidents('MCP-TEST',[action('Single','left',['red'])],api._document_version(original))
            self.assertFalse(result['valid']);self.assertIn('séparément',result['errors'][0])
            self.assertFalse(api.prepare_mcp_incidents('MCP-TEST',[action('Destroy','red')],{'signature':'stale'})['valid'])
        self.assertFalse(result['document_modified']);original.save.assert_not_called()


class TestHistoricalNodeAliases(unittest.TestCase):
    def test_all_reported_incidents_are_mapped_without_losing_single_cutout(self):
        current=fixture();base=deepcopy(current)
        for n in current[0]['children']:
            if n['id'] in ('left','red'):n['id']='RT-'+n['id']
        tree={'nodes':current,'base_tree':{'nodes':base}}
        _,single=api.preview_intentions(current,[action('Single','RT-left',['RT-red'])])
        result=api._incident_rows_for_base(None,tree,single)
        self.assertEqual(result[0]['plan_node_id'],'left')
        self.assertEqual(json.loads(result[0]['affected_node_ids_json']),['left','red'])
        metadata=json.loads(result[0]['remarks'])
        self.assertEqual(metadata['removed_length_mm'],1500)
        self.assertEqual(metadata['removed_width_mm'],1000)
        self.assertEqual(metadata['ux20_node_aliases'],{'RT-left':'left','RT-red':'red'})
        rows=[{'plan_node_id':'RT-left','source_serial_no':'SN','incident_action':'Destroy'},
              {'plan_node_id':'RT-red','source_serial_no':'SN','incident_action':'Destroy'}]
        mapped=api._incident_rows_for_base(None,tree,rows)
        self.assertEqual([r['plan_node_id'] for r in mapped],['left','red'])
        self.assertEqual(rows[0]['plan_node_id'],'RT-left')

    def test_geometry_not_in_base_is_refused_instead_of_assigning_wrong_source(self):
        current=fixture();base=deepcopy(current);current[0]['children'][1].update(id='RT-left',length_mm=1400)
        with self.assertRaisesRegex(ValueError,'base historique'):
            api._incident_rows_for_base(None,{'nodes':current,'base_tree':{'nodes':base}},[{'plan_node_id':'RT-left','source_serial_no':'SN'}])


if __name__ == '__main__':
    unittest.main()
