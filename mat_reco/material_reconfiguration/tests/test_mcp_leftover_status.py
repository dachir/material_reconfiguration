"""MCP leftovers must be classified as Partial on their physical Serial No."""
import json
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock, patch

import frappe
import frappe.defaults
from mat_reco.material_reconfiguration.services import repack_draft_service as service
from mat_reco.material_reconfiguration.services import serial_creation_service, glass_stock


class Doc(SimpleNamespace):
    def get(self, key, default=None):
        return getattr(self,key,default)


class MCPLeftoverStatusTests(TestCase):
    def ensure(self, node_type):
        return service._ensure_output_serial_exists_or_create('LEFT', 'RAW', 'Stores',
            material_cutting_plan='MCP',length_mm=800,width_mm=610,node_type=node_type)

    def test_existing_leftover_serial_is_partial_without_changing_warehouse_or_value(self):
        with patch.object(frappe,'db',new=MagicMock()) as db:
            db.has_column.return_value=True
            db.get_value.return_value=frappe._dict(name='LEFT',item_code='RAW',warehouse='Stores')
            self.ensure('leftover')
        updates=db.set_value.call_args.args[2]
        self.assertEqual(updates['custom_material_status'],'Partial')
        self.assertNotIn('warehouse',updates)
        self.assertNotIn('status',updates)
        self.assertNotIn('purchase_rate',updates)
        self.assertNotIn('valuation_rate',updates)

    def test_new_leftover_serial_is_partial(self):
        serial=Doc(name='LEFT',insert=MagicMock())
        with patch.object(frappe,'db',new=MagicMock()) as db, \
             patch.object(frappe,'new_doc',return_value=serial), \
             patch.object(frappe.defaults,'get_user_default',return_value='UG'):
            db.has_column.return_value=True
            db.get_value.return_value=None
            self.ensure('leftover')
        self.assertEqual(serial.custom_material_status,'Partial')
        self.assertFalse(hasattr(serial,'warehouse'))
        serial.insert.assert_called_once_with(ignore_permissions=True)

    def test_finished_good_status_remains_full_and_unknown_type_is_not_guessed(self):
        with patch.object(frappe,'db',new=MagicMock()) as db:
            db.has_column.return_value=True
            db.get_value.return_value=frappe._dict(name='LEFT',item_code='RAW',warehouse='Stores')
            self.ensure('finished_good')
            self.assertEqual(db.set_value.call_args.args[2]['custom_material_status'],'Full')
            self.ensure(None)
            self.assertNotIn('custom_material_status',db.set_value.call_args.args[2])

    def test_existing_bundle_and_missing_row_type_use_mcp_classification(self):
        row=frappe._dict(name='ROW',item_code='RAW',t_warehouse='Stores',serial_and_batch_bundle='BUNDLE',
                        custom_mcp_serial_nos_json=json.dumps(['LEFT']))
        doc=Doc(name='SE',company='UG',stock_entry_type='Repack',custom_material_cutting_plan='MCP',items=[row])
        metadata={'LEFT':dict(node_type='leftover',length_mm=800,width_mm=610)}
        with patch.object(service,'validate_single_output_rows_before_submit'), \
             patch.object(serial_creation_service,'_get_mcp_serial_dimension_map',return_value=metadata), \
             patch.object(service,'_extract_serial_nos_from_stock_entry_detail',return_value={'LEFT'}), \
             patch.object(service,'_create_bundle') as bundle, \
             patch.object(frappe,'db',new=MagicMock()) as db:
            db.has_column.return_value=True
            db.get_value.return_value=frappe._dict(name='LEFT',item_code='RAW',warehouse='Stores')
            service.ensure_mcp_bundles_for_stock_entry(doc)
        updates=db.set_value.call_args.args[2]
        self.assertEqual(updates['custom_material_status'],'Partial')
        self.assertEqual(updates['custom_dimension_length_mm'],800)
        self.assertEqual(updates['custom_dimension_width_mm'],610)
        bundle.assert_not_called()
        self.assertEqual(row.serial_and_batch_bundle,'BUNDLE')
        sn=dict(name='LEFT',item_code='RAW',warehouse='Stores',status='Active',**updates)
        rows,_=glass_stock.physical_rows([sn],{'RAW':dict(custom_item_types='PRIMAIRE')},{'Stores'})
        self.assertEqual(rows[0]['classification'],'chutes')
        self.assertEqual(glass_stock.overview(rows,{'RAW':{}})['chutes'],1)
