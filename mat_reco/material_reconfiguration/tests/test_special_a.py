"""Native stock, invoicing and reconciliation behind shared A/B special documents."""
import unittest
import uuid
from unittest.mock import patch

import frappe
from frappe.utils import nowdate, flt
from mat_reco.material_reconfiguration.services import special_b as b
from mat_reco.material_reconfiguration.tests import test_special_b as fixtures
from mat_reco.material_reconfiguration.report.situation_des_comptes_clients_b.situation_des_comptes_clients_b import execute


class SpecialATests(unittest.TestCase):
    cleanup=fixtures.SpecialBTests.cleanup
    new_order=fixtures.SpecialBTests.new_order
    remove_files=fixtures.SpecialBTests.remove_files
    delivery=fixtures.SpecialBTests.delivery

    def setUp(self):
        fixtures.SpecialBTests.setUp(self)
        # Keep invoice validators and native GL active, but never contact a fiscal
        # service while exercising rollback-only ERPNext fixtures.
        if 'e_def' in frappe.get_installed_apps():
            fiscal=patch('e_def.e_def.api.sales_invoice_on_submit')
            fiscal.start();self.addCleanup(fiscal.stop)
        self.b_order=self.order
        self.order=self.new_order('A')
        if frappe.get_meta('Item').has_field('custom_edef_type_article'):
            self.item.db_set('custom_edef_type_article','BIE')
        if frappe.get_meta('Sales Invoice').has_field('custom_edef_type_facture'):
            frappe.defaults.set_user_default('custom_edef_type_facture','FV')
            frappe.local.new_doc_templates.pop('Sales Invoice',None)
        self.cash=frappe.db.get_value('Account',{'company':self.company,'account_type':'Cash','is_group':0},'name')
        if not self.cash:
            self.cash=frappe.db.get_value('Account',{'company':self.company,'account_type':'Bank','is_group':0},'name')
        self.mode=frappe.get_doc(dict(doctype='Mode of Payment',mode_of_payment='QA A '+uuid.uuid4().hex[:8],type='Cash',
            accounts=[dict(company=self.company,default_account=self.cash)])).insert().name

    def cleanup(self):
        SpecialBTests.cleanup(self)
        frappe.clear_cache(user='Administrator')
        frappe.local.new_doc_templates.pop('Sales Invoice',None)

    def payment(self,amount,allocations=None,submit=True):
        doc=frappe.get_doc(dict(doctype=b.PAYMENT,company=self.company,customer=self.customer,currency=self.order.currency,
            sales_order=self.order.name,posting_date=nowdate(),mode_of_payment=self.mode,reference=uuid.uuid4().hex,
            amount=amount,allocations=[dict(bordereau=bl.name,amount=value) for bl,value in (allocations or [])])).insert()
        if submit:doc.submit()
        return doc

    def test_delivery_creates_one_native_delivery_and_invoice(self):
        before_issue=frappe.db.count('Stock Entry')
        bl=self.delivery()
        self.assertEqual(bl.order_type,'A')
        self.assertTrue(bl.delivery_note);self.assertTrue(bl.sales_invoice)
        dn=frappe.get_doc('Delivery Note',bl.delivery_note);invoice=frappe.get_doc('Sales Invoice',bl.sales_invoice)
        self.assertEqual(dn.docstatus,1);self.assertEqual(invoice.docstatus,1)
        self.assertFalse(invoice.update_stock)
        self.assertEqual(invoice.items[0].delivery_note,dn.name)
        self.assertEqual(invoice.items[0].sales_order,self.order.name)
        self.assertEqual(invoice.grand_total,bl.grand_total)
        self.assertEqual(frappe.db.count('Stock Entry'),before_issue)
        self.assertEqual(frappe.db.get_value('Bin',{'item_code':self.item.name,'warehouse':self.warehouse},'actual_qty'),2)
        self.assertTrue(frappe.db.exists('GL Entry',dict(voucher_type='Sales Invoice',voucher_no=invoice.name,party_type='Customer')))
        self.assertEqual(b.get_order_summary(self.order.name)['items'][0]['remaining_qty'],0)
        with self.assertRaises(frappe.ValidationError):b.make_delivery(self.order.name)

    def test_partial_deliveries_and_taxes_use_native_ttc(self):
        tax=frappe.db.get_value('Account',{'company':self.company,'account_type':'Tax','is_group':0},'name')
        if not tax:self.skipTest('No tax account in fixture company')
        order=frappe.copy_doc(self.order);order.amended_from=None;order.docstatus=0
        order.custom_technical_study=None
        order.append('taxes',dict(charge_type='On Net Total',account_head=tax,description='TVA',rate=18))
        order.insert();order.submit();frappe.get_doc('Chantier Technical Study',order.custom_technical_study).submit()
        self.order=order
        first=self.delivery(1);second=self.delivery(2)
        self.assertEqual(first.net_total+second.net_total,order.net_total)
        self.assertAlmostEqual(first.grand_total+second.grand_total,order.grand_total)
        self.assertGreater(first.tax_amount,0)
        self.assertEqual(sum(frappe.get_doc('Sales Invoice',d.sales_invoice).grand_total for d in [first,second]),order.grand_total)

    def test_payment_one_entry_multiple_invoices_and_no_double_b_balance(self):
        first=self.delivery(1);second=self.delivery(2)
        receipt=self.payment(150,[(first,100),(second,50)])
        self.assertTrue(receipt.payment_entry)
        pe=frappe.get_doc('Payment Entry',receipt.payment_entry)
        self.assertEqual(pe.docstatus,1)
        self.assertEqual(pe.paid_amount,150)
        self.assertEqual({r.reference_name:r.allocated_amount for r in pe.references},
                         {first.sales_invoice:100,second.sales_invoice:50})
        self.assertEqual(frappe.db.get_value('Sales Invoice',first.sales_invoice,'outstanding_amount'),0)
        self.assertEqual(frappe.db.get_value('Sales Invoice',second.sales_invoice,'outstanding_amount'),150)
        rows=execute(dict(company=self.company,customer=self.customer,currency=self.order.currency,
                          sales_order=self.b_order.name,from_date=nowdate(),to_date=nowdate()))[1]
        self.assertFalse(any(r.get('reference_name') in [first.name,second.name,receipt.name] for r in rows))
        self.assertTrue(all(not r.get('debit') and not r.get('credit') for r in rows))
        self.payment(150,[(second,150)])
        self.assertEqual(frappe.db.get_value('Sales Invoice',second.sales_invoice,'outstanding_amount'),0)

    def test_advance_reallocation_keeps_same_payment_entry(self):
        receipt=self.payment(50)
        payment_entry=receipt.payment_entry
        bl=self.delivery(1)
        self.assertEqual(frappe.db.get_value('Sales Invoice',bl.sales_invoice,'outstanding_amount'),100)
        receipt.append('allocations',dict(bordereau=bl.name,amount=50));receipt.save()
        self.assertEqual(receipt.payment_entry,payment_entry)
        self.assertEqual(frappe.db.get_value('Payment Entry',payment_entry,'docstatus'),1)
        self.assertEqual(frappe.db.get_value('Sales Invoice',bl.sales_invoice,'outstanding_amount'),50)
        self.assertEqual(frappe.db.count('Payment Entry',{'custom_ug_special_payment':receipt.name}),1)
        receipt.cancel()
        self.assertEqual(frappe.db.get_value('Sales Invoice',bl.sales_invoice,'outstanding_amount'),100)

    def test_cancellation_reverses_payment_invoice_and_stock(self):
        bl=self.delivery(1)
        receipt=self.payment(100,[(bl,100)])
        with self.assertRaises(frappe.ValidationError):bl.cancel()
        receipt.cancel()
        self.assertEqual(frappe.db.get_value('Payment Entry',receipt.payment_entry,'docstatus'),2)
        bl.reload();bl.cancel()
        self.assertEqual(frappe.db.get_value('Sales Invoice',bl.sales_invoice,'docstatus'),2)
        self.assertEqual(frappe.db.get_value('Delivery Note',bl.delivery_note,'docstatus'),2)
        self.assertEqual(frappe.db.get_value('Bin',{'item_code':self.item.name,'warehouse':self.warehouse},'actual_qty'),5)
        self.assertEqual(b.get_order_summary(self.order.name)['items'][0]['remaining_qty'],3)

    def test_invoice_failure_rolls_back_delivery_and_no_double_exit(self):
        bl=self.delivery(1,submit=False)
        before_dn=frappe.db.count('Delivery Note');before_si=frappe.db.count('Sales Invoice')
        frappe.db.savepoint('before_special_invoice')
        try:
            with patch('erpnext.stock.doctype.delivery_note.delivery_note.make_sales_invoice',side_effect=frappe.ValidationError('QA invoice failure')):
                with self.assertRaises(frappe.ValidationError):bl.submit()
        finally:frappe.db.rollback(save_point='before_special_invoice')
        self.assertEqual(frappe.db.count('Delivery Note'),before_dn)
        self.assertEqual(frappe.db.count('Sales Invoice'),before_si)
        self.assertEqual(frappe.db.get_value('Bin',{'item_code':self.item.name,'warehouse':self.warehouse},'actual_qty'),5)
        self.assertEqual(frappe.db.get_value(b.DELIVERY,bl.name,'docstatus'),0)

    def test_native_documents_are_owned_and_mixed_payment_counts_each_share_once(self):
        bl=self.delivery(1)
        with self.assertRaises(frappe.ValidationError):frappe.get_doc('Sales Invoice',bl.sales_invoice).cancel()
        with self.assertRaises(frappe.ValidationError):frappe.get_doc('Delivery Note',bl.delivery_note).cancel()
        b_bl=self.delivery(1,order=self.b_order)
        receipt=self.payment(100,[(bl,50),(b_bl,50)])
        self.assertEqual(receipt.order_type,'Mixte')
        pe=frappe.get_doc('Payment Entry',receipt.payment_entry)
        self.assertEqual(pe.paid_amount,50)
        self.assertEqual(b.payment_share(receipt),50)
        self.assertEqual(b.accounting_amount(receipt),50)
        self.assertEqual(frappe.db.get_value('Sales Invoice',bl.sales_invoice,'outstanding_amount'),50)
        self.assertEqual(b.get_order_summary(self.b_order.name)['received'],50)
        rows=execute(dict(company=self.company,customer=self.customer,currency=self.order.currency,
                          sales_order=self.b_order.name,from_date=nowdate(),to_date=nowdate()))[1]
        self.assertEqual(sum(r.get('credit',0) for r in rows),50)
        with self.assertRaises(frappe.ValidationError):frappe.get_doc('Payment Entry',receipt.payment_entry).cancel()

    def test_mixed_reallocation_replaces_only_the_accounted_share(self):
        bl=self.delivery(1);b_bl=self.delivery(1,order=self.b_order)
        receipt=self.payment(100,[(bl,50),(b_bl,50)])
        original=receipt.payment_entry
        receipt.allocations[0].amount=80;receipt.allocations[1].amount=20;receipt.save()
        self.assertEqual(frappe.db.get_value('Payment Entry',original,'docstatus'),2)
        self.assertNotEqual(receipt.payment_entry,original)
        self.assertEqual(frappe.db.count('Payment Entry',{'custom_ug_special_payment':receipt.name,'docstatus':1}),1)
        self.assertEqual(frappe.db.get_value('Payment Entry',receipt.payment_entry,'paid_amount'),80)
        self.assertEqual(frappe.db.get_value('Sales Invoice',bl.sales_invoice,'outstanding_amount'),20)
        self.assertEqual(b.payment_share(receipt),20)
        receipt.cancel()
        self.assertEqual(frappe.db.get_value('Sales Invoice',bl.sales_invoice,'outstanding_amount'),100)
        self.assertEqual(b.allocated(b_bl.name),0)

    def test_partial_fixed_discount_and_fixed_charge_are_not_duplicated(self):
        tax=frappe.db.get_value('Account',{'company':self.company,'account_type':'Tax','is_group':0},'name')
        if not tax:self.skipTest('No tax account in fixture company')
        order=frappe.copy_doc(self.order);order.docstatus=0;order.amended_from=None;order.custom_technical_study=None
        order.apply_discount_on='Net Total';order.discount_amount=180
        order.append('taxes',dict(charge_type='Actual',account_head=tax,description='Frais fixes',tax_amount=30))
        order.append('taxes',dict(charge_type='On Net Total',account_head=tax,description='TVA',rate=18))
        order.insert();order.submit();frappe.get_doc('Chantier Technical Study',order.custom_technical_study).submit()
        first=self.delivery(1,order=order);second=self.delivery(2,order=order)
        self.assertAlmostEqual(first.net_total+second.net_total,order.net_total)
        self.assertAlmostEqual(first.grand_total+second.grand_total,order.grand_total,places=2)
        self.assertEqual(sum(frappe.get_doc('Sales Invoice',x.sales_invoice).discount_amount for x in [first,second]),180)

    def test_foreign_currency_receipt_uses_invoice_party_currency(self):
        order=frappe.copy_doc(self.order);order.docstatus=0;order.amended_from=None;order.custom_technical_study=None
        order.currency='XOF';order.conversion_rate=.0016
        order.price_list_currency='USD';order.plc_conversion_rate=1
        order.insert();order.submit();frappe.get_doc('Chantier Technical Study',order.custom_technical_study).submit()
        self.order=order
        bl=self.delivery(1)
        receipt=self.payment(bl.grand_total,[(bl,bl.grand_total)])
        invoice=frappe.get_doc('Sales Invoice',bl.sales_invoice)
        self.assertEqual(invoice.outstanding_amount,0)
        pe=frappe.get_doc('Payment Entry',receipt.payment_entry)
        expected=bl.grand_total if pe.paid_from_account_currency=='XOF' else flt(bl.grand_total*order.conversion_rate,2)
        self.assertEqual(pe.paid_amount,expected)

    def test_standard_first_delivery_does_not_repeat_fixed_discount_or_tax(self):
        from erpnext.selling.doctype.sales_order.sales_order import make_delivery_note
        tax=frappe.db.get_value('Account',{'company':self.company,'account_type':'Tax','is_group':0},'name')
        if not tax:self.skipTest('No tax account in fixture company')
        order=frappe.copy_doc(self.order);order.docstatus=0;order.amended_from=None;order.custom_technical_study=None
        order.apply_discount_on='Net Total';order.discount_amount=180
        order.append('taxes',dict(charge_type='Actual',account_head=tax,description='Frais fixes standard',tax_amount=30))
        order.append('taxes',dict(charge_type='On Net Total',account_head=tax,description='TVA',rate=18))
        order.insert();order.submit();frappe.get_doc('Chantier Technical Study',order.custom_technical_study).submit()
        standard=make_delivery_note(order.name)
        standard.items[0].qty=2
        standard.calculate_taxes_and_totals()
        standard.insert();standard.submit()
        self.assertEqual(standard.discount_amount,180)
        self.assertEqual(standard.taxes[0].tax_amount,30)
        special=self.delivery(1,order=order)
        note=frappe.get_doc('Delivery Note',special.delivery_note)
        invoice=frappe.get_doc('Sales Invoice',special.sales_invoice)
        self.assertEqual(note.discount_amount,0)
        self.assertEqual(invoice.discount_amount,0)
        self.assertEqual(note.taxes[0].tax_amount,0)
        self.assertEqual(invoice.taxes[0].tax_amount,0)
        self.assertAlmostEqual(standard.net_total+note.net_total,order.net_total)
        self.assertAlmostEqual(standard.grand_total+note.grand_total,order.grand_total,places=2)

    def test_different_foreign_currency_rates_require_separate_receipts(self):
        deliveries=[]
        for conversion_rate in (.0016,.0016005):
            order=frappe.copy_doc(self.order);order.docstatus=0;order.amended_from=None;order.custom_technical_study=None
            order.currency='XOF';order.conversion_rate=conversion_rate
            order.price_list_currency='USD';order.plc_conversion_rate=1
            order.items[0].rate=100000
            order.insert();order.submit();frappe.get_doc('Chantier Technical Study',order.custom_technical_study).submit()
            deliveries.append(self.delivery(1,order=order))
        self.order=order
        if frappe.get_doc('Sales Invoice',deliveries[0].sales_invoice).party_account_currency=='XOF':
            self.skipTest('Requires a customer account in company currency')
        before=frappe.db.count('Payment Entry')
        with self.assertRaisesRegex(frappe.ValidationError,'taux différents'):
            self.payment(200000,[(bl,100000) for bl in deliveries])
        self.assertEqual(frappe.db.count('Payment Entry'),before)

    def test_mixed_standard_delivery_with_unattributable_fixed_charges_is_rejected(self):
        from erpnext.selling.doctype.sales_order.sales_order import make_delivery_note
        tax=frappe.db.get_value('Account',{'company':self.company,'account_type':'Tax','is_group':0},'name')
        if not tax:self.skipTest('No tax account in fixture company')
        order=frappe.copy_doc(self.order);order.docstatus=0;order.amended_from=None;order.custom_technical_study=None
        order.apply_discount_on='Net Total';order.discount_amount=30
        order.append('taxes',dict(charge_type='Actual',account_head=tax,description='Frais fixes communs',tax_amount=10))
        order.insert();order.submit();frappe.get_doc('Chantier Technical Study',order.custom_technical_study).submit()
        other=self.new_order('A')
        standard=make_delivery_note(order.name)
        standard.items[0].qty=1
        source=other.items[0]
        standard.append('items',dict(item_code=source.item_code,item_name=source.item_name,description=source.description,
            qty=1,rate=source.rate,uom=source.uom,stock_uom=source.stock_uom,conversion_factor=source.conversion_factor,
            warehouse=source.warehouse,against_sales_order=other.name,so_detail=source.name))
        standard.calculate_taxes_and_totals()
        standard.insert();standard.submit()
        before=frappe.db.count('Delivery Note')
        with self.assertRaisesRegex(frappe.ValidationError,'plusieurs commandes'):
            b.make_delivery(order.name)
        self.assertEqual(frappe.db.count('Delivery Note'),before)

    def test_error_after_invoice_rolls_back_native_documents_and_sync_queue(self):
        bl=self.delivery(1,submit=False)
        types=['Delivery Note','Sales Invoice','GL Entry']
        if 'fisc_sync' in frappe.get_installed_apps():types.append('FISC Sync Queue')
        before={dt:frappe.db.count(dt) for dt in types}
        frappe.db.savepoint('qa_after_native_invoice')
        try:
            with patch.object(frappe.db,'commit',side_effect=AssertionError('Intermediate commit forbidden')):
                with patch.object(bl,'db_set',side_effect=RuntimeError('QA after invoice')):
                    with self.assertRaisesRegex(RuntimeError,'QA after invoice'):bl.submit()
        finally:frappe.db.rollback(save_point='qa_after_native_invoice')
        self.assertEqual({dt:frappe.db.count(dt) for dt in types},before)
        self.assertEqual(frappe.db.get_value(b.DELIVERY,bl.name,'docstatus'),0)

    def test_partial_commit_guard_cannot_be_swallowed_or_retried(self):
        from frappe.utils import CallbackManager
        from mat_reco.material_reconfiguration.services.special_a import operation
        callbacks=CallbackManager()
        with patch.object(frappe.db,'before_commit',callbacks):
            with self.assertRaisesRegex(frappe.ValidationError,'validation partielle'):
                with operation(b.DELIVERY,'QA-TRANSACTION'):
                    for _ in range(2):
                        with self.assertRaisesRegex(frappe.ValidationError,'seule transaction'):
                            callbacks.run()
            # The normal framework commit remains allowed after the operation.
            callbacks.run()

    def test_mixed_receipt_prevents_cancelling_its_b_opening(self):
        opening=frappe.get_doc(dict(doctype=b.OPENING,company=self.company,customer=self.customer,
            currency=self.order.currency,sales_order=self.b_order.name,posting_date=nowdate(),
            amount=100,migration_reference=uuid.uuid4().hex,remarks='QA reprise B par commande')).insert()
        opening.submit()
        a_bl=self.delivery(1);b_bl=self.delivery(1,order=self.b_order)
        receipt=self.payment(100,[(a_bl,50),(b_bl,50)])
        # The source order is A, but this payment also moves the B account.
        self.assertEqual(receipt.sales_order,self.order.name)
        with self.assertRaisesRegex(frappe.ValidationError,'mouvements B'):
            opening.cancel()
        receipt.cancel();b_bl.cancel();opening.reload();opening.cancel()
        self.assertEqual(opening.docstatus,2)
        self.assertEqual(frappe.db.get_value('Sales Invoice',a_bl.sales_invoice,'docstatus'),1)

    def test_manufactured_serials_use_native_reservations_and_reverse_once(self):
        from frappe.utils import add_days
        from mat_reco.material_reconfiguration.services import production_reservations as reservations
        context=patch.object(reservations,'COMPANY',self.company)
        context.start();self.addCleanup(context.stop)
        parent=frappe.get_cached_value('Item',self.cut,'custom_parent_item')
        glass=frappe.get_doc(dict(doctype='Item',item_code='QA-A-RES-'+uuid.uuid4().hex[:8],item_name='QA A serial glass',
            item_group=self.item.item_group,stock_uom='PC',is_stock_item=1,is_sales_item=1,has_serial_no=1,
            custom_item_types='DECOUPE',custom_parent_item=parent,custom_requires_dimensions=1,custom_thickness_mm=self.thickness,
            item_defaults=[dict(company=self.company,default_warehouse=self.warehouse)])).insert()
        if glass.meta.has_field('custom_edef_type_article'):glass.db_set('custom_edef_type_article','BIE')
        order=frappe.get_doc(dict(doctype='Sales Order',company=self.company,customer=self.customer,custom_ug_order_type='A',
            branch=self.branch,delivery_date=add_days(nowdate(),7),items=[dict(item_code=glass.name,qty=2,rate=100,
                warehouse=self.warehouse,custom_client_length_mm=1200,custom_client_width_mm=900,
                custom_client_thickness_mm=self.thickness)])).insert()
        order.submit();frappe.get_doc('Chantier Technical Study',order.custom_technical_study).submit()
        serials=['QA-A-SERIAL-'+uuid.uuid4().hex[:12] for _ in range(2)]
        for name in serials:
            frappe.get_doc(dict(doctype='Serial No',serial_no=name,item_code=glass.name,
                custom_dimension_length_mm=1200,custom_dimension_width_mm=900,
                custom_dimension_thickness_mm=self.thickness)).insert()
        entry=frappe.get_doc(dict(doctype='Stock Entry',stock_entry_type='Repack',company=self.company,branch=self.branch,
            custom_sales_order=order.name,items=[dict(item_code=self.item.name,qty=1,s_warehouse=self.warehouse),
                dict(item_code=glass.name,qty=2,t_warehouse=self.warehouse,allow_zero_valuation_rate=1,
                    serial_no='\n'.join(serials),use_serial_batch_fields=1,custom_sales_order_item=order.items[0].name,
                    custom_dimension_length_mm=1200,custom_dimension_width_mm=900,
                    custom_dimension_thickness_mm=self.thickness)])).insert()
        entry.submit()
        self.assertEqual(frappe.db.count('Stock Reservation Entry',{'voucher_no':order.name,'docstatus':1}),2)
        bl=self.delivery(1,order=order)
        chosen=bl.items[0].serial_no.splitlines()
        self.assertEqual(len(chosen),1)
        self.assertIn(chosen[0],serials)
        self.assertEqual(frappe.db.get_value('Serial No',chosen[0],'warehouse'),None)
        self.assertEqual(frappe.db.get_value('Bin',{'item_code':glass.name,'warehouse':self.warehouse},'actual_qty'),1)
        self.assertEqual(sum(flt(r.delivered_qty) for r in frappe.get_all('Stock Reservation Entry',
            filters={'voucher_no':order.name,'docstatus':1},fields=['delivered_qty'])),1)
        bl.cancel()
        self.assertEqual(frappe.db.get_value('Serial No',chosen[0],'warehouse'),self.warehouse)
        self.assertEqual(frappe.db.get_value('Bin',{'item_code':glass.name,'warehouse':self.warehouse},'actual_qty'),2)
        self.assertEqual(sum(flt(r.delivered_qty) for r in frappe.get_all('Stock Reservation Entry',
            filters={'voucher_no':order.name,'docstatus':1},fields=['delivered_qty'])),0)
