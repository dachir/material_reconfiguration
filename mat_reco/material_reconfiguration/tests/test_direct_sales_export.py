"""Direct B sales export after stock completion, without creating a technical sheet."""
from contextlib import ExitStack
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

import frappe
from mat_reco.material_reconfiguration.services import order_b_export as exchange
from mat_reco.material_reconfiguration.services import order_b_stock as stock


class DirectSalesExportTests(unittest.TestCase):
    def run_export(self, kinds, sheet=None, sheet_status=None, complete=True):
        order = SimpleNamespace(name='SO-B', custom_ug_b_export_file=None,
            custom_technical_study=sheet,
            items=[frappe._dict(item_code=kind) for kind in kinds], add_comment=MagicMock())
        database = MagicMock()
        database.get_value.return_value = sheet_status
        archive = SimpleNamespace(name='ARCHIVE', file_url='/private/files/export.zip')

        def reject(message, *args, **kwargs):
            raise frappe.ValidationError(message)

        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.object(frappe, 'db', new=database))
        stack.enter_context(patch.object(frappe, 'session', new=SimpleNamespace(user='test')))
        stack.enter_context(patch.object(frappe, 'throw', side_effect=reject))
        stack.enter_context(patch.object(frappe, 'get_cached_value',
            side_effect=lambda doctype, name, field: name))
        stack.enter_context(patch.object(exchange, 'get_order', return_value=order))
        stack.enter_context(patch.object(exchange, 'is_complete', return_value=complete))
        stack.enter_context(patch.object(exchange, 'now_datetime', return_value='2026-10-31 12:00:00'))
        package = stack.enter_context(patch.object(exchange, 'package', return_value=b'CSV'))
        save = stack.enter_context(patch('frappe.utils.file_manager.save_file', return_value=archive))
        stack.enter_context(patch.object(stock, 'refresh_tasks'))
        return package, save, database

    def test_direct_sales_export_without_ft_after_all_stock_exits(self):
        for kinds in (('PRIMAIRE',), ('ACCESSOIRE',), ('SERVICE',),
                ('PRIMAIRE', 'ACCESSOIRE', 'SERVICE')):
            with self.subTest(kinds=kinds):
                package, save, db = self.run_export(kinds)
                self.assertEqual(exchange.export_order.__wrapped__('SO-B')['file'], 'ARCHIVE')
                package.assert_called_once(); save.assert_called_once()
                db.get_value.assert_not_called()

    def test_direct_sales_still_require_completed_stock_exits(self):
        package, save, _ = self.run_export(('PRIMAIRE',), complete=False)
        with self.assertRaisesRegex(frappe.ValidationError, 'sorties physiques'):
            exchange.export_order.__wrapped__('SO-B')
        package.assert_not_called(); save.assert_not_called()

    def test_manufacturing_and_mixed_orders_still_require_validated_ft(self):
        for kinds in (('OUVRAGE',), ('DECOUPE',), ('PRIMAIRE', 'OUVRAGE')):
            for sheet, status in ((None, None), ('FT', 0), ('FT', 2)):
                with self.subTest(kinds=kinds, status=status):
                    package, save, _ = self.run_export(kinds, sheet, status)
                    with self.assertRaisesRegex(frappe.ValidationError, 'fiche technique'):
                        exchange.export_order.__wrapped__('SO-B')
                    package.assert_not_called(); save.assert_not_called()

    def test_manufacturing_export_still_requires_both_ft_and_stock_completion(self):
        for complete in (False, True):
            with self.subTest(complete=complete):
                _, save, _ = self.run_export(('DECOUPE',), 'FT', 1, complete)
                if complete:
                    self.assertEqual(exchange.export_order.__wrapped__('SO-B')['file'], 'ARCHIVE')
                    save.assert_called_once()
                else:
                    with self.assertRaisesRegex(frappe.ValidationError, 'sorties physiques'):
                        exchange.export_order.__wrapped__('SO-B')
                    save.assert_not_called()
