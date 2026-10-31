"""Validated chantier entry point without changing downstream operations."""
from contextlib import ExitStack
from copy import deepcopy
import unittest
from unittest.mock import patch

from mat_reco.material_reconfiguration.services import commercial_cockpit as cockpit


def snapshot():
    data = {kind: [] for kind in cockpit.DT}
    capabilities = {'can_read_' + value: True for value in cockpit.CAP.values()}
    data.update(capabilities=capabilities, companies=[dict(name='UG', default_currency='XOF')],
        customers=[], warnings=[], truncated=False, incomplete_children=set(),
        as_of='2026-10-31 12:00:00')
    for key in ('order_items', 'delivery_items', 'allocations', 'invoice_items',
            'native_delivery_items', 'payment_references', 'quotation_items',
            'project_lines', 'project_extras'):
        data[key] = []
    return data


def chantier(name, docstatus=0, customer='C'):
    return dict(name=name, customer=customer, company='UG', currency='XOF',
        designation=name, docstatus=docstatus,
        status='Cancelled' if docstatus == 2 else 'Preparation' if docstatus == 0 else 'Confirmed')


def order(name, circuit='A', source='DRAFT'):
    return dict(name=name, custom_ug_order_type=circuit, custom_chantier=source,
        customer='C', company='UG', currency='XOF', docstatus=1,
        status='To Deliver and Bill', grand_total=1180, net_total=1000, conversion_rate=1)


def projection(data, **changes):
    values = dict(customer='C', circuit='all', state='all', followup='all')
    values.update(changes)
    return cockpit.project(data, values)


class CommercialValidatedProjectsTests(unittest.TestCase):
    def test_validated_only_hides_drafts_and_cancelled_in_every_state(self):
        for state in ('open', 'all'):
            with self.subTest(state=state):
                data = snapshot()
                data['project'] = [chantier('DRAFT'), chantier('VALID', 1), chantier('CANCELLED', 2)]
                result = projection(data, state=state)
                self.assertEqual([row['name'] for row in result['documents']], ['VALID'])
                self.assertEqual(set(result['details']), {'Chantier::VALID'})

    def test_draft_only_customer_is_absent_from_overview(self):
        data = snapshot()
        data['project'] = [chantier('DRAFT')]
        result = projection(data, customer='')
        self.assertEqual(result['clients'], [])
        self.assertEqual(result['documents'], [])
        self.assertEqual(result['kpis']['orders'], 0)
        self.assertEqual(result['kpis']['balances_a'], [])
        self.assertEqual(result['kpis']['balances_b'], [])

    def test_validated_only_customer_remains_discoverable(self):
        data = snapshot()
        data['project'] = [chantier('VALID', 1), chantier('HIDDEN-DRAFT', customer='OTHER')]
        result = projection(data, customer='')
        self.assertEqual([row['customer'] for row in result['clients']], ['C'])
        self.assertEqual(result['documents'], [])

    def test_linked_orders_and_financial_values_are_unchanged_for_a_and_b(self):
        data = snapshot()
        data['order'] = [order('A'), order('B', 'B')]
        data['order_items'] = [dict(parent=name, name=name + '-ROW', qty=5,
            delivered_qty=0, uom='PC', is_stock_item=1) for name in ('A', 'B')]
        without_project = projection(data)
        with_project_data = deepcopy(data)
        with_project_data['project'] = [chantier('DRAFT')]
        with_project = projection(with_project_data)
        self.assertEqual(with_project['clients'], without_project['clients'])
        self.assertEqual(with_project['kpis'], without_project['kpis'])
        self.assertEqual(with_project['orders'], without_project['orders'])
        self.assertEqual({row['name'] for row in with_project['documents']}, {'A', 'B'})
        self.assertNotIn('Chantier::DRAFT', with_project['details'])
        self.assertEqual(with_project['edges'], [])
        self.assertEqual(with_project_data['project'][0]['docstatus'], 0)

    def test_quotation_of_hidden_draft_remains_visible_and_keeps_customer(self):
        data = snapshot()
        data['project'] = [chantier('DRAFT')]
        data['quotation'] = [dict(name='Q', custom_chantier='DRAFT', party_name='C',
            company='UG', currency='XOF', docstatus=0, grand_total=1180)]
        result = projection(data)
        self.assertEqual([row['name'] for row in result['documents']], ['Q'])
        self.assertEqual([row['customer'] for row in result['clients']], ['C'])
        self.assertEqual(result['edges'], [])
        self.assertEqual(result['details']['Quotation::Q']['linked_documents'], [])

    def test_project_scope_does_not_change_other_customer_visibility(self):
        data = snapshot()
        data['project'] = [chantier('OTHER-VALID', 1, customer='OTHER'), chantier('DRAFT')]
        result = projection(data)
        self.assertEqual(result['documents'], [])
        self.assertEqual({row['customer'] for row in result['clients']}, {'OTHER'})

    def test_snapshot_adds_validated_filter_to_native_project_query_only(self):
        caps = snapshot()['capabilities']
        values = dict(customer='', circuit='all', state='all', followup='all',
            company='UG', from_date='2026-10-01', to_date='2026-10-31')
        with ExitStack() as stack:
            stack.enter_context(patch.object(cockpit, '_read_fields',
                side_effect=lambda doctype, fields, **kw: fields))
            stack.enter_context(patch.object(cockpit, '_children',
                side_effect=lambda data, key, *args: data.update({key: []})))
            stack.enter_context(patch.object(cockpit, '_completion_scope'))
            stack.enter_context(patch.object(cockpit.frappe, 'has_permission', return_value=False))
            query = stack.enter_context(patch.object(cockpit.frappe, 'get_list', return_value=[]))
            cockpit._snapshot(values, caps)
        project_queries = [call for call in query.call_args_list if call.args[0] == 'Chantier']
        self.assertEqual(len(project_queries), 1)
        query_filters = project_queries[0].kwargs['filters']
        self.assertEqual(query_filters['company'], 'UG')
        self.assertEqual(query_filters['creation'], ['between', ['2026-10-01', '2026-10-31']])
        self.assertEqual(query_filters['docstatus'], 1)
        for call in query.call_args_list:
            if call.args[0] in ('Sales Order', 'Quotation'):
                self.assertNotIn('docstatus', call.kwargs['filters'])

    def test_linked_source_lookup_cannot_reintroduce_draft_project(self):
        data = snapshot()
        with patch.object(cockpit, '_read_fields', side_effect=lambda doctype, fields, **kw: fields), \
                patch.object(cockpit.frappe, 'get_list', return_value=[chantier('VALID', 1)]) as query:
            cockpit._add_visible_sources(data, 'project', {'DRAFT', 'VALID'},
                ['name', 'customer', 'docstatus'])
        query.assert_called_once()
        self.assertEqual(query.call_args.args[0], 'Chantier')
        self.assertEqual(query.call_args.kwargs['filters'],
            {'name': ['in', ['DRAFT', 'VALID']], 'docstatus': 1})
        self.assertEqual([row['name'] for row in data['project']], ['VALID'])

    def test_quotation_source_lookup_preserves_existing_native_scope(self):
        data = snapshot()
        with patch.object(cockpit, '_read_fields', side_effect=lambda doctype, fields, **kw: fields), \
                patch.object(cockpit.frappe, 'get_list', return_value=[dict(name='DRAFT', docstatus=0)]) as query:
            cockpit._add_visible_sources(data, 'quotation', {'DRAFT'}, ['name', 'docstatus'])
        self.assertEqual(query.call_args.kwargs['filters'], {'name': ['in', ['DRAFT']]})
        self.assertEqual([row['name'] for row in data['quotation']], ['DRAFT'])

    def test_source_lookup_keeps_native_read_permission_requirement(self):
        data = snapshot()
        data['capabilities']['can_read_projects'] = False
        with patch.object(cockpit.frappe, 'get_list') as query:
            cockpit._add_visible_sources(data, 'project', {'VALID'}, ['name', 'docstatus'])
        query.assert_not_called()
        self.assertEqual(data['project'], [])


if __name__ == '__main__':
    unittest.main()
