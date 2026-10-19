"""New type-based projects have independent commercial and technical timelines."""
import json
import unittest
import uuid
from unittest.mock import patch

import frappe
from frappe.utils import nowdate, add_days
from frappe.desk.doctype.notification_log.notification_log import NotificationLog
from mat_reco.material_reconfiguration.services import technical_study_service as technical
from mat_reco.material_reconfiguration.services import chantier_work_types as work
from mat_reco.material_reconfiguration.services import ft_activation as activation
from mat_reco.material_reconfiguration.services import task_notifications
from mat_reco.material_reconfiguration.services.workshop_service import _tree


class IndependentChantierTests(unittest.TestCase):
    def setUp(self):
        self.user=frappe.session.user;frappe.set_user('Administrator');frappe.db.savepoint('qa_independent')
        self.addCleanup(self.cleanup)
        self.email=patch.object(NotificationLog,'after_insert');self.email.start();self.addCleanup(self.email.stop)
        self.recipients=patch.object(task_notifications,'recipients',return_value=['Administrator']);self.recipients.start();self.addCleanup(self.recipients.stop)
        self.company='Marsavco SA'
        if not frappe.db.exists('Company',self.company):self.skipTest('Requires glass-enabled company')
        self.customer=frappe.db.get_value('Customer',{},'name')
        self.cut='DPV10MM' if frappe.db.exists('Item','DPV10MM') else frappe.db.get_value('Item',{'custom_item_types':'DECOUPE','has_serial_no':1},'name')
        definition=technical.seed_item(self.cut)
        self.thickness=technical.composition_thickness(definition)
        self.typeid=uuid.uuid4().hex
        self.doc=frappe.get_doc(dict(doctype='Chantier',designation='QA Deux parcours',company=self.company,customer=self.customer,
            selling_price_list='Standard Selling',work_types=[dict(type_id=self.typeid,designation='Vitre commerciale claire',thickness_mm=self.thickness,proposed_item=self.cut)],
            lines=[dict(work_type=self.typeid,designation='Vitre commerciale claire',qty=2,length_mm=1200,width_mm=900,rate=100,uom='PC'),
                   dict(work_type=self.typeid,designation='Vitre commerciale claire',qty=1,length_mm=600,width_mm=600,rate=50,uom='PC')])).insert()

    def cleanup(self):
        frappe.db.rollback(save_point='qa_independent');frappe.set_user(self.user);frappe.clear_messages()

    def activate(self,active=1):
        self.doc.reload();activation.set_ft_active(self.doc.name,active,str(self.doc.modified));self.doc.reload()

    def study(self):
        self.activate()
        return frappe.get_doc('Chantier Technical Study',technical.prepare_study(self.doc.name))

    def quote(self):
        self.doc.submit();return frappe.get_doc('Quotation',technical.generate_quotation(self.doc.name,request_key=uuid.uuid4().hex))

    def order(self):
        quote=self.quote();quote.submit()
        study=self.study();study.submit()
        return frappe.get_doc('Sales Order',technical.confirm_order(quote.name,'QA accord',add_days(nowdate(),7),uuid.uuid4().hex))

    def test_type_mandatory_and_thickness_inherited(self):
        self.assertEqual(self.doc.workflow_version,2)
        self.assertTrue(all(r.thickness_mm==self.thickness for r in self.doc.lines))
        self.doc.lines[0].work_type='UNKNOWN'
        with self.assertRaisesRegex(frappe.ValidationError,'type d’ouvrage'):self.doc.save()

    def test_same_type_can_be_used_in_different_sections(self):
        for index,row in enumerate(self.doc.lines):
            section=frappe.get_doc(dict(doctype='Chantier Section',chantier=self.doc.name,section_name=f'QA Section {index}')).insert()
            row.section=section.name
        self.doc.save()
        self.assertEqual(len(work.prepare_type_rows(self.doc)),1)
        self.assertNotEqual(self.doc.lines[0].section,self.doc.lines[1].section)

    def test_quote_without_ft_but_order_requires_validated_ft(self):
        quote=self.quote();quote.submit()
        self.assertFalse(frappe.db.exists('Chantier Technical Study',{'chantier':self.doc.name}))
        with self.assertRaisesRegex(frappe.ValidationError,'Fiche technique validée'):
            technical.confirm_order(quote.name,'QA',add_days(nowdate(),7),uuid.uuid4().hex)
        study=self.study()
        with self.assertRaisesRegex(frappe.ValidationError,'Fiche technique validée'):
            technical.confirm_order(quote.name,'QA',add_days(nowdate(),7),uuid.uuid4().hex)
        study.submit()
        name=technical.confirm_order(quote.name,'QA',add_days(nowdate(),7),uuid.uuid4().hex)
        self.assertEqual(frappe.get_doc('Sales Order',name).docstatus,1)

    def test_ft_before_commercial_does_not_lock_project(self):
        study=self.study();self.assertEqual(len(study.lines),1)
        self.doc.reload();self.doc.lines[0].qty=4;self.doc.designation='Commercial indépendant';self.doc.save()
        self.assertEqual(study.source_hash,technical.source_hash(self.doc))
        self.doc.submit();self.assertEqual(self.doc.docstatus,1)
        study.reload();study.submit();self.assertEqual(study.docstatus,1)

    def test_study_after_commercial_and_frozen_manufacturing_definition(self):
        order=self.order();study=self.study()
        self.assertEqual(len(study.lines),1)
        tree=_tree(order,order.items[0]);self.assertEqual(tree['length_mm'],1200)
        self.assertFalse(order.items[0].custom_technical_snapshot)
        work.freeze_order(order)
        order.reload();first=order.items[0].custom_technical_snapshot
        self.assertTrue(first)
        self.assertEqual(json.loads(first)['technical_study'],study.name)
        self.assertNotEqual(order.items[0].item_code,self.cut)
        # A frozen command does not follow later changes to the study record.
        frappe.db.set_value('Chantier Technical Study',study.name,'source_hash','a different revision')
        order.reload();self.assertEqual(_tree(order,order.items[0])['length_mm'],1200)
        self.assertEqual(order.items[0].custom_technical_snapshot,first)

    def test_common_services_recalculate_per_piece_and_not_twice(self):
        group=frappe.db.get_value('Item Group',{'is_group':0},'name')
        service=frappe.get_doc(dict(doctype='Item',item_code='QA-TYPE-SERVICE',item_name='QA Rabotage commun',item_group=group,
            stock_uom='Meter',is_stock_item=0,is_sales_item=1,custom_item_types='SERVICE',custom_service_calc_basis='PERIMETRE')).insert()
        self.doc.work_types[0].common_extras=json.dumps([dict(key='RAB',item_code=service.name,rate=10,factor=1)])
        self.doc.save();self.assertEqual(len(self.doc.commercial_extras),2)
        self.assertAlmostEqual(self.doc.commercial_extras[0].qty,8.4)
        self.assertAlmostEqual(self.doc.commercial_extras[1].qty,2.4)
        self.doc.save();self.assertEqual(len(self.doc.commercial_extras),2)
        self.doc.lines[1].excluded_type_extras=json.dumps(['RAB']);self.doc.save()
        self.assertEqual(len(self.doc.commercial_extras),2)
        self.doc.set('commercial_extras',[]);self.doc.save()
        self.assertEqual(len(self.doc.commercial_extras),2)
        new=self.doc.append('lines',dict(work_type=self.typeid,qty=1,rate=0,length_mm=500,width_mm=500,uom='PC'))
        self.doc.save();self.assertEqual(len(self.doc.commercial_extras),3)
        self.assertTrue(any(e.parent_line_id==new.line_id for e in self.doc.commercial_extras))
        self.doc.remove(new);self.doc.save()
        quote=self.quote();self.assertEqual(len(quote.items),4)
        self.assertAlmostEqual(sum(r.amount for r in quote.items),358)

    def test_type_change_signals_stale_study_without_blocking_commercial(self):
        study=self.study();self.doc.reload();self.doc.work_types[0].designation='Nouveau libellé';self.doc.save()
        self.assertNotEqual(study.source_hash,technical.source_hash(self.doc))
        self.doc.submit();self.assertEqual(self.doc.docstatus,1)
        with self.assertRaises(frappe.ValidationError):study.submit()

    def test_notification_is_independent_and_deactivation_after_submit_works(self):
        self.doc.submit();self.activate()
        todo=frappe.get_all('ToDo',filters={'reference_type':'Chantier','reference_name':self.doc.name,'status':'Open'},pluck='name')
        self.assertTrue(todo)
        self.activate(0)
        self.assertTrue(all(frappe.db.get_value('ToDo',name,'status')=='Cancelled' for name in todo))
        self.assertEqual(self.doc.docstatus,1)

    def test_taxes_flow_to_order_and_invoice(self):
        from erpnext.selling.doctype.sales_order.sales_order import make_sales_invoice
        account=frappe.db.get_value('Account',{'company':self.company,'account_type':'Tax','is_group':0},'name')
        if not account:self.skipTest('Requires company tax account')
        template=frappe.get_doc(dict(doctype='Sales Taxes and Charges Template',title='QA Types TVA',company=self.company,
            taxes=[dict(charge_type='On Net Total',account_head=account,description='TVA 18 %',rate=18)])).insert()
        self.doc.taxes_and_charges=template.name;self.doc.save()
        order=self.order();invoice=make_sales_invoice(order.name)
        self.assertEqual(order.taxes_and_charges,template.name)
        self.assertAlmostEqual(order.total_taxes_and_charges,45)
        self.assertEqual(invoice.taxes_and_charges,template.name)
        self.assertAlmostEqual(invoice.grand_total,295)

    def test_print_groups_section_type_and_dimensions(self):
        from pathlib import Path
        from bs4 import BeautifulSoup
        section=frappe.get_doc(dict(doctype='Chantier Section',chantier=self.doc.name,section_name='QA Façade')).insert()
        for row in self.doc.lines:row.section=section.name
        self.doc.save();quote=self.quote()
        formats=json.loads(Path(frappe.get_app_path('mat_reco','fixtures','print_format.json')).read_text())
        template=next(p['html'] for p in formats if p['name']=='Devis v2')
        html=frappe.render_template(template,dict(doc=quote));soup=BeautifulSoup(html,'html.parser')
        self.assertIn('QA Façade',soup.select_one('.section-heading').get_text())
        self.assertIn('Vitre commerciale claire',soup.select_one('.work-type-heading').get_text())
        self.assertNotIn('UG-COM-',soup.get_text())

    def test_cockpit_mcp_freezes_and_expands_new_commercial_sku(self):
        from mat_reco.material_reconfiguration.services import workshop_service as ws
        order=self.order();study=self.study();row=order.items[0]
        tree=_tree(order,row)
        source=next(n['primary_item'] for n in ws._walk(tree) if n['item_type']=='DECOUPE')
        node=next(n for n in ws._walk(tree) if n['item_type']=='DECOUPE')
        spec=dict(sales_order=order.name,orders=[order.name],node_id=node['id'],qty=2,
            needs=[dict(sales_order=order.name,node_id=node['id'],qty=2)],operation='QA-TYPE-MCP')
        spec['signature']=ws._scope_signature(spec)
        plan=frappe.get_doc(dict(doctype='Material Cutting Plan',company=self.company,source_item=source,
            mcp_mode='Planification',selected_sales_orders=[dict(sales_order=order.name)],workshop_request_json=json.dumps(spec)))
        demands=ws.workshop_cutting_demands(plan)
        self.assertEqual(len(demands),2)
        self.assertTrue(all(d['sales_order']==order.name and d['length_mm']==1200 and d['width_mm']==900 for d in demands))
        order.reload();self.assertTrue(order.items[0].custom_technical_snapshot)
        self.assertFalse(order.items[1].custom_technical_snapshot)

    def test_description_defaults_to_type_and_remains_editable_through_quotation(self):
        self.doc.lines[0].designation=''
        self.doc.lines[1].designation='Vitre du balcon, finition particulière'
        self.doc.save();self.doc.reload()
        self.assertEqual(self.doc.lines[0].designation,'Vitre commerciale claire')
        self.assertEqual(self.doc.lines[1].designation,'Vitre du balcon, finition particulière')
        self.doc.save();quote=self.quote()
        row=next(r for r in quote.items if r.custom_chantier_line==self.doc.lines[1].line_id)
        self.assertEqual(row.description,'Vitre du balcon, finition particulière')
        self.assertEqual(row.item_name,'Vitre du balcon, finition particulière')

    def test_autocomplete_includes_types_without_lines_and_custom_descriptions(self):
        self.doc.append('work_types',dict(type_id='QA-UNUSED',designation='QA Autocomplete type seul',thickness_mm=6))
        self.doc.lines[0].designation='QA Autocomplete description libre'
        self.doc.save()
        suggestions=technical.designation_suggestions('QA Autocomplete')
        self.assertIn('QA Autocomplete type seul',suggestions)
        self.assertIn('QA Autocomplete description libre',suggestions)

    def test_line_overrides_survive_save_and_later_type_default_changes(self):
        group=frappe.db.get_value('Item Group',{'is_group':0},'name')
        item=frappe.get_doc(dict(doctype='Item',item_code='QA-TYPE-OVERRIDE',item_name='QA Complément ajustable',item_group=group,
            stock_uom='PC',is_stock_item=0,is_sales_item=1,custom_item_types='SERVICE',custom_service_calc_basis='MANUEL')).insert()
        self.doc.work_types[0].common_extras=json.dumps([dict(key='SHARED',item_code=item.name,qty=2,factor=1,rate=10)])
        self.doc.save()
        extra=next(r for r in self.doc.commercial_extras if r.parent_line_id==self.doc.lines[0].line_id)
        # A new browser draft has a provisional identity until server validation.
        extra.line_id='type-extra:'+extra.parent_line_id+':SHARED'
        extra.qty=7;extra.rate=13;extra.inherited_qty_override=1;extra.inherited_rate_override=1
        technical.save_commercial(self.doc.name,str(self.doc.modified),frappe.as_json(self.doc.lines),
            commercial_extras=frappe.as_json(self.doc.commercial_extras),work_types=frappe.as_json(self.doc.work_types))
        self.doc.reload()
        self.doc.work_types[0].common_extras=json.dumps([dict(key='SHARED',item_code=item.name,qty=3,factor=1,rate=99)])
        self.doc.save();self.doc.reload()
        first=next(r for r in self.doc.commercial_extras if r.parent_line_id==self.doc.lines[0].line_id)
        second=next(r for r in self.doc.commercial_extras if r.parent_line_id==self.doc.lines[1].line_id)
        self.assertEqual((first.qty,first.rate),(7,13));self.assertEqual((second.qty,second.rate),(3,99))
        quote=self.quote();quoted=next(r for r in quote.items if r.custom_chantier_line==first.line_id)
        self.assertEqual((quoted.qty,quoted.rate,quoted.amount),(7,13,91))

    def direct_lines(self):
        group=frappe.db.get_value('Item Group',{'is_group':0},'name')
        for kind in ('SERVICE','ACCESSOIRE'):
            item=frappe.get_doc(dict(doctype='Item',item_code='QA-DIRECT-'+kind,item_name='QA Direct '+kind,
                item_group=group,stock_uom='PC',is_stock_item=0,is_sales_item=1,custom_item_types=kind)).insert()
            self.doc.append('lines',dict(line_kind='Vente directe',sale_item=item.name,qty=2,rate=25))
        primary=frappe.db.get_value('Item',{'custom_item_types':'PRIMAIRE','disabled':0,'is_sales_item':1},'name')
        self.assertTrue(primary)
        self.doc.append('lines',dict(line_kind='Vente directe',sale_item=primary,qty=1,rate=100))

    def test_standalone_plates_accessories_and_services_without_types_or_ft(self):
        self.doc.set('lines',[]);self.doc.set('work_types',[]);self.direct_lines();self.doc.save()
        quote=self.quote();quote.submit()
        order=frappe.get_doc('Sales Order',technical.confirm_order(quote.name,'Vente directe QA',add_days(nowdate(),7),uuid.uuid4().hex))
        self.assertEqual(len(order.items),3);self.assertEqual(order.docstatus,1)
        self.assertFalse(frappe.db.exists('Chantier Technical Study',{'chantier':self.doc.name}))
        self.assertTrue(all(not r.custom_technical_snapshot and not r.custom_ug_work_type for r in order.items))
        self.assertAlmostEqual(order.net_total,200)
        self.assertFalse(frappe.db.exists('ToDo',{'reference_type':'Sales Order','reference_name':order.name,'description':['like','[Univers Glass — Atelier]%']}))
        from mat_reco.material_reconfiguration.services.chantier_service import get_dossier
        self.assertFalse(get_dossier(self.doc.name)['lines'])

    def test_mixed_quote_direct_order_then_manufacturing_order_after_ft(self):
        self.direct_lines();self.doc.save();quote=self.quote();quote.submit()
        with self.assertRaisesRegex(frappe.ValidationError,'Fiche technique validée'):
            technical.confirm_order(quote.name,'Mixte QA',add_days(nowdate(),7),uuid.uuid4().hex)
        direct=frappe.get_doc('Sales Order',technical.confirm_order(quote.name,'Direct QA',add_days(nowdate(),7),uuid.uuid4().hex,direct_only=1))
        self.assertEqual(len(direct.items),3)
        study=self.study();self.assertEqual(len(study.lines),1);study.submit()
        rest=frappe.get_doc('Sales Order',technical.confirm_order(quote.name,'Fabrication QA',add_days(nowdate(),7),uuid.uuid4().hex))
        self.assertEqual(len(rest.items),2);self.assertTrue(all(r.custom_ug_work_type==self.typeid for r in rest.items))

    def test_native_erp_order_creation_cannot_bypass_ft_gate(self):
        from erpnext.selling.doctype.quotation.quotation import make_sales_order
        quote=self.quote();quote.submit();order=make_sales_order(quote.name)
        order.custom_customer_acceptance='QA ERPNext';order.delivery_date=add_days(nowdate(),7)
        for row in order.items:row.delivery_date=order.delivery_date
        with self.assertRaisesRegex(frappe.ValidationError,'Fiche technique validée'):order.insert()

    def test_sections_remain_creatable_after_types_works_and_ft_until_validation(self):
        from mat_reco.material_reconfiguration.services.chantier_service import create_section
        study=self.study();self.doc.reload()
        result=create_section(self.doc.name,str(self.doc.modified),'QA Section après FT')
        self.assertTrue(any(s.name==result['name'] for s in result['sections']))
        self.doc.reload();self.assertEqual(len(self.doc.lines),2)
        self.assertEqual(len(self.doc.work_types),1)
        self.assertEqual(frappe.get_doc('Chantier Technical Study',study.name).docstatus,0)
        self.doc.submit()
        with self.assertRaisesRegex(frappe.ValidationError,'validation du chantier'):
            create_section(self.doc.name,str(self.doc.modified),'QA Trop tard')
