from contextlib import ExitStack
import json
import unittest
from unittest.mock import Mock, patch
import frappe
from mat_reco.material_reconfiguration.services import mcp_action_preview as api
from mat_reco.material_reconfiguration.tests.test_mcp_action_preview import doc

class TestResetPlanning(unittest.TestCase):
    def setUp(self):
        self.previous_flags=getattr(frappe.local,"flags",None)
        frappe.local.flags=frappe._dict(in_test=True)
    def tearDown(self):
        if self.previous_flags is None:del frappe.local.flags
        else:frappe.local.flags=self.previous_flags
    def document(self):
        value=doc();value.flags=frappe._dict()
        value.material_plan_incidents=[frappe._dict(incident_action='Destroy',plan_node_id='piece',is_active=1)]
        value.effective_result_json=json.dumps({'nodes':[], 'compensation_events':[{'id':'old'}]})
        value.set=lambda key,data:value.update({key:data})
        value._build_summary_from_tree=Mock(return_value={'planned_piece_count':1})
        value._apply_summary_to_fields=Mock();value.save=Mock()
        return value
    def patches(self,value,receipts=(set(),set())):
        stack=ExitStack()
        stack.enter_context(patch.object(api,'_load_doc',return_value=value))
        stack.enter_context(patch.object(frappe,'db',Mock(),create=True))
        stack.enter_context(patch('mat_reco.material_reconfiguration.services.mcp_compensation_service.submitted_receipts',return_value=receipts))
        stack.enter_context(patch('mat_reco.material_reconfiguration.services.cutting_plan_service.update_active_input_flags'))
        stack.enter_context(patch('mat_reco.material_reconfiguration.doctype.material_cutting_plan.mcp_sheet_sync.sync_mcp_sheets'))
        return stack
    def test_reset_restores_exact_snapshot_and_removes_all_incidents(self):
        value=self.document();initial=value.result_json
        with self.patches(value):response=api.reset_mcp_incidents(value.name,api._document_version(value))
        self.assertTrue(response['reset']);self.assertEqual(value.material_plan_incidents,[])
        self.assertEqual(response['effective_tree'],json.loads(initial));self.assertEqual(value.result_json,initial)
        value.save.assert_called_once();value._apply_summary_to_fields.assert_called_once()
    def test_stale_version_never_deletes(self):
        value=self.document()
        with self.patches(value):response=api.reset_mcp_incidents(value.name,{})
        self.assertTrue(response['conflict']);value.save.assert_not_called();self.assertEqual(len(value.material_plan_incidents),1)
    def test_submitted_repack_never_deletes(self):
        value=self.document()
        with self.patches(value,({'produced'},set())):response=api.reset_mcp_incidents(value.name,api._document_version(value))
        self.assertFalse(response['valid']);value.save.assert_not_called();self.assertEqual(len(value.material_plan_incidents),1)
    def test_missing_snapshot_never_deletes(self):
        value=self.document();value.result_json='{}'
        with self.patches(value):response=api.reset_mcp_incidents(value.name,api._document_version(value))
        self.assertFalse(response['valid']);value.save.assert_not_called();self.assertEqual(len(value.material_plan_incidents),1)
    def test_failed_save_rolls_back(self):
        value=self.document();value.save.side_effect=RuntimeError('save failed')
        with self.patches(value),self.assertRaises(RuntimeError):
            database=frappe.db;api.reset_mcp_incidents(value.name,api._document_version(value))
        database.rollback.assert_called_once_with(save_point='mcp_reset_incidents')
