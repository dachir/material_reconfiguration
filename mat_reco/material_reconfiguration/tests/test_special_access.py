"""Special-module access grants both circuits; native roles keep native workflows."""

import json
import unittest
import uuid
from contextlib import contextmanager
from pathlib import Path

import frappe
from frappe.client import get as get_document

from mat_reco.material_reconfiguration.services import order_b
from mat_reco.material_reconfiguration.services import special_b as special
from mat_reco.material_reconfiguration.tests import test_order_b_stock as fixtures


class SpecialAccessTests(unittest.TestCase):
    cleanup = fixtures.OrderBStockTests.cleanup
    new_order = fixtures.OrderBStockTests.new_order
    remove_files = fixtures.OrderBStockTests.remove_files

    def setUp(self):
        # The existing fixture owns the savepoint and rolls all business data back.
        fixtures.OrderBStockTests.setUp(self)
        self.orders = {"B": self.order, "A": self.new_order("A")}
        self.users = []
        self.addCleanup(self.clear_user_caches)
        mode = frappe.db.get_value("Mode of Payment", {}, "name")
        if not mode:
            mode = frappe.get_doc(dict(
                doctype="Mode of Payment",
                mode_of_payment="QA Special Access " + uuid.uuid4().hex[:8],
                type="Cash",
            )).insert().name
        self.documents = {special.DELIVERY: {}, special.PAYMENT: {}}
        for kind, order in self.orders.items():
            delivery = frappe.get_doc(special.make_delivery(order.name)).insert()
            payment = frappe.get_doc(special.make_payment(sales_order=order.name))
            payment.update(dict(mode_of_payment=mode, reference=uuid.uuid4().hex, amount=100))
            payment.insert()
            self.documents[special.DELIVERY][kind] = delivery
            self.documents[special.PAYMENT][kind] = payment

    def clear_user_caches(self):
        for name in self.users:
            frappe.clear_cache(user=name)

    def make_user(self, roles):
        user = frappe.get_doc(dict(
            doctype="User",
            email="qa-special-access-" + uuid.uuid4().hex[:12] + "@example.invalid",
            first_name="QA Special Access",
            enabled=1,
            user_type="System User",
            send_welcome_email=0,
            roles=[dict(role=role) for role in roles],
        )).insert()
        self.users.append(user.name)
        frappe.clear_cache(user=user.name)
        return user.name

    @contextmanager
    def as_user(self, name):
        previous = frappe.session.user
        frappe.set_user(name)
        try:
            yield
        finally:
            frappe.set_user(previous)
            frappe.clear_messages()

    def test_special_module_users_can_read_and_prepare_both_circuits(self):
        # System Manager deliberately has access to these modules even without
        # the dedicated B role; its explicit module permission must also admit B.
        for module_role in (order_b.ROLE, "System Manager"):
            with self.subTest(module_role=module_role):
                user = self.make_user([module_role, "Sales User", "Stock User", "Accounts User"])
                with self.as_user(user):
                    self.assertTrue(order_b.can_access())
                    for doctype, documents in self.documents.items():
                        self.assertTrue(frappe.has_permission(doctype, "read"))
                        self.assertTrue(frappe.has_permission(doctype, "create"))
                        names = {doc.name for doc in documents.values()}
                        listed = set(frappe.get_list(doctype, filters={"name": ["in", list(names)]}, pluck="name"))
                        self.assertEqual(listed, names)
                        for kind, doc in documents.items():
                            self.assertTrue(frappe.has_permission(doc=doc, ptype="read"))
                            self.assertEqual(get_document(doctype, doc.name)["order_type"], kind)
                    for kind, order in self.orders.items():
                        self.assertTrue(frappe.has_permission(doc=order, ptype="read"))
                        self.assertEqual(special.make_delivery(order.name)["order_type"], kind)
                        self.assertEqual(special.make_payment(sales_order=order.name)["order_type"], kind)

    def test_standard_roles_cannot_open_special_documents_but_keep_native_access(self):
        for role, native in (("Sales User", "Sales Order"),
                             ("Stock User", "Delivery Note"),
                             ("Accounts User", "Payment Entry")):
            with self.subTest(role=role):
                user = self.make_user([role])
                with self.as_user(user):
                    self.assertFalse(order_b.can_access())
                    self.assertTrue(frappe.has_permission(native, "read"))
                    self.assertTrue(frappe.has_permission(native, "create"))
                    for doctype, documents in self.documents.items():
                        for action in ("read", "create", "write", "submit", "cancel"):
                            self.assertFalse(frappe.has_permission(doctype, action))
                        with self.assertRaises(frappe.PermissionError):
                            frappe.get_list(doctype, filters={"name": ["in", [doc.name for doc in documents.values()]]})
                        for doc in documents.values():
                            self.assertFalse(frappe.has_permission(doc=doc, ptype="read"))
                            with self.assertRaises(frappe.PermissionError):
                                get_document(doctype, doc.name)
                    for order in self.orders.values():
                        with self.assertRaises(frappe.PermissionError):
                            special.make_delivery(order.name)
                        with self.assertRaises(frappe.PermissionError):
                            special.make_payment(sales_order=order.name)

    def test_standard_sales_user_retains_a_orders_and_cannot_read_b_orders(self):
        user = self.make_user(["Sales User", "Stock User", "Accounts User"])
        with self.as_user(user):
            self.assertTrue(frappe.has_permission(doc=self.orders["A"], ptype="read"))
            self.assertFalse(frappe.has_permission(doc=self.orders["B"], ptype="read"))
            names = set(frappe.get_list("Sales Order", filters={
                "name": ["in", [order.name for order in self.orders.values()]],
            }, pluck="name"))
            self.assertEqual(names, {self.orders["A"].name})
            for doctype in (special.DELIVERY, special.PAYMENT):
                self.assertFalse(frappe.has_permission(doctype, "read"))


class SpecialAccessMetadataTests(unittest.TestCase):
    def test_special_modules_do_not_grant_permissions_to_standard_roles(self):
        for slug in ("bordereau_special", "reglement_special"):
            with self.subTest(doctype=slug):
                path = Path(frappe.get_app_path("mat_reco", "material_reconfiguration", "doctype", slug, slug + ".json"))
                meta = json.loads(path.read_text())
                self.assertEqual({row["role"] for row in meta["permissions"]}, {order_b.ROLE, "System Manager"})
                routing = next(field for field in meta["fields"] if field["fieldname"] == "order_type")
                self.assertTrue(routing["hidden"])
                self.assertTrue(routing["read_only"])

