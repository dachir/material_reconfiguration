"""Immutable technical trace of a commercial cockpit request."""
import frappe
from frappe.model.document import Document


class CommercialOperation(Document):
    def validate(self):
        if not frappe.flags.get("in_commercial_operation") or not self.is_new():
            frappe.throw("Ce journal immuable est créé uniquement par le cockpit commercial.")

    def on_trash(self):
        frappe.throw("Le journal des opérations commerciales doit être conservé.")
