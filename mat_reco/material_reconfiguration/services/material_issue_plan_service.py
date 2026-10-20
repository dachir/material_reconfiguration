# Copyright (c) 2026, Richard Amouzou and contributors
# For license information, please see license.txt

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint, flt


def _issue_tag(plan_name: str) -> str:
    return f"[Material Issue Plan: {plan_name}]"


def _selected_rows(doc):
    return [
        row
        for row in (doc.get("material_issue_candidate") or [])
        if cint(row.is_qualified) and (row.serial_no or "").strip()
    ]


def _ensure_no_duplicate_issue(doc):
    existing = frappe.get_all(
        "Stock Entry",
        filters={
            "docstatus": ["!=", 2],
            "remarks": ["like", f"%{_issue_tag(doc.name)}%"],
        },
        fields=["name", "docstatus"],
        limit_page_length=5,
    )

    if existing:
        names = ", ".join(d.name for d in existing)
        frappe.throw(
            _("A Material Issue already exists for this plan: {0}").format(names)
        )


def _validate_plan_for_issue(doc):
    if doc.docstatus != 1:
        frappe.throw(_("Material Issue Plan must be submitted before creating Material Issue."))

    if not (doc.company or "").strip():
        frappe.throw(_("Company is required."))

    if not (doc.source_warehouse or "").strip():
        frappe.throw(_("Source Warehouse is required."))

    if not (doc.source_item or "").strip():
        frappe.throw(_("Source Item is required."))

    if not (doc.issue_reason or "").strip():
        frappe.throw(_("Reason is required."))

    rows = _selected_rows(doc)
    if not rows:
        frappe.throw(_("Please select at least one Serial No to issue."))

    for row in rows:
        serial_no = (row.serial_no or "").strip()
        serial_doc = frappe.db.get_value(
            "Serial No",
            serial_no,
            ["name", "item_code", "warehouse", "status"],
            as_dict=True,
        )

        if not serial_doc:
            frappe.throw(_("Serial No {0} does not exist anymore.").format(serial_no))

        if (serial_doc.item_code or "").strip() != (row.item_code or "").strip():
            frappe.throw(
                _("Serial No {0} item mismatch. Expected {1}, found {2}.").format(
                    serial_no, row.item_code, serial_doc.item_code
                )
            )

        if (serial_doc.warehouse or "").strip() != (doc.source_warehouse or "").strip():
            frappe.throw(
                _("Serial No {0} is no longer in warehouse {1}. Current warehouse: {2}.").format(
                    serial_no, doc.source_warehouse, serial_doc.warehouse
                )
            )

    _ensure_no_duplicate_issue(doc)


def _apply_optional_dimension_fields(se_row, candidate_row):
    optional_map = {
        "custom_dimension_length_mm": flt(candidate_row.length_mm),
        "custom_dimension_width_mm": flt(candidate_row.width_mm),
        "custom_dimension_thickness_mm": flt(candidate_row.thickness_mm),
        "custom_surface_mm2": flt(candidate_row.length_mm) * flt(candidate_row.width_mm),
    }

    for fieldname, value in optional_map.items():
        if hasattr(se_row, fieldname):
            setattr(se_row, fieldname, value)


def create_material_issue_from_plan(doc):
    _validate_plan_for_issue(doc)

    selected_rows = _selected_rows(doc)
    remarks = (
        f"{_issue_tag(doc.name)}\n"
        f"Reason: {doc.issue_reason}"
    )

    se = frappe.new_doc("Stock Entry")
    se.stock_entry_type = "Material Issue"
    se.company = doc.company
    se.posting_date = doc.posting_date
    se.remarks = remarks

    for row in selected_rows:
        se_row = se.append("items", {})
        se_row.item_code = row.item_code
        se_row.s_warehouse = doc.source_warehouse
        se_row.qty = 1
        se_row.serial_no = row.serial_no

        _apply_optional_dimension_fields(se_row, row)

    if not se.items:
        frappe.throw(_("No Stock Entry rows were generated."))

    se.insert(ignore_permissions=True)
    se.submit()

    return se.name


def cancel_material_issues_for_plan(doc):
    issue_docs = frappe.get_all(
        "Stock Entry",
        filters={
            "remarks": ["like", f"%{_issue_tag(doc.name)}%"],
            "docstatus": ["!=", 2],
        },
        fields=["name", "docstatus"],
        limit_page_length=100,
    )

    for d in issue_docs:
        se = frappe.get_doc("Stock Entry", d.name)
        if se.docstatus == 1:
            se.cancel()