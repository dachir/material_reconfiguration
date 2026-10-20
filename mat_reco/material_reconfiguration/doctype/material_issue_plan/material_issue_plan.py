# Copyright (c) 2026, Richard Amouzou and contributors
# For license information, please see license.txt

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt

from mat_reco.material_reconfiguration.services.stock_candidate_service import (
    get_available_cutting_bins,
)
from mat_reco.material_reconfiguration.services.material_issue_plan_service import (
    create_material_issue_from_plan,
    cancel_material_issues_for_plan,
)


class MaterialIssuePlan(Document):
    """Simple stock issue planner for PRIMAIRE items.

    Architecture kept intentionally close to Material Cutting Plan:
    - controller stays light
    - stock loading happens on save
    - stock issue generation/cancellation is delegated to a service
    """

    def before_save(self):
        self._validate_source_item()
        self._load_issue_candidates()
        self._update_totals()

        if not self.status:
            self.status = "Draft"

    def on_submit(self):
        create_material_issue_from_plan(self)
        self.status = "Issued"

    def on_cancel(self):
        cancel_material_issues_for_plan(self)
        self.status = "Cancelled"

    def _validate_source_item(self):
        source_item = (self.source_item or "").strip()
        if not source_item:
            return

        source_type = (
            frappe.db.get_value("Item", source_item, "custom_item_types") or ""
        ).strip()

        if source_type != "PRIMAIRE":
            frappe.throw(_("Source Item must be of type PRIMAIRE."))

    def _load_issue_candidates(self):
        source_item = (self.source_item or "").strip()
        source_warehouse = (self.source_warehouse or "").strip()

        if not source_item or not source_warehouse:
            try:
                self.set("material_issue_candidate", [])
            except Exception:
                pass
            return

        previously_selected = set()
        previous_remarks = {}

        for row in (self.get("material_issue_candidate") or []):
            serial_no = (row.serial_no or "").strip()
            if not serial_no:
                continue
            if cint(row.is_qualified):
                previously_selected.add(serial_no)
            if row.remarks:
                previous_remarks[serial_no] = row.remarks

        bins = get_available_cutting_bins(
            item_code=source_item,
            warehouse=source_warehouse,
            variant_item_codes=None,
            serial_nos=None,
        )

        try:
            self.set("material_issue_candidate", [])
        except Exception:
            pass

        for b in bins:
            serial_no = (b.get("serial_no") or "").strip()
            if not serial_no:
                continue

            self.append(
                "material_issue_candidate",
                {
                    "serial_no": serial_no,
                    "item_code": b.get("item_code"),
                    "warehouse": b.get("warehouse"),
                    "material_status": b.get("material_status"),
                    "length_mm": flt(b.get("length_mm")),
                    "width_mm": flt(b.get("width_mm")),
                    "thickness_mm": flt(b.get("thickness_mm")),
                    "remarks": previous_remarks.get(serial_no) or "",
                    "is_qualified": 1 if serial_no in previously_selected else 0,
                },
            )

    def _update_totals(self):
        total_serials = 0
        total_area_mm2 = 0.0

        for row in (self.get("material_issue_candidate") or []):
            if not cint(row.is_qualified):
                continue

            total_serials += 1
            total_area_mm2 += flt(row.length_mm) * flt(row.width_mm)

        self.total_selected_serials = total_serials
        self.total_selected_area_m2 = total_area_mm2 / 1_000_000.0