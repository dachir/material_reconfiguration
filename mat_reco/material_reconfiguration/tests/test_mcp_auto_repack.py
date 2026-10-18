"""Automatic Repack submission remains synchronous, permission checked and idempotent."""
import json
import unittest
from contextlib import ExitStack
from unittest.mock import MagicMock, patch

import frappe
from mat_reco.material_reconfiguration.services import mcp_repack as service


class MCPAutoRepackTests(unittest.TestCase):
    def setUp(self):
        self.plan=frappe._dict(name='MCP',company='UG',add_waiste_to_stock=1)
        self.plan.db_set=MagicMock()
        self.entry=MagicMock(name='entry');self.entry.name='SE'
        self.db=MagicMock()
        self.stack=ExitStack();self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(frappe,'db',self.db))
        self.linked=self.stack.enter_context(patch.object(frappe,'get_all',return_value=[]))
        self.get_doc=self.stack.enter_context(patch.object(frappe,'get_doc',return_value=self.entry))
        self.builder=self.stack.enter_context(patch.object(service.repack_draft_service,'make_repack_draft',return_value={'doctype':'Stock Entry'}))
        self.stack.enter_context(patch.object(service,'get_active_accounting_dimension_fields',return_value=[]))
        self.stack.enter_context(patch.object(service,'_apply_input_inventory_dimensions'))
        self.complete=self.stack.enter_context(patch.object(service,'_execution_complete',return_value=True))
        self.dimensions=self.stack.enter_context(patch.object(service,'resolve_and_apply_stock_entry_dimensions'))

    def test_new_repack_is_inserted_and_submitted_with_permissions_and_tracking(self):
        self.assertEqual(service.execute_on_submit(self.plan),'SE')
        self.entry.check_permission.assert_called_with('submit')
        self.entry.insert.assert_called_once_with();self.entry.submit.assert_called_once_with()
        self.assertEqual(self.entry.add_waiste_to_stock,1)
        self.plan.db_set.assert_any_call('status','Executed')
        self.plan.db_set.assert_any_call('created_stock_entries_json','["SE"]')
        self.db.commit.assert_not_called()

    def test_existing_single_draft_is_submitted_without_creating_another(self):
        self.linked.return_value=[frappe._dict(name='SE',docstatus=0)]
        service.execute_on_submit(self.plan)
        self.builder.assert_not_called();self.entry.insert.assert_not_called()
        self.entry.check_permission.assert_any_call('write');self.entry.submit.assert_called_once_with()

    def test_multiple_drafts_are_rejected_without_stock_movement(self):
        self.linked.return_value=[frappe._dict(name='SE1',docstatus=0),frappe._dict(name='SE2',docstatus=0)]
        with self.assertRaises(frappe.ValidationError):service.execute_on_submit(self.plan)
        self.entry.submit.assert_not_called();self.builder.assert_not_called()

    def test_failure_propagates_without_marking_plan_executed_or_committing(self):
        self.entry.submit.side_effect=frappe.ValidationError('Stock indisponible')
        with self.assertRaisesRegex(frappe.ValidationError,'Stock indisponible'):service.execute_on_submit(self.plan)
        self.plan.db_set.assert_not_called();self.db.commit.assert_not_called()

    def test_partial_draft_cannot_mark_whole_plan_executed(self):
        self.complete.return_value=False
        with self.assertRaises(frappe.ValidationError):service.execute_on_submit(self.plan)
        self.plan.db_set.assert_not_called();self.db.commit.assert_not_called()

    def test_missing_submit_permission_stops_before_stock_entry_creation(self):
        self.entry.check_permission.side_effect=frappe.PermissionError('Permission refusée')
        with self.assertRaises(frappe.PermissionError):service.execute_on_submit(self.plan)
        self.entry.insert.assert_not_called();self.entry.submit.assert_not_called()
        self.plan.db_set.assert_not_called()

    def test_conflicting_order_dimensions_do_not_choose_an_arbitrary_branch(self):
        self.plan.selected_sales_orders=[frappe._dict(sales_order='SO1'),frappe._dict(sales_order='SO2')]
        self.entry.get.return_value=None
        first=frappe._dict(branch='A',check_permission=MagicMock())
        second=frappe._dict(branch='B',check_permission=MagicMock())
        self.get_doc.side_effect=[self.entry,first,second]
        with patch.object(service,'get_active_accounting_dimension_fields',return_value=['branch']):
            with self.assertRaises(frappe.ValidationError):service.execute_on_submit(self.plan)
        self.entry.insert.assert_not_called();self.entry.submit.assert_not_called()

    def test_already_executed_plan_does_not_consume_stock_twice(self):
        self.linked.return_value=[frappe._dict(name='SE',docstatus=1)]
        with patch.object(service.repack_draft_service,'build_effective_nodes',return_value=[]), \
             patch.object(service.repack_draft_service,'_collect_expected_serials',return_value=({'OUT'},{'IN'})), \
             patch.object(service.repack_draft_service,'_collect_generated_outputs_and_inputs_from_serials',return_value=({'OUT'},{'IN'})):
            self.assertEqual(service.execute_on_submit(self.plan),'SE')
        self.builder.assert_not_called();self.entry.submit.assert_not_called()


class NativeMCPAutoRepackTests(unittest.TestCase):
    def setUp(self):
        frappe.db.savepoint('qa_auto_repack')
        self.user=frappe.session.user;frappe.set_user('Administrator')
        self.company='Marsavco SA'
        if not frappe.db.exists('Company',self.company):self.skipTest('Requires configured glass site')
        self.warehouse=frappe.db.get_value('Warehouse',{'company':self.company,'is_group':0,'disabled':0},'name')
        self.group=frappe.db.get_value('Item Group',{'is_group':0},'name')
        for code,kind in [('QA-AUTO-RAW','PRIMAIRE'),('QA-AUTO-CUT','DECOUPE')]:
            item=frappe.get_doc(dict(doctype='Item',item_code=code,item_name=code,item_group=self.group,stock_uom='PC',
                is_stock_item=1,has_serial_no=1,has_batch_no=0,custom_item_types=kind,
                custom_is_reconfigurable=int(kind=='PRIMAIRE'),custom_requires_dimensions=1,
                custom_sheet_length_mm=1000,custom_sheet_width_mm=1000,custom_thickness_mm=4,
                custom_parent_item='QA-AUTO-RAW' if kind=='DECOUPE' else None))
            item.append('item_defaults',dict(company=self.company,default_warehouse=self.warehouse));item.insert()
        from mat_reco.material_reconfiguration.services.serial_creation_service import _create_or_update_serial_no
        _create_or_update_serial_no('QA-AUTO-SHEET','QA-AUTO-RAW',self.company,'input',1000,1000)
        frappe.db.set_value('Serial No','QA-AUTO-SHEET','custom_dimension_thickness_mm',4)
        receipt=frappe.new_doc('Stock Entry');receipt.company=self.company;receipt.stock_entry_type='Material Receipt'
        receipt.branch='Kinshasa'
        receipt.append('items',dict(item_code='QA-AUTO-RAW',t_warehouse=self.warehouse,qty=1,basic_rate=100,
            serial_no='QA-AUTO-SHEET',use_serial_batch_fields=1,quality_status='A',to_quality_status='A',
            custom_dimension_length_mm=1000,custom_dimension_width_mm=1000,custom_dimension_thickness_mm=4))
        receipt.insert();receipt.submit()
        self.plan=frappe.get_doc(dict(doctype='Material Cutting Plan',company=self.company,source_item='QA-AUTO-RAW',
            source_warehouse=self.warehouse,mcp_mode='Planification')).insert()
        order=frappe.get_doc(dict(doctype='Sales Order',company=self.company,customer='AQUA LOISIR',branch='Kinshasa',delivery_date=frappe.utils.add_days(frappe.utils.nowdate(),7),items=[dict(item_code='QA-AUTO-CUT',qty=1,rate=100,uom='PC',custom_client_length_mm=500,custom_client_width_mm=1000,custom_client_thickness_mm=4)])).insert()
        order.submit()
        self.plan.append('selected_sales_orders',{'sales_order':order.name})
        tree=dict(nodes=[dict(id='QA-AUTO-SHEET',node_type='input_serial',serial_no='QA-AUTO-SHEET',item_code='QA-AUTO-RAW',
            length_mm=1000,width_mm=1000,thickness_mm=4,area_mm2=1000000,children=[
                dict(id='QA-AUTO-FG',piece_uid='QA-AUTO-FG',node_type='finished_good',piece_item_code='QA-AUTO-CUT',length_mm=500,width_mm=1000,thickness_mm=4),
                dict(id='QA-AUTO-LEFT',node_type='leftover',length_mm=500,width_mm=1000,thickness_mm=4)])])
        self.plan.db_set('result_json',json.dumps(tree));self.plan.db_set('effective_result_json',json.dumps(tree))

    def tearDown(self):
        frappe.set_user(self.user);frappe.db.rollback(save_point='qa_auto_repack');frappe.clear_messages()
        for code in ('QA-AUTO-RAW','QA-AUTO-CUT'):frappe.clear_document_cache('Item',code)

    def test_native_plan_submit_immediately_creates_submitted_repack_and_stock(self):
        self.plan.submit();self.plan.reload()
        self.assertEqual(self.plan.docstatus,1);self.assertEqual(self.plan.status,'Executed')
        names=json.loads(self.plan.created_stock_entries_json)
        self.assertEqual(len(names),1)
        entry=frappe.get_doc('Stock Entry',names[0])
        self.assertEqual(entry.docstatus,1);self.assertEqual(entry.custom_material_cutting_plan,self.plan.name)
        self.assertEqual(next(row for row in entry.items if row.s_warehouse).quality_status,'A')
        self.assertEqual(entry.branch,'Kinshasa')
        self.assertFalse(frappe.db.get_value('Serial No','QA-AUTO-SHEET','warehouse'))
        for serial in ('QA-AUTO-FG','QA-AUTO-LEFT'):
            self.assertEqual(frappe.db.get_value('Serial No',serial,'warehouse'),self.warehouse)
        self.assertEqual(service.execute_on_submit(self.plan),entry.name)
        self.assertEqual(frappe.db.count('Stock Entry',{'custom_material_cutting_plan':self.plan.name,'docstatus':1}),1)

    def test_submit_failure_rolls_back_plan_and_repack(self):
        from erpnext.stock.doctype.stock_entry.stock_entry import StockEntry
        frappe.db.savepoint('qa_submit_failure')
        with patch.object(StockEntry,'on_submit',side_effect=frappe.ValidationError('Stock refusé')):
            with self.assertRaisesRegex(frappe.ValidationError,'Stock refusé'):self.plan.submit()
        frappe.db.rollback(save_point='qa_submit_failure')
        self.plan.reload();self.assertEqual(self.plan.docstatus,0)
        self.assertEqual(frappe.db.count('Stock Entry',{'custom_material_cutting_plan':self.plan.name}),0)
        self.assertEqual(frappe.db.get_value('Serial No','QA-AUTO-SHEET','warehouse'),self.warehouse)
