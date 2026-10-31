"""Technical sheet links are auxiliary, validated and permission-scoped."""
import unittest
from unittest.mock import patch

import frappe
from mat_reco.material_reconfiguration.services import workshop_service as service


def root(name='SO', sources=None, chantier=None):
    return dict(id=name, chantier=chantier, children=[], required_qty=5, remaining_qty=3,
        _technical_study_names=sources or ['FT'])


class WorkshopStudyLinksTests(unittest.TestCase):
    def attach(self, roots, visible, permitted=True):
        with patch.object(frappe, 'has_permission', return_value=permitted) as permission, \
                patch.object(frappe, 'get_list', return_value=[frappe._dict(row) for row in visible]) as query:
            service._attach_technical_studies(roots)
        return permission, query

    def test_readable_validated_sheet_is_attached_without_touching_quantities(self):
        order = root()
        _, query = self.attach([order], [dict(name='FT', docstatus=1, sales_order='SO')])
        self.assertEqual(order['technical_studies'], [dict(name='FT', docstatus=1)])
        self.assertEqual((order['required_qty'], order['remaining_qty'], order['children']), (5, 3, []))
        self.assertNotIn('_technical_study_names', order)
        self.assertEqual(query.call_args.args, ('Chantier Technical Study',))
        self.assertEqual(query.call_args.kwargs['filters'], {'name': ['in', ['FT']], 'docstatus': 1})

    def test_unreadable_sheet_leaks_no_reference(self):
        order = root()
        permission, query = self.attach([order], [], permitted=False)
        permission.assert_called_once_with('Chantier Technical Study', 'read')
        query.assert_not_called()
        self.assertEqual(order['technical_studies'], [])
        self.assertNotIn('_technical_study_names', order)

    def test_record_permissions_can_hide_a_sheet_even_with_doctype_read(self):
        order = root()
        _, query = self.attach([order], [])
        query.assert_called_once()
        self.assertEqual(order['technical_studies'], [])
        self.assertNotIn('_technical_study_names', order)

    def test_sheet_of_another_order_is_not_attached(self):
        order = root()
        self.attach([order], [dict(name='FT', docstatus=1, sales_order='OTHER')])
        self.assertEqual(order['technical_studies'], [])

    def test_legacy_chantier_sheet_is_attached_only_to_its_chantier(self):
        orders = [root('SO-1', chantier='CH'), root('SO-2', chantier='OTHER')]
        self.attach(orders, [dict(name='FT', docstatus=1, chantier='CH')])
        self.assertEqual(orders[0]['technical_studies'], [dict(name='FT', docstatus=1)])
        self.assertEqual(orders[1]['technical_studies'], [])

    def test_references_are_batched_and_preserved_with_collapsed_children(self):
        orders = [root('SO-1', ['FT-1', 'FT-1']), root('SO-2', ['FT-2'])]
        _, query = self.attach(orders, [dict(name='FT-1', docstatus=1, sales_order='SO-1'),
            dict(name='FT-2', docstatus=1, sales_order='SO-2')])
        query.assert_called_once()
        self.assertEqual(query.call_args.kwargs['filters']['name'], ['in', ['FT-1', 'FT-2']])
        self.assertEqual([order['technical_studies'][0]['name'] for order in orders], ['FT-1', 'FT-2'])
        self.assertTrue(all(not order['children'] for order in orders))

    def test_no_reference_requires_no_extra_permission_or_query(self):
        order = dict(id='SO', children=[])
        permission, query = self.attach([order], [])
        permission.assert_not_called(); query.assert_not_called()
        self.assertEqual(order['technical_studies'], [])
