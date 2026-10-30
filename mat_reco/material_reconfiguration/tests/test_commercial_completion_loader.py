"""Read-only sibling and child scopes used to prove commercial completion."""
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from mat_reco.material_reconfiguration.services import commercial_cockpit as cockpit


class CommercialCompletionLoaderTests(unittest.TestCase):
    def data(self):
        return dict(project=[dict(name='CH')], quotation=[dict(name='Q')],
            order=[dict(name='CURRENT')], capabilities=dict(can_read_orders=True,
                can_read_quotations=True), incomplete_children=set(), warnings=[])

    def meta(self, readable_table=True):
        return SimpleNamespace(get_field=lambda name: SimpleNamespace(permlevel=0),
            get_permlevel_access=lambda permission: [0] if readable_table else [])

    def test_peers_ignore_period_and_circuit_without_widening_financial_scope(self):
        data = self.data()
        responses = [[dict(name='OTHER', docstatus=0, custom_chantier='CH')],
            [dict(name='OLD-Q', docstatus=1, custom_chantier='CH', status='Lost')]]
        with patch.object(cockpit, '_read_fields', side_effect=lambda doctype, fields, **kw: fields), \
                patch.object(cockpit.frappe, 'get_meta', return_value=self.meta()), \
                patch.object(cockpit.frappe, 'get_list', side_effect=responses) as query:
            cockpit._completion_scope(data)
        self.assertEqual(data['order'], [dict(name='CURRENT')])
        self.assertEqual(data['quotation'], [dict(name='Q')])
        self.assertEqual(data['completion_orders'][0]['name'], 'OTHER')
        self.assertEqual(data['completion_quotations'][0]['name'], 'OLD-Q')
        self.assertFalse(data['completion_scope_incomplete'])
        self.assertEqual(query.call_args_list[0].kwargs['or_filters'], [
            ['Sales Order', 'custom_chantier', 'in', ['CH']],
            ['Sales Order Item', 'prevdoc_docname', 'in', ['Q']]])
        for index, call in enumerate(query.call_args_list):
            self.assertEqual(call.kwargs['filters'], {'docstatus': ['<', 2]})
            self.assertTrue(call.kwargs['distinct'])
            self.assertEqual(call.kwargs['limit_page_length'], cockpit.MAX_PARENTS + 1)
            self.assertEqual(call.kwargs['fields'], ['name', 'docstatus', 'custom_chantier'] +
                (['status'] if index == 1 else []))

    def test_hidden_quotation_status_keeps_completion_scope_unknown(self):
        data = self.data()
        with patch.object(cockpit, '_read_fields', side_effect=lambda doctype, fields, **kw:
                [field for field in fields if field != 'status']), \
                patch.object(cockpit.frappe, 'get_meta', return_value=self.meta()), \
                patch.object(cockpit.frappe, 'get_list', return_value=[]) as query:
            cockpit._completion_scope(data)
        self.assertTrue(data['completion_scope_incomplete'])
        self.assertEqual(data['completion_quotations'], [])
        self.assertEqual(query.call_count, 1)
        self.assertEqual(query.call_args.args[0], 'Sales Order')

    def test_hidden_order_table_prevents_positive_completion_proof(self):
        data = self.data()
        with patch.object(cockpit, '_read_fields', side_effect=lambda doctype, fields, **kw: fields), \
                patch.object(cockpit.frappe, 'get_meta', return_value=self.meta(False)), \
                patch.object(cockpit.frappe, 'get_list', return_value=[]) as query:
            cockpit._completion_scope(data)
        self.assertTrue(data['completion_scope_incomplete'])
        self.assertEqual(query.call_args_list[0].kwargs['or_filters'], [
            ['Sales Order', 'custom_chantier', 'in', ['CH']]])

    def test_missing_parent_link_field_does_not_query_peers(self):
        data = self.data()
        with patch.object(cockpit, '_read_fields', side_effect=lambda doctype, fields, **kw:
                [field for field in fields if field != 'custom_chantier']), \
                patch.object(cockpit.frappe, 'get_meta', return_value=self.meta()), \
                patch.object(cockpit.frappe, 'get_list') as query:
            cockpit._completion_scope(data)
        self.assertTrue(data['completion_scope_incomplete'])
        query.assert_not_called()

    def test_absent_read_permissions_keep_scope_unknown(self):
        data = self.data()
        data['capabilities'] = {}
        with patch.object(cockpit, '_read_fields', side_effect=lambda doctype, fields, **kw: fields), \
                patch.object(cockpit.frappe, 'get_list') as query:
            cockpit._completion_scope(data)
        self.assertTrue(data['completion_scope_incomplete'])
        query.assert_not_called()

    def test_truncated_metadata_does_not_turn_financial_scope_incomplete(self):
        data = self.data()
        rows = [dict(name=str(index), docstatus=1, custom_chantier='CH')
            for index in range(cockpit.MAX_PARENTS + 1)]
        with patch.object(cockpit, '_read_fields', side_effect=lambda doctype, fields, **kw: fields), \
                patch.object(cockpit.frappe, 'get_meta', return_value=self.meta()), \
                patch.object(cockpit.frappe, 'get_list', return_value=rows):
            cockpit._completion_scope(data)
        self.assertTrue(data['completion_scope_incomplete'])
        self.assertEqual(len(data['completion_orders']), cockpit.MAX_PARENTS)
        self.assertNotIn('truncated', data)
        self.assertNotIn('incomplete_parents', data)

    def test_permission_denied_by_native_list_retains_unknown_scope(self):
        data = self.data()
        with patch.object(cockpit, '_read_fields', side_effect=lambda doctype, fields, **kw: fields), \
                patch.object(cockpit.frappe, 'get_meta', return_value=self.meta()), \
                patch.object(cockpit.frappe, 'get_list', side_effect=cockpit.frappe.PermissionError):
            cockpit._completion_scope(data)
        self.assertTrue(data['completion_scope_incomplete'])

    def test_missing_new_child_quantities_are_marked_unknown(self):
        for key, doctype, kind, table, fields in (
                ('quotation_items', 'Quotation Item', 'quotation', 'items', ['name', 'qty', 'stock_qty']),
                ('project_lines', 'Chantier Line', 'project', 'lines', ['name', 'line_id', 'qty']),
                ('project_extras', 'Chantier Commercial Extra', 'project', 'commercial_extras', ['name', 'line_id', 'qty'])):
            with self.subTest(key=key):
                data = self.data()
                with patch.object(cockpit, '_read_fields', return_value=['name']), \
                        patch.object(cockpit.frappe, 'get_meta', return_value=self.meta()), \
                        patch.object(cockpit.frappe, 'get_all', return_value=[dict(name='ROW')]):
                    cockpit._children(data, key, doctype, kind, table, fields)
                self.assertIn(key, data['incomplete_children'])


if __name__ == '__main__':
    unittest.main()
