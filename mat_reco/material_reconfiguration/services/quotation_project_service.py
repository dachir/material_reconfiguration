"""Carry the quotation chantier through the standard ERPNext mapper."""

import frappe
from frappe import _


def map_quotation_project(doc, method, source_doc):
    """Keep ERPNext mapping intact and reject mixed chantier destinations."""
    if source_doc.doctype != "Quotation":
        return

    project = source_doc.get("custom_project")
    if not project:
        return

    if doc.get("project") and doc.project != project:
        frappe.throw(
            _("Quotation {0} belongs to project {1}, but the Sales Order belongs to project {2}.").format(
                source_doc.name, project, doc.project
            )
        )

    doc.project = project
