"""Submitted A/B orders hand off once to FT, then to workshop."""
import unittest
import uuid
from unittest.mock import patch

import frappe
from frappe.utils import add_days,nowdate
from mat_reco.material_reconfiguration.tests import test_independent_chantier as fixtures
from mat_reco.material_reconfiguration.services import technical_study_service as technical
from mat_reco.material_reconfiguration.services import task_notifications as tasks
from mat_reco.material_reconfiguration.services import order_technical


class OrderTechnicalTests(unittest.TestCase):
    setUp=fixtures.IndependentChantierTests.setUp
    cleanup=fixtures.IndependentChantierTests.cleanup
    quote=fixtures.IndependentChantierTests.quote

    def confirm(self,kind='A'):
        quote=self.quote();quote.submit()
        return frappe.get_doc('Sales Order',technical.confirm_order(quote.name,'QA accord',add_days(nowdate(),7),uuid.uuid4().hex,order_type=kind))

    def todos(self,doc,stage,status='Open'):
        return frappe.get_all('ToDo',filters={'reference_type':doc.doctype,'reference_name':doc.name,'status':status,
            'description':['like',f'[Univers Glass — {tasks.STAGES[stage][1]}]%']},pluck='name')

    def test_both_circuits_create_ft_once_and_only_validation_hands_off_to_atelier(self):
        for kind in ('A','B'):
            with self.subTest(kind=kind):
                frappe.db.savepoint('qa_each_circuit')
                order=self.confirm(kind)
                study=frappe.get_doc('Chantier Technical Study',order.custom_technical_study)
                self.assertEqual(study.docstatus,0);self.assertEqual(study.sales_order,order.name)
                self.assertEqual(len(study.lines),1);self.assertTrue(self.todos(study,'technical'))
                self.assertFalse(self.todos(order,'workshop'))
                self.assertEqual(order_technical.prepare(order),study.name)
                self.assertEqual(len(self.todos(study,'technical')),1)
                study.submit()
                self.assertTrue(self.todos(study,'technical','Closed'));self.assertTrue(self.todos(order,'workshop'))
                tasks.study_finished(study)
                self.assertEqual(len(self.todos(order,'workshop')),1)
                frappe.db.rollback(save_point='qa_each_circuit');self.doc.reload()

    def test_native_draft_has_no_technical_task_and_service_order_has_review_ft(self):
        group=frappe.db.get_value('Item Group',{'is_group':0},'name')
        item=frappe.get_doc(dict(doctype='Item',item_code='QA-FT-'+uuid.uuid4().hex[:10],item_name='QA Service',
            item_group=group,stock_uom='PC',is_stock_item=0,is_sales_item=1,custom_item_types='SERVICE')).insert()
        order=frappe.get_doc(dict(doctype='Sales Order',company=self.company,customer=self.customer,delivery_date=add_days(nowdate(),7),
            items=[dict(item_code=item.name,qty=1,rate=100,delivery_date=add_days(nowdate(),7))])).insert()
        self.assertFalse(order.custom_technical_study)
        self.assertFalse(frappe.db.exists('Chantier Technical Study',{'sales_order':order.name}))
        order.submit();study=frappe.get_doc('Chantier Technical Study',order.custom_technical_study)
        self.assertFalse(study.chantier);self.assertFalse(study.lines);self.assertTrue(self.todos(study,'technical'))
        self.assertFalse(technical.get_study(study.name)['stale'])
        study.submit();self.assertFalse(self.todos(order,'workshop'))

    def test_partial_orders_keep_separate_ft_and_their_own_quantities(self):
        self.doc.submit()
        order_names=[]
        for index,row in enumerate(self.doc.lines):
            quote=frappe.get_doc('Quotation',technical.generate_quotation(self.doc.name,selections=[dict(line_id=row.line_id,qty=row.qty)],request_key=uuid.uuid4().hex))
            quote.submit()
            order=frappe.get_doc('Sales Order',technical.confirm_order(quote.name,'QA partiel',add_days(nowdate(),7),uuid.uuid4().hex))
            order_names.append(order.custom_technical_study)
            _,scope,_=order_technical.context(frappe.get_doc('Chantier Technical Study',order.custom_technical_study))
            self.assertEqual(len(scope.lines),1);self.assertEqual(scope.lines[0].qty,row.qty)
        self.assertNotEqual(*order_names)
        self.doc.reload();self.assertEqual(len(self.doc.lines),2)

    def test_cancelled_order_cancels_pending_ft_tasks(self):
        order=self.confirm('B');study=frappe.get_doc('Chantier Technical Study',order.custom_technical_study)
        self.assertTrue(self.todos(study,'technical'));order.cancel()
        self.assertTrue(self.todos(study,'technical','Cancelled'))
        with self.assertRaises(frappe.ValidationError):study.submit()

    def test_ft_cancel_then_reprepare_has_new_handoff_and_pointer(self):
        order=self.confirm('B');study=frappe.get_doc('Chantier Technical Study',order.custom_technical_study)
        study.submit();study.cancel()
        self.assertTrue(self.todos(order,'workshop','Cancelled'))
        name=order_technical.prepare_for_order(order.name)
        self.assertNotEqual(name,study.name)
        order.reload();self.assertEqual(order.custom_technical_study,name)
        self.assertTrue(self.todos(frappe.get_doc('Chantier Technical Study',name),'technical'))

    def test_b_prohibits_native_delivery_and_invoice(self):
        from mat_reco.material_reconfiguration.services.order_b import validate_downstream
        order=self.confirm('B')
        for dt,field in [('Sales Invoice','sales_order'),('Delivery Note','against_sales_order')]:
            with self.subTest(doctype=dt):
                with self.assertRaisesRegex(frappe.ValidationError,'Circuit B'):
                    validate_downstream(frappe.get_doc(dict(doctype=dt,items=[{field:order.name}])))

    def test_transaction_failure_does_not_silently_skip_ft(self):
        quote=self.quote();quote.submit();frappe.db.savepoint('qa_failed_handoff')
        with patch.object(order_technical,'prepare',side_effect=frappe.ValidationError('QA handoff failed')):
            with self.assertRaisesRegex(frappe.ValidationError,'QA handoff failed'):
                technical.confirm_order(quote.name,'QA',add_days(nowdate(),7),uuid.uuid4().hex)
        frappe.db.rollback(save_point='qa_failed_handoff')
        self.assertFalse(frappe.db.exists('Sales Order',{'custom_chantier':self.doc.name}))

    def test_native_cutting_order_uses_its_validated_ft_in_cockpit(self):
        from mat_reco.material_reconfiguration.services.workshop_service import _tree
        from mat_reco.material_reconfiguration.services.chantier_work_types import freeze_order
        order=frappe.get_doc(dict(doctype='Sales Order',company=self.company,customer=self.customer,delivery_date=add_days(nowdate(),7),
            items=[dict(item_code=self.cut,qty=2,rate=100,delivery_date=add_days(nowdate(),7),
                custom_client_length_mm=1200,custom_client_width_mm=900,custom_client_thickness_mm=self.thickness)])).insert()
        order.submit();study=frappe.get_doc('Chantier Technical Study',order.custom_technical_study)
        with self.assertRaises(frappe.ValidationError):_tree(order,order.items[0])
        study.submit();tree=_tree(order,order.items[0])
        self.assertEqual(tree['technical_study'],study.name);self.assertEqual(tree['length_mm'],1200)
        freeze_order(order);order.reload();self.assertTrue(order.items[0].custom_technical_snapshot)

    def test_b_visibility_and_board_are_restricted_to_its_role(self):
        from mat_reco.material_reconfiguration.report.suivi_commandes_b.suivi_commandes_b import execute
        a=self.confirm('A')
        # Reuse a native service order for B without consuming the source quotation twice.
        b=frappe.copy_doc(a);b.custom_ug_order_type='B';b.custom_chantier=None;b.custom_technical_study=None;b.custom_chantier_order_key=None;b.custom_chantier_order_scope=None
        for r in b.items:r.prevdoc_docname=None;r.quotation_item=None;r.custom_chantier_line=None
        b.insert()
        user=frappe.get_doc(dict(doctype='User',email='qa-b-'+uuid.uuid4().hex[:8]+'@example.invalid',first_name='QA B',
            send_welcome_email=0,roles=[dict(role='Sales User')])).insert()
        self.addCleanup(lambda:frappe.clear_cache(user=user.name))
        self.assertTrue(frappe.has_permission(doc=a,user=user.name,ptype='read'))
        self.assertFalse(frappe.has_permission(doc=b,user=user.name,ptype='read'))
        frappe.set_user(user.name)
        try:
            names=frappe.get_list('Sales Order',filters={'name':['in',[a.name,b.name]]},pluck='name')
            self.assertIn(a.name,names);self.assertNotIn(b.name,names)
            with self.assertRaises(frappe.PermissionError):execute({})
        finally:frappe.set_user('Administrator')
        user.append('roles',dict(role='UG COMMANDES B'));user.save();frappe.clear_cache(user=user.name)
        self.assertTrue(frappe.has_permission(doc=b,user=user.name,ptype='read'))
        columns,rows=execute({'customer':self.customer})
        self.assertTrue(columns);self.assertIn(b.name,{r.name for r in rows})
