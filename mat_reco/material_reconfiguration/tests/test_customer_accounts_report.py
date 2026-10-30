"""Read-only A/B customer report recipes; fixtures are in memory, never a site."""
from collections import Counter
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import frappe

from mat_reco.material_reconfiguration.report.situation_des_comptes_clients import situation_des_comptes_clients as report
from mat_reco.material_reconfiguration.report.situation_des_comptes_clients_b import situation_des_comptes_clients_b as legacy


class Meta:
    def __init__(self, fields=(), tables=None, forbidden=()):
        self.fields = set(fields)
        self.tables = tables or {}
        self.forbidden = set(forbidden)

    def has_field(self, field):
        return field in self.fields or field in self.tables

    def get_permitted_fieldnames(self, **kwargs):
        return self.fields - self.forbidden

    def get_permlevel_access(self, permission):
        return [0]

    def get_field(self, field):
        return SimpleNamespace(permlevel=0, options=self.tables[field]) if field in self.tables else None


class Doc(SimpleNamespace):
    def get(self, key, default=None):
        return getattr(self, key, default)

    def check_permission(self, permission):
        self.checks.append(permission)
        if self.get('denied'):
            raise frappe.PermissionError('Denied')


class CustomerAccountsReportTests(unittest.TestCase):
    def setUp(self):
        self.docs, self.queries = {}, []
        self.child_meta = Meta(('sales_order', 'delivery_note', 'dn_detail', 'against_sales_order',
            'reference_doctype', 'reference_name', 'allocated_amount', 'bordereau', 'amount'))
        self.patchers = [patch.object(report.reports, 'report_access'),
            patch.object(frappe, 'get_list', side_effect=self.get_list),
            patch.object(frappe, 'get_doc', side_effect=lambda dt, name: self.docs[dt, name]),
            patch.object(frappe, 'get_meta', return_value=self.child_meta),
            patch.object(frappe, 'has_permission', return_value=True),
            patch.object(frappe, 'throw', side_effect=lambda message, exc=frappe.ValidationError, **kw: self.reject(message, exc)),
            patch.object(report.b, 'money', side_effect=lambda amount, currency: round(amount, 0 if currency in ('XOF', 'XAF') else 2)),
            patch.object(frappe, 'db', SimpleNamespace(get_value=self.get_value))]
        for patcher in self.patchers:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.order('A1', 'A')
        self.order('B1', 'B')

    def reject(self, message, exc):
        raise exc(message)

    def doc(self, dt, name, **values):
        defaults = dict(doctype=dt, name=name, docstatus=1, company='UG', customer='Client', currency='XOF',
            posting_date='2026-10-15', creation='2026-10-15 08:00:00', checks=[])
        defaults.update(values)
        tables = {key: 'Children' for key in ('items', 'allocations', 'references') if key in defaults}
        defaults['meta'] = Meta(set(defaults) - set(tables), tables)
        doc = Doc(**defaults)
        self.docs[dt, name] = doc
        return doc

    def order(self, name, kind, **values):
        values.setdefault('conversion_rate', 1)
        return self.doc('Sales Order', name, custom_ug_order_type=kind, **values)

    def invoice(self, name='INV-A', order='A1', amount=118, **values):
        defaults = dict(grand_total=amount, rounded_total=amount, paid_amount=0, write_off_amount=0,
            is_pos=0, is_opening='No', conversion_rate=1, party_account_currency='XOF', return_against=None,
            items=[frappe._dict(sales_order=order)])
        defaults.update(values)
        return self.doc('Sales Invoice', name, **defaults)

    def delivery(self, name='BL-B', order='B1', kind='B', amount=100, **values):
        return self.doc(report.b.DELIVERY, name, sales_order=order, order_type=kind,
            net_total=amount, grand_total=amount if kind == 'B' else 118, **values)

    def receipt(self, name='RS-B', amount=40, allocations=None, order='B1', kind='B', **values):
        return self.doc(report.b.PAYMENT, name, sales_order=order, order_type=kind, amount=amount,
            payment_entry=None, allocations=[frappe._dict(bordereau=bl, amount=value) for bl, value in allocations or []], **values)

    def payment(self, name='PE-A', amount=58, refs=None, unallocated=0, **values):
        defaults = dict(party='Client', party_type='Customer', payment_type='Receive', paid_amount=amount,
            received_amount=amount, paid_from_account_currency='XOF', paid_to_account_currency='XOF', unallocated_amount=unallocated,
            references=[frappe._dict(reference_doctype=dt, reference_name=ref, allocated_amount=value) for dt, ref, value in refs or [('Sales Invoice', 'INV-A', amount - unallocated)]])
        defaults.update(values)
        return self.doc('Payment Entry', name, **defaults)

    def get_value(self, dt, name, fields, as_dict=False):
        doc = self.docs.get((dt, name))
        if not doc:
            return None
        if isinstance(fields, str):
            return doc.get(fields)
        values = {field: doc.get(field) for field in fields}
        return frappe._dict(values) if as_dict else list(values.values())

    def match(self, doc, field, condition):
        value = doc.get(field)
        if isinstance(condition, list):
            op, expected = condition
            if op == 'in':
                return value in expected
            if op == '<=':
                return value is not None and value <= expected
            if op == 'is':
                return not value if expected == 'not set' else bool(value)
            return value == expected
        return value == condition

    def get_list(self, dt, filters=None, fields=None, pluck=None, or_filters=None, **kwargs):
        self.queries.append(dt)
        result = []
        for (doctype, name), doc in self.docs.items():
            if doctype != dt or not all(self.match(doc, field, condition) for field, condition in (filters or {}).items()):
                continue
            if or_filters and not any(self.match(doc, row[0], row[1:]) for row in or_filters):
                continue
            result.append(doc.get(pluck) if pluck else frappe._dict({field: doc.get(field) for field in fields or ('name',)}))
        return result

    def run_report(self, **filters):
        values = dict(from_date='2026-10-01', to_date='2026-10-31')
        values.update(filters)
        return report.execute(values)[1]

    def final(self, data, kind, currency='XOF'):
        return next(row['balance'] for row in reversed(data)
            if row['description'] == 'Solde final' and row['order_type'] == kind and row['currency'] == currency)

    def test_default_all_keeps_a_ttc_b_ht_and_mixed_payment_shares_separate(self):
        self.invoice()
        self.delivery()
        self.delivery('BL-A', 'A1', 'A')
        self.receipt('RS-M', 98, [('BL-B', 40), ('BL-A', 58)], kind='Mixte')
        self.payment()
        rows = self.run_report()
        self.assertEqual(self.final(rows, 'A'), 60)
        self.assertEqual(self.final(rows, 'B'), 60)
        movements = [row for row in rows if row.get('reference_name')]
        self.assertEqual(Counter(row['reference_name'] for row in movements), {'INV-A': 1, 'PE-A': 1, 'BL-B': 1, 'RS-M': 1})
        self.assertEqual({row['basis'] for row in rows if row['order_type'] == 'A'}, {'TTC'})
        self.assertEqual({row['basis'] for row in rows if row['order_type'] == 'B'}, {'HT'})

    def test_b_only_never_queries_native_accounting(self):
        self.invoice()
        self.delivery()
        self.receipt()
        rows = self.run_report(order_type='B')
        self.assertEqual({row['order_type'] for row in rows}, {'B'})
        self.assertNotIn('Sales Invoice', self.queries)
        self.assertNotIn('Payment Entry', self.queries)

    def test_a_only_does_not_add_special_delivery_or_receipt_again(self):
        self.invoice()
        self.delivery('BL-A', 'A1', 'A')
        self.receipt('RS-A', 58, [('BL-A', 58)], order='A1', kind='A').payment_entry = 'PE-A'
        self.payment()
        rows = self.run_report(order_type='A')
        self.assertEqual(self.final(rows, 'A'), 60)
        self.assertFalse(any(row.get('reference_name') in ('BL-A', 'RS-A') for row in rows))

    def test_one_native_payment_covering_several_invoices_counted_once(self):
        self.order('A2', 'A')
        self.invoice()
        self.invoice('INV-2', 'A2', 236)
        self.payment(amount=200, refs=[('Sales Invoice', 'INV-A', 118), ('Sales Invoice', 'INV-2', 82)])
        rows = self.run_report(order_type='A')
        self.assertEqual(self.final(rows, 'A'), 154)
        self.assertEqual(len([row for row in rows if row.get('reference_name') == 'PE-A']), 1)
        order_rows = self.run_report(order_type='A', sales_order='A2')
        self.assertEqual(self.final(order_rows, 'A'), 154)

    def test_native_advances_including_special_unallocated_source(self):
        self.payment(amount=50, refs=[('Sales Order', 'A1', 30)], unallocated=20)
        rows = self.run_report(order_type='A', sales_order='A1')
        self.assertEqual(self.final(rows, 'A'), -50)
        self.docs.pop(('Payment Entry', 'PE-A'))
        self.receipt('RS-A', 75, order='A1', kind='A').payment_entry = 'PE-ADV'
        self.payment('PE-ADV', 75, refs=[], unallocated=75).references = []
        rows = self.run_report(order_type='A')
        self.assertEqual(self.final(rows, 'A'), -75)

    def test_untagged_native_payment_and_unrelated_invoice_are_not_assumed_a(self):
        self.invoice(order=None)
        self.payment(refs=[], unallocated=58).references = []
        rows = self.run_report(order_type='A')
        self.assertEqual(self.final(rows, 'A'), 0)
        self.assertFalse(any(row.get('reference_name') for row in rows))

    def test_native_credit_note_and_refund_are_signed_correctly(self):
        self.invoice()
        self.invoice('RETURN', amount=-118)
        self.payment(amount=118)
        self.payment('REFUND', 118, refs=[('Sales Invoice', 'RETURN', -118)], payment_type='Pay')
        rows = self.run_report(order_type='A')
        self.assertEqual(self.final(rows, 'A'), 0)
        refund = next(row for row in rows if row.get('reference_name') == 'REFUND')
        self.assertEqual(refund['debit'], 118)
        self.assertEqual(refund['credit'], 0)

    def test_invoice_order_can_be_read_through_delivery_note_and_return_origin(self):
        self.doc('Delivery Note', 'DN', items=[frappe._dict(name='DN-ITEM', against_sales_order='A1')])
        self.invoice(items=[frappe._dict(delivery_note='DN', dn_detail='DN-ITEM')])
        self.invoice('RETURN', amount=-118, items=[frappe._dict()], return_against='INV-A')
        rows = self.run_report(order_type='A', sales_order='A1')
        self.assertEqual(self.final(rows, 'A'), 0)

    def test_multi_order_invoice_is_whole_in_global_and_refused_for_order_filter(self):
        self.order('A2', 'A')
        self.invoice(items=[frappe._dict(sales_order='A1'), frappe._dict(sales_order='A2')])
        self.assertEqual(self.final(self.run_report(order_type='A'), 'A'), 118)
        with self.assertRaisesRegex(frappe.ValidationError, 'plusieurs commandes A'):
            self.run_report(order_type='A', sales_order='A1')

    def test_manual_invoice_lines_are_not_silently_attributed_to_one_order(self):
        self.invoice(items=[frappe._dict(sales_order='A1'), frappe._dict(sales_order=None)])
        rows = self.run_report(order_type='A')
        self.assertEqual(self.final(rows, 'A'), 118)
        self.assertIsNone(next(row for row in rows if row.get('reference_name') == 'INV-A')['sales_order'])
        with self.assertRaisesRegex(frappe.ValidationError, 'lignes sans commande'):
            self.run_report(order_type='A', sales_order='A1')

    def test_missing_native_accounting_access_is_explicit_and_b_remains_available(self):
        with patch.object(frappe, 'has_permission', side_effect=lambda dt, *args, **kw: dt != 'Sales Invoice'):
            with self.assertRaisesRegex(frappe.PermissionError, 'Sélectionner le type B'):
                self.run_report()
            self.assertEqual(self.final(self.run_report(order_type='B'), 'B'), 0)

    def test_multi_order_unallocated_advance_is_never_guessed_for_order(self):
        self.order('A2', 'A')
        self.invoice()
        self.invoice('INV-2', 'A2', 118)
        self.payment(amount=150, refs=[('Sales Invoice', 'INV-A', 50), ('Sales Invoice', 'INV-2', 50)], unallocated=50)
        self.assertEqual(self.final(self.run_report(order_type='A'), 'A'), 86)
        with self.assertRaisesRegex(frappe.ValidationError, 'avance commune'):
            self.run_report(order_type='A', sales_order='A1')

    def test_period_opening_and_no_movement_keep_debit_or_credit_balance(self):
        self.invoice(posting_date='2026-09-30')
        self.payment(posting_date='2026-09-30')
        rows = self.run_report(order_type='A')
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]['balance'], 60)
        self.assertEqual(rows[-1]['balance'], 60)
        self.doc(report.b.OPENING, 'OPEN', sales_order=None, amount=-100, posting_date='2026-10-01')
        rows = self.run_report(order_type='B')
        self.assertEqual(len(rows), 2)
        self.assertEqual(self.final(rows, 'B'), -100)

    def test_advance_later_allocated_to_future_invoice_stays_in_original_period(self):
        self.invoice(posting_date='2026-11-15')
        self.payment(posting_date='2026-10-15')
        october = self.run_report(order_type='A')
        self.assertEqual(self.final(october, 'A'), -58)
        self.assertFalse(any(row.get('reference_name') == 'INV-A' for row in october))
        november = self.run_report(order_type='A', from_date='2026-11-01', to_date='2026-11-30')
        self.assertEqual(november[0]['balance'], -58)
        self.assertEqual(self.final(november, 'A'), 60)

    def test_invoice_opening_on_first_day_is_initial_not_a_second_debit(self):
        self.invoice(is_opening='Yes', posting_date='2026-10-01')
        rows = self.run_report(order_type='A')
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]['balance'], 118)

    def test_canceled_native_or_special_documents_are_excluded(self):
        self.invoice(docstatus=2)
        self.payment(docstatus=2)
        self.delivery(docstatus=2)
        self.receipt(docstatus=2)
        self.assertTrue(all(row['balance'] == 0 for row in self.run_report()))

    def test_currency_group_uses_native_conversion_and_never_mixes_balances(self):
        self.order('USD-A', 'A', currency='USD', conversion_rate=600)
        self.invoice('USD-INV', 'USD-A', 100, currency='USD', conversion_rate=600)
        self.doc('Company', 'UG', default_currency='XOF')
        self.payment(amount=30000, refs=[('Sales Invoice', 'USD-INV', 30000)])
        rows = self.run_report(order_type='A', currency='USD')
        self.assertEqual(self.final(rows, 'A', 'USD'), 50)
        self.assertTrue(all(row['currency'] == 'USD' for row in rows))

    def test_parent_and_financial_field_permissions_are_not_bypassed(self):
        self.invoice().denied = True
        with self.assertRaises(frappe.PermissionError):
            self.run_report(order_type='A')
        self.docs['Sales Invoice', 'INV-A'].denied = False
        self.docs['Sales Invoice', 'INV-A'].meta.forbidden.add('grand_total')
        with self.assertRaises(frappe.PermissionError):
            self.run_report(order_type='A')

    def test_invalid_filter_and_mismatching_order_are_rejected(self):
        with self.assertRaises(frappe.ValidationError):
            self.run_report(order_type='invalid')
        with self.assertRaises(frappe.ValidationError):
            self.run_report(order_type='A', sales_order='B1')

    def test_legacy_import_remains_b_only_by_default(self):
        self.invoice()
        self.delivery()
        rows = legacy.execute(dict(from_date='2026-10-01', to_date='2026-10-31'))[1]
        self.assertEqual({row['order_type'] for row in rows}, {'B'})


if __name__ == '__main__':
    unittest.main()
