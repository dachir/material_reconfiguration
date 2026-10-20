from __future__ import annotations

import frappe

from erpnext.accounts.doctype.accounting_dimension.accounting_dimension import (
    create_accounting_dimensions_for_doctype,
)


def sync_material_receipt_plan_accounting_dimensions():
    """Create active ERPNext Accounting Dimension fields on Material Receipt Plan.

    ERPNext normally creates dimension fields when an Accounting Dimension is
    created/updated. This after-migrate sync also covers dimensions that existed
    before Material Receipt Plan was introduced.
    """
    if not frappe.db.exists("DocType", "Material Receipt Plan"):
        return

    create_accounting_dimensions_for_doctype("Material Receipt Plan")
    frappe.clear_cache(doctype="Material Receipt Plan")
