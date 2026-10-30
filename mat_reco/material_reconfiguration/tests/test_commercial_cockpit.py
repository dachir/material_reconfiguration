"""Permission-scoped cockpit calculations; no site, stock or accounting writes."""
from copy import deepcopy
import unittest
from unittest.mock import patch

from mat_reco.material_reconfiguration.services import commercial_cockpit as cockpit


def filters(**kwargs):
    return dict(customer='C', circuit='all', state='all', followup='all', **kwargs)


def snapshot():
    data = {kind: [] for kind in cockpit.DT}
    data.update(capabilities={'can_read_' + key: True for key in cockpit.CAP.values()},
        companies=[dict(name='UG', default_currency='XOF')], customers=[],
        warnings=[], truncated=False, incomplete_children=set(), as_of='2026-10-30 12:00:00')
    for key in ('order_items', 'delivery_items', 'allocations', 'invoice_items',
                'native_delivery_items', 'payment_references'):
        data[key] = []
    return data


def order(name, kind='A', customer='C', currency='XOF', **kwargs):
    return dict(name=name, custom_ug_order_type=kind, customer=customer, company='UG', currency=currency,
        docstatus=1, status='To Deliver and Bill', grand_total=1180, net_total=1000, conversion_rate=1, **kwargs)


def line(parent, name, qty=5, delivered=0, uom='PC'):
    return dict(parent=parent, name=name, qty=qty, delivered_qty=delivered, uom=uom, is_stock_item=1)


def delivery(name, so, kind='B', amount=300, **kwargs):
    return dict(name=name, sales_order=so, order_type=kind, customer='C', company='UG', currency='XOF',
        net_total=amount, grand_total=amount * (1.18 if kind == 'A' else 1), docstatus=1, **kwargs)


def payment(name, amount, kind='B', **kwargs):
    return dict(name=name, order_type=kind, amount=amount, customer='C', company='UG', currency='XOF',
        docstatus=1, **kwargs)


def invoice(name, so, amount, outstanding, **kwargs):
    return dict(name=name, customer='C', company='UG', currency='XOF', party_account_currency='XOF',
        grand_total=amount, outstanding_amount=outstanding, docstatus=1, **kwargs)


class CommercialCockpitTests(unittest.TestCase):
    def result(self, data, **changes):
        values = filters()
        values.update(changes)
        return cockpit.project(data, values)

    def metric(self, result, order_name):
        return result['details']['Sales Order::' + order_name]['metrics']

    def account(self, result, name='C'):
        return next(row for row in result['clients'] if row['customer'] == name)

    def test_mixed_receipt_is_one_node_with_two_distinct_allocations(self):
        data = snapshot()
        data['order'] = [order('A'), order('B', 'B')]
        data['order_items'] = [line('A', 'a', delivered=2), line('B', 'b', qty=8)]
        data['delivery'] = [delivery('BLA', 'A', 'A', 200, sales_invoice='SI'), delivery('BLB', 'B')]
        data['delivery_items'] = [dict(parent='BLB', sales_order_item='b', qty=3)]
        data['invoice'] = [invoice('SI', 'A', 236, 136)]
        data['invoice_items'] = [dict(parent='SI', sales_order='A')]
        data['payment'] = [payment('RS', 180, 'Mixte', sales_order='A', unallocated_amount=0)]
        data['allocations'] = [dict(parent='RS', bordereau='BLA', amount=100),
                               dict(parent='RS', bordereau='BLB', amount=80)]
        result = self.result(data)
        receipts = [row for row in result['documents'] if row['kind'] == 'payment']
        self.assertEqual(len(receipts), 1)
        self.assertEqual(receipts[0]['basis'], '')
        self.assertEqual(receipts[0]['metrics']['amount_a'], 100)
        self.assertEqual(receipts[0]['metrics']['amount_b'], 80)
        links = [row for row in result['edges'] if row['kind'] == 'allocation']
        self.assertEqual(sorted(row['amount'] for row in links), [80, 100])
        self.assertEqual(self.metric(result, 'A')['balance'], 136)
        self.assertEqual(self.metric(result, 'B')['balance'], 220)
        self.assertEqual(result['kpis']['remaining_qty'], 8)

    def test_filtered_b_keeps_visible_allocation_of_mixed_payment(self):
        data = snapshot()
        data['order'] = [order('B', 'B')]
        data['order_items'] = [line('B', 'b')]
        data['delivery'] = [delivery('BLB', 'B')]
        data['payment'] = [payment('RS', 180, 'Mixte', sales_order='hidden-A', unallocated_amount=0)]
        data['allocations'] = [dict(parent='RS', bordereau='hidden-A-BL', amount=100),
                               dict(parent='RS', bordereau='BLB', amount=80)]
        result = self.result(data, circuit='B')
        self.assertEqual(self.metric(result, 'B')['balance'], 220)
        self.assertEqual(self.metric(result, 'B')['received'], 80)
        receipt = result['details']['Reglement Special::RS']
        self.assertIsNone(receipt['metrics']['amount_a'])
        self.assertEqual(len([row for row in result['edges'] if row['kind'] == 'allocation']), 1)
        self.assertNotIn('hidden-A', str(result['documents']))
        self.assertNotIn('hidden-A-BL', str(result['edges']))

    def test_piece_kpi_does_not_add_area_or_service_units(self):
        data = snapshot()
        data['order'] = [order('A')]
        data['order_items'] = [line('A', 'pc', 5, 2), line('A', 'm2', 100, 20, 'M2'),
                               line('A', 'service', 40, 40, 'Meter')]
        result = self.result(data)
        metric = self.metric(result, 'A')
        self.assertEqual(metric['ordered_qty'], 5)
        self.assertEqual(metric['remaining_qty'], 3)
        self.assertEqual(result['kpis']['remaining_qty'], 3)
        self.assertEqual(metric['remaining_all'], 83)
        self.assertTrue(metric['can_deliver'])

    def test_piece_kpi_excludes_service_sold_in_pc(self):
        data = snapshot()
        data['order'] = [order('A')]
        data['order_items'] = [line('A', 'glass', 2), dict(line('A', 'service-pc', 3), is_stock_item=0),
                               dict(line('A', 'service-meter', 1, uom='Meter'), is_stock_item=0)]
        metric = self.metric(self.result(data), 'A')
        self.assertEqual(metric['ordered_qty'], 2)
        self.assertEqual(metric['remaining_qty'], 2)
        self.assertEqual(metric['remaining_all'], 6)
        data['order_items'][0] = dict(line('A', 'glass', 4, 2, 'M2'), stock_uom='PC', stock_qty=2, conversion_factor=.5)
        metric = self.metric(self.result(data), 'A')
        self.assertEqual(metric['ordered_qty'], 2)
        self.assertEqual(metric['delivered_qty'], 1)
        data['order_items'] = [line('A', 'm2', 100, 20, 'M2')]
        metric = self.metric(self.result(data), 'A')
        self.assertEqual(metric['remaining_qty'], 0)
        self.assertTrue(metric['can_deliver'])

    def test_native_rounding_does_not_invent_a_payment(self):
        data = snapshot()
        data['order'] = [order('A')]
        data['order_items'] = [line('A', 'a')]
        data['delivery'] = [delivery('BL', 'A', 'A', 100.1, sales_invoice='SI')]
        data['invoice'] = [invoice('SI', 'A', 118.1, 118, rounded_total=118)]
        data['invoice_items'] = [dict(parent='SI', sales_order='A')]
        result = self.result(data)
        self.assertEqual(self.metric(result, 'A')['received'], 0)
        self.assertEqual(result['details']['Bordereau Special::BL']['metrics']['received'], 0)
        self.assertEqual(result['details']['Sales Invoice::SI']['amount'], 118)

    def test_shared_invoice_counted_once_for_client_but_not_guessed_per_order(self):
        data = snapshot()
        data['order'] = [order('A1'), order('A2')]
        data['order_items'] = [line('A1', 'a1'), line('A2', 'a2')]
        data['invoice'] = [invoice('SI', 'A1', 1180, 800)]
        data['invoice_items'] = [dict(parent='SI', sales_order='A1'), dict(parent='SI', sales_order='A2')]
        result = self.result(data)
        self.assertEqual(self.account(result)['balances_a'][0]['amount'], 800)
        self.assertIsNone(self.metric(result, 'A1')['balance'])
        self.assertIsNone(self.metric(result, 'A2')['balance'])

    def test_missing_invoice_permission_is_unknown_not_zero(self):
        data = snapshot()
        data['order'] = [order('A')]
        data['order_items'] = [line('A', 'a')]
        data['capabilities']['can_read_invoices'] = False
        result = self.result(data)
        self.assertIsNone(self.metric(result, 'A')['balance'])
        self.assertIsNone(self.account(result)['balances_a'][0]['amount'])

    def test_unreadable_linked_invoice_is_unknown_despite_doctype_read(self):
        data = snapshot()
        data['order'] = [order('A')]
        data['order_items'] = [line('A', 'a')]
        data['delivery'] = [delivery('BL', 'A', 'A', 100, sales_invoice='unreadable-SI')]
        result = self.result(data)
        self.assertIsNone(self.metric(result, 'A')['balance'])
        self.assertIsNone(self.account(result)['balances_a'][0]['amount'])
        self.assertIsNone(result['details']['Bordereau Special::BL']['metrics']['balance'])
        self.assertNotIn('unreadable-SI', str(result['documents']))
        data['capabilities']['can_read_orders'] = False
        data['order'] = []
        data['order_items'] = []
        result = self.result(data)
        self.assertIsNone(self.account(result)['balances_a'][0]['amount'])

    def test_missing_payment_permission_or_child_amount_keeps_b_balance_unknown(self):
        data = snapshot()
        data['order'] = [order('B', 'B')]
        data['order_items'] = [line('B', 'b')]
        data['delivery'] = [delivery('BL', 'B')]
        data['capabilities']['can_read_payments'] = False
        self.assertIsNone(self.metric(self.result(data), 'B')['balance'])
        data['capabilities']['can_read_payments'] = True
        data['payment'] = [payment('RS', 10, sales_order='B', unallocated_amount=0)]
        data['allocations'] = [dict(parent='RS', bordereau='BL')]
        self.assertIsNone(self.metric(self.result(data), 'B')['balance'])

    def test_missing_opening_permission_does_not_break_bl_balance(self):
        data = snapshot()
        data['order'] = [order('B', 'B')]
        data['order_items'] = [line('B', 'b')]
        data['delivery'] = [delivery('BL', 'B')]
        data['capabilities']['can_read_openings'] = False
        metric = self.metric(self.result(data), 'B')
        self.assertEqual(metric['balance'], 300)
        self.assertIsNone(metric['order_balance'])

    def test_financial_parent_limit_marks_balances_incomplete(self):
        data = snapshot()
        data['order'] = [order('B', 'B')]
        data['order_items'] = [line('B', 'b')]
        data['delivery'] = [delivery('BL', 'B')]
        data['incomplete_parents'] = {'payment'}
        data['truncated'] = True
        result = self.result(data)
        self.assertIsNone(self.metric(result, 'B')['balance'])
        self.assertIsNone(self.account(result)['balances_b'][0]['amount'])
        self.assertTrue(result['truncated'])
        data['incomplete_parents'] = {'quotation'}
        self.assertEqual(self.metric(self.result(data), 'B')['balance'], 300)

    def test_b_advance_and_opening_affect_account_not_bl_balance(self):
        data = snapshot()
        data['order'] = [order('B', 'B')]
        data['order_items'] = [line('B', 'b')]
        data['delivery'] = [delivery('BL', 'B')]
        data['payment'] = [payment('allocated', 80, sales_order='B', unallocated_amount=0),
                           payment('advance', 50, sales_order='B', unallocated_amount=50),
                           payment('global-advance', 100, unallocated_amount=100)]
        data['allocations'] = [dict(parent='allocated', bordereau='BL', amount=80)]
        data['opening'] = [dict(name='opening', customer='C', company='UG', currency='XOF', amount=20, docstatus=1)]
        result = self.result(data)
        self.assertEqual(self.metric(result, 'B')['balance'], 220)
        self.assertEqual(self.metric(result, 'B')['order_balance'], 170)
        self.assertEqual(self.account(result)['balances_b'][0]['amount'], 220)
        self.assertEqual(self.account(result)['account_balances_b'][0]['amount'], 90)
        self.assertEqual(self.account(result)['advances_b'][0]['amount'], 150)

    def test_global_b_advance_is_visible_even_without_any_order(self):
        data = snapshot()
        data['payment'] = [payment('advance', 100, unallocated_amount=100)]
        result = self.result(data)
        self.assertEqual(self.account(result)['account_balances_b'][0]['amount'], -100)
        self.assertEqual(self.account(result)['balances_b'], [])

    def test_native_a_advance_uses_recorded_receipt_conversion(self):
        data = snapshot()
        data['order'] = [order('A')]
        data['order_items'] = [line('A', 'a')]
        data['payment'] = [payment('advance', 100, 'A', sales_order='A', unallocated_amount=100)]
        data['native_payment'] = [dict(name='PE', company='UG', party='C', docstatus=1,
            custom_ug_special_payment='advance', paid_amount=200, unallocated_amount=50,
            paid_from_account_currency='USD')]
        metric = self.metric(self.result(data), 'A')
        self.assertEqual(metric['balance'], 0)
        self.assertEqual(metric['advances'], 25)
        self.assertEqual(metric['order_balance'], -25)

    def test_company_and_currency_amounts_stay_separate(self):
        data = snapshot()
        data['order'] = [order('B1', 'B'), order('B2', 'B', currency='USD')]
        data['order_items'] = [line('B1', 'b1'), line('B2', 'b2')]
        data['delivery'] = [delivery('BL1', 'B1'), dict(delivery('BL2', 'B2'), currency='USD')]
        result = self.result(data)
        self.assertEqual([(row['currency'], row['amount']) for row in result['kpis']['balances_b']], [('USD', 300), ('XOF', 300)])
        self.assertEqual(self.metric(result, 'B1')['order_amount'], 1000)

    def test_proposal_only_clients_are_discoverable_and_overview_has_no_graph(self):
        data = snapshot()
        data['quotation'] = [dict(name='Q', party_name='C', company='UG', currency='XOF', customer_name='Commercial', grand_total=1180, docstatus=0)]
        data['project'] = [dict(name='CH', customer='OTHER', designation='Maison', docstatus=0)]
        result = self.result(data, customer='')
        self.assertEqual({row['customer'] for row in result['clients']}, {'C', 'OTHER'})
        self.assertEqual(result['documents'], [])
        self.assertEqual(result['kpis']['orders'], 0)

    def test_graph_prefers_visible_quote_and_order_parents(self):
        data = snapshot()
        data['order'] = [order('A', custom_chantier='CH', custom_technical_study='FT')]
        data['order_items'] = [dict(line('A', 'a'), prevdoc_docname='Q')]
        data['quotation'] = [dict(name='Q', party_name='C', custom_chantier='CH', docstatus=1)]
        data['project'] = [dict(name='CH', customer='C', docstatus=1)]
        data['study'] = [dict(name='FT', sales_order='A', chantier='CH', docstatus=0),
                         dict(name='independent', chantier='CH', docstatus=0)]
        links = {(row['source'], row['target']) for row in self.result(data)['edges']}
        self.assertIn(('Chantier::CH', 'Quotation::Q'), links)
        self.assertIn(('Quotation::Q', 'Sales Order::A'), links)
        self.assertIn(('Sales Order::A', 'Chantier Technical Study::FT'), links)
        self.assertNotIn(('Chantier::CH', 'Sales Order::A'), links)
        self.assertNotIn(('Chantier::CH', 'Chantier Technical Study::FT'), links)
        self.assertIn(('Chantier::CH', 'Chantier Technical Study::independent'), links)
        data['quotation'] = []
        links = {(row['source'], row['target']) for row in self.result(data)['edges']}
        self.assertIn(('Chantier::CH', 'Sales Order::A'), links)

    def test_native_payment_is_associated_to_order_through_its_invoice(self):
        data = snapshot()
        data['order'] = [order('A')]
        data['order_items'] = [line('A', 'a')]
        data['invoice'] = [invoice('SI', 'A', 118, 18)]
        data['invoice_items'] = [dict(parent='SI', sales_order='A')]
        data['native_payment'] = [dict(name='PE', company='UG', party='C', docstatus=1,
            paid_amount=100, unallocated_amount=0, paid_from_account_currency='XOF')]
        data['payment_references'] = [dict(parent='PE', reference_doctype='Sales Invoice', reference_name='SI', allocated_amount=100)]
        result = self.result(data)
        links = result['details']['Sales Order::A']['linked_documents']
        self.assertIn(('Payment Entry', 'PE'), {(row['doctype'], row['name']) for row in links})
        self.assertEqual(len(links), len({(row['doctype'], row['name']) for row in links}))
        data['payment_references'][0]['reference_doctype'] = 'Purchase Invoice'
        result = self.result(data)
        self.assertNotIn('Payment Entry::PE', result['details'])

    def test_readable_specials_do_not_require_readable_sales_orders(self):
        data = snapshot()
        data['capabilities']['can_read_orders'] = False
        data['delivery'] = [delivery('BL', 'hidden-so')]
        data['payment'] = [payment('RS', 80, unallocated_amount=0)]
        data['allocations'] = [dict(parent='RS', bordereau='BL', amount=80)]
        result = self.result(data)
        self.assertEqual(self.account(result)['balances_b'][0]['amount'], 220)
        self.assertNotIn('Sales Order::hidden-so', result['details'])
        self.assertIsNone(result['details']['Bordereau Special::BL']['sales_order'])

    def test_projection_never_calls_database(self):
        data = snapshot()
        data['order'] = [order('A')]
        data['order_items'] = [line('A', 'a')]
        with patch.object(cockpit.frappe, 'get_list', side_effect=AssertionError('DB access')), \
                patch.object(cockpit.frappe, 'get_all', side_effect=AssertionError('DB access')):
            self.result(data)

    def test_focused_api_preserves_global_client_index(self):
        focus = snapshot()
        focus['project'] = [dict(name='CH', customer='C', docstatus=0)]
        index = deepcopy(focus)
        index['project'].append(dict(name='OTHER-CH', customer='OTHER', docstatus=0))
        with patch.object(cockpit, '_capabilities', return_value=focus['capabilities']), \
                patch.object(cockpit, '_snapshot', side_effect=[focus, index]), \
                patch.object(cockpit.frappe, 'has_permission', return_value=False):
            result = cockpit.get_dashboard.__wrapped__(dict(customer='C'))
        self.assertEqual({row['customer'] for row in result['clients']}, {'C', 'OTHER'})
        self.assertEqual({row['customer'] for row in result['documents']}, {'C'})


if __name__ == '__main__':
    unittest.main()
