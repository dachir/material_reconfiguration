"""Native Sales Order numbering uses separate transactional A/B counters."""
import re
import unittest
import uuid

import frappe
from frappe.utils import nowdate,add_days


class SalesOrderTypeTests(unittest.TestCase):
    def setUp(self):
        self.user=frappe.session.user;frappe.set_user('Administrator');frappe.db.savepoint('qa_order_types')
        self.addCleanup(self.cleanup)
        self.company='Marsavco SA';self.customer=frappe.db.get_value('Customer',{},'name')
        if not self.customer or not frappe.db.exists('Company',self.company):self.skipTest('Requires local ERPNext company/customer')
        self.item=frappe.get_doc(dict(doctype='Item',item_code='QA-TYPE-'+uuid.uuid4().hex[:10],item_name='QA Numérotation commande',
            item_group=frappe.db.get_value('Item Group',{'is_group':0},'name'),stock_uom='PC',is_stock_item=0,is_sales_item=1,custom_item_types='SERVICE')).insert()

    def cleanup(self):
        frappe.db.rollback(save_point='qa_order_types');frappe.set_user(self.user);frappe.clear_messages()

    def order(self,kind):
        return frappe.get_doc(dict(doctype='Sales Order',customer=self.customer,company=self.company,
            transaction_date=nowdate(),delivery_date=add_days(nowdate(),7),custom_ug_order_type=kind,
            items=[dict(item_code=self.item.name,qty=1,rate=10,delivery_date=add_days(nowdate(),7))])).insert()

    def test_independent_counters_and_correct_type_in_name(self):
        orders=[self.order(t) for t in ('A','B','A','B')]
        numbers=[]
        for doc,kind in zip(orders,('A','B','A','B')):
            match=re.fullmatch(r'SAL-ORD-'+('B-' if kind=='B' else '')+r'(\d{4})-(\d{5})',doc.name)
            self.assertIsNotNone(match,doc.name);numbers.append(int(match.group(2)))
        self.assertEqual(numbers[2],numbers[0]+1);self.assertEqual(numbers[3],numbers[1]+1)

    def test_invalid_type_and_reclassification_are_rejected(self):
        with self.assertRaisesRegex(frappe.ValidationError,'type de commande'):self.order('C')
        doc=self.order('A');original=doc.name;doc.custom_ug_order_type='B'
        with self.assertRaisesRegex(frappe.ValidationError,'ne peut plus'):doc.save()
        doc.reload();self.assertEqual(doc.name,original);self.assertEqual(doc.custom_ug_order_type,'A')

    def test_native_amendment_retains_type_and_number(self):
        doc=self.order('B');doc.submit();doc.cancel()
        amended=frappe.copy_doc(doc);amended.amended_from=doc.name;amended.docstatus=0;amended.insert()
        self.assertEqual(amended.name,doc.name+'-1');self.assertEqual(amended.custom_ug_order_type,'B')
