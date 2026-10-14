from copy import deepcopy
from contextlib import ExitStack
import json
import unittest
from unittest.mock import Mock, patch
import frappe
from mat_reco.material_reconfiguration.services import mcp_action_preview as api
from mat_reco.material_reconfiguration.services import mcp_compensation_service as persistence
from mat_reco.material_reconfiguration.services import repack_draft_service as repack
from mat_reco.material_reconfiguration.tests.test_mcp_compensation_persistence import Document, fail


def fixture(target_length=600,target_width=800):
    return [dict(id='S1',serial_no='S1',item_code='RAW',length_mm=800,width_mm=600,
                 children=[dict(id='p',piece_uid='unit',piece_item_code='FG',sales_order='SO',sales_order_item='ROW',
                     node_type='finished_good',x=0,y=0,length_mm=800,width_mm=600,rotation=False)]),
            dict(id='S2',serial_no='S2',item_code='RAW',length_mm=target_length+100,width_mm=target_width+100,
                 children=[dict(id='zone',node_type='leftover',x=100,y=100,length_mm=target_length,width_mm=target_width)])]


def move(target='zone',**parameters):
    return dict(action='Move',source_node_id='p',target_node_ids=[target],parameters=parameters)


def piece(nodes):
    return next(c for n in nodes for c in n['children'] if c['id']=='p')


class TestMoveRotation(unittest.TestCase):
    def test_inter_sheet_rotation_keeps_identity_area_and_other_coordinates(self):
        base=fixture();before=deepcopy(base)
        nodes,rows=api.preview_intentions(base,[move()],allow_rotation=True)
        result=piece(nodes)
        self.assertEqual((result['length_mm'],result['width_mm']),(600,800))
        self.assertEqual((result['x'],result['y']),(100,100))
        self.assertTrue(result['rotation']);self.assertEqual(result['source_serial_no'],'S2')
        self.assertEqual(result['piece_uid'],'unit');self.assertEqual(result['sales_order_item'],'ROW')
        self.assertEqual(json.loads(rows[0]['remarks'])['move_rotation_degrees'],90)
        self.assertEqual(rows[0]['move_case'],'swap')
        self.assertEqual(api._validate_nodes(nodes),api._validate_nodes(base))
        self.assertEqual(base,before)

    def test_prefers_current_orientation_when_both_fit(self):
        nodes,rows=api.preview_intentions(fixture(1000,1000),[move()],allow_rotation=True)
        self.assertEqual((piece(nodes)['length_mm'],piece(nodes)['width_mm']),(800,600))
        self.assertEqual(json.loads(rows[0]['remarks'])['move_rotation_degrees'],0)

    def test_explicit_rotation_and_disabled_rule(self):
        with self.assertRaises(ValueError):api.preview_intentions(fixture(),[move(rotation_degrees=0)],allow_rotation=True)
        with self.assertRaises(ValueError):api.preview_intentions(fixture(),[move()],allow_rotation=False)
        with self.assertRaisesRegex(ValueError,'désactivée'):
            api.preview_intentions(fixture(),[move(rotation_degrees=90)],allow_rotation=False)
        nodes,_=api.preview_intentions(fixture(1000,1000),[move(rotation_degrees=90)],allow_rotation=True)
        self.assertEqual((piece(nodes)['length_mm'],piece(nodes)['width_mm']),(600,800))

    def test_canonical_rows_replay_the_rotation_and_two_turns_restore_orientation(self):
        nodes,rows=api.preview_intentions(fixture(),[move()],allow_rotation=True)
        second,all_rows=api.preview_intentions(fixture(),[*rows,move('p__freed',rotation_degrees=90)],allow_rotation=True)
        replayed,_=api.preview_intentions(fixture(),all_rows,allow_rotation=True)
        self.assertEqual(api._geometry_signature(second),api._geometry_signature(replayed))
        self.assertEqual(piece(second)['source_serial_no'],'S1')
        self.assertFalse(piece(second)['rotation'])
        self.assertEqual((piece(second)['length_mm'],piece(second)['width_mm']),(800,600))

    def test_l_shaped_destination_allows_full_bottom_arm_without_filling_hole(self):
        base=fixture();base[0].update(length_mm=900,width_mm=350);base[0]['children'][0].update(length_mm=900,width_mm=350)
        base[1].update(length_mm=1200,width_mm=1000,removed_length_mm=800,removed_width_mm=600)
        base[1]['children']=[dict(id='zone',node_type='leftover',geometry_type='single',x=0,y=0,
            length_mm=1200,width_mm=1000,removed_length_mm=800,removed_width_mm=600)]
        nodes,_=api.preview_intentions(base,[move()],allow_rotation=True)
        self.assertEqual((piece(nodes)['x'],piece(nodes)['y']),(0,600))
        self.assertEqual(api._validate_nodes(nodes),api._validate_nodes(base))
        residuals=[c for c in nodes[1]['children'] if c['id']!='p']
        self.assertFalse(any(c.get('removed_length_mm') for c in residuals))
        with self.assertRaises(ValueError):api.preview_intentions(base,[move(target_x_mm=0,target_y_mm=0)],allow_rotation=True)

    def test_l_shaped_destination_fits_only_after_rotation(self):
        base=fixture();base[0].update(width_mm=250);base[0]['children'][0].update(width_mm=250)
        base[1].update(length_mm=1200,width_mm=1000,removed_length_mm=900,removed_width_mm=800)
        base[1]['children']=[dict(id='zone',node_type='leftover',geometry_type='single',x=0,y=0,
            length_mm=1200,width_mm=1000,removed_length_mm=900,removed_width_mm=800)]
        nodes,_=api.preview_intentions(base,[move()],allow_rotation=True)
        self.assertEqual((piece(nodes)['x'],piece(nodes)['y'],piece(nodes)['length_mm'],piece(nodes)['width_mm']),(900,0,250,800))
        self.assertEqual(api._validate_nodes(nodes),api._validate_nodes(base))

    def test_rejects_bad_angles_and_insufficient_space(self):
        for angle in (45,180,True,'90'):
            with self.assertRaises(ValueError):api.preview_intentions(fixture(),[move(rotation_degrees=angle)],allow_rotation=True)
        with self.assertRaises(ValueError):api.preview_intentions(fixture(500,700),[move()],allow_rotation=True)

    def test_save_hook_preserves_successive_moves_and_repack_output_identity(self):
        original=Document({'nodes':fixture()});doc=Document({'nodes':fixture()});doc.previous=original
        nodes,rows=api.preview_intentions(fixture(),[move()],allow_rotation=True)
        doc.material_plan_incidents=[frappe._dict(rows[0])]
        with patch.object(persistence,'submitted_receipts',return_value=(set(),set())):
            self.assertTrue(persistence.preserve_compensated_plan(doc))
            saved=json.loads(doc.effective_result_json)
            self.assertTrue(saved['ux20_incidents_resolved']);self.assertEqual(piece(saved['nodes'])['length_mm'],600)
            reloaded=Document(saved);reloaded.material_plan_incidents=deepcopy(doc.material_plan_incidents)
            reloaded.previous=Document(saved);reloaded.previous.material_plan_incidents=deepcopy(doc.material_plan_incidents)
            expected,next_rows=api.preview_intentions(saved['nodes'],[move('p__freed',rotation_degrees=90)],allow_rotation=True)
            reloaded.material_plan_incidents.append(frappe._dict(next_rows[0]))
            persistence.preserve_compensated_plan(reloaded)
            final=json.loads(reloaded.effective_result_json)
            self.assertEqual(api._geometry_signature(final['nodes']),api._geometry_signature(expected))
        se=Document();se['items']=[]
        with patch.object(repack,'_set_item_uom_fields'):
            repack._build_output_rows(se,reloaded,final['nodes'])
        outputs=[r for r in se['items'] if r.item_code=='FG']
        self.assertEqual(len(outputs),1);self.assertEqual(outputs[0].qty,1)
        self.assertEqual(outputs[0].serial_no,'p')
        self.assertEqual((outputs[0].custom_dimension_length_mm,outputs[0].custom_dimension_width_mm),(800,600))

    def test_submitted_piece_cannot_be_moved(self):
        doc=Document({'nodes':fixture()});doc.previous=Document({'nodes':fixture()})
        _,rows=api.preview_intentions(fixture(),[move()],allow_rotation=True)
        doc.material_plan_incidents=[frappe._dict(rows[0])]
        with patch.object(persistence,'submitted_receipts',return_value=({'p'},set())),patch.object(frappe,'throw',side_effect=fail):
            with self.assertRaises(frappe.ValidationError):persistence.preserve_compensated_plan(doc)

    def test_preview_api_uses_server_rotation_flag_and_ignores_client_dimensions(self):
        doc=Document({'nodes':fixture()});doc.allow_rotation=1;doc.check_permission=Mock()
        version=api._document_version(doc)
        with patch.object(frappe,'get_doc',return_value=doc):
            result=api.preview_mcp_action.__wrapped__('MCP','Move','p',['zone'],{'length_mm':1,'width_mm':1},[],version)
        self.assertTrue(result['valid'],result['errors'])
        self.assertEqual((piece(result['effective_nodes'])['length_mm'],piece(result['effective_nodes'])['width_mm']),(600,800))
        doc.allow_rotation=0;version=api._document_version(doc)
        with patch.object(frappe,'get_doc',return_value=doc):
            denied=api.preview_mcp_action.__wrapped__('MCP','Move','p',['zone'],{'allow_rotation':True},[],version)
        self.assertFalse(denied['valid'])

    def test_prepare_revalidates_rotated_move_with_incremental_save_hook_without_writing(self):
        original=Document({'nodes':fixture()})
        probe=Document({'nodes':fixture()});probe.previous=original
        probe.before_save=lambda:persistence.preserve_compensated_plan(probe)
        probe.save=Mock(side_effect=AssertionError('No write'))
        version=api._document_version(original)
        with ExitStack() as stack:
            stack.enter_context(patch.object(api,'_load_doc',return_value=original))
            stack.enter_context(patch.object(frappe,'get_doc',return_value=probe))
            stack.enter_context(patch.object(persistence,'submitted_receipts',return_value=(set(),set())))
            prepared=api.prepare_mcp_incidents.__wrapped__('MCP',[move()],version)
        self.assertTrue(prepared['valid'],prepared.get('errors'))
        self.assertEqual(piece(prepared['effective_tree']['nodes'])['length_mm'],600)
        self.assertEqual(prepared['incidents'][0]['target_zone_id'],'zone')
        probe.save.assert_not_called()
