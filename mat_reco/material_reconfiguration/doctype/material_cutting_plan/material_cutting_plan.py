# Copyright (c) 2026, Richard Amouzou and contributors
# For license information, please see license.txt

from __future__ import annotations

import json

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint

from mat_reco.material_reconfiguration.doctype.item_variant_detail.item_variant_detail import (
    validate_variant_item_code,
)
from mat_reco.material_reconfiguration.doctype.material_cutting_plan.mcp_sheet_sync import (
    sync_mcp_sheets,
)
from mat_reco.material_reconfiguration.services.mcp_incident_service import (
    apply_incidents_to_nodes,
    build_incident_map,
)
from mat_reco.material_reconfiguration.services.cutting_plan_service import (
    generate_material_cutting_plan,
    generate_return_terrain_cutting_plan,
    update_active_input_flags,
)
from mat_reco.material_reconfiguration.services.order_explosion_service import (
    explode_sales_orders_into_cutting_demands,
)
from mat_reco.material_reconfiguration.services.stock_candidate_service import (
    get_available_cutting_bins,
)

MCP_MODE_PLANIFICATION = "Planification"
MCP_MODE_RETOUR_TERRAIN = "Retour Terrain"


class MaterialCuttingPlan(Document):
    """Material Cutting Plan aggregates multiple Sales Orders and generates an
    optimized cutting plan using available stock bins. This DocType stores
    the resulting tree and summary in JSON form and tracks piece counts and
    bins used. The status field transitions to 'Simulated' when at least one
    piece is planned.
    """

    def before_save(self):
        self._validate_source_item()
        self._validate_variant_rows()

        if not self.selected_sales_orders:
            self._clear_plan_results()
            return

        sales_orders = [
            row.sales_order
            for row in (self.selected_sales_orders or [])
            if row.sales_order
        ]
        if not sales_orders:
            self._clear_plan_results()
            return

        selected_serials = self._get_selected_input_serial_nos()
        if not selected_serials:
            frappe.throw(self._get_missing_input_message())

        demands = explode_sales_orders_into_cutting_demands(
            sales_order_names=sales_orders,
            source_item=self.source_item,
            max_depth=int(self.max_depth or 10),
        )

        variant_item_codes = [
            row.variant_item_code
            for row in (self.get("item_variant_detail") or [])
            if row.variant_item_code
        ]

        bins = get_available_cutting_bins(
            item_code=self.source_item,
            warehouse=self.source_warehouse,
            variant_item_codes=variant_item_codes,
            serial_nos=selected_serials,
        )

        mode = self._get_mcp_mode()

        existing_tree = {}
        try:
            if mode == MCP_MODE_RETOUR_TERRAIN:
                existing_tree = (
                    json.loads(self.effective_result_json)
                    if self.effective_result_json
                    else (json.loads(self.result_json) if self.result_json else {})
                )
            else:
                existing_tree = json.loads(self.result_json) if self.result_json else {}
        except Exception:
            existing_tree = {}

        if mode == MCP_MODE_RETOUR_TERRAIN and existing_tree:
            result = generate_return_terrain_cutting_plan(
                plan_name=self.name or "NEW-MCP",
                demands=demands,
                bins=bins,
                existing_tree=existing_tree,
                mcp_doc=self,
                kerf_mm=float(self.kerf_mm or 0),
                allow_rotation=bool(self.allow_rotation),
                packing_algorithm=self.packing_algorithm or "maxrects",
                packing_heuristic=self.packing_heuristic or "best_area_fit",
            )

            # En Retour Terrain, on ne touche pas au result_json de simulation.
            # La base vivante devient effective_result_json.
            self.effective_result_json = json.dumps(
                result["tree"], ensure_ascii=False, indent=2
            )

            sync_mcp_sheets(
                self,
                source_json_field="effective_result_json",
                child_table_field="effective_mcp_sheets",
            )

            effective_tree = self._safe_json_load(self.effective_result_json)
            effective_tree = effective_tree.get("tree") or effective_tree

            effective_summary = self._build_summary_from_tree(effective_tree)
            self._apply_summary_to_fields(effective_summary)

        else:
            result = generate_material_cutting_plan(
                plan_name=self.name or "NEW-MCP",
                demands=demands,
                bins=bins,
                kerf_mm=float(self.kerf_mm or 0),
                allow_rotation=bool(self.allow_rotation),
                packing_algorithm=self.packing_algorithm or "maxrects",
                packing_heuristic=self.packing_heuristic or "best_area_fit",
            )

            self.result_json = json.dumps(result["tree"], ensure_ascii=False, indent=2)

            # Mark only the serials actually used by the generated plan
            update_active_input_flags(self, result["tree"])

            self._build_simulation_lines(demands=demands, result=result)

            sync_mcp_sheets(
                self,
                source_json_field="result_json",
                child_table_field="mcp_sheets",
            )

            self.effective_result_json = self.result_json

            sync_mcp_sheets(
                self,
                source_json_field="effective_result_json",
                child_table_field="effective_mcp_sheets",
            )

            self._apply_summary_to_fields(result["summary"] or {})

        if cint(self.planned_piece_count) > 0:
            self.status = "Simulated"

    def before_submit(self):
        pass

    def _materialize_effective_plan(self, source_json_field="result_json"):
        raw_tree = self._safe_json_load(self.get(source_json_field))
        if not raw_tree:
            self.effective_result_json = None
            try:
                self.set("effective_mcp_sheets", [])
            except Exception:
                pass
            return {}

        tree = raw_tree.get("tree") or raw_tree
        nodes = tree.get("nodes") or []

        if nodes:
            incident_map = build_incident_map(self)
            effective_nodes = (
                apply_incidents_to_nodes(nodes, incident_map)
                if incident_map
                else nodes
            )
            effective_tree = dict(tree)
            effective_tree["nodes"] = effective_nodes
        else:
            effective_tree = tree

        self.effective_result_json = json.dumps(
            effective_tree, ensure_ascii=False, indent=2
        )

        sync_mcp_sheets(
            self,
            source_json_field="effective_result_json",
            child_table_field="effective_mcp_sheets",
        )

        return effective_tree

    def _build_summary_from_tree(self, tree: dict) -> dict:
        tree = tree or {}
        nodes = tree.get("nodes") or []

        requested_piece_count = 0
        planned_piece_count = 0
        used_input_serial_count = 0
        total_required_area_mm2 = 0.0
        total_used_input_area_mm2 = 0.0
        total_leftover_area_mm2 = 0.0
        total_waste_area_mm2 = 0.0

        try:
            for row in (self.get("simulation_lines") or []):
                qty_required = float(row.qty_required or 0)
                length_mm = float(row.length_mm or 0)
                width_mm = float(row.width_mm or 0)

                requested_piece_count += int(qty_required)
                total_required_area_mm2 += qty_required * length_mm * width_mm
        except Exception:
            pass

        leftover_count = 0
        waste_count = 0

        for node in nodes:
            node_type = (node.get("node_type") or "").strip()

            if node_type == "input_serial":
                used_input_serial_count += 1
                total_used_input_area_mm2 += (
                    float(node.get("length_mm") or node.get("length") or 0)
                    * float(node.get("width_mm") or node.get("width") or 0)
                )

            for child in (node.get("children") or []):
                child_type = (child.get("node_type") or "").strip()
                child_area = (
                    float(child.get("length_mm") or child.get("length") or 0)
                    * float(child.get("width_mm") or child.get("width") or 0)
                )

                if child_type == "finished_good":
                    planned_piece_count += 1
                elif child_type == "leftover":
                    leftover_count += 1
                    total_leftover_area_mm2 += child_area
                elif child_type in ("waste", "destroyed"):
                    waste_count += 1
                    total_waste_area_mm2 += child_area

        missing_piece_count = max(0, requested_piece_count - planned_piece_count)

        return {
            "requested_piece_count": requested_piece_count,
            "planned_piece_count": planned_piece_count,
            "missing_piece_count": missing_piece_count,
            "used_input_serial_count": used_input_serial_count,
            "leftover_count": leftover_count,
            "waste_count": waste_count,
            "total_required_area_m2": total_required_area_mm2 / 1_000_000,
            "total_used_input_area_m2": total_used_input_area_mm2 / 1_000_000,
            "total_leftover_area_m2": total_leftover_area_mm2 / 1_000_000,
            "total_waste_area_m2": total_waste_area_mm2 / 1_000_000,
        }

    def _apply_summary_to_fields(self, summary: dict):
        summary = summary or {}

        self.summary_json = json.dumps(summary, ensure_ascii=False, indent=2)
        self.requested_piece_count = summary.get("requested_piece_count", 0)
        self.planned_piece_count = summary.get("planned_piece_count", 0)
        self.missing_piece_count = summary.get("missing_piece_count", 0)
        self.used_input_serial_count = summary.get("used_input_serial_count", 0)
        self.total_required_area_m2 = summary.get("total_required_area_m2", 0)
        self.total_used_input_area_m2 = summary.get("total_used_input_area_m2", 0)
        self.total_leftover_area_m2 = summary.get("total_leftover_area_m2", 0)
        self.total_waste_area_m2 = summary.get("total_waste_area_m2", 0)

    @staticmethod
    def _safe_json_load(value):
        if not value:
            return {}
        if isinstance(value, dict):
            return value
        try:
            return json.loads(value)
        except Exception:
            return {}

    def _validate_source_item(self):
        source_item = (self.source_item or "").strip()
        if not source_item:
            return

        source_type = (
            frappe.db.get_value("Item", source_item, "custom_item_types") or ""
        ).strip()
        if source_type != "PRIMAIRE":
            frappe.throw(_("Source Item must be of type PRIMAIRE."))

    def _validate_variant_rows(self):
        seen = set()
        cleaned_rows = []

        for row in (self.get("item_variant_detail") or []):
            code = validate_variant_item_code(
                row.variant_item_code, source_item=self.source_item
            )
            if not code or code in seen:
                continue
            seen.add(code)
            row.variant_item_code = code
            cleaned_rows.append(row)

        self.set("item_variant_detail", [])
        for row in cleaned_rows:
            self.append(
                "item_variant_detail", {"variant_item_code": row.variant_item_code}
            )

    def _get_mcp_mode(self) -> str:
        mode = (self.get("mcp_mode") or MCP_MODE_PLANIFICATION).strip()
        if mode not in (MCP_MODE_PLANIFICATION, MCP_MODE_RETOUR_TERRAIN):
            return MCP_MODE_PLANIFICATION
        return mode

    def _get_qualified_serial_nos(self) -> list[str]:
        seen = set()
        serials = []
        for row in (self.get("mcp_stock_candidate") or []):
            serial_no = (row.serial_no or "").strip()
            if not serial_no or not cint(row.is_qualified):
                continue
            if serial_no in seen:
                continue
            seen.add(serial_no)
            serials.append(serial_no)
        return serials

    def _get_active_input_serial_nos(self) -> list[str]:
        seen = set()
        serials = []
        for row in (self.get("mcp_stock_candidate") or []):
            serial_no = (row.serial_no or "").strip()
            if not serial_no or not cint(row.is_active_input):
                continue
            if serial_no in seen:
                continue
            seen.add(serial_no)
            serials.append(serial_no)
        return serials

    def _get_selected_input_serial_nos(self) -> list[str]:
        if self._get_mcp_mode() == MCP_MODE_RETOUR_TERRAIN:
            return self._get_active_input_serial_nos()
        return self._get_qualified_serial_nos()

    def _get_missing_input_message(self) -> str:
        if self._get_mcp_mode() == MCP_MODE_RETOUR_TERRAIN:
            return _(
                "Please keep at least one active input Serial No before saving in Retour Terrain mode."
            )
        return _(
            "Please click Get Stock and keep at least one qualified Serial No before saving."
        )

    def _clear_plan_results(self):
        self.result_json = None
        self.summary_json = None
        self.requested_piece_count = 0
        self.planned_piece_count = 0
        self.missing_piece_count = 0
        self.used_input_serial_count = 0
        self.total_required_area_m2 = 0
        self.total_used_input_area_m2 = 0
        self.total_leftover_area_m2 = 0
        self.total_waste_area_m2 = 0

        try:
            self.set("simulation_lines", [])
        except Exception:
            pass

        try:
            self.set("mcp_sheets", [])
        except Exception:
            pass

        self.effective_result_json = None

        try:
            self.set("effective_mcp_sheets", [])
        except Exception:
            pass

        for row in (self.get("mcp_stock_candidate") or []):
            row.is_active_input = 0

    def _build_simulation_lines(self, *, demands, result):
        try:
            self.set("simulation_lines", [])
        except Exception:
            return

        demand_map = {d["piece_uid"]: d for d in demands}
        planned_piece_uids = []

        try:
            for node in result["tree"].get("nodes", []):
                for child in node.get("children", []):
                    if child.get("node_type") == "finished_good":
                        planned_piece_uids.append(child.get("piece_uid"))
        except Exception:
            planned_piece_uids = []

        aggregated = {}
        for d in demands:
            key = (
                d.get("piece_item_code"),
                d.get("length_mm"),
                d.get("width_mm"),
                d.get("thickness_mm"),
            )
            entry = aggregated.setdefault(key, {"qty_required": 0, "qty_planned": 0})
            entry["qty_required"] += 1

        for uid in planned_piece_uids:
            d = demand_map.get(uid)
            if not d:
                continue
            key = (
                d.get("piece_item_code"),
                d.get("length_mm"),
                d.get("width_mm"),
                d.get("thickness_mm"),
            )
            entry = aggregated.setdefault(key, {"qty_required": 0, "qty_planned": 0})
            entry["qty_planned"] += 1

        for key, data in aggregated.items():
            comp_item, l, w, t = key
            qty_req = data.get("qty_required", 0)
            qty_plan = data.get("qty_planned", 0)
            qty_avail = qty_plan
            pending = max(0, qty_req - qty_plan)

            try:
                self.append(
                    "simulation_lines",
                    {
                        "component_item": comp_item,
                        "length_mm": l,
                        "width_mm": w,
                        "thickness_mm": t,
                        "qty_required": qty_req,
                        "qty_planned": qty_plan,
                        "qty_available": qty_avail,
                        "pending_qty": pending,
                    },
                )
            except Exception:
                continue

