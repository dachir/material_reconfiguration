import unittest

import frappe
from mat_reco.material_reconfiguration.services.quotation_project_service import map_quotation_project


class QuotationProjectTests(unittest.TestCase):
    def quotation(self, project):
        return frappe._dict(doctype="Quotation", name="Q-TEST", custom_project=project)

    def test_project_copied(self):
        target = frappe._dict(project=None)
        map_quotation_project(target, "after_mapping", self.quotation("PROJECT-A"))
        self.assertEqual(target.project, "PROJECT-A")

    def test_same_project_can_be_combined(self):
        target = frappe._dict(project="PROJECT-A")
        map_quotation_project(target, "after_mapping", self.quotation("PROJECT-A"))
        self.assertEqual(target.project, "PROJECT-A")

    def test_different_projects_rejected(self):
        target = frappe._dict(project="PROJECT-B")
        with self.assertRaises(frappe.ValidationError):
            map_quotation_project(target, "after_mapping", self.quotation("PROJECT-A"))
        self.assertEqual(target.project, "PROJECT-B")

    def test_empty_source_preserves_target(self):
        target = frappe._dict(project="PROJECT-B")
        map_quotation_project(target, "after_mapping", self.quotation(None))
        self.assertEqual(target.project, "PROJECT-B")

    def test_other_mapping_unchanged(self):
        target = frappe._dict(project="PROJECT-B")
        map_quotation_project(target, "after_mapping", frappe._dict(doctype="Customer", custom_project="PROJECT-A"))
        self.assertEqual(target.project, "PROJECT-B")
