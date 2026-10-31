"""Direct sales skip FT; manufacturing still creates one scoped, idempotent FT.

These tests use the real preparation rules and never initialise a site or database.
"""
from contextlib import ExitStack
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

import frappe
from mat_reco.material_reconfiguration.services import order_technical as service
from mat_reco.material_reconfiguration.services import order_b_stock as stock
from mat_reco.material_reconfiguration.services import task_notifications as tasks
from mat_reco.material_reconfiguration.services import technical_study_service as technical


class Study(frappe._dict):
    def append(self, field, value):
        self.setdefault(field, []).append(frappe._dict(value))

    def insert(self, **kwargs):
        self.inserted = True


class Order(SimpleNamespace):
    def get(self, field, default=None):
        return getattr(self, field, default)


class DirectSalesTechnicalTests(unittest.TestCase):
    def order(self, circuit='A', kinds=('PRIMAIRE', 'SERVICE', 'ACCESSOIRE'), chantier=None):
        return Order(name='SO-' + circuit, docstatus=1, custom_ug_order_type=circuit,
            custom_chantier=chantier, custom_technical_study=None,
            items=[frappe._dict(item_code=kind, name='ROW-' + str(i)) for i, kind in enumerate(kinds)])

    def patch_items(self):
        return patch.object(frappe, 'get_cached_value', side_effect=lambda doctype, item, field: item)

    def test_direct_a_and_b_skip_study_task_and_source_reconstruction(self):
        for circuit in ('A', 'B'):
            for kinds in (('PRIMAIRE',), ('SERVICE',), ('ACCESSOIRE',),
                    ('PRIMAIRE', 'SERVICE', 'ACCESSOIRE')):
                with self.subTest(circuit=circuit, kinds=kinds), self.patch_items(), \
                        patch.object(frappe, 'db', new=MagicMock()) as db, \
                        patch.object(service, 'context') as context, \
                        patch.object(frappe, 'get_doc') as get_doc, \
                        patch.object(tasks, 'send_tasks') as notify:
                    order = self.order(circuit, kinds)
                    self.assertFalse(service.requires_study(order))
                    self.assertIsNone(service.prepare(order))
                    self.assertFalse(order.custom_technical_study)
                    context.assert_not_called(); get_doc.assert_not_called(); notify.assert_not_called()
                    db.get_value.assert_not_called(); db.set_value.assert_not_called()

    def test_direct_chantier_does_not_handoff_even_if_unused_types_exist(self):
        dossier = frappe._dict(workflow_version=2, work_types=[frappe._dict(type_id='UNUSED')])
        for circuit in ('A', 'B'):
            with self.subTest(circuit=circuit), self.patch_items(), \
                    patch.object(frappe, 'db', new=MagicMock()) as db, \
                    patch.object(frappe, 'get_doc', return_value=dossier), \
                    patch.object(service, 'context') as context, \
                    patch.object(tasks, 'send_tasks') as notify:
                order = self.order(circuit, chantier='CH')
                self.assertIsNone(service.prepare(order))
                context.assert_not_called(); notify.assert_not_called(); db.set_value.assert_not_called()

    def test_only_ouvrage_or_decoupe_needs_study(self):
        for circuit in ('A', 'B'):
            for kind in ('OUVRAGE', 'DECOUPE'):
                with self.subTest(circuit=circuit, kind=kind), self.patch_items():
                    self.assertTrue(service.requires_study(self.order(circuit, (kind,))))
                    self.assertTrue(service.requires_study(self.order(circuit, ('SERVICE', kind, 'PRIMAIRE'))))

    def harness(self, dossier, existing=None):
        stack = ExitStack()
        self.addCleanup(stack.close)
        database = stack.enter_context(patch.object(frappe, 'db', new=MagicMock()))
        study = Study(name='FT-1', docstatus=0, lines=[])
        database.get_value.side_effect = lambda doctype, *a, **kw: (
            existing if doctype == 'Chantier Technical Study' else 'SO-A')
        get_doc = stack.enter_context(patch.object(frappe, 'get_doc', return_value=study))
        stack.enter_context(self.patch_items())
        context = stack.enter_context(patch.object(service, 'context', return_value=(None, dossier, 'HASH')))
        stack.enter_context(patch.object(technical, 'seed_item', return_value=dict(item_type='OUVRAGE')))
        notify = stack.enter_context(patch.object(tasks, 'send_tasks'))
        return database, study, context, get_doc, notify

    def test_mixed_order_ft_contains_only_used_types_and_no_direct_lines(self):
        dossier = frappe._dict(work_types=[
            frappe._dict(type_id='T', designation='Double vitrage', thickness_mm=24, proposed_item='OUVRAGE'),
            frappe._dict(type_id='UNUSED', designation='Unused', thickness_mm=8)], lines=[
            frappe._dict(work_type='T'), frappe._dict(work_type='T'),
            frappe._dict(line_kind='Vente directe', work_type=None, sale_item='PRIMAIRE'),
            frappe._dict(line_kind='Vente directe', work_type=None, sale_item='SERVICE'),
            frappe._dict(line_kind='Vente directe', work_type=None, sale_item='ACCESSOIRE')])
        for circuit in ('A', 'B'):
            with self.subTest(circuit=circuit):
                db, study, context, _, notify = self.harness(dossier)
                order = self.order(circuit, ('OUVRAGE', 'PRIMAIRE', 'SERVICE', 'ACCESSOIRE'))
                self.assertEqual(service.prepare(order), study.name)
                self.assertEqual([row.line_id for row in study.lines], ['T'])
                self.assertTrue(study.inserted); context.assert_called_once()
                self.assertEqual(order.custom_technical_study, study.name)
                db.set_value.assert_called_once()
                notify.assert_called_once_with(study, 'technical', 'order-validated:' + order.name)

    def test_missing_used_types_does_not_insert_empty_study(self):
        dossier = frappe._dict(work_types=[], lines=[])
        db, study, _, _, notify = self.harness(dossier)
        self.assertIsNone(service.prepare(self.order(kinds=('OUVRAGE',))))
        self.assertFalse(study.inserted); db.set_value.assert_not_called(); notify.assert_not_called()

    def test_existing_study_is_reused_without_rebuilding_or_inserting(self):
        db, study, context, get_doc, notify = self.harness(None, existing='FT-1')
        self.assertEqual(service.prepare(self.order(kinds=('DECOUPE',))), 'FT-1')
        context.assert_not_called(); self.assertFalse(study.inserted)
        get_doc.assert_called_once_with('Chantier Technical Study', 'FT-1')
        notify.assert_called_once()

    def test_draft_orders_create_no_ft(self):
        order = self.order(kinds=('OUVRAGE',)); order.docstatus = 0
        with patch.object(frappe, 'db', new=MagicMock()) as db, \
                patch.object(tasks, 'send_tasks') as notify:
            self.assertIsNone(service.prepare(order))
            db.get_value.assert_not_called(); notify.assert_not_called()

    def test_order_submit_hook_readies_direct_b_stock_tasks_only(self):
        for circuit, kind, expected in (('A', 'PRIMAIRE', False), ('B', 'PRIMAIRE', True),
                ('B', 'SERVICE', True), ('B', 'DECOUPE', False)):
            with self.subTest(circuit=circuit, kind=kind), self.patch_items(), \
                    patch.object(service, 'prepare', return_value=None) as prepare, \
                    patch.object(stock, 'refresh_tasks') as refresh:
                order = self.order(circuit, (kind,))
                self.assertIsNone(tasks.order_created(order))
                prepare.assert_called_once_with(order)
                if expected:
                    refresh.assert_called_once_with(order.name, 'order-created')
                else:
                    refresh.assert_not_called()

    def test_direct_b_stock_task_does_not_require_ft_validation(self):
        order = self.order('B', ('PRIMAIRE',))
        with self.patch_items(), patch.object(frappe, 'db', new=MagicMock()) as db, \
                patch.object(frappe, 'get_doc', return_value=order), \
                patch.object(stock, 'is_complete', return_value=False), \
                patch.object(stock, '_receipts', return_value=({}, {}, {}, {})), \
                patch.object(stock, 'physical_rows', return_value=order.items), \
                patch.object(tasks, 'send_tasks') as notify, \
                patch.object(tasks, 'close_tasks'):
            stock.refresh_tasks(order.name, 'submit')
            notify.assert_called_once_with(order, 'b_issue', 'ready:submit')
            db.get_value.assert_not_called()

    def test_manufacturing_b_still_waits_for_validated_ft_before_stock_task(self):
        order = self.order('B', ('DECOUPE',))
        with self.patch_items(), patch.object(frappe, 'db', new=MagicMock()), \
                patch.object(frappe, 'get_doc', return_value=order), \
                patch.object(stock, 'is_complete') as complete, \
                patch.object(tasks, 'send_tasks') as notify:
            stock.refresh_tasks(order.name, 'submit')
            complete.assert_not_called(); notify.assert_not_called()

    def test_complete_direct_b_order_readies_sage_without_ft(self):
        order = self.order('B', ('SERVICE',))
        with self.patch_items(), patch.object(frappe, 'db', new=MagicMock()), \
                patch.object(frappe, 'get_doc', return_value=order), \
                patch.object(stock, 'is_complete', return_value=True), \
                patch.object(tasks, 'send_tasks') as notify, \
                patch.object(tasks, 'close_tasks') as close:
            stock.refresh_tasks(order.name, 'submit')
            close.assert_called_once_with(order, 'b_issue')
            notify.assert_called_once_with(order, 'b_export', 'ready:submit')


if __name__ == '__main__':
    unittest.main()
