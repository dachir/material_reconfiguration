"""Quotation/order schedule date regressions, with native calendar rules and no writes."""
import copy
from types import SimpleNamespace
import unittest

import frappe
from frappe.utils import getdate

from mat_reco.material_reconfiguration.services import chantier_service, commercial_actions


class Draft(frappe._dict):
    def set(self, key, value):
        self[key] = value


def order(rows, **values):
    return Draft(doctype='Sales Order', docstatus=0, transaction_date='2026-10-30',
        payment_schedule=[frappe._dict(row) for row in rows], items=[], **values)


class CommercialPaymentScheduleTests(unittest.TestCase):
    def test_native_erpnext_date_validation_rejects_old_schedule_and_accepts_rebased_one(self):
        from unittest.mock import patch
        from erpnext.controllers.accounts_controller import AccountsController

        class ScheduleRow(frappe._dict):
            def validate_from_to_dates(self, *args):
                pass

        def reject(message, *args, **kwargs):
            raise frappe.ValidationError(message)

        doc = order([])
        doc.payment_schedule = [ScheduleRow(idx=1, due_date='2026-10-29', invoice_portion=100, payment_amount=100)]
        with patch.object(frappe, 'throw', side_effect=reject), \
                patch('erpnext.controllers.accounts_controller._', side_effect=lambda message: message):
            with self.assertRaisesRegex(frappe.ValidationError, 'Due Date.*before Posting Date'):
                AccountsController.validate_payment_schedule_dates(doc)
            chantier_service.rebase_order_payment_schedule(doc, '2026-10-29')
            AccountsController.validate_payment_schedule_dates(doc)

    def test_immediate_schedule_copied_from_previous_day_uses_order_date(self):
        doc = order([dict(due_date='2026-10-29', invoice_portion=100,
            payment_amount=120000, base_payment_amount=120000)])
        chantier_service.rebase_order_payment_schedule(doc, '2026-10-29')
        self.assertEqual(getdate(doc.payment_schedule[0].due_date), getdate('2026-10-30'))
        self.assertEqual(doc.payment_schedule[0].invoice_portion, 100)
        self.assertEqual(doc.payment_schedule[0].payment_amount, 120000)
        self.assertEqual(doc.payment_schedule[0].base_payment_amount, 120000)

    def test_native_credit_days_and_discount_rules_use_order_date(self):
        doc = order([dict(due_date='2026-11-28', due_date_based_on='Day(s) after invoice date',
            credit_days=30, discount_date='2026-11-03',
            discount_validity_based_on='Day(s) after invoice date', discount_validity=5,
            discount=2, discount_type='Percentage')])
        chantier_service.rebase_order_payment_schedule(doc, '2026-10-29')
        row = doc.payment_schedule[0]
        self.assertEqual(getdate(row.due_date), getdate('2026-11-29'))
        self.assertEqual(getdate(row.discount_date), getdate('2026-11-04'))
        self.assertEqual((row.discount, row.discount_type), (2, 'Percentage'))

    def test_native_end_of_month_rule_is_recomputed_instead_of_shifted(self):
        doc = order([dict(due_date='2026-10-10', credit_days=10,
            due_date_based_on='Day(s) after the end of the invoice month')])
        chantier_service.rebase_order_payment_schedule(doc, '2026-09-29')
        self.assertEqual(getdate(doc.payment_schedule[0].due_date), getdate('2026-11-10'))

    def test_manual_installments_keep_intervals_amounts_and_description(self):
        doc = order([dict(due_date='2026-10-29', discount_date='2026-10-28', invoice_portion=25,
            payment_amount=250, mode_of_payment='Cash', description='Acompte'),
            dict(due_date='2026-11-28', invoice_portion=75, payment_amount=750)])
        chantier_service.rebase_order_payment_schedule(doc, '2026-10-29')
        first, second = doc.payment_schedule
        self.assertEqual(getdate(first.due_date), getdate('2026-10-30'))
        self.assertEqual(getdate(first.discount_date), getdate('2026-10-29'))
        self.assertEqual(getdate(second.due_date), getdate('2026-11-29'))
        self.assertEqual((first.invoice_portion, second.invoice_portion), (25, 75))
        self.assertEqual((first.payment_amount, second.payment_amount), (250, 750))
        self.assertEqual((first.mode_of_payment, first.description), ('Cash', 'Acompte'))

    def test_mapping_chantier_order_does_not_modify_source_quotation(self):
        source = frappe._dict(doctype='Quotation', name='Q', custom_chantier='C',
            transaction_date='2026-10-29', payment_schedule=[frappe._dict(due_date='2026-10-29')])
        before = copy.deepcopy(source)
        doc = order(copy.deepcopy(source.payment_schedule))
        doc['items'] = [frappe._dict(prevdoc_docname='Q', custom_chantier_section='S')]
        chantier_service.map_chantier(doc, 'after_mapping', source)
        self.assertEqual(getdate(doc.payment_schedule[0].due_date), getdate('2026-10-30'))
        self.assertEqual(source, before)
        self.assertEqual(doc.custom_chantier, 'C')
        self.assertIsNone(doc['items'][0].custom_chantier_section)

    def test_standard_mapping_without_chantier_is_unchanged(self):
        source = frappe._dict(doctype='Quotation', name='Q', transaction_date='2026-10-29')
        doc = order([dict(due_date='2026-10-29')])
        chantier_service.map_chantier(doc, 'after_mapping', source)
        self.assertEqual(doc.payment_schedule[0].due_date, '2026-10-29')

    def test_populated_target_with_another_quotation_keeps_existing_schedule(self):
        from unittest.mock import patch
        source = frappe._dict(doctype='Quotation', name='Q', custom_chantier='C', transaction_date='2026-10-29')
        doc = order([dict(due_date='2026-11-01')], custom_chantier='C')
        doc['items'] = [frappe._dict(prevdoc_docname='OTHER'), frappe._dict(prevdoc_docname='Q')]
        with patch.object(chantier_service.frappe, 'get_cached_value', return_value='C'):
            chantier_service.map_chantier(doc, 'after_mapping', source)
        self.assertEqual(doc.payment_schedule[0].due_date, '2026-11-01')

    def test_cockpit_user_date_rebases_after_mapping_and_keeps_delivery_dates(self):
        doc = order([dict(due_date='2026-10-30')], delivery_date='2026-11-05')
        doc.meta = SimpleNamespace(get_permitted_fieldnames=lambda **kwargs:['transaction_date', 'delivery_date'])
        doc['items'] = [frappe._dict(delivery_date='2026-11-05')]
        commercial_actions._headers(doc, dict(transaction_date='2026-11-02', delivery_date='2026-11-06'))
        self.assertEqual(getdate(doc.payment_schedule[0].due_date), getdate('2026-11-02'))
        self.assertEqual(doc['items'][0].delivery_date, '2026-11-06')

    def test_same_date_submitted_order_and_other_doctypes_are_not_changed(self):
        for changes, previous in (({}, '2026-10-30'), ({'docstatus':1}, '2026-10-29'),
                ({'doctype':'Quotation'}, '2026-10-29'), ({}, None)):
            with self.subTest(changes=changes, previous=previous):
                doc = order([dict(due_date='2026-10-29')])
                doc.update(changes)
                chantier_service.rebase_order_payment_schedule(doc, previous)
                self.assertEqual(doc.payment_schedule[0].due_date, '2026-10-29')
