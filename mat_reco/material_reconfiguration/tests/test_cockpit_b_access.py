"""Cockpit visibility must not grant access to commercial documents."""
import unittest
from unittest.mock import patch

import frappe
from mat_reco.material_reconfiguration.services import order_b, workshop_service


class CockpitBAccessTests(unittest.TestCase):
    def test_preview_scopes_order_read_and_restores_after_failure(self):
        def fresh(*args, **kwargs):
            self.assertTrue(order_b.can_read_cockpit('operator'))
            self.assertIsNone(order_b.has_permission(frappe._dict(custom_ug_order_type='B'),'operator','read'))
            raise RuntimeError('stop before planning')

        with patch.object(frappe,'get_roles',return_value=[order_b.COCKPIT_ROLE]), \
             patch.object(workshop_service,'_fresh_request',side_effect=fresh):
            with self.assertRaisesRegex(RuntimeError,'stop before planning'):
                workshop_service.preview_action('B-ORDER','NODE',1)
        self.assertFalse(frappe.flags.get('ug_cockpit_b_read'))

    def test_execute_keeps_native_operation_permission_and_restores_scope(self):
        def permission(doctype, action):
            self.assertEqual((doctype,action),('Workshop Operation','read'))
            self.assertTrue(order_b.can_read_cockpit('operator'))
            self.assertFalse(order_b.has_permission(frappe._dict(custom_ug_order_type='B'),'operator','write'))
            raise frappe.PermissionError('operation denied')

        with patch.object(frappe,'get_roles',return_value=[order_b.COCKPIT_ROLE]), \
             patch.object(workshop_service,'_permission',side_effect=permission):
            with self.assertRaises(frappe.PermissionError):
                workshop_service.execute_action('B-ORDER','NODE',1,'key','version')
        self.assertFalse(frappe.flags.get('ug_cockpit_b_read'))

    def test_scoped_read_excludes_form_and_writes(self):
        doc=frappe._dict(custom_ug_order_type='B')
        with patch.object(frappe,'get_roles',return_value=[order_b.COCKPIT_ROLE]):
            self.assertTrue(order_b.query_conditions('operator'))
            self.assertFalse(order_b.has_permission(doc,'operator','read'))
            with order_b.cockpit_read():
                self.assertEqual(order_b.query_conditions('operator'),'')
                self.assertIsNone(order_b.has_permission(doc,'operator','read'))
                for action in ('write','submit','cancel','delete'):
                    self.assertFalse(order_b.has_permission(doc,'operator',action))
                self.assertTrue(order_b.study_query_conditions('operator'))
            self.assertFalse(order_b.has_permission(doc,'operator','read'))

    def test_scope_requires_role_and_restores_after_exception(self):
        with patch.object(frappe,'get_roles',return_value=[]):
            with self.assertRaisesRegex(RuntimeError,'stop'):
                with order_b.cockpit_read():
                    self.assertTrue(order_b.query_conditions('operator'))
                    raise RuntimeError('stop')
            self.assertFalse(frappe.flags.get('ug_cockpit_b_read'))

    def test_nested_scope_restores_parent(self):
        with order_b.cockpit_read():
            with order_b.cockpit_read():
                self.assertTrue(frappe.flags.ug_cockpit_b_read)
            self.assertTrue(frappe.flags.ug_cockpit_b_read)
        self.assertFalse(frappe.flags.get('ug_cockpit_b_read'))
