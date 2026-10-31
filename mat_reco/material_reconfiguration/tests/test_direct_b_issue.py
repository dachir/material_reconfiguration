"""Direct B sales do not need a study; native stock safeguards still apply."""
from contextlib import ExitStack
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import frappe

from mat_reco.material_reconfiguration.services import order_b_stock as stock


class Record(SimpleNamespace):
    def get(self, key, default=None):
        return getattr(self, key, default)

    def get_doc_before_save(self):
        return None

    def check_permission(self, *args, **kwargs):
        pass


class DirectBIssueTests(unittest.TestCase):
    """Exercise the real validator, replacing database reads and production history."""

    def setUp(self):
        self.row = Record(name='SO-ROW', item_code='GLASS', qty=2, stock_qty=2,
            conversion_factor=1, custom_client_length_mm=1200,
            custom_client_width_mm=900, custom_client_thickness_mm=10)
        self.order = Record(name='SO-B', company='UG', status='To Deliver and Bill',
            custom_technical_study=None, items=[self.row])
        self.detail = Record(custom_sales_order_item=self.row.name, item_code='GLASS',
            s_warehouse='Stores - UG', t_warehouse=None, qty=1, conversion_factor=1,
            uom='PC', serial_no='')
        self.doc = Record(name='ISSUE', company='UG', stock_entry_type='Material Issue',
            custom_ug_b_sales_order=self.order.name, items=[self.detail])
        self.item_type = 'PRIMAIRE'
        self.sheet_status = 0
        self.actual_qty = 2
        self.reservations = []
        self.reserved_serials = []
        self.booked = {}
        self.owners = {'SN-1': self.row.name}
        self.serial = Record(name='SN-1', item_code='GLASS', warehouse='Stores - UG',
            status='Active', custom_dimension_length_mm=1200,
            custom_dimension_width_mm=900, custom_dimension_thickness_mm=10)
        self.db = SimpleNamespace(sql=Mock(side_effect=lambda *a, **kw:self.reservations),
            get_value=Mock(side_effect=self.db_value))
        stack = self.enterContext(ExitStack())
        stack.enter_context(patch.object(stock.frappe, 'db', self.db))
        stack.enter_context(patch.object(stock.frappe, 'throw', side_effect=self.reject))
        stack.enter_context(patch.object(stock.frappe, 'get_doc', side_effect=self.document))
        stack.enter_context(patch.object(stock.frappe, 'get_cached_value', side_effect=self.item_value))
        stack.enter_context(patch.object(stock.frappe, 'get_all',
            side_effect=lambda *a, **kw:self.reserved_serials))
        stack.enter_context(patch.object(stock, 'get_order', return_value=self.order))
        stack.enter_context(patch.object(stock, 'issued_quantities',
            side_effect=lambda *a, **kw:self.booked))
        stack.enter_context(patch.object(stock, '_receipts',
            side_effect=lambda *a, **kw:({}, {}, {}, self.owners)))

    @staticmethod
    def reject(message, *args, **kwargs):
        raise frappe.ValidationError(message)

    def item_value(self, doctype, name, field):
        self.assertEqual(doctype, 'Item')
        self.assertIn(name, ('GLASS', 'MANUFACTURED'))
        item_type = 'OUVRAGE' if name == 'MANUFACTURED' else self.item_type
        return dict(is_stock_item=1, stock_uom='PC', custom_item_types=item_type)[field]

    def db_value(self, doctype, *args, **kwargs):
        if doctype == 'Chantier Technical Study':
            return self.sheet_status
        if doctype == 'Bin':
            return self.actual_qty
        self.fail('Unexpected database read: ' + doctype)

    def document(self, doctype, name, **kwargs):
        if doctype == 'Warehouse':
            return Record(name=name, company='UG', is_group=0)
        if doctype == 'Serial No':
            return self.serial
        self.fail('Unexpected document read: ' + doctype)

    def manufactured(self, sheet_status=None):
        self.item_type = 'OUVRAGE'
        if sheet_status is not None:
            self.order.custom_technical_study = 'FT'
            self.sheet_status = sheet_status

    def test_direct_glass_and_accessory_need_no_study(self):
        for item_type, serials in (('PRIMAIRE', 'SN-1'), ('ACCESSOIRE', '')):
            with self.subTest(item_type=item_type):
                self.item_type = item_type
                self.detail.serial_no = serials
                stock.validate_issue(self.doc)
        self.assertFalse(any(call.args[0] == 'Chantier Technical Study'
            for call in self.db.get_value.call_args_list))

    def test_direct_line_can_be_issued_while_another_manufacturing_line_waits_for_study(self):
        other = Record(name='SO-OTHER', item_code='MANUFACTURED', qty=1, stock_qty=1,
            conversion_factor=1, custom_chantier_work_type='TYPE')
        self.order.items.append(other)
        stock.validate_issue(self.doc)

    def test_manufacturing_without_study_is_refused(self):
        self.manufactured()
        self.detail.serial_no = 'SN-1'
        with self.assertRaisesRegex(frappe.ValidationError, 'Valider la fiche technique'):
            stock.validate_issue(self.doc)

    def test_manufacturing_with_draft_study_is_refused(self):
        self.manufactured(0)
        self.detail.serial_no = 'SN-1'
        with self.assertRaisesRegex(frappe.ValidationError, 'Valider la fiche technique'):
            stock.validate_issue(self.doc)

    def test_validated_study_keeps_produced_serial_requirement(self):
        self.manufactured(1)
        with self.assertRaisesRegex(frappe.ValidationError, 'Sélectionner les séries produites'):
            stock.validate_issue(self.doc)

    def test_validated_study_and_matching_produced_serial_are_allowed(self):
        self.manufactured(1)
        self.detail.serial_no = 'SN-1'
        stock.validate_issue(self.doc)

    def test_validated_study_does_not_allow_serial_produced_for_another_line(self):
        self.manufactured(1)
        self.detail.serial_no = 'SN-1'
        self.owners = {'SN-1': 'OTHER-ROW'}
        with self.assertRaisesRegex(frappe.ValidationError, 'produite pour cette ligne'):
            stock.validate_issue(self.doc)

    def test_validated_study_does_not_allow_different_produced_dimensions(self):
        self.manufactured(1)
        self.detail.serial_no = 'SN-1'
        self.serial.custom_dimension_width_mm = 800
        with self.assertRaisesRegex(frappe.ValidationError, 'Dimensions de la série'):
            stock.validate_issue(self.doc)

    def test_direct_sale_keeps_serial_warehouse_check(self):
        self.detail.serial_no = 'SN-1'
        self.serial.warehouse = 'Other - UG'
        with self.assertRaisesRegex(frappe.ValidationError, 'Série indisponible'):
            stock.validate_issue(self.doc)

    def test_direct_sale_keeps_serial_quantity_check(self):
        self.detail.serial_no = 'SN-1'
        self.detail.qty = 2
        with self.assertRaisesRegex(frappe.ValidationError, 'nombre de séries'):
            stock.validate_issue(self.doc)

    def test_direct_sale_keeps_stock_availability_check(self):
        self.actual_qty = 0
        with self.assertRaisesRegex(frappe.ValidationError, 'Stock disponible insuffisant'):
            stock.validate_issue(self.doc)

    def test_direct_sale_cannot_use_another_reservation_serial(self):
        self.detail.serial_no = 'SN-1'
        self.reservations = [Record(name='RES', reserved_qty=1, delivered_qty=0)]
        self.reserved_serials = ['SN-1']
        with self.assertRaisesRegex(frappe.ValidationError, 'série choisie est réservée'):
            stock.validate_issue(self.doc)

    def test_direct_sale_keeps_order_quantity_limit(self):
        self.booked = {self.row.name:2}
        with self.assertRaisesRegex(frappe.ValidationError, 'supérieure au solde'):
            stock.validate_issue(self.doc)
