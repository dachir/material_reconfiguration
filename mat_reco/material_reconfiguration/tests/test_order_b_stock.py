"""Real B stock exits, customer-entry boundaries and traceable commercial exchange."""
import csv
import io
import json
import unittest
import uuid
import zipfile
from unittest.mock import patch

import frappe
from frappe.utils import add_days,nowdate,flt
from mat_reco.material_reconfiguration.tests import test_independent_chantier as fixtures
from mat_reco.material_reconfiguration.services import order_b_stock as stock
from mat_reco.material_reconfiguration.services import order_b_export as exchange
from mat_reco.material_reconfiguration.services.order_b import validate_customer_entries


class OrderBStockTests(unittest.TestCase):
    cleanup=fixtures.IndependentChantierTests.cleanup

    def setUp(self):
        fixtures.IndependentChantierTests.setUp(self)
        self.warehouse=frappe.db.get_value('Warehouse',{'company':self.company,'is_group':0,'disabled':0},'name')
        self.branch=frappe.db.get_value('Branch',{},'name') or frappe.get_doc(dict(doctype='Branch',branch='QA B Stock')).insert().name
        self.item=frappe.get_doc(dict(doctype='Item',item_code='QA-B-EXIT-'+uuid.uuid4().hex[:8],item_name='QA Accessoire sortie B',
            item_group=frappe.db.get_value('Item Group',{'is_group':0},'name'),stock_uom='PC',is_stock_item=1,is_sales_item=1,
            custom_item_types='ACCESSOIRE')).insert()
        receipt=frappe.get_doc(dict(doctype='Stock Entry',stock_entry_type='Material Receipt',company=self.company,branch=self.branch,
            items=[dict(item_code=self.item.name,qty=5,t_warehouse=self.warehouse,basic_rate=12,set_basic_rate_manually=1,allow_zero_valuation_rate=0)])).insert()
        receipt.submit()
        self.order=self.new_order()
        self.files=[];self.addCleanup(self.remove_files)

    def remove_files(self):
        from pathlib import Path
        for name in self.files:
            path=Path(name)
            if path.exists():path.unlink()

    def new_order(self,kind='B'):
        order=frappe.get_doc(dict(doctype='Sales Order',company=self.company,customer=self.customer,custom_ug_order_type=kind,branch=self.branch,
            delivery_date=add_days(nowdate(),7),items=[dict(item_code=self.item.name,qty=3,rate=100,warehouse=self.warehouse,
            delivery_date=add_days(nowdate(),7))])).insert()
        order.submit()
        if order.custom_technical_study:
            frappe.get_doc('Chantier Technical Study',order.custom_technical_study).submit()
        return order

    def selection(self,qty=1):
        return [dict(sales_order_item=self.order.items[0].name,qty=qty,warehouse=self.warehouse,serials=[])]

    def issue(self,qty=1,key=None):
        return frappe.get_doc('Stock Entry',stock.create_issue(self.order.name,self.selection(qty),key or uuid.uuid4().hex))

    def test_partial_exit_native_valuation_customer_ledger_absent_and_retry(self):
        key=uuid.uuid4().hex;entry=self.issue(1,key)
        self.assertEqual(entry.docstatus,1);self.assertEqual(entry.purpose,'Material Issue')
        self.assertEqual(stock.issued_quantities(self.order)[self.order.items[0].name],1)
        self.assertFalse(stock.is_complete(self.order))
        self.assertAlmostEqual(frappe.db.get_value('Bin',{'item_code':self.item.name,'warehouse':self.warehouse},'actual_qty'),4)
        self.assertAlmostEqual(flt(entry.items[0].basic_rate),12)
        self.assertEqual(stock.create_issue(self.order.name,self.selection(1),key),entry.name)
        self.assertFalse(frappe.db.exists('GL Entry',{'voucher_type':'Stock Entry','voucher_no':entry.name,'party_type':'Customer'}))
        with self.assertRaisesRegex(frappe.ValidationError,'solde'):self.issue(3)
        self.issue(2);self.assertTrue(stock.is_complete(self.order))

    def test_cancel_exit_restores_stock_and_order_balance(self):
        entry=self.issue(3);self.assertTrue(stock.is_complete(self.order))
        entry.cancel();self.assertFalse(stock.is_complete(self.order));self.assertEqual(stock.issued_quantities(self.order),{})
        self.assertAlmostEqual(frappe.db.get_value('Bin',{'item_code':self.item.name,'warehouse':self.warehouse},'actual_qty'),5)

    def test_finance_block_only_references_to_b_and_never_stock_entries(self):
        a=self.new_order('A')
        for dt,table,doctype_field in [('Payment Entry','references','reference_doctype'),('Journal Entry','accounts','reference_type')]:
            for source,blocked in [(self.order,True),(a,False)]:
                with self.subTest(doctype=dt,kind=source.custom_ug_order_type):
                    doc=frappe.get_doc(dict(doctype=dt,**{table:[{doctype_field:'Sales Order','reference_name':source.name}]}))
                    if blocked:
                        with self.assertRaisesRegex(frappe.ValidationError,'Sage 100'):validate_customer_entries(doc)
                    else:validate_customer_entries(doc)
        self.issue(1)

    def test_export_requires_complete_exits_then_private_file_and_confirmation(self):
        with self.assertRaisesRegex(frappe.ValidationError,'sorties physiques'):exchange.export_order(self.order.name)
        self.issue(3)
        exported=exchange.export_order(self.order.name)
        file=frappe.get_doc('File',exported['file']);self.files.append(file.get_full_path())
        self.assertEqual(file.is_private,1);self.assertEqual(file.attached_to_name,self.order.name)
        content=file.get_content()
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            self.assertEqual(set(archive.namelist()),{'commandes.csv','lignes.csv','taxes.csv','sorties.csv','README.txt'})
            headers=list(csv.DictReader(io.StringIO(archive.read('commandes.csv').decode('utf-8-sig')),delimiter=';'))
            self.assertEqual(headers[0]['Commande'],self.order.name)
            self.assertIn('mapping',archive.read('README.txt').decode())
        self.assertEqual(exchange.export_order(self.order.name),exported)
        exchange.confirm_import(self.order.name,'SAGE-QA-123');self.order.reload()
        self.assertEqual(self.order.custom_ug_b_sage_reference,'SAGE-QA-123');self.assertEqual(self.order.status,'Closed')
        self.assertEqual(exchange.confirm_import(self.order.name,'SAGE-QA-123'),self.order.name)
        self.assertFalse(frappe.db.exists('Sales Invoice Item',{'sales_order':self.order.name}))

    def test_native_api_cannot_forge_export_confirmation(self):
        self.order.custom_ug_b_sage_reference='FORGED'
        with self.assertRaisesRegex(frappe.ValidationError,'actions Export Sage'):self.order.save()

    def test_print_bon_uses_sales_order_lines_without_creating_delivery_or_stock(self):
        template=frappe.get_doc('Print Format','Bon de livraison B')
        before_stock=frappe.db.count('Stock Entry')
        before_delivery=frappe.db.count('Delivery Note')
        html=frappe.render_template(template.html,dict(doc=self.order))
        self.assertIn('BORDEREAU DE LIVRAISON',html)
        self.assertIn(self.order.name,html);self.assertIn(self.item.item_name,html)
        self.assertIn('Réception signature',html);self.assertIn('Direction signature',html)
        self.assertEqual(frappe.db.count('Stock Entry'),before_stock)
        self.assertEqual(frappe.db.count('Delivery Note'),before_delivery)
        self.assertFalse(stock.issued_quantities(self.order))

    def test_preprinted_delivery_fits_fourteen_lines_and_keeps_last_page_signatures(self):
        from bs4 import BeautifulSoup

        doc=frappe.copy_doc(self.order)
        row=doc.items[0].as_dict()
        for format_name in ('Bon de livraison B','Bon Livraison v2'):
            template=frappe.get_doc('Print Format',format_name)
            for count,long_name in ((14,False),(33,False),(14,True)):
                items=[]
                for index in range(count):
                    item=dict(row,idx=index+1)
                    item['item_name']=('VITRE CLAIRE AVEC UNE DESIGNATION TRES LONGUE ' * 6) if long_name else 'VITRE CLAIRE'
                    items.append(item)
                doc.set('items',items)
                soup=BeautifulSoup(frappe.render_template(template.html,dict(doc=doc)),'html.parser')
                pages=soup.select('.ug-delivery-sheet')
                self.assertEqual(len(soup.select('.ug-delivery-items tr')),count)
                self.assertEqual(len(soup.select('.ug-signature')),2)
                self.assertEqual(len(pages[-1].select('.ug-signature')),2)
                self.assertTrue(all(not page.select('.ug-signature') for page in pages[:-1]))
                if count==14 and not long_name:
                    self.assertEqual(len(pages),1)
                else:
                    self.assertGreater(len(pages),1)

    def test_delivery_print_groups_supplements_and_keeps_parent_on_same_page(self):
        from bs4 import BeautifulSoup

        doc=frappe.copy_doc(self.order)
        template=frappe.get_doc('Print Format','Bon Livraison v2')
        row=doc.items[0].as_dict()
        fillers=[dict(row,name='filler-'+str(i),item_name='ARTICLE',custom_parent_row=None) for i in range(15)]
        parent=dict(row,name='parent',item_name='VITRE',custom_parent_row=None)
        service=dict(row,name='service',item_name='RABOTAGE',custom_parent_row='parent',custom_is_service_row=1)
        accessory=dict(row,name='accessory',item_name='FIXATION',custom_parent_row='parent',custom_is_accessory_row=1)
        doc.set('items',fillers+[service,parent,accessory])
        soup=BeautifulSoup(frappe.render_template(template.html,dict(doc=doc)),'html.parser')
        pages=soup.select('.ug-delivery-sheet')
        self.assertEqual(len(pages),2)
        self.assertEqual([r['data-row'] for r in pages[-1].select('tr')],['parent','service','accessory'])
        self.assertEqual([r['data-parent'] for r in pages[-1].select('tr.ug-child')],['parent','parent'])
        self.assertEqual(len(soup.select('tr')),18)
        self.assertTrue(all('↳' in r.get_text() for r in pages[-1].select('tr.ug-child')))

    def test_delivery_print_resolves_parent_using_sales_order_rows(self):
        from bs4 import BeautifulSoup

        row=self.order.items[0].as_dict()
        doc=frappe.get_doc(dict(doctype='Delivery Note',customer_name='QA',posting_date=nowdate(),items=[
            dict(row,name='dn-child',so_detail='so-child',against_sales_order=self.order.name,
                 custom_parent_row=None,item_name='RABOTAGE',custom_is_service_row=1),
            dict(row,name='dn-parent',so_detail='so-parent',against_sales_order=self.order.name,
                 custom_parent_row=None,item_name='VITRE'),
        ]))
        source=[frappe._dict(name='so-child',parent=self.order.name,custom_parent_row='so-parent'),
                frappe._dict(name='so-parent',parent=self.order.name,custom_parent_row=None)]
        template=frappe.get_doc('Print Format','Bon Livraison v2')
        from frappe.utils.jinja import get_jenv
        with patch.dict(get_jenv().globals['frappe'],{'get_all':lambda *args,**kwargs:source}):
            soup=BeautifulSoup(frappe.render_template(template.html,dict(doc=doc)),'html.parser')
        rows=soup.select('.ug-delivery-items tr')
        self.assertEqual([r['data-row'] for r in rows],['dn-parent','dn-child'])
        self.assertEqual(rows[1]['data-parent'],'dn-parent')

    def test_delivery_service_description_shows_per_piece_calculation_without_result(self):
        from bs4 import BeautifulSoup

        doc=frappe.copy_doc(self.order)
        row=doc.items[0].as_dict()
        doc.set('items',[
            dict(row,name='parent',item_name='VITRE',qty=12,custom_parent_row=None),
            dict(row,name='service',item_name='RABOTAGE',qty=162.84,custom_parent_row='parent',custom_is_service_row=1),
            dict(row,name='accessory',item_name='FIXATION',qty=24,custom_parent_row='parent',custom_is_service_row=0,custom_is_accessory_row=1),
        ])
        template=frappe.get_doc('Print Format','Bon Livraison v2')
        soup=BeautifulSoup(frappe.render_template(template.html,dict(doc=doc)),'html.parser')
        service=soup.select_one('tr[data-row="service"]')
        self.assertEqual(service.select_one('.ug-service-calculation').get_text(strip=True),'— 13,57 × 12')
        self.assertNotIn('162.84',service.select_one('.ug-designation').get_text())
        self.assertEqual(service.select_one('.ug-qty').get_text(strip=True),'162.84')
        self.assertFalse(soup.select_one('tr[data-row="accessory"] .ug-service-calculation'))

    def test_foreign_line_is_rejected(self):
        other=self.new_order()
        selection=self.selection();selection[0]['sales_order_item']=other.items[0].name
        with self.assertRaisesRegex(frappe.ValidationError,'inconnue'):
            stock.create_issue(self.order.name,selection,uuid.uuid4().hex)

    def test_manufactured_serials_must_belong_to_the_selected_order_line(self):
        from mat_reco.material_reconfiguration.services import technical_study_service as technical
        self.doc.submit()
        quote=frappe.get_doc('Quotation',technical.generate_quotation(self.doc.name,request_key=uuid.uuid4().hex));quote.submit()
        order=frappe.get_doc('Sales Order',technical.confirm_order(quote.name,'QA séries B',add_days(nowdate(),7),uuid.uuid4().hex,order_type='B'))
        frappe.get_doc('Chantier Technical Study',order.custom_technical_study).submit()
        line=order.items[0];serials=['QA-B-PROD-'+uuid.uuid4().hex[:10] for _ in range(2)]
        repack=frappe.get_doc(dict(doctype='Stock Entry',stock_entry_type='Repack',company=self.company,branch=self.branch,
            items=[dict(item_code=self.item.name,s_warehouse=self.warehouse,qty=1),
                dict(item_code=line.item_code,t_warehouse=self.warehouse,qty=2,serial_no='\n'.join(serials),use_serial_batch_fields=1,
                custom_sales_order_item=line.name,custom_dimension_length_mm=1200,custom_dimension_width_mm=900,
                custom_dimension_thickness_mm=self.thickness)])).insert()
        repack.submit()
        candidates=stock.get_issue_data(order.name)
        actual=next(r for r in candidates['rows'] if r['sales_order_item']==line.name)
        self.assertEqual({r.name for r in actual['serials']},set(serials))
        selected=[dict(sales_order_item=line.name,qty=1,warehouse=self.warehouse,serials=serials[:1])]
        entry=frappe.get_doc('Stock Entry',stock.create_issue(order.name,selected,uuid.uuid4().hex,accounting_dimensions={'branch':self.branch}))
        self.assertEqual(entry.docstatus,1);self.assertFalse(frappe.db.get_value('Serial No',serials[0],'warehouse'))
        bad=[dict(sales_order_item=order.items[1].name,qty=1,warehouse=self.warehouse,serials=serials[1:])]
        with self.assertRaisesRegex(frappe.ValidationError,'produite pour cette ligne'):
            stock.create_issue(order.name,bad,uuid.uuid4().hex,accounting_dimensions={'branch':self.branch})

    def test_zero_valuation_stock_is_issued_without_customer_posting(self):
        item=frappe.copy_doc(self.item);item.item_code='QA-B-ZERO-'+uuid.uuid4().hex[:8];item.insert()
        receipt=frappe.get_doc(dict(doctype='Stock Entry',stock_entry_type='Material Receipt',company=self.company,branch=self.branch,
            items=[dict(item_code=item.name,t_warehouse=self.warehouse,qty=2,allow_zero_valuation_rate=1)])).insert();receipt.submit()
        order=frappe.get_doc(dict(doctype='Sales Order',company=self.company,customer=self.customer,custom_ug_order_type='B',branch=self.branch,
            delivery_date=add_days(nowdate(),7),items=[dict(item_code=item.name,qty=2,rate=100,warehouse=self.warehouse,delivery_date=add_days(nowdate(),7))])).insert()
        order.submit()
        if order.custom_technical_study:
            frappe.get_doc('Chantier Technical Study',order.custom_technical_study).submit()
        name=stock.create_issue(order.name,[dict(sales_order_item=order.items[0].name,qty=2,warehouse=self.warehouse,serials=[])],uuid.uuid4().hex)
        entry=frappe.get_doc('Stock Entry',name)
        self.assertEqual(flt(entry.items[0].basic_rate),0);self.assertTrue(stock.is_complete(order))
        self.assertEqual(flt(frappe.db.get_value('Bin',{'item_code':item.name,'warehouse':self.warehouse},'actual_qty')),0)
        self.assertFalse(frappe.db.exists('GL Entry',{'voucher_type':'Stock Entry','voucher_no':name,'party_type':'Customer'}))
