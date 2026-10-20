import frappe
from frappe.utils import flt


def validate(doc, method=None):
    requires_map = {}

    for row in doc.items:
        if not row.item_code:
            continue

        if row.item_code not in requires_map:
            requires_map[row.item_code] = frappe.db.get_value(
                "Item", row.item_code, "custom_requires_dimensions"
            ) or 0

        if requires_map[row.item_code]:
            if not (
                flt(row.custom_client_length_mm) > 0
                and flt(row.custom_client_width_mm) > 0
            ):
                frappe.throw(
                    f"Dimensions required for item {row.item_code} (row {row.idx})."
                )