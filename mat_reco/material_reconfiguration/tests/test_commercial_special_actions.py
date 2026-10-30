"""Modal selection tests: pure mocks, no Frappe site or business documents."""
from copy import deepcopy
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import frappe
from mat_reco.material_reconfiguration.services import commercial_special_actions as actions


class Doc(SimpleNamespace):
    def get(self, key, default=None):
        return getattr(self, key, default)

    def set(self, key, value):
        setattr(self, key, value)

    def append(self, key, value):
        child = Doc(**value)
        getattr(self, key).append(child)
        return child

    def check_permission(self, action):
        pass

    def as_dict(self):
        return deepcopy(vars(self))

    def save(self, *args, **kwargs):
        raise AssertionError('Modal adapters must not save business documents')

    insert = submit = cancel = save


def stop(message, exc=frappe.ValidationError, **kwargs):
    raise exc(message)


def row(identity, *, parent=None, ordered=10, remaining=10):
    return dict(id=identity, parent_id=parent, ordered_qty=ordered, remaining_qty=remaining)


class CommercialSpecialActionTests(unittest.TestCase):
    def setUp(self):
        self.messages = patch.object(actions.frappe, 'throw', side_effect=stop)
        self.messages.start()
        self.addCleanup(self.messages.stop)
        flags = patch.object(actions.frappe, 'flags', frappe._dict(mute_messages=False))
        flags.start()
        self.addCleanup(flags.stop)

    def test_numbers_reject_nonfinite_boolean_and_negative_values(self):
        for value in ('nan', 'inf', float('-inf'), True, -1, 'bad', None):
            with self.subTest(value=value), self.assertRaises(frappe.ValidationError):
                actions._number(value, positive=True)
        self.assertEqual(actions._number('1.25', positive=True), 1.25)
        self.assertEqual(actions._number(0), 0)
        with self.assertRaises(frappe.ValidationError):
            actions._number(0, positive=True)

    def test_malformed_dates_are_validation_errors(self):
        for value in ({}, [], True, 'not-a-date', ''):
            with self.subTest(value=value), self.assertRaises(frappe.ValidationError):
                actions._date(value)
        self.assertEqual(actions._date('2026-10-30'), '2026-10-30')

    def test_duplicate_foreign_and_forged_row_fields_are_rejected(self):
        for selections in ([dict(id='a'), dict(id='a')], [dict(id='a', item_code='FORGED')],
                           [dict(id='')], [dict(id='a', selected='false')]):
            with self.subTest(selections=selections), self.assertRaises(frappe.ValidationError):
                actions._rows(selections)
        with self.assertRaises(frappe.ValidationError):
            actions._delivery_selections(None, [row('own')], [dict(id='foreign', qty=1)])

    def test_delivery_services_remain_independently_selectable(self):
        available = [row('glass'), row('service', parent='glass', ordered=50, remaining=40),
                     row('accessory', parent='glass', ordered=20, remaining=20), row('other')]
        result = actions._delivery_selections(None, available, [dict(id='glass', qty=2),
            dict(id='service', qty=999, selected=False), dict(id='other', qty=1, selected=False)])
        self.assertEqual(result['glass']['qty'], 2)
        self.assertNotIn('service', result)
        self.assertNotIn('accessory', result)
        self.assertNotIn('other', result)

    def test_service_can_be_delivered_alone_with_its_own_remaining_quantity(self):
        available = [row('glass', ordered=10, remaining=4), row('service', parent='glass', ordered=50, remaining=7)]
        result = actions._delivery_selections(None, available, [dict(id='service', qty=2)])
        self.assertEqual(result['service']['qty'], 2)
        self.assertNotIn('glass', result)
        with self.assertRaises(frappe.ValidationError):
            actions._delivery_selections(None, available, [dict(id='glass', qty=5)])
        with self.assertRaises(frappe.ValidationError):
            actions._delivery_selections(None, available, [dict(id='service', qty=8)])

    def test_hidden_read_and_write_field_permlevels_are_rejected(self):
        meta = Mock()
        meta.has_field.return_value = True
        meta.get_permitted_fieldnames.return_value = ['qty']
        with patch.object(actions.frappe, 'get_meta', return_value=meta):
            actions._fields('Bordereau Special Item', ['qty'], 'write', parenttype=actions.DELIVERY)
            for permission in ('read', 'write'):
                with self.subTest(permission=permission), self.assertRaises(frappe.PermissionError):
                    actions._fields('Bordereau Special Item', ['serial_no'], permission, parenttype=actions.DELIVERY)

    def test_table_permission_is_checked_before_its_child_fields(self):
        meta = Mock()
        meta.has_field.return_value = True
        meta.get_field.return_value = Doc(fieldtype='Table', options='Bordereau Special Item')
        meta.get_permitted_fieldnames.return_value = []
        meta.get_permlevel_access.return_value = []
        with patch.object(actions.frappe, 'get_meta', return_value=meta), self.assertRaises(frappe.PermissionError):
            actions._table(actions.DELIVERY, 'items', ['qty'], 'write')

    def test_native_permitted_fieldnames_excludes_table_but_table_level_allows(self):
        parent = Mock()
        parent.get_field.return_value = Doc(fieldtype='Table', options='Bordereau Special Item', permlevel=0)
        parent.get_permitted_fieldnames.return_value = ['warehouse']
        parent.get_permlevel_access.return_value = [0]
        child = Mock()
        child.has_field.return_value = True
        child.get_permitted_fieldnames.return_value = ['qty']
        with patch.object(actions.frappe, 'get_meta', side_effect=[parent, child]):
            actions._table(actions.DELIVERY, 'items', ['qty'], 'write')
        child.get_permitted_fieldnames.assert_called_once_with(parenttype=actions.DELIVERY, permission_type='write')

    def test_protected_write_fields_cannot_reach_native_builder(self):
        source = Doc(doctype='Sales Order')
        with patch.object(actions, '_context', return_value=('delivery', None, None)), \
             patch.object(actions, '_write_context', side_effect=frappe.PermissionError), \
             patch.object(actions, '_apply_delivery') as build, self.assertRaises(frappe.PermissionError):
            actions.build_special(source, 'delivery', [], dict(warehouse='WH'))
        build.assert_not_called()

    def test_prepare_partial_delivery_does_not_validate_the_whole_order(self):
        source_line = Doc(name='line', item_code='GLASS', item_name='Glass', description='Glass', qty=5,
            net_amount=100, uom='PC', warehouse='Stores - UG', conversion_factor=1)
        order = Doc(doctype='Sales Order', name='SO', company='Univers Glass', currency='XOF', items=[source_line])
        stock = dict(rows=[dict(sales_order_item='line', has_serial_no=1, serials=[])], dimensions=[], warehouses=['Stores - UG'])
        from mat_reco.material_reconfiguration.services import ug_warehouse
        with patch.object(actions.special, 'delivered', return_value={'line': 2}), \
             patch.object(actions.special, 'get_delivery_data', return_value=stock), \
             patch.object(actions.special, 'make_delivery') as full_mapping, \
             patch.object(actions.special, 'delivery_validate') as validation, \
             patch.object(ug_warehouse, 'operational_warehouse', return_value='Stores - UG'), \
             patch.object(ug_warehouse, 'is_glass', return_value=True):
            prepared, _, default = actions._delivery_data(order)
        self.assertEqual(prepared[0]['remaining_qty'], 3)
        self.assertEqual(prepared[0]['serial_no'], '')
        self.assertTrue(prepared[0]['selected'])
        self.assertEqual(default, 'Stores - UG')
        full_mapping.assert_not_called()
        validation.assert_not_called()

    def test_automatic_serial_suggestions_are_distinct_across_identical_lines(self):
        from mat_reco.material_reconfiguration.services import production_reservations, ug_warehouse
        lines = [Doc(name='line'+str(i), item_code='PLATE', item_name='Plate', qty=1, net_amount=100,
            uom='PC', warehouse='WH', conversion_factor=1) for i in (1, 2)]
        order = Doc(doctype='Sales Order', name='SO', company='UG', currency='XOF', items=lines)
        candidates = [dict(name='S1', warehouse='WH'), dict(name='S2', warehouse='WH')]
        stock = dict(rows=[dict(sales_order_item=line.name, has_serial_no=1, serials=candidates) for line in lines])
        with patch.object(actions.special, 'delivered', return_value={}), \
             patch.object(actions.special, 'get_delivery_data', return_value=stock), \
             patch.object(ug_warehouse, 'operational_warehouse', return_value='WH'), \
             patch.object(ug_warehouse, 'is_glass', return_value=True), \
             patch.object(production_reservations, 'active_reservations', return_value=[]):
            prepared, _, _ = actions._delivery_data(order)
        self.assertEqual([row['serial_no'] for row in prepared], ['S1', 'S2'])
        self.assertEqual([row['auto_serial_no'] for row in prepared], ['S1', 'S2'])

    def test_partial_delivery_resizes_only_unchanged_automatic_serial_suggestion(self):
        source_line = Doc(name='line', item_code='GLASS')
        order = Doc(doctype='Sales Order', name='SO', company='Univers Glass', customer='C', currency='XOF',
            custom_ug_order_type='B', items=[source_line])
        available = [dict(row('line', ordered=3, remaining=3), warehouse='WH', serial_no='S1\nS2\nS3',
            auto_serial_no='S1\nS2\nS3', conversion_factor=1,
            serials=[dict(name='S'+str(i), warehouse='WH') for i in range(1, 4)])]
        doc = Doc(doctype=actions.DELIVERY, items=[])
        with patch.object(actions, '_delivery_data', return_value=(available, {'dimensions': []}, 'WH')), \
             patch.object(actions, '_warehouse', side_effect=lambda name, company: name), \
             patch.object(actions, 'nowdate', return_value='2026-10-30'), \
             patch.object(actions.frappe, 'new_doc', return_value=doc):
            doc.update = lambda values: vars(doc).update(values)
            built = actions._apply_delivery(order, None, order,
                [dict(id='line', qty=1, serial_no='S1\nS2\nS3')], {})
        self.assertIs(built, doc)
        self.assertEqual(built.items[0].serial_no, 'S1')
        self.assertEqual(built.items[0].qty, 1)

    def test_manual_duplicate_or_unavailable_series_are_rejected(self):
        with self.assertRaises(frappe.ValidationError):
            actions._serials('S1\nS1')
        with self.assertRaises(frappe.ValidationError):
            actions._serials([{'name': 'S1'}])

    def test_submitted_receipt_only_allows_allocate_action(self):
        source = Doc(doctype=actions.PAYMENT, docstatus=1)
        self.assertEqual(actions._action(source, 'allocate'), 'payment')
        with self.assertRaises(frappe.ValidationError):
            actions._action(source, 'edit')
        with self.assertRaises(frappe.ValidationError):
            actions._action(Doc(doctype=actions.PAYMENT, docstatus=0), 'allocate')

    def payment(self, docstatus=0):
        return Doc(doctype=actions.PAYMENT, name='RS', docstatus=docstatus, amount=300, company='UG', customer='C',
            currency='XOF', reference='REFERENCE', posting_date='2026-10-30', mode_of_payment='Cash',
            sales_order='SO', payment_entry='PE' if docstatus else None, allocations=[])

    def test_one_receipt_can_allocate_to_a_and_b_without_creating_another_document(self):
        doc = self.payment(1)
        candidates = [dict(id='BLA', remaining_amount=200), dict(id='BLB', remaining_amount=150)]
        with patch.object(actions, '_payment_doc', return_value=doc), \
             patch.object(actions, '_payment_rows', return_value=candidates):
            result = actions._apply_payment(doc, doc, [dict(id='BLA', amount=100), dict(id='BLB', amount=150)],
                dict(amount=300, reference='REFERENCE'), 'allocate')
        self.assertIs(result, doc)
        self.assertEqual(result.name, 'RS')
        self.assertEqual(result.docstatus, 1)
        self.assertEqual(result.payment_entry, 'PE')
        self.assertEqual(result.amount, 300)
        self.assertEqual([(r.bordereau, r.amount) for r in result.allocations], [('BLA', 100), ('BLB', 150)])

    def test_posted_receipt_header_cannot_be_changed_by_an_allocation(self):
        for changed in (dict(amount=301), dict(reference='FORGED'), dict(posting_date='2026-10-31'),
                        dict(mode_of_payment='Other'), dict(sales_order='OTHER')):
            doc = self.payment(1)
            with self.subTest(changed=changed), patch.object(actions, '_payment_doc', return_value=doc), \
                 patch.object(actions, '_payment_rows', return_value=[]), self.assertRaises(frappe.ValidationError):
                actions._apply_payment(doc, doc, [], changed, 'allocate')

    def test_allocations_must_fit_current_bl_balance_and_cash_received(self):
        for choices in ([dict(id='BLA', amount=201)], [dict(id='BLA', amount=200), dict(id='BLB', amount=150)],
                        [dict(id='FOREIGN', amount=1)]):
            doc = self.payment(1)
            candidates = [dict(id='BLA', remaining_amount=200), dict(id='BLB', remaining_amount=150)]
            with self.subTest(choices=choices), patch.object(actions, '_payment_doc', return_value=doc), \
                 patch.object(actions, '_payment_rows', return_value=candidates), self.assertRaises(frappe.ValidationError):
                actions._apply_payment(doc, doc, choices, {}, 'allocate')

    def test_advance_with_no_allocations_preserves_one_cash_amount(self):
        doc = self.payment(1)
        with patch.object(actions, '_payment_doc', return_value=doc), patch.object(actions, '_payment_rows', return_value=[]):
            result = actions._apply_payment(doc, doc, [], {}, 'allocate')
        self.assertEqual(result.amount, 300)
        self.assertEqual(result.allocations, [])

    def test_hidden_existing_allocation_cannot_be_silently_removed(self):
        doc = self.payment(1)
        doc.allocations = [Doc(bordereau='HIDDEN-BL', amount=100)]
        with patch.object(actions.frappe, 'get_list', return_value=[]), self.assertRaises(frappe.PermissionError):
            actions._payment_rows(doc)

    def test_unselected_broken_native_bl_does_not_block_valid_b_or_advance(self):
        from mat_reco.material_reconfiguration.services import special_a
        names = [Doc(name='BROKEN-A'), Doc(name='VALID-B')]
        documents = {'BROKEN-A': Doc(name='BROKEN-A', order_type='A'),
            'VALID-B': Doc(name='VALID-B', order_type='B', sales_order='SO', net_total=200)}
        for error in (frappe.ValidationError, frappe.PermissionError):
            doc = self.payment()
            warnings = []
            with self.subTest(error=error), patch.object(actions.frappe, 'get_list', return_value=names), \
                 patch.object(actions.frappe, 'get_doc', side_effect=lambda dtype, name: documents[name]), \
                 patch.object(actions, '_payment_delivery_fields'), \
                 patch.object(special_a, 'payment_limit', side_effect=error('PRIVATE-INVOICE')), \
                 patch.object(actions.special, 'allocated', return_value=0):
                rows = actions._payment_rows(doc, warnings)
            self.assertEqual([row['id'] for row in rows], ['VALID-B'])
            self.assertEqual(warnings, ['Bordereau à vérifier.'])
            self.assertFalse(actions.frappe.flags.mute_messages)
            with patch.object(actions, '_payment_doc', return_value=doc), \
                 patch.object(actions, '_payment_rows', return_value=rows):
                result = actions._apply_payment(doc, doc, [], {}, 'allocate')
            self.assertEqual(result.amount, 300)
            self.assertEqual(result.allocations, [])

    def test_broken_previously_allocated_bl_still_raises_native_error(self):
        from mat_reco.material_reconfiguration.services import special_a
        doc = self.payment(1)
        doc.allocations = [Doc(bordereau='PRIOR-A', amount=100)]
        for error in (frappe.ValidationError, frappe.PermissionError):
            with self.subTest(error=error), patch.object(actions.frappe, 'get_list', return_value=[Doc(name='PRIOR-A')]), \
                 patch.object(actions.frappe, 'get_doc', return_value=Doc(name='PRIOR-A', order_type='A')), \
                 patch.object(actions, '_payment_delivery_fields'), \
                 patch.object(special_a, 'payment_limit', side_effect=error('NATIVE-ERROR')), self.assertRaises(error):
                actions._payment_rows(doc, [])
            self.assertFalse(actions.frappe.flags.mute_messages)

    def test_payment_candidates_do_not_swallow_programming_errors(self):
        from mat_reco.material_reconfiguration.services import special_a
        with patch.object(actions.frappe, 'get_list', return_value=[Doc(name='A')]), \
             patch.object(actions.frappe, 'get_doc', return_value=Doc(name='A', order_type='A')), \
             patch.object(actions, '_payment_delivery_fields'), \
             patch.object(special_a, 'payment_limit', side_effect=RuntimeError('BUG')), self.assertRaises(RuntimeError):
            actions._payment_rows(self.payment(), [])
        self.assertFalse(actions.frappe.flags.mute_messages)

    def test_unknown_header_fields_never_reach_a_native_document(self):
        source = Doc(doctype='Sales Order')
        with patch.object(actions, '_context', return_value=('payment', None, None)), \
             patch.object(actions, '_apply_payment') as build, self.assertRaises(frappe.ValidationError):
            actions.build_special(source, 'payment', [], dict(company='FORGED'))
        build.assert_not_called()


if __name__ == '__main__':
    unittest.main()
