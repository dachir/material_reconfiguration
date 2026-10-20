import frappe
from frappe.model.document import Document


def validate_rows(rows):
    if not rows:
        frappe.throw('Le modèle doit contenir au moins une section.')
    for i, row in enumerate(rows, 1):
        parent = row.get('parent_row') or 0
        if not row.get('section_name') or int(parent) != float(parent) or not 0 <= int(parent) < i:
            frappe.throw('Chaque section doit avoir un nom et une ligne parente précédente (ou 0).')
        if parent and not rows[int(parent) - 1].get('is_group'):
            frappe.throw('Une section parente doit autoriser les sous-sections.')


class ChantierSectionTemplate(Document):
    def validate(self):
        validate_rows(self.sections)
