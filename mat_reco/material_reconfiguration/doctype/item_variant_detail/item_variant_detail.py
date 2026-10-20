# Copyright (c) 2026, Richard Amouzou and contributors
# For license information, please see license.txt

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document


ALLOWED_VARIANT_ITEM_TYPE = "PRIMAIRE"


def validate_variant_item_code(variant_item_code: str | None, *, source_item: str | None = None) -> str:
    """Validate that a variant item exists and is of type PRIMAIRE."""
    code = (variant_item_code or "").strip()
    if not code:
        return ""

    item_type = (frappe.db.get_value("Item", code, "custom_item_types") or "").strip()
    if item_type != ALLOWED_VARIANT_ITEM_TYPE:
        frappe.throw(
            _("Item {0} must be of type {1} to be used as a variant.").format(
                frappe.bold(code), frappe.bold(ALLOWED_VARIANT_ITEM_TYPE)
            )
        )

    if source_item and code == source_item:
        frappe.throw(_("Variant item {0} cannot be the same as the Source Item.").format(frappe.bold(code)))

    return code


class ItemVariantDetail(Document):
    def validate(self):
        validate_variant_item_code(self.variant_item_code)
