"""Rollback-only receipt/refund lifecycle, native A GL and separate B ledger."""
import unittest
import uuid
from unittest.mock import patch
import frappe
from frappe.utils import nowdate
from mat_reco.material_reconfiguration.services import special_b as b, special_refunds as refunds
from mat_reco.material_reconfiguration.tests.test_special_a import SpecialATests
from mat_reco.material_reconfiguration.report.situation_des_comptes_clients.situation_des_comptes_clients import execute


class SpecialRefundTests(unittest.TestCase):
    def setUp(self):
        # Other apps may own the first alphabetical Item Group. Choose a shared
        # group for these native ERP fixtures, keeping Item validation active.
        groups=frappe.get_all('Item Group',filters={'is_group':0},fields=['name','company'])
        group=next(row.name for row in groups if not row.company)
        original=frappe.db.get_value
        def value(doctype, filters=None, fieldname='name', *args, **kwargs):
            if doctype=='Item Group' and filters=={'is_group':0} and fieldname=='name':return group
            return original(doctype,filters,fieldname,*args,**kwargs)
        with patch.object(frappe.db,'get_value',side_effect=value):
            SpecialATests.setUp(self)

    def cleanup(self):
        from mat_reco.material_reconfiguration.tests.test_special_b import SpecialBTests
        SpecialBTests.cleanup(self)
        frappe.clear_cache(user='Administrator')
        frappe.local.new_doc_templates.pop('Sales Invoice',None)
    new_order = SpecialATests.new_order
    remove_files = SpecialATests.remove_files
    delivery = SpecialATests.delivery
    payment = SpecialATests.payment

    def receipt_b(self, amount=120):
        return frappe.get_doc(dict(doctype=b.PAYMENT, company=self.company, customer=self.customer,
            currency=self.b_order.currency, sales_order=self.b_order.name, posting_date=nowdate(),
            mode_of_payment=self.mode, reference=uuid.uuid4().hex, amount=amount)).insert().submit()

    def refund(self, source, amount, submit=True):
        doc=refunds.build(source, 'refund', [], dict(amount=amount, posting_date=nowdate(),
            mode_of_payment=self.mode, reference=uuid.uuid4().hex))
        doc.insert()
        if submit:doc.submit()
        return doc

    def balance(self, kind, order):
        rows=execute(dict(company=self.company, customer=self.customer, currency=order.currency,
            sales_order=order.name, order_type=kind, from_date=nowdate(), to_date=nowdate()))[1]
        return next(r['balance'] for r in reversed(rows) if r['description']=='Solde final')

    def test_b_partial_multiple_refunds_and_cancellation(self):
        count=frappe.db.count('Payment Entry')
        source=self.receipt_b()
        first=self.refund(source,30);second=self.refund(source,20)
        source.reload()
        self.assertEqual((source.refunded_amount,source.unallocated_amount),(50,70))
        self.assertEqual(self.balance('B',self.b_order),-70)
        self.assertEqual(b.get_order_summary(self.b_order.name)['balance'],-70)
        self.assertEqual(frappe.db.count('Payment Entry'),count)
        with self.assertRaises(frappe.ValidationError):source.cancel()
        first.cancel();source.reload()
        self.assertEqual((source.refunded_amount,source.unallocated_amount),(20,100))
        self.assertEqual(self.balance('B',self.b_order),-100)
        second.cancel();source.reload()
        self.assertEqual(source.unallocated_amount,120)

    def test_over_refund_and_competing_drafts(self):
        source=self.receipt_b()
        with self.assertRaises(frappe.ValidationError):self.refund(source,121)
        one=self.refund(source,80,False);two=self.refund(source,80,False)
        one.submit()
        with self.assertRaises(frappe.ValidationError):two.submit()
        source.reload();self.assertEqual(source.unallocated_amount,40)
        with self.assertRaises(frappe.ValidationError):self.refund(one,1)

    def test_allocated_cash_cannot_be_refunded_or_allocated_twice(self):
        source=self.receipt_b()
        bl=self.delivery(order=self.b_order)
        source.append('allocations',dict(bordereau=bl.name,amount=50));source.save()
        with self.assertRaises(frappe.ValidationError):self.refund(source,71)
        self.refund(source,70)
        source.reload();self.assertEqual(source.unallocated_amount,0)
        source.allocations[0].amount=51
        with self.assertRaises(frappe.ValidationError):source.save()

    def test_a_native_pay_and_account_report_count_once(self):
        source=self.payment(120)
        refund=self.refund(source,30)
        native=frappe.get_doc('Payment Entry',refund.payment_entry)
        self.assertEqual(native.payment_type,'Pay')
        self.assertEqual(native.docstatus,1)
        received=frappe.get_doc('Payment Entry',source.payment_entry)
        self.assertTrue(any(row.reference_name==native.name for row in received.references))
        self.assertEqual(received.unallocated_amount,90)
        self.assertEqual(self.balance('A',self.order),-90)
        self.assertTrue(frappe.db.exists('GL Entry',dict(voucher_type='Payment Entry',voucher_no=native.name,is_cancelled=0)))
        refund.cancel();source.reload()
        self.assertEqual(source.unallocated_amount,120)
        self.assertEqual(frappe.db.get_value('Payment Entry',native.name,'docstatus'),2)
        self.assertEqual(self.balance('A',self.order),-120)

    def test_cockpit_preparation_has_no_bl_allocation_or_account_override(self):
        source=self.receipt_b()
        data=refunds.prepare(source,'refund')
        self.assertEqual(data['rows'],[])
        self.assertEqual(data['values']['amount'],120)
        self.assertEqual(data['payment_kind'],'Remboursement')
        with self.assertRaises(frappe.ValidationError):
            refunds.build(source,'refund',[],dict(customer='OTHER'))

    def test_mixed_receipt_refunds_only_its_unused_a_advance(self):
        bl=self.delivery(qty=1,order=self.b_order)
        source=self.payment(150,[(bl,100)])
        self.assertEqual(source.order_type,'Mixte')
        refund=self.refund(source,20)
        self.assertEqual(refund.order_type,'A')
        source.reload()
        self.assertEqual(source.unallocated_amount,30)
        self.assertEqual(self.balance('B',self.b_order),0)
        self.assertEqual(self.balance('A',self.order),-30)
        native=frappe.get_doc('Payment Entry',source.payment_entry)
        self.assertEqual(native.unallocated_amount,30)

    def test_a_remaining_advance_can_be_allocated_after_refund(self):
        source=self.payment(120)
        self.refund(source,30)
        bl=self.delivery()
        source.reload();source.append('allocations',dict(bordereau=bl.name,amount=90));source.save()
        source.reload();self.assertEqual(source.unallocated_amount,0)
        native=frappe.get_doc('Payment Entry',source.payment_entry)
        self.assertEqual(native.unallocated_amount,0)
        self.assertEqual(self.balance('A',self.order),210)

    def test_refund_from_cockpit_is_idempotent(self):
        from mat_reco.material_reconfiguration.services import commercial_actions as cockpit
        source=self.receipt_b()
        prepared=cockpit.prepare_action(b.PAYMENT,source.name,'refund')
        self.assertEqual(prepared['payment_kind'],'Remboursement')
        args=dict(source_doctype=b.PAYMENT,source_name=source.name,action='refund',selections=[],
            values=dict(amount=30,posting_date=nowdate(),mode_of_payment=self.mode,reference=uuid.uuid4().hex),
            source_modified=str(source.modified),request_key=uuid.uuid4().hex,intent='submit')
        first=cockpit.execute_action(**args);second=cockpit.execute_action(**args)
        self.assertEqual(first['document']['name'],second['document']['name'])
        self.assertTrue(second['replay'])
        source.reload();self.assertEqual(source.refunded_amount,30)

    def test_native_failure_rolls_back_refund_and_gl(self):
        from mat_reco.material_reconfiguration.services import commercial_actions as cockpit
        source=self.payment(120)
        before=(frappe.db.count(b.PAYMENT),frappe.db.count('Payment Entry'),frappe.db.count('GL Entry'))
        with patch.object(refunds,'sync_source',side_effect=frappe.ValidationError('QA rollback')):
            with self.assertRaisesRegex(frappe.ValidationError,'QA rollback'):
                cockpit.execute_action(b.PAYMENT,source.name,'refund',selections=[],
                    values=dict(amount=30,posting_date=nowdate(),mode_of_payment=self.mode,reference=uuid.uuid4().hex),
                    source_modified=str(source.modified),request_key=uuid.uuid4().hex,intent='submit')
        self.assertEqual(before,(frappe.db.count(b.PAYMENT),frappe.db.count('Payment Entry'),frappe.db.count('GL Entry')))
        source.reload();self.assertEqual(source.unallocated_amount,120)

    def test_b_refund_allowed_for_previously_cancelled_source_order(self):
        source=self.receipt_b()
        # Simulate the persisted state of a historical cancelled command. No
        # cancellation rule or link validation is disabled in application code.
        frappe.db.set_value('Sales Order',self.b_order.name,'docstatus',2)
        refund=self.refund(source,120)
        self.assertEqual(refund.docstatus,1)
        source.reload();self.assertEqual(source.unallocated_amount,0)

    def test_future_refund_does_not_reduce_prior_period_cash(self):
        from frappe.utils import add_days
        source=self.payment(120)
        refund=self.refund(source,30,False)
        refund.posting_date=add_days(nowdate(),1)
        refund.save();refund.submit()
        self.assertEqual(self.balance('A',self.order),-120)

    def test_full_a_refund_clears_the_receivable_once(self):
        source=self.payment(120)
        refund=self.refund(source,120)
        self.assertEqual(self.balance('A',self.order),0)
        source.reload();self.assertEqual(source.unallocated_amount,0)
        with self.assertRaises(frappe.ValidationError):self.refund(source,1)
        refund.cancel();source.reload();self.assertEqual(source.unallocated_amount,120)
