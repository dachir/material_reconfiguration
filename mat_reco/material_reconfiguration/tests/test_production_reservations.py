"""Native serial reservations across production, partial B deliveries and reversals."""
import unittest
import uuid
from unittest.mock import patch

import frappe
from frappe.utils import add_days, nowdate
from mat_reco.material_reconfiguration.tests import test_order_b_stock as fixtures
from mat_reco.material_reconfiguration.services import production_reservations as reservations
from mat_reco.material_reconfiguration.services import special_b
from mat_reco.material_reconfiguration.services import order_b_stock


class ProductionReservationTests(unittest.TestCase):
    setUp_base = fixtures.OrderBStockTests.setUp
    cleanup = fixtures.OrderBStockTests.cleanup
    new_order = fixtures.OrderBStockTests.new_order
    remove_files = fixtures.OrderBStockTests.remove_files

    def setUp(self):
        self.setUp_base()
        context = patch.object(reservations, 'COMPANY', self.company)
        context.start(); self.addCleanup(context.stop)
        parent = frappe.get_cached_value('Item', self.cut, 'custom_parent_item')
        self.glass = frappe.get_doc(dict(doctype='Item', item_code='QA-RES-CUT-'+uuid.uuid4().hex[:9],
            item_name='QA reserved glass', item_group=self.item.item_group, stock_uom='PC',
            is_stock_item=1, is_sales_item=1, has_serial_no=1, custom_item_types='DECOUPE',
            custom_parent_item=parent, custom_requires_dimensions=1, custom_thickness_mm=self.thickness,
            item_defaults=[dict(company=self.company, default_warehouse=self.warehouse)])).insert()
        self.manufacturing_order = self.glass_order(3)
        self.serial_names = ['QA-RES-'+uuid.uuid4().hex[:15] for _ in range(3)]
        for serial in self.serial_names:
            frappe.get_doc(dict(doctype='Serial No', serial_no=serial, item_code=self.glass.name,
                custom_dimension_length_mm=1200, custom_dimension_width_mm=900,
                custom_dimension_thickness_mm=self.thickness)).insert()
        self.production = frappe.get_doc(dict(doctype='Stock Entry', stock_entry_type='Repack', company=self.company,
            branch=self.branch, custom_sales_order=self.manufacturing_order.name, items=[
                dict(item_code=self.item.name, qty=1, s_warehouse=self.warehouse),
                dict(item_code=self.glass.name, qty=3, t_warehouse=self.warehouse, allow_zero_valuation_rate=1,
                    serial_no='\n'.join(self.serial_names), use_serial_batch_fields=1,
                    custom_sales_order_item=self.manufacturing_order.items[0].name,
                    custom_dimension_length_mm=1200, custom_dimension_width_mm=900,
                    custom_dimension_thickness_mm=self.thickness),
            ])).insert()
        self.production.submit()

    def glass_order(self, qty):
        order=frappe.get_doc(dict(doctype='Sales Order',company=self.company,customer=self.customer,
            custom_ug_order_type='B',branch=self.branch,delivery_date=add_days(nowdate(),7),
            items=[dict(item_code=self.glass.name,qty=qty,rate=100,warehouse=self.warehouse,
                        custom_client_length_mm=1200,custom_client_width_mm=900,
                        custom_client_thickness_mm=self.thickness)])).insert()
        order.submit();order.reload()
        frappe.get_doc('Chantier Technical Study',order.custom_technical_study).submit()
        return order

    def active(self):
        return frappe.get_all('Stock Reservation Entry',filters={
            'voucher_no':self.manufacturing_order.name,'docstatus':1},pluck='name')

    def deliver(self, qty):
        doc=frappe.get_doc(special_b.make_delivery(self.manufacturing_order.name))
        doc.items[0].qty=qty
        doc.accounting_dimensions_json=frappe.as_json({'branch':self.branch})
        doc.insert();doc.submit()
        return doc

    def test_production_reserves_exact_serials_once(self):
        self.assertEqual(len(self.active()),3)
        reserved=set()
        for name in self.active():
            doc=frappe.get_doc('Stock Reservation Entry',name)
            self.assertEqual(doc.custom_ug_production_entry,self.production.name)
            self.assertEqual(doc.reserved_qty,1)
            reserved.update(row.serial_no for row in doc.sb_entries)
        self.assertEqual(reserved,set(self.serial_names))
        reservations.stock_updated(self.production)
        self.assertEqual(len(self.active()),3)

    def test_partial_delivery_and_cancel_restore_reservations(self):
        first=self.deliver(1)
        self.assertEqual(len(first.items[0].serial_no.splitlines()),1)
        self.assertEqual(len(self.active()),2)
        second=self.deliver(2)
        self.assertFalse(self.active())
        second.cancel()
        self.assertEqual(len(self.active()),2)
        for serial in second.items[0].serial_no.splitlines():
            self.assertEqual(frappe.db.get_value('Serial No',serial,'warehouse'),self.warehouse)
        final=self.deliver(2)
        self.assertFalse(self.active())
        self.assertEqual(special_b.get_order_summary(self.manufacturing_order.name)['items'][0]['remaining_qty'],0)

    def test_other_order_cannot_release_or_consume_reserved_series(self):
        other=self.glass_order(1)
        selection=[dict(sales_order_item=other.items[0].name,warehouse=self.warehouse,qty=1,serials=[self.serial_names[0]])]
        with self.assertRaises(frappe.ValidationError):
            order_b_stock.create_issue(other.name,selection,uuid.uuid4().hex,{'branch':self.branch})
        self.assertEqual(len(self.active()),3)

    def test_failed_issue_rolls_back_reservation_release(self):
        doc=frappe.get_doc(special_b.make_delivery(self.manufacturing_order.name));doc.items[0].qty=1
        doc.accounting_dimensions_json=frappe.as_json({'branch':self.branch});doc.insert()
        frappe.db.savepoint('qa_release_rollback')
        from erpnext.stock.doctype.stock_entry.stock_entry import StockEntry
        with patch.object(StockEntry,'submit',side_effect=RuntimeError('stock failure')):
            with self.assertRaisesRegex(RuntimeError,'stock failure'):doc.submit()
        frappe.db.rollback(save_point='qa_release_rollback')
        self.assertEqual(len(self.active()),3)
        doc.reload();self.assertEqual(doc.docstatus,0)

    def test_cancel_production_cancels_its_reservations(self):
        self.production.cancel()
        self.assertFalse(self.active())

    def test_manual_choice_is_kept_and_stale_auto_choice_is_cleared(self):
        doc=frappe.get_doc(special_b.make_delivery(self.manufacturing_order.name))
        row=doc.items[0]
        row.qty=1
        row.serial_no=self.serial_names[-1]
        reservations.fill_delivery(doc)
        self.assertEqual(row.serial_no,self.serial_names[-1])
        row.auto_serial_no=row.serial_no
        row.warehouse='Different warehouse'
        reservations.fill_delivery(doc)
        self.assertEqual(row.serial_no,'')
        self.assertEqual(row.auto_serial_no,'')
