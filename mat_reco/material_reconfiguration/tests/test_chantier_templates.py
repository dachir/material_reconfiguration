"""Integration coverage; every fixture and naming counter is rolled back."""
import unittest
import frappe
from mat_reco.material_reconfiguration.services.chantier_templates import apply_sections, save_template


class TestChantierTemplates(unittest.TestCase):
    def setUp(self):
        self.user = frappe.session.user
        frappe.set_user('Administrator')
        frappe.db.savepoint('section_template_test')
        self.company = frappe.db.get_value('Company', {}, 'name')
        self.customer = frappe.db.get_value('Customer', {}, 'name')
        if not self.company or not self.customer:
            self.skipTest('A company and customer are required.')

    def tearDown(self):
        frappe.db.rollback(save_point='section_template_test')
        frappe.set_user(self.user)

    def chantier(self):
        return frappe.get_doc(dict(doctype='Chantier', designation='Test modèle sections',
            company=self.company, customer=self.customer)).insert()

    def section(self, chantier, label, parent=None, group=1):
        return frappe.get_doc(dict(doctype='Chantier Section', chantier=chantier,
            section_name=label, parent_chantier_section=parent, is_group=group)).insert()

    def test_copy_and_snapshot_keep_tree_without_lines(self):
        source, target, from_template = self.chantier(), self.chantier(), self.chantier()
        root = self.section(source.name, 'Bâtiment')
        floor = self.section(source.name, 'Étage', root.name)
        self.section(source.name, 'Pièce', floor.name, group=0)
        self.section(source.name, 'Extérieur')
        existing = self.section(target.name, 'Existante')
        model = save_template(source.name, 'Test-' + frappe.generate_hash(length=12))
        self.section(source.name, 'Ajout après modèle')
        self.assertEqual(apply_sections(target.name, source_chantier=source.name)['count'], 5)
        self.assertEqual(apply_sections(from_template.name, template=model)['count'], 4)
        rows = frappe.get_all('Chantier Section', filters={'chantier': from_template.name},
            fields=['name','section_name','parent_chantier_section','is_group'], order_by='lft')
        self.assertEqual([r.section_name for r in rows], ['Bâtiment','Étage','Pièce','Extérieur'])
        self.assertEqual(rows[1].parent_chantier_section, rows[0].name)
        self.assertEqual(rows[2].parent_chantier_section, rows[1].name)
        self.assertFalse(rows[2].is_group)
        self.assertTrue(frappe.db.exists('Chantier Section', existing.name))
        self.assertFalse(frappe.get_doc('Chantier', from_template.name).lines)

    def test_invalid_sources_and_validated_target_are_rejected(self):
        source, target = self.chantier(), self.chantier()
        self.section(source.name, 'Racine')
        with self.assertRaises(frappe.ValidationError):
            apply_sections(target.name, source_chantier=target.name)
        with self.assertRaises(frappe.ValidationError):
            apply_sections(target.name)
        frappe.db.set_value('Chantier', target.name, 'docstatus', 1)
        with self.assertRaises(frappe.ValidationError):
            apply_sections(target.name, source_chantier=source.name)

    def test_guest_cannot_copy_or_save_template(self):
        source, target = self.chantier(), self.chantier()
        self.section(source.name, 'Racine')
        frappe.set_user('Guest')
        with self.assertRaises(frappe.PermissionError):
            apply_sections(target.name, source_chantier=source.name)
        with self.assertRaises(frappe.PermissionError):
            save_template(source.name, 'Forbidden')
