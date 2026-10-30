"""A tax-only B remainder must not keep the commercial work queue open.

Pure snapshot projections: no site, stock, accounting or production writes.
"""
from copy import deepcopy
import unittest

from mat_reco.material_reconfiguration.services import commercial_cockpit as cockpit


def complete_b():
    data = {kind: [] for kind in cockpit.DT}
    data.update(capabilities={'can_read_' + key: True for key in cockpit.CAP.values()},
        companies=[dict(name='UG', default_currency='XOF')], customers=[], warnings=[],
        truncated=False, incomplete_children=set(), incomplete_parents=set(),
        as_of='2026-10-30 12:00:00')
    for key in ('order_items', 'delivery_items', 'allocations', 'invoice_items',
                'native_delivery_items', 'payment_references'):
        data[key] = []
    data['order'] = [dict(name='B', custom_ug_order_type='B', customer='C', company='UG',
        currency='XOF', docstatus=1, status='To Deliver and Bill', net_total=1000,
        grand_total=1180, conversion_rate=1)]
    data['order_items'] = [dict(parent='B', name='b1', qty=5, delivered_qty=0,
        uom='PC', is_stock_item=1)]
    data['delivery'] = [dict(name='BL', sales_order='B', order_type='B', customer='C',
        company='UG', currency='XOF', net_total=1000, grand_total=1180, docstatus=1)]
    data['delivery_items'] = [dict(parent='BL', sales_order_item='b1', qty=5)]
    data['payment'] = [dict(name='RS', order_type='B', amount=1000, customer='C',
        company='UG', currency='XOF', docstatus=1, sales_order='B', unallocated_amount=0)]
    data['allocations'] = [dict(parent='RS', bordereau='BL', amount=1000)]
    return data


def project(data, state='open', customer='C'):
    return cockpit.project(data, dict(customer=customer, circuit='all', state=state,
        followup='all'))


def names(result, kind):
    return {row['name'] for row in result['documents'] if row['kind'] == kind}


def with_sources(data):
    data['order'][0]['custom_chantier'] = 'CH'
    data['order_items'][0].update(prevdoc_docname='Q', quotation_item='q1',
        stock_qty=5, conversion_factor=1)
    data['quotation'] = [dict(name='Q', party_name='C', company='UG', currency='XOF',
        docstatus=1, status='Ordered', grand_total=1180, custom_chantier='CH')]
    data['quotation_items'] = [dict(parent='Q', name='q1', qty=5, stock_qty=5,
        ordered_qty=5, custom_chantier_line='L1', custom_repere='OUV-001',
        is_alternative=0)]
    data['project'] = [dict(name='CH', customer='C', company='UG', currency='XOF',
        docstatus=1, status='Validé', designation='Maison')]
    data['project_lines'] = [dict(parent='CH', line_id='L1', repere='OUV-001', qty=5)]
    data['project_extras'] = []
    return data


class BTaxCompletionTests(unittest.TestCase):
    def assert_pending(self, data):
        self.assertIn('B', names(project(data), 'order'))

    def test_paid_and_fully_delivered_b_is_hidden_despite_native_ttc_status(self):
        data = complete_b()
        before = deepcopy(data)
        result = project(data)
        self.assertNotIn('B', names(result, 'order'))
        self.assertNotIn('BL', names(result, 'delivery'))
        self.assertNotIn('RS', names(result, 'payment'))
        self.assertEqual(result['kpis']['orders'], 0)
        self.assertEqual(data, before, 'Projection must not mutate native documents or taxes')

    def test_all_state_retains_full_b_history_and_ht_amounts(self):
        result = project(complete_b(), state='all')
        self.assertEqual(names(result, 'order'), {'B'})
        self.assertEqual(names(result, 'delivery'), {'BL'})
        self.assertEqual(names(result, 'payment'), {'RS'})
        metric = result['details']['Sales Order::B']['metrics']
        self.assertEqual(metric['order_amount'], 1000)
        self.assertEqual(metric['delivery_amount'], 1000)
        self.assertEqual(metric['remaining_all'], 0)
        self.assertEqual(metric['delivery_balance'], 0)
        self.assertEqual(metric['order_balance'], 0)

    def test_b_with_undelivered_quantity_stays_open_even_if_fully_paid(self):
        data = complete_b()
        data['delivery_items'][0]['qty'] = 4
        self.assert_pending(data)

    def test_service_quantity_remainder_also_keeps_b_open(self):
        data = complete_b()
        data['order_items'].append(dict(parent='B', name='service', qty=10,
            delivered_qty=0, uom='Meter', is_stock_item=0))
        data['delivery_items'].append(dict(parent='BL', sales_order_item='service', qty=9))
        self.assert_pending(data)

    def test_b_with_uncovered_ht_amount_stays_open_despite_zero_current_bl_balance(self):
        data = complete_b()
        data['delivery'][0]['net_total'] = 900
        data['payment'][0]['amount'] = 900
        data['allocations'][0]['amount'] = 900
        self.assert_pending(data)

    def test_b_with_unpaid_ht_stays_open(self):
        data = complete_b()
        data['payment'][0]['amount'] = 999
        data['allocations'][0]['amount'] = 999
        self.assert_pending(data)

    def test_b_order_specific_opening_debit_stays_open(self):
        data = complete_b()
        data['opening'] = [dict(name='OPEN', customer='C', company='UG', currency='XOF',
            sales_order='B', amount=100, docstatus=1)]
        self.assert_pending(data)

    def test_b_advance_cannot_hide_unpaid_bl(self):
        data = complete_b()
        data['allocations'][0]['amount'] = 900
        data['payment'][0]['unallocated_amount'] = 100
        self.assert_pending(data)

    def test_customer_credit_is_real_work_and_keeps_b_visible(self):
        data = complete_b()
        data['payment'][0].update(amount=1100, unallocated_amount=100)
        result = project(data)
        self.assertIn('B', names(result, 'order'))
        customer = next(row for row in result['clients'] if row['customer'] == 'C')
        self.assertEqual(customer['account_balances_b'][0]['amount'], -100)
        self.assertEqual(customer['advances_b'][0]['amount'], 100)

    def test_pending_special_drafts_keep_the_b_branch_visible(self):
        for kind in ('delivery', 'payment'):
            with self.subTest(kind=kind):
                data = complete_b()
                draft = deepcopy(data[kind][0])
                draft.update(name='DRAFT', docstatus=0)
                data[kind].append(draft)
                self.assert_pending(data)

    def test_draft_b_is_never_implicitly_completed(self):
        data = complete_b()
        data['order'][0]['docstatus'] = 0
        data['order'][0]['status'] = 'Draft'
        self.assert_pending(data)

    def test_cancelled_delivery_or_payment_does_not_complete_b(self):
        for kind in ('delivery', 'payment'):
            with self.subTest(kind=kind):
                data = complete_b()
                data[kind][0]['docstatus'] = 2
                self.assert_pending(data)

    def test_draft_payment_does_not_complete_b(self):
        data = complete_b()
        data['payment'][0]['docstatus'] = 0
        self.assert_pending(data)

    def test_unknown_balances_do_not_hide_b(self):
        for capability in ('can_read_deliveries', 'can_read_payments', 'can_read_openings'):
            with self.subTest(capability=capability):
                data = complete_b()
                data['capabilities'][capability] = False
                self.assert_pending(data)
        for kind, field in (('order', 'net_total'), ('delivery', 'net_total'),
                            ('allocations', 'amount')):
            with self.subTest(kind=kind, field=field):
                data = complete_b()
                data[kind][0].pop(field)
                self.assert_pending(data)

    def test_incomplete_child_or_parent_projection_does_not_hide_b(self):
        for child in ('order_items', 'delivery_items', 'allocations'):
            with self.subTest(child=child):
                data = complete_b()
                data['incomplete_children'].add(child)
                self.assert_pending(data)
        for parent in ('order', 'delivery', 'payment', 'opening'):
            with self.subTest(parent=parent):
                data = complete_b()
                data['incomplete_parents'].add(parent)
                self.assert_pending(data)

    def test_a_keeps_its_native_delivery_and_accounting_state(self):
        data = complete_b()
        data['order'][0]['custom_ug_order_type'] = 'A'
        data['order_items'][0]['delivered_qty'] = 5
        data['delivery'][0].update(order_type='A', sales_invoice='SI')
        data['payment'][0]['order_type'] = 'A'
        data['invoice'] = [dict(name='SI', customer='C', company='UG', currency='XOF',
            party_account_currency='XOF', grand_total=1180, outstanding_amount=180,
            docstatus=1)]
        data['invoice_items'] = [dict(parent='SI', sales_order='B')]
        self.assert_pending(data)
        metric = project(data)['details']['Sales Order::B']['metrics']
        self.assertEqual(metric['order_amount'], 1180)
        self.assertEqual(metric['balance'], 180)

    def test_completed_b_hides_fully_processed_quote_and_project(self):
        data = with_sources(complete_b())
        result = project(data)
        self.assertNotIn('B', names(result, 'order'))
        self.assertNotIn('Q', names(result, 'quotation'))
        self.assertNotIn('CH', names(result, 'project'))
        self.assertEqual(result['clients'], [])
        history = project(data, state='all')
        self.assertIn('Q', names(history, 'quotation'))
        self.assertIn('CH', names(history, 'project'))

    def test_partial_quote_keeps_ancestors_after_its_first_b_order_is_completed(self):
        data = with_sources(complete_b())
        data['quotation_items'][0].update(qty=6, stock_qty=6)
        result = project(data)
        self.assertNotIn('B', names(result, 'order'))
        self.assertIn('Q', names(result, 'quotation'))
        self.assertIn('CH', names(result, 'project'))

    def test_unquoted_project_line_keeps_project_visible(self):
        data = with_sources(complete_b())
        data['project_lines'].append(dict(parent='CH', line_id='L2', repere='OUV-002', qty=1))
        result = project(data)
        self.assertNotIn('Q', names(result, 'quotation'))
        self.assertIn('CH', names(result, 'project'))

    def test_unquoted_project_extra_keeps_project_visible(self):
        data = with_sources(complete_b())
        data['project_extras'].append(dict(parent='CH', line_id='E1', parent_line_id='L1', qty=1))
        result = project(data)
        self.assertIn('CH', names(result, 'project'))

    def test_processed_project_extra_does_not_block_completion(self):
        data = with_sources(complete_b())
        data['project_extras'].append(dict(parent='CH', line_id='E1', parent_line_id='L1', qty=10))
        data['quotation_items'].append(dict(parent='Q', name='q-service', qty=10,
            stock_qty=10, ordered_qty=10, custom_chantier_line='E1', is_alternative=0))
        data['order_items'].append(dict(parent='B', name='b-service', qty=10,
            delivered_qty=0, uom='Meter', is_stock_item=0, prevdoc_docname='Q',
            quotation_item='q-service', stock_qty=10, conversion_factor=1))
        data['delivery_items'].append(dict(parent='BL', sales_order_item='b-service', qty=10))
        result = project(data)
        self.assertNotIn('Q', names(result, 'quotation'))
        self.assertNotIn('CH', names(result, 'project'))

    def test_several_completed_b_orders_cover_one_quote_without_double_counting_receipt(self):
        data = with_sources(complete_b())
        data['order'][0].update(net_total=400, grand_total=472)
        data['order_items'][0].update(qty=2, stock_qty=2)
        data['delivery'][0]['net_total'] = 400
        data['delivery_items'][0]['qty'] = 2
        data['allocations'][0]['amount'] = 400
        data['order'].append(dict(data['order'][0], name='B2', net_total=600, grand_total=708))
        data['order_items'].append(dict(data['order_items'][0], parent='B2', name='b2', qty=3, stock_qty=3))
        data['delivery'].append(dict(data['delivery'][0], name='BL2', sales_order='B2', net_total=600))
        data['delivery_items'].append(dict(parent='BL2', sales_order_item='b2', qty=3))
        data['allocations'].append(dict(parent='RS', bordereau='BL2', amount=600))
        result = project(data)
        self.assertEqual(names(result, 'order'), set())
        self.assertEqual(names(result, 'quotation'), set())
        self.assertEqual(names(result, 'project'), set())
        history = project(data, state='all')
        self.assertEqual(names(history, 'payment'), {'RS'})
        self.assertEqual(names(history, 'order'), {'B', 'B2'})

    def test_other_draft_quote_keeps_project_visible(self):
        data = with_sources(complete_b())
        draft = dict(data['quotation'][0], name='Q-DRAFT', docstatus=0, status='Draft')
        data['quotation'].append(draft)
        result = project(data)
        self.assertIn('Q-DRAFT', names(result, 'quotation'))
        self.assertIn('CH', names(result, 'project'))

    def test_other_open_a_order_keeps_source_quote_and_project(self):
        data = with_sources(complete_b())
        data['quotation_items'][0].update(qty=6, stock_qty=6, ordered_qty=6)
        other = dict(data['order'][0], name='A', custom_ug_order_type='A',
            net_total=200, grand_total=236)
        data['order'].append(other)
        data['order_items'].append(dict(data['order_items'][0], parent='A', name='a1',
            qty=1, stock_qty=1, delivered_qty=0))
        result = project(data)
        self.assertIn('A', names(result, 'order'))
        self.assertIn('Q', names(result, 'quotation'))
        self.assertIn('CH', names(result, 'project'))

    def test_missing_source_lines_do_not_hide_ancestors_without_proof(self):
        for key in ('quotation_items', 'project_lines'):
            with self.subTest(key=key):
                data = with_sources(complete_b())
                data[key] = []
                result = project(data)
                self.assertIn('CH', names(result, 'project'))
                if key == 'quotation_items':
                    self.assertIn('Q', names(result, 'quotation'))

    def test_incomplete_source_children_do_not_hide_ancestors(self):
        for key in ('quotation_items', 'project_lines', 'project_extras'):
            with self.subTest(key=key):
                data = with_sources(complete_b())
                data['incomplete_children'].add(key)
                result = project(data)
                self.assertIn('CH', names(result, 'project'))
                if key == 'quotation_items':
                    self.assertIn('Q', names(result, 'quotation'))

    def test_lost_quote_outside_period_does_not_keep_completed_project_open(self):
        data = with_sources(complete_b())
        data['completion_quotations'] = [dict(data['quotation'][0]),
            dict(name='OLD-LOST', docstatus=1, custom_chantier='CH', status='Lost')]
        self.assertNotIn('CH', names(project(data), 'project'))

    def test_draft_quote_outside_period_keeps_project_open(self):
        data = with_sources(complete_b())
        data['completion_quotations'] = [dict(data['quotation'][0]),
            dict(name='OTHER-DRAFT', docstatus=0, custom_chantier='CH', status='Draft')]
        self.assertIn('CH', names(project(data), 'project'))

    def test_order_outside_period_prevents_hiding_its_source_ancestors(self):
        data = with_sources(complete_b())
        data['completion_orders'] = [dict(data['order'][0]),
            dict(name='OTHER-ORDER', docstatus=1, custom_chantier='CH')]
        result = project(data)
        self.assertNotIn('B', names(result, 'order'))
        self.assertIn('Q', names(result, 'quotation'))
        self.assertIn('CH', names(result, 'project'))

    def test_fully_allocated_global_receipt_does_not_recreate_completed_client(self):
        data = with_sources(complete_b())
        data['payment'][0]['sales_order'] = None
        self.assertEqual(project(data)['clients'], [])

    def test_global_unallocated_credit_remains_visible_after_completed_order_is_hidden(self):
        data = with_sources(complete_b())
        data['payment'][0].update(sales_order=None, amount=1100, unallocated_amount=100)
        result = project(data)
        self.assertNotIn('B', names(result, 'order'))
        self.assertEqual(result['clients'][0]['account_balances_b'][0]['amount'], -100)

    def test_cfa_rounding_is_allowed_but_not_a_whole_franc_ht_shortfall(self):
        data = complete_b()
        data['order'][0]['net_total'] = 1000.4
        self.assertNotIn('B', names(project(data), 'order'))
        data['order'][0]['net_total'] = 1001
        self.assert_pending(data)


if __name__ == '__main__':
    unittest.main()
