# Copyright (c) 2026, Richard Amouzou and contributors
# For license information, please see license.txt

import json
import frappe
from frappe import _
from frappe.model.document import Document

from mat_reco.material_reconfiguration.services.order_explosion_service import (
    explode_sales_orders_into_cutting_demands,
)
from mat_reco.material_reconfiguration.services.stock_candidate_service import (
    get_available_cutting_bins,
)
from mat_reco.material_reconfiguration.services.cutting_plan_service import (
    generate_material_cutting_plan,
)

class MaterialCuttingPlan(Document):
    """Material Cutting Plan aggregates multiple Sales Orders and generates an
    optimized cutting plan using available stock bins. This DocType stores
    the resulting tree and summary in JSON form and tracks piece counts and
    bins used. The status field transitions to 'Simulated' when at least one
    piece is planned.
    """

    def before_save(self):
        # Clear results if no orders are selected
        if not self.selected_sales_orders:
            self.result_json = None
            self.summary_json = None
            return

        # Collect the selected Sales Order names
        sales_orders = [
            row.sales_order
            for row in self.selected_sales_orders
            if row.sales_order
        ]
        if not sales_orders:
            self.result_json = None
            self.summary_json = None
            return

        # Explode selected orders into individual cutting demands
        demands = explode_sales_orders_into_cutting_demands(
            sales_order_names=sales_orders,
            max_depth=int(self.max_depth or 10),
        )

        # Load available bins (full sheets or leftovers)
        bins = get_available_cutting_bins(
            item_code=self.source_item,
            warehouse=self.source_warehouse,
        )

        # Generate a material cutting plan.  We always use the rectpack engine
        # internally, so only algorithm and heuristic options are passed.
        result = generate_material_cutting_plan(
            plan_name=self.name or "NEW-MCP",
            demands=demands,
            bins=bins,
            kerf_mm=float(self.kerf_mm or 0),
            allow_rotation=bool(self.allow_rotation),
            packing_algorithm=self.packing_algorithm or "maxrects",
            packing_heuristic=self.packing_heuristic or "best_area_fit",
        )

        # Store JSON results in text fields
        self.result_json = json.dumps(result["tree"], ensure_ascii=False, indent=2)
        self.summary_json = json.dumps(result["summary"], ensure_ascii=False, indent=2)

        summary = result["summary"]
        # Update count fields
        self.requested_piece_count = summary.get("requested_piece_count", 0)
        self.planned_piece_count = summary.get("planned_piece_count", 0)
        self.missing_piece_count = summary.get("missing_piece_count", 0)
        self.used_input_serial_count = summary.get("used_input_serial_count", 0)

        self.total_required_area_m2 = summary.get("total_required_area_m2", 0)
        self.total_used_input_area_m2 = summary.get("total_used_input_area_m2", 0)
        self.total_leftover_area_m2 = summary.get("total_leftover_area_m2", 0)
        self.total_waste_area_m2 = summary.get("total_waste_area_m2", 0)

        # Automatically set the status to Simulated when pieces are planned
        if self.planned_piece_count > 0:
            self.status = "Simulated"

        # ------------------------------------------------------------------
        # Build simulation_lines entries summarising the cutting requirements
        # per component/dimension/thickness.  This table is used to
        # communicate the number of pieces required, planned and available
        # for each unique cutting demand.  It assumes that a child table
        # field named ``simulation_lines`` exists on this DocType and
        # references the ``Material Cutting Plan Detail`` DocType.
        # Clear any existing rows before appending new ones.
        try:
            # Remove existing rows
            self.set("simulation_lines", [])
        except Exception:
            # If the field does not exist, silently ignore
            pass

        # Build maps of demands and determine which piece_uids were planned
        demand_map = {d["piece_uid"]: d for d in demands}
        planned_piece_uids = []
        try:
            for node in result["tree"].get("nodes", []):
                for child in node.get("children", []):
                    if child.get("node_type") == "finished_good":
                        planned_piece_uids.append(child.get("piece_uid"))
        except Exception:
            # Tree format might be unavailable; skip summary lines
            planned_piece_uids = []

        # Aggregate required and planned quantities by item/dimensions/thickness
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

        # Populate the simulation_lines child table with aggregated data
        for key, data in aggregated.items():
            comp_item, l, w, t = key
            qty_req = data.get("qty_required", 0)
            qty_plan = data.get("qty_planned", 0)
            qty_avail = qty_plan  # use planned pieces as available by default
            pending = max(0, qty_req - qty_plan)
            try:
                self.append("simulation_lines", {
                    "component_item": comp_item,
                    "length_mm": l,
                    "width_mm": w,
                    "thickness_mm": t,
                    "qty_required": qty_req,
                    "qty_planned": qty_plan,
                    "qty_available": qty_avail,
                    "pending_qty": pending,
                })
            except Exception:
                # If the child table or fields are missing, skip adding rows
                continue

    def on_submit(self):
        pass
        #result = create_serial_nos_and_bundles_from_material_cutting_plan(self)

        #messages = []

        #if result.get("serial_nos"):
        #    messages.append(
        #        "<b>Created Serial Nos</b><br>" + "<br>".join(result["serial_nos"])
        #    )

        #if result.get("bundles"):
        #    messages.append(
        #        "<b>Created Serial and Batch Bundles</b><br>" + "<br>".join(result["bundles"])
        #    )

        #if messages:
        #    frappe.msgprint("<br><br>".join(messages))