"""The quotation summary must include line discounts and the additional discount."""
import unittest

import frappe
from bs4 import BeautifulSoup


class DevisPrintDiscountTests(unittest.TestCase):
    def render(self,items,discount=0):
        doc=frappe.get_doc(dict(doctype='Quotation',name='QA-REMISES',currency='XOF',party_name='QA',
            transaction_date='2026-10-23',items=items,taxes=[],discount_amount=discount,total=235,
            net_total=235-discount,grand_total=235-discount,disable_rounded_total=1))
        html=frappe.render_template(frappe.get_doc('Print Format','Devis v2').html,dict(doc=doc))
        return BeautifulSoup(html,'html.parser')

    def test_total_includes_quantity_weighted_parent_and_associated_service_discounts(self):
        soup=self.render([
            dict(name='parent',item_code='VITRE',description='VITRE',qty=3,rate=75,amount=225,discount_amount=25),
            dict(name='child',item_code='SERVICE',description='SERVICE',qty=2,rate=5,amount=10,
                 custom_parent_row='parent',custom_is_service_row=1,discount_amount=5),
        ],discount=10)
        self.assertEqual(soup.select_one('.total-discounts').get_text(strip=True),'95')
        self.assertEqual(soup.select_one('.net-payable').get_text(strip=True),'225')

    def test_global_discount_alone_is_not_counted_twice(self):
        soup=self.render([dict(name='row',item_code='VITRE',qty=1,rate=235,amount=235,discount_amount=0)],discount=35)
        self.assertEqual(soup.select_one('.total-discounts').get_text(strip=True),'35')
        self.assertEqual(soup.select_one('.net-payable').get_text(strip=True),'200')

    def test_no_discount_stays_zero(self):
        soup=self.render([dict(name='row',item_code='VITRE',qty=1,rate=235,amount=235)])
        self.assertEqual(soup.select_one('.total-discounts').get_text(strip=True),'0')
