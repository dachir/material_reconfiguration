"""Glass warehouse defaults automate entry without restricting manual choices."""
import unittest
from unittest.mock import patch
import frappe
from mat_reco.material_reconfiguration.services import ug_warehouse as policy


class UGWarehouseTests(unittest.TestCase):
    def setUp(self):
        for target,kwargs in [
            ('operational_warehouse',dict(side_effect=lambda c:policy.WAREHOUSE if c==policy.COMPANY else None)),
            ('is_glass',dict(side_effect=lambda code:code=='GLASS')),
        ]:
            p=patch.object(policy,target,**kwargs);p.start();self.addCleanup(p.stop)
        p=patch.object(frappe,'get_cached_value',side_effect=lambda dt,code,field:code!='SERVICE')
        p.start();self.addCleanup(p.stop)

    def order(self,company=policy.COMPANY,mixed=False,warehouse=None):
        rows=[dict(item_code='GLASS',warehouse=warehouse)]
        if mixed:rows.append(dict(item_code='ACCESSORY',warehouse='ACCESSORY-WH'))
        return frappe.get_doc(dict(doctype='Sales Order',company=company,docstatus=0,set_warehouse=warehouse,items=rows))

    def test_empty_glass_fields_prefilled_and_accessories_preserved(self):
        doc=self.order();policy.apply_defaults(doc)
        self.assertEqual(doc.set_warehouse,policy.WAREHOUSE)
        self.assertEqual(doc.items[0].warehouse,policy.WAREHOUSE)
        doc=self.order(mixed=True);policy.apply_defaults(doc)
        self.assertIsNone(doc.set_warehouse)
        self.assertEqual(doc.items[0].warehouse,policy.WAREHOUSE)
        self.assertEqual(doc.items[1].warehouse,'ACCESSORY-WH')

    def test_manual_other_warehouse_is_preserved(self):
        doc=self.order(warehouse='OTHER-WH');policy.apply_defaults(doc)
        self.assertEqual(doc.set_warehouse,'OTHER-WH')
        self.assertEqual(doc.items[0].warehouse,'OTHER-WH')

    def test_other_company_and_submitted_orders_unchanged(self):
        doc=self.order(company='OTHER');policy.apply_defaults(doc)
        self.assertIsNone(doc.items[0].warehouse)
        doc=self.order(warehouse='OLD');doc.docstatus=1;policy.apply_defaults(doc)
        self.assertEqual(doc.items[0].warehouse,'OLD')

    def test_existing_issue_adoption_keeps_historical_warehouse(self):
        doc=frappe.get_doc(dict(doctype='Bordereau Special',company=policy.COMPANY,docstatus=0,adopt_existing_stock=1,warehouse='HISTORICAL',items=[dict(item_code='GLASS',warehouse='HISTORICAL')]))
        policy.apply_defaults(doc)
        self.assertEqual(doc.items[0].warehouse,'HISTORICAL')

    def test_mcp_prefill_does_not_replace_explicit_choice(self):
        for selected,expected in [(None,policy.WAREHOUSE),('OTHER','OTHER')]:
            doc=frappe.get_doc(dict(doctype='Material Cutting Plan',company=policy.COMPANY,docstatus=0,source_warehouse=selected))
            policy.apply_defaults(doc)
            self.assertEqual(doc.source_warehouse,expected)

    def test_item_defaults_only_fill_glass_and_keep_manual_choices(self):
        for kind,initial,expected in [('DECOUPE',None,policy.WAREHOUSE),('DECOUPE','OTHER','OTHER'),('ACCESSOIRE',None,None),('ACCESSOIRE','OTHER','OTHER')]:
            doc=frappe.get_doc(dict(doctype='Item',docstatus=0,custom_item_types=kind,item_defaults=[dict(company=policy.COMPANY,default_warehouse=initial)]))
            policy.apply_defaults(doc)
            self.assertEqual(doc.item_defaults[0].default_warehouse,expected)
