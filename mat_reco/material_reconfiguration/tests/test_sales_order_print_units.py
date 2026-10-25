"""Keep millimetre geometry and converted commercial service quantities distinct."""
import unittest
import uuid

import frappe
from bs4 import BeautifulSoup


class SalesOrderPrintUnitsTests(unittest.TestCase):
    def setUp(self):
        self.user=frappe.session.user
        frappe.set_user('Administrator')
        frappe.db.savepoint('qa_print_geometry')
        self.addCleanup(self.cleanup)
        self.template=frappe.get_doc('Print Format','Sales Order v2').html

    def cleanup(self):
        frappe.db.rollback(save_point='qa_print_geometry')
        frappe.set_user(self.user)

    def item(self,basis):
        code='QA-PRINT-'+uuid.uuid4().hex[:10]
        return frappe.get_doc(dict(doctype='Item',item_code=code,item_name='RABOTAGE' if basis=='PERIMETRE' else 'SABLAGE',
            item_group=frappe.db.get_value('Item Group',{'is_group':0},'name'),stock_uom='PC',
            is_stock_item=0,is_sales_item=1,custom_item_types='SERVICE',custom_service_calc_basis=basis)).insert()

    def render(self,items):
        doc=frappe.get_doc(dict(doctype='Sales Order',name='QA-PRINT',customer='QA',customer_name='QA',transaction_date='2026-10-22',items=items))
        return BeautifulSoup(frappe.render_template(self.template,dict(doc=doc)),'html.parser')

    def test_area_and_already_converted_services_do_not_convert_twice(self):
        perimeter=self.item('PERIMETRE')
        surface=self.item('SURFACE')
        soup=self.render([
            dict(name='parent',item_code='QA-GLASS',item_name='VITRE',qty=3,uom='PC',custom_client_length_mm=1200,custom_client_width_mm=800),
            dict(name='edge',item_code=perimeter.name,item_name='RABOTAGE',qty=12.3456,uom='Square Meter',custom_parent_row='parent',custom_is_service_row=1),
            dict(name='area',item_code=surface.name,item_name='SABLAGE',qty=2.88,uom='Meter',custom_parent_row='parent',custom_is_service_row=1),
        ])
        row=soup.select_one('tr[data-row="parent"]')
        self.assertEqual(row.find_all('td')[4].get_text(strip=True),'0.96')
        self.assertEqual([x.get_text(' ',strip=True) for x in row.select('.operation-value')],['12.3456 m','2.88 m²'])
        self.assertIn('2.88',soup.select_one('tfoot').get_text(' ',strip=True))

    def test_manual_units_and_m2_alias_are_preserved(self):
        manual=self.item('MANUEL')
        soup=self.render([
            dict(name='mm',item_code=manual.name,item_name='SERVICE',qty=750,uom='Millimeter',custom_is_service_row=1),
            dict(name='m2',item_code=manual.name,item_name='SERVICE',qty=1.25,uom='M2',custom_is_service_row=1),
        ])
        self.assertIn('750 mm',soup.select_one('tr[data-row="mm"]').get_text(' ',strip=True))
        self.assertIn('1.25 m²',soup.select_one('tr[data-row="m2"]').get_text(' ',strip=True))
