"""Transactional activation, notifications and commercial-lock lifecycle."""
import unittest
from unittest.mock import patch

import frappe
from frappe.desk.doctype.notification_log.notification_log import NotificationLog
from mat_reco.material_reconfiguration.services import ft_activation as ft
from mat_reco.material_reconfiguration.services import technical_study_service as technical
from mat_reco.material_reconfiguration.services import task_notifications


class FTActivationTest(unittest.TestCase):
    def setUp(self):
        # Reproduce historical projects created before the type-based workflow.
        from mat_reco.material_reconfiguration.doctype.chantier.chantier import Chantier
        original_before_insert = Chantier.before_insert
        def historical_before_insert(doc):
            original_before_insert(doc)
            doc.workflow_version = 0
        legacy = patch.object(Chantier, 'before_insert', historical_before_insert)
        legacy.start()
        self.addCleanup(legacy.stop)
        self.user=frappe.session.user
        frappe.set_user('Administrator')
        frappe.db.savepoint('qa_ft_activation')
        self.addCleanup(self.cleanup)
        self.recipient=patch.object(task_notifications,'recipients',return_value=['Administrator']);self.recipient.start()
        self.addCleanup(self.recipient.stop)
        self.email=patch.object(NotificationLog,'after_insert');self.email.start();self.addCleanup(self.email.stop)
        company=frappe.db.get_value('Company',{},'name')
        customer=frappe.db.get_value('Customer',{},'name')
        if not company or not customer:self.skipTest('Requires a company and customer')
        self.doc=frappe.get_doc(dict(doctype='Chantier',designation='QA Activation FT',company=company,
            customer=customer,lines=[dict(designation='Vitre QA',qty=2,uom='PC',rate=100,
                length_mm=1000,width_mm=800,thickness_mm=10)])).insert()

    def cleanup(self):
        frappe.db.rollback(save_point='qa_ft_activation');frappe.set_user(self.user);frappe.clear_messages()

    def activate(self,active=1):
        self.doc.reload();ft.set_ft_active(self.doc.name,active,str(self.doc.modified));self.doc.reload()

    def tasks(self,doctype=None,name=None):
        return frappe.get_all('ToDo',filters={'reference_type':doctype or 'Chantier','reference_name':name or self.doc.name,
            'description':['like','[Univers Glass — Fiche technique]%']},fields=['name','status','reference_name'])

    def logs(self,doctype=None,name=None):
        return frappe.get_all('Notification Log',filters={'document_type':doctype or 'Chantier','document_name':name or self.doc.name,
            'subject':['like','Fiche technique à traiter :%']},pluck='name')

    def test_activation_is_idempotent_and_deactivation_cancels_both_entries(self):
        self.activate();key=self.doc.ft_activation_key
        self.activate();self.assertEqual(key,self.doc.ft_activation_key)
        self.assertEqual(len(self.tasks()),1);self.assertEqual(len(self.logs()),1)
        self.activate(0)
        self.assertEqual([t.status for t in self.tasks()],['Cancelled']);self.assertFalse(self.logs())
        self.activate();self.assertNotEqual(key,self.doc.ft_activation_key)
        self.assertEqual(len([t for t in self.tasks() if t.status=='Open']),1)

    def test_edit_before_preparation_invalidates_activation_and_notifications(self):
        self.activate();self.doc.designation='QA modifié';self.doc.save();self.doc.reload()
        self.assertFalse(self.doc.ft_active);self.assertFalse(self.logs())
        self.assertEqual([t.status for t in self.tasks()],['Cancelled'])
        with self.assertRaisesRegex(frappe.ValidationError,'Activer FT'):
            technical.prepare_study(self.doc.name)

    def test_preparation_and_direct_insertion_require_activation(self):
        with self.assertRaisesRegex(frappe.ValidationError,'Activer FT'):
            technical.prepare_study(self.doc.name)
        doc=frappe.new_doc('Chantier Technical Study');doc.chantier=self.doc.name
        with self.assertRaisesRegex(frappe.ValidationError,'Activer FT'):doc.insert()

    def test_prepared_study_locks_commercial_fields_and_moves_the_existing_task(self):
        self.activate();todo=self.tasks()[0].name;log=self.logs()[0]
        name=technical.prepare_study(self.doc.name)
        self.assertEqual(self.tasks('Chantier Technical Study',name)[0].name,todo)
        self.assertEqual(self.logs('Chantier Technical Study',name),[log])
        task_notifications.handoff_study(self.doc.name,'qa-view',name)
        task_notifications.handoff_study(self.doc.name,'qa-view-again',name)
        self.assertEqual(self.logs('Chantier Technical Study',name),[log])
        for field,value in [('designation','Changé'),('terms','Autres conditions')]:
            self.doc.reload();setattr(self.doc,field,value)
            with self.assertRaisesRegex(frappe.ValidationError,'Supprimer la fiche technique'):self.doc.save()
        self.doc.reload();self.doc.lines[0].qty=3
        with self.assertRaisesRegex(frappe.ValidationError,'Supprimer la fiche technique'):self.doc.save()
        with self.assertRaisesRegex(frappe.ValidationError,'Supprimer la fiche technique'):self.activate(0)

    def test_no_change_does_not_reset_activation(self):
        self.activate();self.doc.save();self.doc.reload();self.assertTrue(self.doc.ft_active)

    def test_deleting_study_cancels_tasks_and_requires_fresh_activation(self):
        self.activate();name=technical.prepare_study(self.doc.name);todo=self.tasks('Chantier Technical Study',name)[0].name
        study=frappe.get_doc('Chantier Technical Study',name)
        technical.delete_study(name,str(study.modified));self.doc.reload()
        self.assertFalse(self.doc.ft_active);self.assertFalse(ft.has_study(self.doc.name))
        self.assertEqual(frappe.db.get_value('ToDo',todo,'status'),'Cancelled')
        self.assertFalse(self.logs('Chantier Technical Study',name))
        self.doc.designation='Déverrouillé';self.doc.save()

    def test_sections_also_invalidate_or_lock(self):
        self.activate()
        section=frappe.get_doc(dict(doctype='Chantier Section',chantier=self.doc.name,section_name='QA A')).insert()
        self.doc.reload();self.assertFalse(self.doc.ft_active);self.assertFalse(self.logs())
        self.activate();technical.prepare_study(self.doc.name)
        section.section_name='QA B'
        with self.assertRaisesRegex(frappe.ValidationError,'Supprimer la fiche technique'):section.save()

    def test_api_cannot_activate_by_saving_readonly_fields(self):
        self.doc.ft_active=1
        with self.assertRaisesRegex(frappe.ValidationError,'bouton'):self.doc.save()
