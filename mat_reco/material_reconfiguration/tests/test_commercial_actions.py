"""Modal orchestration tests with mocks: no site or fiscal/accounting writes."""
from contextlib import nullcontext
from types import SimpleNamespace
import sys
import unittest
from unittest.mock import MagicMock, patch

import frappe
from mat_reco.material_reconfiguration.services import commercial_actions as actions


class Doc:
    def __init__(self, doctype='Sales Order', name='SO', docstatus=0, new=False, **values):
        self.doctype, self.name, self.docstatus = doctype, name, docstatus
        self.modified = '2026-10-30 12:00:00'
        self.meta = SimpleNamespace(is_submittable=True)
        self.new, self.values, self.calls = new, values, []

    def __getattr__(self, key):
        if key in self.__dict__.get('values', {}):
            return self.values[key]
        raise AttributeError(key)

    def get(self, key, default=None):
        return getattr(self, key, self.values.get(key, default))

    def set(self, key, value):
        self.values[key] = value

    def is_new(self):
        return self.new

    def check_permission(self, permission):
        self.calls.append(('permission', permission))

    def has_permission(self, permission):
        return True

    def insert(self, **kwargs):
        self.calls.append(('insert', kwargs))
        self.new = False
        return self

    def save(self):
        self.calls.append(('save',))
        return self

    def submit(self):
        self.calls.append(('submit',))
        self.docstatus = 1

    def as_dict(self):
        return dict(doctype=self.doctype, name=self.name, docstatus=self.docstatus)

    def reload(self):
        self.calls.append(('reload',))
        return self


def rows():
    return [dict(id='parent', ordered_qty=10, remaining_qty=6, parent_id=None),
        dict(id='service', ordered_qty=25, remaining_qty=15, parent_id='parent'),
        dict(id='accessory', ordered_qty=20, remaining_qty=12, parent_id='parent')]


class CommercialActionTests(unittest.TestCase):
    def setUp(self):
        # Native frappe.throw formats a request response; pure tests only need
        # its documented exception contract, without an initialized site.
        def reject(message, exc=frappe.ValidationError, *args, **kwargs):
            raise exc(message)
        self.throw = patch.object(actions.frappe, 'throw', side_effect=reject)
        self.throw.start()
        self.addCleanup(self.throw.stop)
        native_flt = actions.flt
        # Native precision rounding consults System Settings. Pure tests use
        # an explicit rounding policy instead of opening a database connection.
        def number(value, precision=None):
            value = native_flt(value)
            return round(value, precision) if precision is not None else value
        precision = patch.object(actions, 'flt', side_effect=number)
        precision.start()
        self.addCleanup(precision.stop)

    def test_partial_parent_inherits_all_services_at_ratio(self):
        selected = actions._selection(rows(), [dict(id='parent', qty=2)])
        self.assertEqual(selected, dict(parent=2, service=5, accessory=4))

    def test_chantier_quantities_stay_whole_and_preview_uses_surface_and_line_discount(self):
        source = Doc('Chantier', 'CH', 1)
        source.discount_mode = 'Pourcentage'
        macro = frappe._dict(name='row', line_id='parent', qty=10, rate=100, designation='Glass',
            uom='PC', price_per_sqm=1, length_mm=2000, width_mm=1000, discount_percentage=10)
        with patch.object(actions, '_read_rows', return_value=[macro]), \
                patch('mat_reco.material_reconfiguration.services.chantier_service.get_quotation_usage', return_value={'parent':4}):
            prepared = actions._quote_rows(source)
        self.assertEqual(prepared[0]['rate'], 180)
        self.assertEqual(prepared[0]['amount'], 1080)
        with self.assertRaises(frappe.ValidationError):
            actions._selection(prepared, [dict(id='parent', qty=1.5)])

    def test_draft_can_increase_to_residual_excluding_itself(self):
        source = Doc('Sales Order', 'SO', 0)
        source.items = [frappe._dict(name='row', qty=2, rate=100, prevdoc_docname='Q', quotation_item='origin')]
        quote = Doc('Quotation', 'Q', 1)
        original = [frappe._dict(name='origin', qty=10)]
        rows = [dict(id='row', ordered_qty=2, remaining_qty=2, parent_id=None)]
        with patch.object(actions.frappe, 'get_doc', return_value=quote), \
                patch.object(actions, '_read_rows', return_value=original), \
                patch.object(actions, '_order_usage', return_value={'origin':3}) as usage:
            actions._draft_limits(source, rows)
        usage.assert_called_once_with('Q', exclude='SO')
        self.assertEqual(rows[0]['remaining_qty'], 7)
        self.assertEqual(actions._selection(rows, [dict(id='row', qty=6)])['row'], 6)

    def test_order_mapper_gets_only_selected_parent_and_all_attached_rows(self):
        source = Doc('Quotation', 'Q', 1)
        target = Doc('Sales Order', None, new=True)
        target.items = [frappe._dict(quotation_item=name, qty=10, conversion_factor=1) for name in ('parent', 'service', 'accessory')]
        target.run_method = MagicMock()
        target.calculate_taxes_and_totals = MagicMock()
        native = MagicMock(return_value=target)
        with patch.dict(sys.modules, {'erpnext.selling.doctype.quotation.quotation':SimpleNamespace(make_sales_order=native)}), \
                patch.object(actions.frappe, 'new_doc', return_value=target), \
                patch.object(actions, '_commercial_rows', return_value=rows()), \
                patch.object(actions, '_headers'), patch.object(actions, '_scale_order_charges'):
            actions._build_order(source, [dict(id='parent', qty=2)], {})
        self.assertEqual(set(native.call_args.kwargs['args']['filtered_children']), {'parent', 'service', 'accessory'})
        self.assertEqual({row.quotation_item:row.qty for row in target.items}, {'parent':2, 'service':5, 'accessory':4})
        target.run_method.assert_called_once_with('calculate_taxes_and_totals')

    def test_high_fixed_discount_is_scaled_before_native_mapper_calculates(self):
        quote = Doc('Quotation', 'Q', 1, discount_amount=900, additional_discount_percentage=0, taxes=[])
        quote.items = [frappe._dict(name='parent', qty=10, amount=1000)]
        target = Doc('Sales Order', None, new=True, taxes=[])
        target.items = [frappe._dict(quotation_item='parent', qty=10, conversion_factor=1)]
        target.precision = lambda field: 2
        target.run_method = MagicMock()
        calculated = []

        def calculate():
            # This is the native failure trigger for an unscaled full discount.
            self.assertLessEqual(target.discount_amount, target.items[0].qty * 100)
            calculated.append(target.discount_amount)

        target.calculate_taxes_and_totals = calculate

        def native(source_name, target_doc, args):
            target_doc.discount_amount = 900
            target_doc.calculate_taxes_and_totals()
            return target_doc

        available = [dict(id='parent', ordered_qty=10, remaining_qty=10, parent_id=None)]
        with patch.dict(sys.modules, {'erpnext.selling.doctype.quotation.quotation':SimpleNamespace(make_sales_order=native)}), \
                patch.object(actions.frappe, 'new_doc', return_value=target), \
                patch.object(actions.frappe, 'db', MagicMock(sql=MagicMock(return_value=[]))), \
                patch.object(actions, '_order_usage', return_value={}), \
                patch.object(actions, '_commercial_rows', return_value=available), patch.object(actions, '_headers'):
            actions._build_order(quote, [dict(id='parent', qty=1)], {})
        self.assertEqual(calculated, [90])
        self.assertEqual(target.discount_amount, 90)

    def test_editing_partial_order_reallocates_fixed_discount_excluding_own_usage(self):
        quote = Doc('Quotation', 'Q', 1, discount_amount=900, additional_discount_percentage=0, taxes=[])
        quote.items = [frappe._dict(name='origin', qty=10, amount=1000)]
        draft = Doc('Sales Order', 'SO', 0, discount_amount=450, additional_discount_percentage=0, taxes=[])
        draft.items = [frappe._dict(name='so-line', quotation_item='origin', prevdoc_docname='Q', qty=5, amount=500)]
        draft.precision = lambda field: 2
        draft.meta = SimpleNamespace(get_field=lambda field:SimpleNamespace(options='Sales Order Item', permlevel=0),
            get_permlevel_access=lambda permission:[0])
        childmeta = SimpleNamespace(get_permitted_fieldnames=lambda **kwargs:['qty'])
        available = [dict(id='so-line', ordered_qty=5, remaining_qty=10, parent_id=None)]
        with patch.object(actions.frappe, 'get_meta', return_value=childmeta), \
                patch.object(actions.frappe, 'get_doc', return_value=quote), \
                patch.object(actions.frappe, 'db', MagicMock(sql=MagicMock(return_value=[]))), \
                patch.object(actions, '_commercial_rows', return_value=available), \
                patch.object(actions, '_read_rows', return_value=quote.items), \
                patch.object(actions, '_headers'), patch.object(actions, '_order_usage', return_value={}) as usage:
            actions._edit(draft, [dict(id='so-line', qty=1)], {})
        self.assertEqual(draft.items[0].qty, 1)
        self.assertEqual(draft.discount_amount, 90)
        self.assertTrue(usage.call_count >= 2)
        for call in usage.call_args_list:
            self.assertEqual(call.kwargs['exclude'], 'SO')

    def test_foreign_duplicate_and_orphan_child_ids_are_rejected(self):
        for selected in ([dict(id='foreign', qty=1)], [dict(id='parent', qty=1)] * 2,
                [dict(id='service', qty=1)]):
            with self.subTest(selected=selected), self.assertRaises(frappe.ValidationError):
                actions._selection(rows(), selected)

    def test_explicit_service_qty_cannot_break_approved_ratio(self):
        with self.assertRaises(frappe.ValidationError):
            actions._selection(rows(), [dict(id='parent', qty=2), dict(id='service', qty=4)])
        self.assertEqual(actions._selection(rows(), [dict(id='parent', qty=2), dict(id='service', qty=5)])['service'], 5)

    def test_no_finite_positive_or_residual_bypass(self):
        for quantity in (None, True, 0, -1, float('inf'), float('nan'), 'infinity', 7):
            with self.subTest(quantity=quantity), self.assertRaises(frappe.ValidationError):
                actions._selection(rows(), [dict(id='parent', qty=quantity)])

    def test_insufficient_service_residual_prevents_parent_order(self):
        data = rows()
        data[1]['remaining_qty'] = 3
        with self.assertRaises(frappe.ValidationError):
            actions._selection(data, [dict(id='parent', qty=2)])

    def test_payload_does_not_accept_rate_or_item_replacement(self):
        with self.assertRaises(frappe.ValidationError):
            actions._selection(rows(), [dict(id='parent', qty=1, rate=0)])
        source = Doc()
        with self.assertRaises(frappe.ValidationError):
            actions._headers(source, dict(customer='another'))

    def test_submit_never_bypasses_active_workflow(self):
        doc = Doc(new=True)
        permissions = dict(can_save=True, can_submit=False, workflow_name='Approvals', workflow_actions=[])
        with patch.object(actions, 'submission', return_value=permissions), self.assertRaises(frappe.ValidationError):
            actions._apply_intent(doc, 'submit', None)
        self.assertFalse(any(call[0] in ('insert', 'submit') for call in doc.calls))

    def test_native_new_draft_submit_checks_create_and_submit(self):
        doc = Doc(new=True)
        permissions = dict(can_save=True, can_submit=True, workflow_name='', workflow_actions=[])
        with patch.object(actions, 'submission', return_value=permissions):
            actions._apply_intent(doc, 'submit', None)
        self.assertIn(('permission', 'create'), doc.calls)
        self.assertIn(('permission', 'submit'), doc.calls)
        self.assertEqual([call[0] for call in doc.calls if call[0] in ('insert', 'submit')], ['insert', 'submit'])

    def test_workflow_requires_current_permitted_explicit_transition(self):
        doc = Doc()
        permissions = dict(can_save=True, can_submit=False, workflow_name='Approvals',
            workflow_actions=[dict(action='Approve', next_state='Approved', docstatus=1)])
        with patch.object(actions, 'submission', return_value=permissions), self.assertRaises(frappe.PermissionError):
            actions._apply_intent(doc, 'workflow', 'Forged approval')
        with patch.object(actions, 'submission', return_value=permissions), \
                patch('frappe.model.workflow.apply_workflow', return_value=doc) as native:
            actions._apply_intent(doc, 'workflow', 'Approve')
        native.assert_called_once_with(doc.as_dict(), 'Approve')

    def test_actions_require_access_to_special_modules(self):
        with patch.object(actions.frappe, 'has_permission', return_value=False):
            for method, args in ((actions.get_actions, ('Sales Order', 'SO')),
                    (actions.prepare_action, ('Sales Order', 'SO', 'delivery')),
                    (actions.execute_action, ('Sales Order', 'SO', 'delivery'))):
                with self.subTest(method=method.__name__), self.assertRaises(frappe.PermissionError):
                    method.__wrapped__(*args)

    def test_cancelled_history_has_no_actions(self):
        source = Doc('Sales Order', 'SO', 2)
        with patch.object(actions, '_access'), patch.object(actions, '_source', return_value=source):
            self.assertEqual(actions.get_actions.__wrapped__('Sales Order', 'SO'), [])

    def test_new_quotation_keeps_inherited_terms_and_validity_default(self):
        source = Doc('Chantier', 'CH', 1, terms='Approved terms')
        target = Doc('Quotation', None, new=True)
        fields = [dict(fieldname=name) for name in ('transaction_date', 'valid_till', 'terms')]
        with patch.object(actions, '_fields', return_value=fields), \
                patch.object(actions.frappe, 'has_permission', return_value=True), \
                patch.object(actions.frappe, 'new_doc', return_value=target), \
                patch.object(actions, '_commercial_rows', return_value=[]), \
                patch.object(actions, 'nowdate', return_value='2026-10-30'):
            prepared = actions._prepare(source, 'quotation')
        self.assertEqual(prepared['values']['terms'], 'Approved terms')
        self.assertEqual(prepared['values']['valid_till'], '2026-11-29')

    def test_validate_retry_survives_its_own_source_state_change(self):
        source = Doc('Sales Order', 'SO', 1)
        database = MagicMock()
        database.get_value.return_value = SimpleNamespace(scope='same', target_doctype='Sales Order', target_name='SO')
        with patch.object(actions, '_access'), patch.object(actions, '_source', return_value=source), \
                patch.object(actions, 'fingerprint', side_effect=['key', 'same']), \
                patch.object(actions.frappe, 'session', SimpleNamespace(user='user')), \
                patch.object(actions.frappe, 'db', database), \
                patch.object(actions.frappe, 'get_doc', return_value=source), \
                patch.object(actions, '_result', return_value={'replay':True}), \
                patch('mat_reco.material_reconfiguration.services.special_a.operation', return_value=nullcontext()):
            result = actions.execute_action.__wrapped__('Sales Order', 'SO', 'validate', source_modified='old', request_key='id', intent='submit')
        self.assertTrue(result['replay'])

    def test_row_table_and_field_permissions_are_required(self):
        source = Doc()
        source.meta = SimpleNamespace(get_field=lambda name: SimpleNamespace(options='Sales Order Item', permlevel=1),
            get_permlevel_access=lambda permission: [0])
        with self.assertRaises(frappe.PermissionError):
            actions._read_rows(source, 'items')
        source.meta.get_permlevel_access = lambda permission: [0, 1]
        meta = SimpleNamespace(get_permitted_fieldnames=lambda **kwargs: ['qty', 'name'], has_field=lambda name: False)
        with patch.object(actions.frappe, 'get_meta', return_value=meta), self.assertRaises(frappe.PermissionError):
            actions._read_rows(source, 'items')

    def test_retry_is_checked_before_stale_source_and_does_not_create_again(self):
        source = Doc('Quotation', 'Q', 1)
        target = Doc('Sales Order', 'SO', 1)
        database = MagicMock()
        database.get_value.return_value = SimpleNamespace(scope='same', target_doctype='Sales Order', target_name='SO')
        with patch.object(actions, '_access'), patch.object(actions, '_source', return_value=source), \
                patch.object(actions, 'fingerprint', side_effect=['key', 'same']), \
                patch.object(actions.frappe, 'session', SimpleNamespace(user='user')), \
                patch.object(actions.frappe, 'db', database), \
                patch.object(actions.frappe, 'get_doc', return_value=target), \
                patch.object(actions, '_result', return_value={'replay':True}) as result, \
                patch('mat_reco.material_reconfiguration.services.special_a.operation', return_value=nullcontext()), \
                patch.object(actions, '_build_order') as build:
            returned = actions.execute_action.__wrapped__('Quotation', 'Q', 'order', source_modified='old', request_key='id')
        self.assertTrue(returned['replay'])
        build.assert_not_called()
        result.assert_called_once_with(target, replay=True)
        self.assertFalse(database.rollback.called)

    def test_reused_key_with_another_scope_rolls_back(self):
        source = Doc('Quotation', 'Q', 1)
        database = MagicMock()
        database.get_value.return_value = SimpleNamespace(scope='other', target_doctype='Sales Order', target_name='SO')
        with patch.object(actions, '_access'), patch.object(actions, '_source', return_value=source), \
                patch.object(actions, 'fingerprint', side_effect=['key', 'same']), \
                patch.object(actions.frappe, 'session', SimpleNamespace(user='user')), \
                patch.object(actions.frappe, 'db', database), \
                patch('mat_reco.material_reconfiguration.services.special_a.operation', return_value=nullcontext()), \
                self.assertRaises(frappe.ValidationError):
            actions.execute_action.__wrapped__('Quotation', 'Q', 'order', source_modified=source.modified, request_key='id')
        database.rollback.assert_called_once()

    def test_native_permission_failure_rolls_back_without_journal(self):
        source = Doc('Quotation', 'Q', 1)
        target = Doc(new=True)
        database = MagicMock()
        database.get_value.return_value = None
        with patch.object(actions, '_access'), patch.object(actions, '_source', return_value=source), \
                patch.object(actions.frappe, 'session', SimpleNamespace(user='user')), \
                patch.object(actions.frappe, 'db', database), \
                patch.object(actions.frappe, 'has_permission', return_value=True), \
                patch.object(actions.frappe, 'get_doc') as journal, \
                patch.object(actions, '_build_order', return_value=target), \
                patch.object(actions, '_apply_intent', side_effect=frappe.PermissionError('denied')), \
                patch('mat_reco.material_reconfiguration.services.special_a.operation', return_value=nullcontext()), \
                self.assertRaises(frappe.PermissionError):
            actions.execute_action.__wrapped__('Quotation', 'Q', 'order', source_modified=source.modified, request_key='id')
        database.rollback.assert_called_once()
        journal.assert_not_called()

    def test_fixed_charges_use_remaining_amount_after_standard_first_order(self):
        tax = lambda idx, amount: SimpleNamespace(idx=idx, charge_type='Actual', tax_amount=amount,
            account_head='Freight', description='Freight', precision=lambda field: 2)
        quote = Doc('Quotation', 'Q', 1, discount_amount=50, additional_discount_percentage=0,
            taxes=[tax(1, 100)])
        quote.items = [frappe._dict(name='row', qty=10, amount=1000)]
        quote.discount_amount = 50
        quote.additional_discount_percentage = 0
        prior = Doc('Sales Order', 'previous', 1, taxes=[tax(1, 100)])
        prior.items = [frappe._dict(prevdoc_docname='Q')]
        prior.discount_amount = 50
        target = Doc('Sales Order', None, taxes=[tax(1, 100)])
        target.precision = lambda field: 2
        with patch.object(actions.frappe, 'db', MagicMock(sql=MagicMock(return_value=['previous']))), \
                patch.object(actions.frappe, 'get_doc', return_value=prior), \
                patch.object(actions, '_order_usage', return_value={'row':4}):
            actions._scale_order_charges(quote, target, {'row':6})
        self.assertEqual(target.discount_amount, 0)
        self.assertEqual(target.get('taxes')[0].tax_amount, 0)

    def test_fixed_charges_reject_unattributable_prior_mixed_order(self):
        quote = Doc('Quotation', 'Q', discount_amount=50, additional_discount_percentage=0, taxes=[])
        quote.items = [frappe._dict(name='row', qty=10, amount=1000)]
        prior = Doc('Sales Order', 'previous', 1, taxes=[])
        prior.items = [frappe._dict(prevdoc_docname='Q'), frappe._dict(prevdoc_docname='OTHER')]
        prior.discount_amount = 50
        with patch.object(actions.frappe, 'db', MagicMock(sql=MagicMock(return_value=['previous']))), \
                patch.object(actions.frappe, 'get_doc', return_value=prior), self.assertRaises(frappe.ValidationError):
            actions._scale_order_charges(quote, Doc(), {'row':6})


if __name__ == '__main__':
    unittest.main()
