"""Transactional recipe for the B-only delivery and cash subledger."""
import unittest
import uuid
from collections import Counter

import frappe
from frappe.utils import nowdate,add_days,flt
from mat_reco.material_reconfiguration.tests.test_order_b_stock import OrderBStockTests
from mat_reco.material_reconfiguration.services import special_b as b
from mat_reco.material_reconfiguration.report.situation_des_comptes_clients_b.situation_des_comptes_clients_b import execute


class SpecialBTests(unittest.TestCase):
    setUp=OrderBStockTests.setUp
    cleanup=OrderBStockTests.cleanup
    new_order=OrderBStockTests.new_order
    remove_files=OrderBStockTests.remove_files

    def delivery(self,qty=None,order=None,submit=True):
        order=order or self.order
        doc=frappe.get_doc(b.make_delivery(order.name))
        if qty is not None:doc.items[0].qty=qty
        doc.accounting_dimensions_json=frappe.as_json({'branch':self.branch})
        doc.insert()
        if submit:doc.submit()
        return doc

    def payment(self,amount,allocations=None,order=True,date=None,submit=True):
        mode=frappe.db.get_value('Mode of Payment',{},'name') or frappe.get_doc(dict(doctype='Mode of Payment',mode_of_payment='QA SPECIAL CASH',type='Cash')).insert().name
        doc=frappe.get_doc(dict(doctype=b.PAYMENT,company=self.order.company,customer=self.order.customer,currency=self.order.currency,
            sales_order=self.order.name if order else None,posting_date=date or nowdate(),mode_of_payment=mode,reference=uuid.uuid4().hex,
            amount=amount,allocations=[dict(bordereau=bl.name,amount=value) for bl,value in (allocations or [])])).insert()
        if submit:doc.submit()
        return doc

    def report(self,**filters):
        return execute(dict(company=self.order.company,customer=self.order.customer,currency=self.order.currency,
            from_date=add_days(nowdate(),-10),to_date=nowdate(),**filters))[1]

    def balance(self,**filters):
        rows=self.report(**filters)
        return next(r['balance'] for r in reversed(rows) if r['description']=='Solde final')

    def test_one_delivery_uses_native_issue_and_no_customer_accounting(self):
        before_invoice=frappe.db.count('Sales Invoice');before_payment=frappe.db.count('Payment Entry')
        bl=self.delivery();entry=frappe.get_doc('Stock Entry',bl.stock_entry)
        self.assertEqual(entry.docstatus,1);self.assertEqual(entry.custom_ug_special_delivery,bl.name)
        self.assertEqual(entry.items[0].qty,3);self.assertEqual(entry.items[0].basic_rate,12)
        self.assertEqual(b.get_order_summary(self.order.name)['items'][0]['remaining_qty'],0)
        self.payment(300,[(bl,300)])
        self.assertEqual(self.balance(),0)
        self.assertEqual(frappe.db.count('Sales Invoice'),before_invoice);self.assertEqual(frappe.db.count('Payment Entry'),before_payment)
        self.assertFalse(frappe.db.exists('GL Entry',dict(voucher_type='Stock Entry',voucher_no=entry.name,party_type='Customer')))
        import erpnext
        if erpnext.is_perpetual_inventory_enabled(self.company):
            ledger=frappe.get_all('GL Entry',filters=dict(voucher_type='Stock Entry',voucher_no=entry.name,is_cancelled=0),fields=['debit','credit'])
            self.assertTrue(ledger)
            self.assertAlmostEqual(sum(r.debit for r in ledger),36)
            self.assertAlmostEqual(sum(r.credit for r in ledger),36)

    def test_partial_deliveries_and_over_delivery(self):
        first=self.delivery(1);second=self.delivery(2)
        self.assertNotEqual(first.stock_entry,second.stock_entry)
        self.assertEqual(first.grand_total+second.grand_total,self.order.grand_total)
        bad=frappe.get_doc(first.as_dict());bad.name=None;bad.docstatus=0;bad.stock_entry=None
        with self.assertRaises(frappe.ValidationError):bad.insert()
        self.assertEqual(b.stock.issued_quantities(self.order)[self.order.items[0].name],3)

    def test_multiple_receipts_one_bl_and_one_receipt_multiple_bls_count_once(self):
        first=self.delivery(1);second=self.delivery(2)
        p=self.payment(150,[(first,100),(second,50)],order=False)
        self.assertEqual(b.allocated(first.name),100);self.assertEqual(b.allocated(second.name),50)
        rows=self.report();credits=[r for r in rows if r.get('reference_name')==p.name]
        self.assertEqual(len(credits),1);self.assertEqual(credits[0]['credit'],150)
        self.assertEqual(self.balance(),150)
        self.payment(100,[(second,100)]);self.payment(50,[(second,50)])
        self.assertEqual(self.balance(),0);self.assertEqual(b.allocated(second.name),200)
        with self.assertRaises(frappe.ValidationError):self.payment(1,[(second,1)])

    def test_advance_can_be_allocated_after_submit_without_second_credit(self):
        p=self.payment(120)
        self.assertEqual(self.balance(),-120)
        bl=self.delivery();p.append('allocations',dict(bordereau=bl.name,amount=120));p.save();p.reload()
        self.assertEqual(p.unallocated_amount,0);self.assertEqual(self.balance(),180)
        self.assertEqual(len([r for r in self.report() if r.get('reference_name')==p.name]),1)
        p.amount=121
        with self.assertRaises(frappe.ValidationError):p.save()

    def test_cancel_receipt_releases_allocation_and_bl_reverses_stock(self):
        bl=self.delivery();p=self.payment(100,[(bl,100)])
        with self.assertRaises(frappe.ValidationError):bl.cancel()
        entry=frappe.get_doc('Stock Entry',bl.stock_entry)
        with self.assertRaises(frappe.ValidationError):entry.cancel()
        p.cancel();self.assertEqual(self.balance(),300);self.assertEqual(b.allocated(bl.name),0)
        bl.reload();bl.cancel();self.assertEqual(frappe.db.get_value('Stock Entry',entry.name,'docstatus'),2)
        self.assertEqual(self.balance(),0)
        self.assertEqual(frappe.db.get_value('Bin',{'item_code':self.item.name,'warehouse':self.warehouse},'actual_qty'),5)

    def test_same_client_multiple_orders_and_a_order_are_excluded_from_b_ledger(self):
        other=self.new_order();a_order=self.new_order('A')
        with self.assertRaises(frappe.ValidationError):b.make_delivery(a_order.name)
        with self.assertRaises(frappe.ValidationError):b.make_payment(a_order.name)
        first=self.delivery(1);second=self.delivery(1,order=other)
        p=self.payment(150,[(first,75),(second,75)],order=False)
        self.assertEqual(self.balance(),50)
        self.assertEqual(b.get_order_summary(self.order.name)['received'],75)
        self.assertEqual(b.get_order_summary(other.name)['received'],75)
        self.assertEqual(self.balance(sales_order=self.order.name),25)
        self.assertEqual(len([r for r in self.report() if r.get('reference_name')==p.name]),1)
        self.assertFalse(any(r.get('sales_order')==a_order.name for r in self.report()))

    def test_opening_debit_credit_no_movement_period_and_duplicate_import(self):
        for amount in (100,-100):
            opening=frappe.get_doc(dict(doctype=b.OPENING,company=self.order.company,customer=self.order.customer,currency=self.order.currency,
                posting_date=add_days(nowdate(),-5),amount=amount,migration_reference=uuid.uuid4().hex,remarks='Reprise du système historique')).insert();opening.submit()
            self.assertEqual(self.balance(),amount)
            duplicate=frappe.copy_doc(opening);duplicate.name=None;duplicate.docstatus=0;duplicate.migration_reference=uuid.uuid4().hex
            with self.assertRaises(frappe.ValidationError):duplicate.insert()
            opening.cancel()
        opening=frappe.get_doc(dict(doctype=b.OPENING,company=self.order.company,customer=self.order.customer,currency=self.order.currency,
            posting_date=add_days(nowdate(),-5),amount=100,migration_reference=uuid.uuid4().hex,remarks='Historique antérieur uniquement')).insert();opening.submit()
        bl=self.delivery();self.payment(50,[(bl,50)])
        self.assertEqual(self.balance(),350)
        rows=execute(dict(company=self.order.company,customer=self.order.customer,currency=self.order.currency,
            from_date=add_days(nowdate(),1),to_date=add_days(nowdate(),10)))[1]
        self.assertEqual(len(rows),2);self.assertEqual(rows[0]['balance'],350);self.assertEqual(rows[-1]['balance'],350)
        with self.assertRaises(frappe.ValidationError):opening.cancel()
        with self.assertRaises(frappe.ValidationError):self.payment(10,date=add_days(nowdate(),-6))

    def test_partial_multiple_articles_and_service_only_delivery(self):
        service=frappe.get_doc(dict(doctype='Item',item_code='QA-SPECIAL-SERVICE-'+uuid.uuid4().hex[:8],item_name='QA SERVICE',
            item_group=self.item.item_group,stock_uom='PC',is_stock_item=0,is_sales_item=1,custom_item_types='SERVICE')).insert()
        order=frappe.get_doc(dict(doctype='Sales Order',company=self.order.company,customer=self.order.customer,custom_ug_order_type='B',branch=self.branch,
            delivery_date=add_days(nowdate(),7),items=[dict(item_code=self.item.name,qty=3,rate=100,warehouse=self.warehouse),dict(item_code=service.name,qty=2,rate=50)])).insert()
        order.submit();frappe.get_doc('Chantier Technical Study',order.custom_technical_study).submit()
        doc=frappe.get_doc(b.make_delivery(order.name));doc.items[0].qty=1;doc.items[1].qty=1;doc.accounting_dimensions_json=frappe.as_json({'branch':self.branch});doc.insert();doc.submit()
        self.assertEqual(doc.grand_total,150);self.assertEqual(len(frappe.get_doc('Stock Entry',doc.stock_entry).items),1)
        last=self.delivery(order=order);self.assertEqual(last.grand_total,250)
        self.assertEqual([r['remaining_qty'] for r in b.get_order_summary(order.name)['items']],[0,0])

    def test_zero_cost_native_stock_and_serialized_item(self):
        item=frappe.get_doc(dict(doctype='Item',item_code='QA-SPECIAL-SN-'+uuid.uuid4().hex[:8],item_name='QA Série',
            item_group=self.item.item_group,stock_uom='PC',is_stock_item=1,is_sales_item=1,has_serial_no=1,custom_item_types='ACCESSOIRE')).insert()
        serial='QA-SP-'+uuid.uuid4().hex[:12]
        receipt=frappe.get_doc(dict(doctype='Stock Entry',stock_entry_type='Material Receipt',company=self.order.company,branch=self.branch,
            items=[dict(item_code=item.name,qty=1,t_warehouse=self.warehouse,basic_rate=0,allow_zero_valuation_rate=1,
                        serial_no=serial,use_serial_batch_fields=1)])).insert();receipt.submit()
        order=frappe.get_doc(dict(doctype='Sales Order',company=self.order.company,customer=self.order.customer,custom_ug_order_type='B',branch=self.branch,
            delivery_date=add_days(nowdate(),7),items=[dict(item_code=item.name,qty=1,rate=50,warehouse=self.warehouse)])).insert();order.submit()
        frappe.get_doc('Chantier Technical Study',order.custom_technical_study).submit()
        doc=frappe.get_doc(b.make_delivery(order.name));doc.items[0].serial_no=serial;doc.accounting_dimensions_json=frappe.as_json({'branch':self.branch});doc.insert();doc.submit()
        self.assertEqual(frappe.get_doc('Stock Entry',doc.stock_entry).items[0].basic_rate,0)
        self.assertFalse(frappe.db.get_value('Serial No',serial,'warehouse'))
        doc.cancel();self.assertEqual(frappe.db.get_value('Serial No',serial,'warehouse'),self.warehouse)

    def test_legacy_issue_adoption_does_not_issue_twice(self):
        entry=b.stock.create_issue(self.order.name,[dict(sales_order_item=self.order.items[0].name,qty=1,warehouse=self.warehouse,serials=[])],uuid.uuid4().hex,{'branch':self.branch})
        count=frappe.db.count('Stock Entry')
        name=b.make_from_issue(entry);doc=frappe.get_doc(b.DELIVERY,name);doc.submit()
        self.assertEqual(frappe.db.count('Stock Entry'),count)
        self.assertEqual(doc.stock_entry,entry);self.assertEqual(b.delivered(self.order)[self.order.items[0].name],1)
        with self.assertRaises(frappe.ValidationError):b.make_from_issue(entry)

    def test_fractional_partial_deliveries_exclude_order_taxes(self):
        tax=frappe.db.get_value('Account',{'company':self.company,'account_type':'Tax','is_group':0},'name')
        order=frappe.get_doc(dict(doctype='Sales Order',company=self.order.company,customer=self.order.customer,custom_ug_order_type='B',branch=self.branch,
            delivery_date=add_days(nowdate(),7),items=[dict(item_code=self.item.name,qty=3,rate=.333333,warehouse=self.warehouse)],
            taxes=[dict(charge_type='On Net Total',account_head=tax,description='TVA 18',rate=18)] if tax else [])).insert()
        order.submit();frappe.get_doc('Chantier Technical Study',order.custom_technical_study).submit()
        deliveries=[self.delivery(1,order=order) for _ in range(3)]
        self.assertAlmostEqual(sum(d.net_total for d in deliveries),order.net_total)
        self.assertAlmostEqual(sum(d.grand_total for d in deliveries),order.net_total)
        self.assertTrue(all(d.tax_amount == 0 for d in deliveries))
        self.assertTrue(all(d.grand_total == d.net_total for d in deliveries))
        for delivery in deliveries:
            self.payment(delivery.grand_total, [(delivery, delivery.grand_total)], order=False)
        rows=execute(dict(company=order.company,customer=order.customer,currency=order.currency,
            sales_order=order.name,from_date=nowdate(),to_date=nowdate()))[1]
        self.assertEqual(rows[-1]['balance'],0)
        self.assertAlmostEqual(sum(r.get('debit',0) for r in rows),order.net_total)

    def test_access_foreign_currency_and_duplicate_receipt_are_rejected(self):
        first=self.delivery(1)
        p=self.payment(10,[(first,10)])
        duplicate=frappe.copy_doc(p);duplicate.docstatus=0
        with self.assertRaises(frappe.ValidationError):duplicate.insert()
        wrong=frappe.copy_doc(p);wrong.docstatus=0;wrong.reference=uuid.uuid4().hex;wrong.currency='EUR' if p.currency!='EUR' else 'USD'
        with self.assertRaises(frappe.ValidationError):wrong.insert()
        user=frappe.session.user
        try:
            frappe.set_user('Guest')
            with self.assertRaises(frappe.PermissionError):b.get_order_summary(self.order.name)
            with self.assertRaises(frappe.PermissionError):execute(dict(from_date=nowdate(),to_date=nowdate()))
        finally:frappe.set_user(user)

    def test_cfa_delivery_uses_unrounded_basis_and_integer_final_amount(self):
        tax=frappe.db.get_value('Account',{'company':self.company,'account_type':'Tax','is_group':0},'name')
        order=frappe.get_doc(dict(doctype='Sales Order',company=self.order.company,customer=self.order.customer,custom_ug_order_type='B',branch=self.branch,
            currency='XOF',conversion_rate=.0016,price_list_currency='USD',plc_conversion_rate=1,
            delivery_date=add_days(nowdate(),7),items=[dict(item_code=self.item.name,qty=1,rate=.45,warehouse=self.warehouse)],
            taxes=[dict(charge_type='On Net Total',account_head=tax,description='TVA 18',rate=18)] if tax else [])).insert()
        order.submit();frappe.get_doc('Chantier Technical Study',order.custom_technical_study).submit()
        bl=self.delivery(order=order)
        self.assertEqual(bl.grand_total,b.money(order.net_total,'XOF'))
        self.assertEqual(bl.grand_total,int(bl.grand_total))

    def test_service_only_bl_and_native_excel_pdf_exports(self):
        item=frappe.get_doc(dict(doctype='Item',item_code='QA-SPECIAL-NONSTOCK-'+uuid.uuid4().hex[:8],item_name='QA Prestation',
            item_group=self.item.item_group,stock_uom='PC',is_stock_item=0,is_sales_item=1,custom_item_types='SERVICE')).insert()
        order=frappe.get_doc(dict(doctype='Sales Order',company=self.order.company,customer=self.order.customer,custom_ug_order_type='B',branch=self.branch,
            delivery_date=add_days(nowdate(),7),items=[dict(item_code=item.name,qty=1,rate=50)])).insert();order.submit()
        before=frappe.db.count('Stock Entry');bl=self.delivery(order=order)
        self.assertFalse(bl.stock_entry);self.assertEqual(frappe.db.count('Stock Entry'),before)
        from mat_reco.printing import render_mat_reco_a4
        html=render_mat_reco_a4(bl)
        self.assertIn(bl.name,html);self.assertIn('QA Prestation',html)
        self.assertIn('50',html)
        from frappe.desk.query_report import _export_query
        params=frappe._dict(report_name='Situation des comptes clients B',file_format_type='Excel',filters=frappe.as_json(dict(
            company=self.company,customer=order.customer,from_date=add_days(nowdate(),-1),to_date=nowdate())),custom_columns='[]',visible_idx=[])
        name,extension,content=_export_query(params,{},populate_response=False)
        self.assertEqual(extension,'xlsx');self.assertTrue(content.startswith(b'PK'))
        from frappe.utils.pdf import get_pdf
        from pypdf import PdfReader
        from io import BytesIO
        pdf=get_pdf('<html><body>'+html+'</body></html>')
        self.assertGreaterEqual(len(PdfReader(BytesIO(pdf)).pages),1)
