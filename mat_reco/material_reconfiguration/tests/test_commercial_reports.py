"""Shared report filters and idempotent metadata migration, without a database."""
import unittest
from unittest.mock import MagicMock, patch

import frappe
from mat_reco.material_reconfiguration.services import commercial_reports as reports


def reject(message, *args, **kwargs):
    raise frappe.ValidationError(message)


class CommercialReportFilterTests(unittest.TestCase):
    def test_default_and_explicit_types(self):
        self.assertEqual(reports.selected_types(reports.normalise({})), ('A', 'B'))
        for value, expected in [('A', ('A',)), ('B', ('B',)), ('All', ('A', 'B')), ('A + B', ('A', 'B'))]:
            self.assertEqual(reports.selected_types(reports.normalise({'order_type': value})), expected)

    @patch.object(frappe, 'throw', side_effect=reject)
    def test_invalid_types_and_reversed_period_are_rejected(self, _throw):
        for filters in ({'order_type': 'Mixte'}, {'from_date': '2026-11-01', 'to_date': '2026-10-01'}, ['A']):
            with self.subTest(filters=filters), self.assertRaises(frappe.ValidationError):
                reports.normalise(filters)

    @patch.object(frappe, 'throw', side_effect=reject)
    def test_order_filter_checks_native_read_and_type(self, _throw):
        order = MagicMock()
        order.get.side_effect = {'custom_ug_order_type': 'B', 'company': 'Company', 'customer': 'Client', 'currency': 'XOF'}.get
        with patch.object(frappe, 'get_doc', return_value=order):
            with self.assertRaises(frappe.ValidationError):
                reports.normalise({'order_type': 'A', 'sales_order': 'SO-B'})
            order.check_permission.assert_called_once_with('read')
            order.check_permission.side_effect = frappe.PermissionError('denied')
            with self.assertRaises(frappe.PermissionError):
                reports.normalise({'order_type': 'All', 'sales_order': 'SO-B'})

    def test_type_a_accepts_historical_empty_order_type(self):
        order = MagicMock()
        order.get.side_effect = {'custom_ug_order_type': None}.get
        with patch.object(frappe, 'get_doc', return_value=order):
            self.assertEqual(reports.normalise({'order_type': 'A', 'sales_order': 'SO-OLD'}).order_type, 'A')

    def test_metadata_merge_is_native_and_idempotent(self):
        old, new, module, _ = reports.REPORTS['orders']
        state = {old, new}
        db = MagicMock()
        db.exists.side_effect = lambda doctype, name: doctype == 'Report' and name in state
        report = MagicMock()
        report.roles = [frappe._dict(role='System Manager'), frappe._dict(role='UG COMMANDES B')]

        def rename(doctype, source, target, **kwargs):
            state.discard(source)

        with patch.object(frappe, 'db', db), patch.object(reports, 'rename_doc', side_effect=rename) as renamed, \
                patch.object(frappe, 'reload_doc') as reloaded, patch.object(frappe, 'get_doc', return_value=report), \
                patch.object(frappe, 'clear_cache'), \
                patch('mat_reco.material_reconfiguration.services.commercial_cockpit_setup.readable_roles', return_value=['System Manager']):
            reports.install_report('orders')
            reports.install_report('orders')
        renamed.assert_called_once_with('Report', old, new, force=True, merge=True,
            ignore_permissions=True, show_alert=False, rebuild_search=False)
        self.assertEqual(reloaded.call_count, 2)
        reloaded.assert_called_with('material_reconfiguration', 'report', module)
        db.set_value.assert_called_with('Report', {'reference_report': old}, 'reference_report', new, update_modified=False)
        self.assertNotIn(old, state)

    def test_workspace_labels_are_renamed_without_altering_unrelated_content(self):
        old, new, _, _ = reports.REPORTS['accounts']
        content = [{'id': 'existing', 'data': {'shortcut_name': old}}, {'data': {'text': 'Keep this'}}]
        renamed = reports._rename_content(content, old, new)
        self.assertEqual(renamed[0]['data']['shortcut_name'], new)
        self.assertEqual(renamed[1], content[1])
        self.assertEqual(content[0]['data']['shortcut_name'], old)
