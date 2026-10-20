import frappe
from frappe.model.document import Document


class WorkshopOperation(Document):
    def validate(self):
        if not frappe.flags.in_workshop_operation:
            frappe.throw('Ce journal est créé uniquement par le cockpit atelier.')

    def on_trash(self):
        frappe.throw('Le journal des opérations atelier doit être conservé.')
