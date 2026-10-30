"""A/B follow-up arithmetic without a site, business writes or transactions."""
from copy import deepcopy
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import frappe

from mat_reco.material_reconfiguration.report.suivi_commandes import suivi_commandes as report
from mat_reco.material_reconfiguration.services import commercial_cockpit as commercial


def snapshot():
    data = {kind: [] for kind in commercial.DT}
    data.update(capabilities={'can_read_' + key: True for key in commercial.CAP.values()},
        companies=[dict(name='UG', default_currency='XOF')], incomplete_children=set())
    for field in ('invoice_items', 'native_delivery_items', 'payment_references', 'allocations'):
        data[field] = []
    return data


def order(name, kind='A'):
    return dict(name=name, customer='C', company='UG', currency='XOF', docstatus=1,
        custom_ug_order_type=kind, net_total=1000, grand_total=1180, conversion_rate=1)


def add_a(data):
    data['order'].append(order('A'))
    data['native_delivery'].append(dict(name='DN', docstatus=1, grand_total=236))
    data['native_delivery_items'].append(dict(parent='DN', against_sales_order='A'))
    data['invoice'].append(dict(name='SI', docstatus=1, company='UG', currency='XOF',
        party_account_currency='XOF', grand_total=236, outstanding_amount=136))
    data['invoice_items'].append(dict(parent='SI', sales_order='A'))


def add_b(data):
    data['order'].append(order('B', 'B'))
    data['delivery'].append(dict(name='BLB', sales_order='B', order_type='B', docstatus=1,
        currency='XOF', net_total=300, grand_total=354))


class OrderFollowupTests(unittest.TestCase):
    def test_standard_a_uses_native_ttc_and_invoice_balance(self):
        data = snapshot()
        add_a(data)
        row = report.financial_metrics(data)['A']
        self.assertEqual(row['order_amount'], 1180)
        self.assertEqual(row['delivery_amount'], 236)
        self.assertEqual(row['bl_count'], 1)
        self.assertEqual(row['received'], 100)
        self.assertEqual(row['delivery_balance'], 136)

    def test_a_special_delivery_does_not_duplicate_its_native_document(self):
        data = snapshot()
        add_a(data)
        data['delivery'].append(dict(name='BLA', sales_order='A', order_type='A', docstatus=1,
            net_total=200, grand_total=236, delivery_note='DN', sales_invoice='SI'))
        row = report.financial_metrics(data)['A']
        self.assertEqual(row['bl_count'], 1)
        self.assertEqual(row['delivery_amount'], 236)
        self.assertEqual(row['received'], 100)

    def test_b_remains_ht_and_excludes_cancelled_documents(self):
        data = snapshot()
        add_b(data)
        data['delivery'].append(dict(name='CANCELLED', sales_order='B', order_type='B',
            docstatus=2, net_total=700, grand_total=826))
        data['payment'].append(dict(name='CANCELLED-RS', order_type='B', docstatus=2,
            amount=900, unallocated_amount=0, sales_order='B'))
        data['allocations'].append(dict(parent='CANCELLED-RS', bordereau='BLB', amount=900))
        row = report.financial_metrics(data)['B']
        self.assertEqual(row['order_amount'], 1000)
        self.assertEqual(row['delivery_amount'], 300)
        self.assertEqual(row['bl_count'], 1)
        self.assertEqual(row['received'], 0)
        self.assertEqual(row['order_balance'], 300)

    def test_mixed_receipt_splits_a_b_once_without_adding_payment_entry(self):
        data = snapshot()
        add_a(data)
        add_b(data)
        data['delivery'].append(dict(name='BLA', sales_order='A', order_type='A', docstatus=1,
            net_total=200, grand_total=236, delivery_note='DN', sales_invoice='SI'))
        data['payment'].append(dict(name='RS', order_type='Mixte', docstatus=1, amount=180,
            sales_order='A', currency='XOF', unallocated_amount=0))
        data['allocations'] = [dict(parent='RS', bordereau='BLA', amount=100),
            dict(parent='RS', bordereau='BLB', amount=80)]
        data['native_payment'] = [dict(name='PE', docstatus=1, payment_type='Receive', paid_amount=100,
            unallocated_amount=0, custom_ug_special_payment='RS', paid_from_account_currency='XOF')]
        data['payment_references'] = [dict(parent='PE', reference_doctype='Sales Invoice',
            reference_name='SI', allocated_amount=100)]
        metrics = report.financial_metrics(data)
        self.assertEqual(metrics['A']['received'], 100)
        self.assertEqual(metrics['A']['order_balance'], 136)
        self.assertEqual(metrics['B']['received'], 80)
        self.assertEqual(metrics['B']['order_balance'], 220)

    def test_b_opening_and_unallocated_advance_once(self):
        data = snapshot()
        add_b(data)
        data['opening'] = [dict(name='OPEN', sales_order='B', amount=50, docstatus=1)]
        data['payment'] = [dict(name='ADV', order_type='B', sales_order='B', amount=20,
            unallocated_amount=20, docstatus=1)]
        row = report.financial_metrics(data)['B']
        self.assertEqual(row['received'], 20)
        self.assertEqual(row['advances'], 20)
        self.assertEqual(row['delivery_balance'], 300)
        self.assertEqual(row['order_balance'], 330)

    def test_a_native_order_advance_is_counted_once(self):
        data = snapshot()
        add_a(data)
        data['native_payment'] = [dict(name='PE', docstatus=1, payment_type='Receive', paid_amount=140,
            unallocated_amount=0, paid_from_account_currency='XOF')]
        data['payment_references'] = [dict(parent='PE', reference_doctype='Sales Invoice',
            reference_name='SI', allocated_amount=100), dict(parent='PE', reference_doctype='Sales Order',
            reference_name='A', allocated_amount=40)]
        row = report.financial_metrics(data)['A']
        self.assertEqual(row['received'], 140)
        self.assertEqual(row['advances'], 40)
        self.assertEqual(row['order_balance'], 96)

    def test_unreadable_invoice_does_not_look_paid(self):
        data = snapshot()
        add_a(data)
        data['capabilities']['can_read_invoices'] = False
        data['invoice'] = []
        data['invoice_items'] = []
        row = report.financial_metrics(data)['A']
        self.assertIsNone(row['delivery_balance'])
        self.assertIsNone(row['received'])
        self.assertIsNone(row['order_balance'])

    def test_unreadable_native_delivery_keeps_amount_unknown(self):
        data = snapshot()
        add_a(data)
        data['capabilities']['can_read_native_deliveries'] = False
        row = report.financial_metrics(data)['A']
        self.assertIsNone(row['delivery_amount'])
        self.assertIsNone(row['bl_count'])

    def test_native_multi_order_delivery_is_counted_without_guessing_total(self):
        data = snapshot()
        add_a(data)
        data['native_delivery_items'].append(dict(parent='DN', against_sales_order='OTHER'))
        row = report.financial_metrics(data)['A']
        self.assertEqual(row['bl_count'], 1)
        self.assertIsNone(row['delivery_amount'])

    def test_multi_order_invoice_does_not_duplicate_entire_debt(self):
        data = snapshot()
        add_a(data)
        data['order'].append(order('A2'))
        data['invoice_items'].append(dict(parent='SI', sales_order='A2'))
        metrics = report.financial_metrics(data)
        self.assertIsNone(metrics['A']['delivery_balance'])
        self.assertIsNone(metrics['A2']['delivery_balance'])

    def test_stage_is_specific_to_a_or_b_without_requiring_sage_for_a(self):
        delivered = frappe._dict(docstatus=1, to_issue_qty=0, issued_qty=4, remaining_qty=0, remaining_all=0)
        self.assertEqual(report._stage(delivered, [], None, 'A'), 'Livrée')
        self.assertEqual(report._stage(delivered, [], None, 'B'), 'À exporter vers Sage')
        partial = frappe._dict(docstatus=1, to_issue_qty=3, issued_qty=1, remaining_qty=0, remaining_all=3)
        self.assertEqual(report._stage(partial, [], None, 'A'), 'Livraison partielle')
        self.assertEqual(report._stage(partial, [], None, 'B'), 'Sortie partielle')

    def test_stage_waits_for_validated_technical_study_of_manufactured_items(self):
        row = frappe._dict(docstatus=1, to_issue_qty=2, issued_qty=0, remaining_qty=2, produced_qty=0)
        self.assertEqual(report._stage(row, ['manufactured'], dict(docstatus=0), 'A'), 'Fiche technique à préparer')
        self.assertEqual(report._stage(row, ['manufactured'], dict(docstatus=1), 'A'), 'À produire')

    def test_services_only_are_not_delivered_just_because_no_stock_remains(self):
        row = frappe._dict(docstatus=1, to_issue_qty=0, issued_qty=0, remaining_qty=0,
            remaining_all=5, has_delivery=False)
        self.assertEqual(report._stage(row, [], None, 'A'), 'À livrer')
        self.assertEqual(report._stage(row, [], None, 'B'), 'À sortir')
        row.remaining_all = 3
        row.has_delivery = True
        self.assertEqual(report._stage(row, [], None, 'A'), 'Livraison partielle')
        self.assertEqual(report._stage(row, [], None, 'B'), 'Sortie partielle')
        row.remaining_all = 0
        self.assertEqual(report._stage(row, [], None, 'A'), 'Livrée')
        self.assertEqual(report._stage(row, [], None, 'B'), 'À exporter vers Sage')

    def test_a_refund_advance_never_increases_received_or_reduces_debt(self):
        data = snapshot()
        add_a(data)
        data['native_payment'] = [dict(name='REFUND', docstatus=1, payment_type='Pay', paid_amount=40,
            unallocated_amount=0, paid_from_account_currency='XOF')]
        data['payment_references'] = [dict(parent='REFUND', reference_doctype='Sales Order',
            reference_name='A', allocated_amount=40)]
        values = report.financial_metrics(data)['A']
        self.assertEqual(values['delivery_balance'], 136)
        self.assertIsNone(values['received'])
        self.assertIsNone(values['advances'])
        self.assertIsNone(values['order_balance'])

    def test_native_customer_credit_is_not_silently_omitted_from_order_receipt(self):
        data = snapshot()
        add_a(data)
        data['native_payment'] = [dict(name='PE', docstatus=1, payment_type='Receive', paid_amount=100,
            unallocated_amount=60, paid_from_account_currency='XOF')]
        data['payment_references'] = [dict(parent='PE', reference_doctype='Sales Order',
            reference_name='A', allocated_amount=40)]
        values = report.financial_metrics(data)['A']
        self.assertEqual(values['delivery_balance'], 136)
        self.assertIsNone(values['received'])
        self.assertIsNone(values['advances'])
        self.assertIsNone(values['order_balance'])

    def test_native_invoice_receipt_with_unallocated_credit_is_not_a_partial_total(self):
        data = snapshot()
        add_a(data)
        data['native_payment'] = [dict(name='PE', docstatus=1, payment_type='Receive', paid_amount=160,
            unallocated_amount=60, paid_from_account_currency='XOF')]
        data['payment_references'] = [dict(parent='PE', reference_doctype='Sales Invoice',
            reference_name='SI', allocated_amount=100)]
        values = report.financial_metrics(data)['A']
        self.assertEqual(values['delivery_balance'], 136)
        self.assertIsNone(values['received'])
        self.assertIsNone(values['advances'])
        self.assertIsNone(values['order_balance'])

    def test_compatibility_import_defaults_to_b_and_preserves_explicit_filter(self):
        from mat_reco.material_reconfiguration.report.suivi_commandes_b.suivi_commandes_b import execute
        with patch.object(report, 'execute', return_value=([], [])) as current:
            execute({'customer': 'C'})
            self.assertEqual(current.call_args.args[0], dict(customer='C', order_type='B'))
            execute({'order_type': 'All'})
            self.assertEqual(current.call_args.args[0]['order_type'], 'All')

    def test_columns_expose_type_and_monetary_basis(self):
        columns = {column['fieldname']: column for column in report._columns()}
        self.assertEqual(columns['order_type']['label'], 'Type')
        self.assertEqual(columns['basis']['label'], 'Base montants')
        self.assertEqual(columns['bl_amount']['options'], 'currency')

    def test_financial_projection_does_not_mutate_source_documents(self):
        data = snapshot()
        add_a(data)
        add_b(data)
        before = deepcopy(data)
        report.financial_metrics(data)
        self.assertEqual(data, before)

    def test_execute_filter_a_b_or_both_includes_legacy_empty_a(self):
        from mat_reco.material_reconfiguration.services import commercial_reports
        from mat_reco.material_reconfiguration.services import workshop_service, order_b_stock
        data = snapshot()
        data['order'] = [dict(order('A'), transaction_date='2026-10-30'),
            dict(order('B', 'B'), transaction_date='2026-10-29'),
            dict(order('LEGACY', ''), transaction_date='2026-10-28')]
        native = {row['name']: SimpleNamespace(items=[], check_permission=Mock(), get=lambda field: None)
                  for row in data['order']}
        with patch.object(commercial_reports, 'report_access') as access, \
                patch.object(commercial, '_capabilities', return_value=data['capabilities']), \
                patch.object(commercial, '_snapshot', return_value=data), \
                patch.object(commercial, '_read_fields', return_value=[]), \
                patch.object(frappe, 'get_doc', side_effect=lambda dt, name: native[name]), \
                patch.object(workshop_service, '_receipts', return_value=({}, {}, {}, {})), \
                patch.object(order_b_stock, 'physical_rows', return_value=[]), \
                patch.object(order_b_stock, 'issued_quantities', return_value={}):
            for selected, expected in [('A', {'A', 'LEGACY'}), ('B', {'B'}), ('All', {'A', 'B', 'LEGACY'})]:
                _, rows = report.execute(dict(order_type=selected))
                self.assertEqual({row.name for row in rows}, expected)
                self.assertTrue(all(row.basis == ('HT' if row.order_type == 'B' else 'TTC') for row in rows))
            self.assertEqual(access.call_count, 3)
            native['A'].check_permission.assert_called_with('read')

    def test_execute_rejects_truncation_instead_of_a_partial_financial_report(self):
        from mat_reco.material_reconfiguration.services import commercial_reports
        with patch.object(commercial_reports, 'report_access'), \
                patch.object(commercial, '_capabilities', return_value={}), \
                patch.object(commercial, '_snapshot', return_value=dict(truncated=True)), \
                patch.object(frappe, 'throw', side_effect=ValueError('Affiner')):
            with self.assertRaisesRegex(ValueError, 'Affiner'):
                report.execute(dict(order_type='All'))

    def test_execute_rejects_unauthorized_access_before_reading_documents(self):
        from mat_reco.material_reconfiguration.services import commercial_reports
        with patch.object(commercial_reports, 'report_access', side_effect=frappe.PermissionError), \
                patch.object(commercial, '_snapshot') as read:
            with self.assertRaises(frappe.PermissionError):
                report.execute(dict(order_type='A'))
            read.assert_not_called()


if __name__ == '__main__':
    unittest.main()
