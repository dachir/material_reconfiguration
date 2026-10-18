"""Real ToDo/Desk notification delivery, recipients and handoff idempotency."""
import unittest
from unittest.mock import patch

import frappe

from mat_reco.material_reconfiguration.services import task_notifications as service
from mat_reco.material_reconfiguration.services.technical_study_service import prepare_study
from frappe.desk.doctype.notification_log.notification_log import NotificationLog


class TaskNotificationTests(unittest.TestCase):
    def setUp(self):
        self.user = frappe.session.user
        frappe.set_user('Administrator')
        frappe.db.savepoint('qa_ug_notifications')
        self.email_patch = patch.object(NotificationLog, 'after_insert')
        self.email_patch.start()
        self.addCleanup(self.email_patch.stop)
        if not frappe.db.exists('Company', 'Marsavco SA') or not frappe.db.exists('Customer', 'AQUA LOISIR'):
            self.skipTest('Requires the glass-enabled local test company')
        role = 'QA Univers Glass Notifications'
        if not frappe.db.exists('Role', role):
            frappe.get_doc(dict(doctype='Role', role_name=role)).insert()
        self.users = []
        for number, enabled, access in [(1,1,True),(2,1,True),(3,0,True),(4,1,False)]:
            user = frappe.get_doc(dict(doctype='User', email=f'qa-ug-task-{number}@example.invalid',
                first_name=f'QA UG {number}', enabled=enabled, send_welcome_email=0,
                roles=[dict(role=role)]+([dict(role='Stock Manager')] if access else []))).insert()
            self.users.append(user.name)
        frappe.db.set_single_value('Mat Reco Settings', 'chantier_notification_role', role)
        frappe.db.set_single_value('Mat Reco Settings', 'technical_notification_role', role)
        frappe.db.set_single_value('Mat Reco Settings', 'workshop_notification_role', role)
        self.chantier = frappe.get_doc(dict(doctype='Chantier', designation='QA Notifications',
            company='Marsavco SA', customer='AQUA LOISIR', currency='USD',
            lines=[dict(repere='QA-1', designation='Vitre QA', qty=2, uom='PC')])).insert()
        self.study = frappe.get_doc('Chantier Technical Study', prepare_study(self.chantier.name))

    def tearDown(self):
        frappe.db.rollback(save_point='qa_ug_notifications')
        for user in getattr(self, 'users', []):
            frappe.clear_cache(user=user)
        frappe.set_user(self.user)
        frappe.clear_messages()

    def logs(self):
        return frappe.get_all('Notification Log', filters={'document_type':self.study.doctype,
            'document_name':self.study.name}, fields=['name','for_user'])

    def todos(self):
        return frappe.get_all('ToDo', filters={'reference_type':self.study.doctype,
            'reference_name':self.study.name}, fields=['name','allocated_to','status'])

    def chantier_tasks(self):
        return frappe.get_all('ToDo',filters={'reference_type':'Chantier',
            'reference_name':self.chantier.name},fields=['allocated_to','status'])

    def chantier_logs(self):
        return frappe.get_all('Notification Log',filters={'document_type':'Chantier',
            'document_name':self.chantier.name},fields=['for_user','name'])

    def test_validated_study_notifies_managers_once_and_closes_technical_tasks(self):
        service.send_tasks(self.study,'technical','qa-first')
        self.study.docstatus=1
        service.study_finished(self.study)
        service.study_finished(self.study)
        self.assertEqual({r.status for r in self.todos()},{'Closed'})
        self.assertEqual({r.allocated_to for r in self.chantier_tasks()},set(self.users[:2]))
        self.assertEqual(len(self.chantier_logs()),2)

    def test_chantier_validation_closes_manager_tasks(self):
        self.study.docstatus=1
        service.study_finished(self.study)
        self.chantier.docstatus=1
        service.chantier_finished(self.chantier)
        self.assertEqual({r.status for r in self.chantier_tasks()},{'Closed'})

    def test_cancelled_study_cancels_pending_manager_tasks(self):
        self.study.docstatus=1
        service.study_finished(self.study)
        self.study.docstatus=2
        service.study_finished(self.study)
        self.assertEqual({r.status for r in self.chantier_tasks()},{'Cancelled'})
        self.assertEqual(len(self.chantier_logs()),2)

    def test_ug_chantier_targets_only_members_who_can_already_validate(self):
        for number,roles in [(5,['UG CHANTIER','Sales Manager']),(6,['UG CHANTIER'])]:
            user=frappe.get_doc(dict(doctype='User',email=f'qa-ug-task-{number}@example.invalid',
                first_name=f'QA manager {number}',enabled=1,send_welcome_email=0,
                roles=[dict(role=role) for role in roles])).insert()
            self.users.append(user.name)
        frappe.db.set_single_value('Mat Reco Settings','chantier_notification_role','UG CHANTIER')
        self.study.docstatus=1
        service.study_finished(self.study)
        self.assertEqual({r.for_user for r in self.chantier_logs()},{self.users[4]})
        self.assertTrue(frappe.has_permission(doc=self.chantier,user=self.users[4],ptype='submit'))
        self.assertFalse(frappe.has_permission(doc=self.chantier,user=self.users[5],ptype='submit'))

    def test_named_technical_role_has_consultation_access(self):
        user=frappe.get_doc(dict(doctype='User',email='qa-ug-task-5@example.invalid',
            first_name='QA UG named role',enabled=1,send_welcome_email=0,
            roles=[dict(role='UG FICHE TECHNIQUE')])).insert()
        self.users.append(user.name)
        self.assertTrue(frappe.has_permission(doc=self.study,user=user.name,ptype='read'))
        self.assertFalse(frappe.has_permission(doc=self.study,user=user.name,ptype='submit'))
        frappe.db.set_single_value('Mat Reco Settings','technical_notification_role','UG FICHE TECHNIQUE')
        service.handoff_study(self.chantier.name,'qa-named-role',self.study.name)
        self.assertIn(user.name,{r.for_user for r in self.logs()})

    def test_each_authorized_role_member_gets_notification_and_task(self):
        service.handoff_study(self.chantier.name, 'qa-first', self.study.name)
        self.assertEqual({r.for_user for r in self.logs()}, set(self.users[:2]))
        self.assertEqual({r.allocated_to for r in self.todos()}, set(self.users[:2]))

    def test_retry_is_idempotent_but_new_handoff_notifies_again(self):
        for key in ['qa-first','qa-first','qa-second']:
            service.handoff_study(self.chantier.name,key,self.study.name)
        self.assertEqual(len(self.logs()),4)
        self.assertEqual(len(self.todos()),2)

    def test_finished_study_closes_generated_tasks(self):
        service.send_tasks(self.study,'technical','qa-first')
        self.study.docstatus=1
        service.study_finished(self.study)
        self.assertEqual({r.status for r in self.todos()},{'Closed'})

    def test_only_glass_orders_trigger_workshop_notifications(self):
        order=frappe._dict(items=[frappe._dict(item_code='QA-ITEM')])
        with patch.object(frappe,'get_cached_value',return_value='DECOUPE'), patch.object(service,'send_tasks') as send:
            service.order_created(order)
            send.assert_called_once_with(order,'workshop','order-created')
        with patch.object(frappe,'get_cached_value',return_value='SERVICE'), patch.object(service,'send_tasks') as send:
            service.order_created(order)
            send.assert_not_called()

    def test_other_chantier_cannot_be_used_for_handoff(self):
        with self.assertRaises(frappe.DoesNotExistError):
            service.handoff_study('nonexistent-chantier','qa-invalid',self.study.name)
