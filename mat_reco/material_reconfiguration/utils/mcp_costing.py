#mat_reco/material_reconfiguration/utils/mcp_costing.py

from __future__ import annotations

import json

import frappe
from frappe.utils import flt

from mat_reco.material_reconfiguration.services.mcp_incident_service import (
    apply_incidents_to_nodes,
    build_incident_map,
    ensure_effective_fields,
)


DELTA_EPS = 1e-6


def _area_mm2(L: float, W: float) -> float:
    return max(flt(L), 0.0) * max(flt(W), 0.0)


def _norm_dims(L: float, W: float) -> tuple[float, float]:
    L = flt(L)
    W = flt(W)
    return (L, W) if L >= W else (W, L)


def _norm_dims_key(L: float, W: float, precision: int = 3) -> tuple[float, float]:
    L = round(flt(L), precision)
    W = round(flt(W), precision)
    return (L, W) if L >= W else (W, L)


def _get_bundle_name(it) -> str:
    return (it.get("serial_and_batch_bundle") or it.get("serial_batch_bundle") or "").strip()


def _safe_json_load(value):
    if not value:
        return {}
    if isinstance(value, dict):
        return value
    try:
        return json.loads(value)
    except Exception:
        return {}


def _get_mcp_tree(mcp):
    result_json = mcp.get("effective_result_json") or mcp.get("result_json") or mcp.get("result_tree_json")
    parsed = _safe_json_load(result_json)
    if not parsed:
        return {}
    return parsed.get("tree") or parsed


def _tree_is_return_terrain_resolved(tree):
    if not isinstance(tree, dict):
        return False
    if tree.get("return_terrain_resolved"):
        return True
    options = tree.get("options") or {}
    return bool(options.get("return_terrain_resolved"))


def _get_effective_children(mcp):
    tree = _get_mcp_tree(mcp)
    nodes = tree.get("nodes") or []
    incident_map = {} if _tree_is_return_terrain_resolved(tree) else build_incident_map(mcp)

    result = []
    for node in apply_incidents_to_nodes(nodes, incident_map):
        for child in node.get("children") or []:
            row = ensure_effective_fields(child)
            row["source_item_code"] = node.get("item_code") or mcp.get("source_item")
            result.append(row)

    return result

def _allocate_area_repack_costs_from_stock_entry(
    doc,
    *,
    serial_dim_map=None,
    skip_destroyed=False,
    skip_waste=False,
) -> dict:
    """
    Common area-based costing engine for Repack Stock Entry.

    Rules:
    1) total_input_cost = sum(abs(basic_amount)) of input rows
    2) total_input_area = sum(area of input serials)
    3) unit_cost = total_input_cost / total_input_area
    4) allocate cost to output rows based on output area
    5) apply delta to last output row
    """
    serial_dim_map = serial_dim_map or {}

    items = doc.get("items") or []

    # ---------------------------------------------------------
    # 1) Total input cost
    # ---------------------------------------------------------
    total_input_cost = 0.0
    for it in items:
        if it.get("s_warehouse"):
            total_input_cost += abs(flt(it.get("basic_amount") or 0))

    if total_input_cost <= 0:
        frappe.throw("Input basic_amount is zero; cannot allocate repack costs.")

    # ---------------------------------------------------------
    # 2) Total input area from input serials
    # ---------------------------------------------------------
    input_serials = []

    for it in items:
        if not it.get("s_warehouse"):
            continue

        bundle_name = _get_bundle_name(it)
        if bundle_name:
            if not frappe.db.exists("Serial and Batch Bundle", bundle_name):
                frappe.throw(f"Serial and Batch Bundle not found: {bundle_name}")

            bundle_doc = frappe.get_doc("Serial and Batch Bundle", bundle_name)
            for e in (bundle_doc.get("entries") or bundle_doc.get("items") or []):
                sn = (e.get("serial_no") or "").strip()
                if sn:
                    input_serials.append(sn)
        else:
            serial_no_text = (it.get("serial_no") or "").strip()
            if serial_no_text:
                for sn in serial_no_text.splitlines():
                    sn = sn.strip()
                    if sn:
                        input_serials.append(sn)

    input_serials = list(dict.fromkeys(input_serials))

    if not input_serials:
        frappe.throw("No input serials found; cannot compute input area.")

    sn_rows = frappe.get_all(
        "Serial No",
        filters={"name": ["in", input_serials]},
        fields=["name", "custom_dimension_length_mm", "custom_dimension_width_mm"],
    )

    dims_map = {
        d["name"]: (
            flt(d.get("custom_dimension_length_mm") or 0),
            flt(d.get("custom_dimension_width_mm") or 0),
        )
        for d in sn_rows
    }

    total_input_area = 0.0
    missing_dims = []

    for sn in input_serials:
        L, W = dims_map.get(sn, (0.0, 0.0))
        a = _area_mm2(L, W)
        if a <= 0:
            missing_dims.append(sn)
        total_input_area += a

    if total_input_area <= 0:
        frappe.throw("Total input area is zero; check Serial No dimensions.")

    if missing_dims:
        frappe.throw(
            "Some input serials have missing/zero dimensions on Serial No: "
            + ", ".join(missing_dims[:20])
            + (" ..." if len(missing_dims) > 20 else "")
        )

    unit_cost = total_input_cost / total_input_area

    # ---------------------------------------------------------
    # 3) Build output cost rows from actual Stock Entry rows
    # ---------------------------------------------------------
    lines = []
    allocated_total = 0.0

    for idx, it in enumerate(items, start=1):
        if not it.get("t_warehouse"):
            continue

        item_code = it.get("item_code")
        qty = flt(it.get("qty") or 0)
        if not item_code or qty <= 0:
            continue

        node_type = (it.get("custom_cutting_node_type") or "").strip()

        # 1) dimensions from row first
        L = flt(it.get("custom_dimension_length_mm") or 0)
        W = flt(it.get("custom_dimension_width_mm") or 0)

        # 2) fallback from first serial on row if row dims missing
        if L <= 0 or W <= 0:
            row_serials = _get_row_serials(it)
            if row_serials:
                first_serial = row_serials[0]
                dim_row = serial_dim_map.get(first_serial) or {}
                L = flt(dim_row.get("length_mm") or 0)
                W = flt(dim_row.get("width_mm") or 0)
                if not node_type:
                    node_type = (dim_row.get("node_type") or "").strip()

        L, W = _norm_dims_key(L, W)

        if skip_destroyed and node_type == "destroyed":
            continue

        if skip_waste and node_type == "waste":
            continue

        if L <= 0 or W <= 0:
            frappe.throw(
                f"Missing output dimensions on Stock Entry row {idx} for item {item_code}."
            )

        line_area_total = _area_mm2(L, W) * qty
        line_amount_total = unit_cost * line_area_total
        valuation_rate = (line_amount_total / qty) if qty else 0.0

        allocated_total += line_amount_total

        lines.append(
            {
                "row_index": idx,
                "row_type": node_type or "output",
                "item_code": item_code,
                "length_mm": L,
                "width_mm": W,
                "qty": qty,
                "line_area_mm2": line_area_total,
                "line_amount": line_amount_total,
                "valuation_rate": valuation_rate,
            }
        )

    if not lines:
        frappe.throw("No valid output rows found for repack costing.")

    # ---------------------------------------------------------
    # 4) Delta fix on last line
    # ---------------------------------------------------------
    delta = flt(total_input_cost - allocated_total)

    if abs(delta) > DELTA_EPS and lines:
        last = lines[-1]
        qty = flt(last.get("qty") or 0)
        if qty > 0:
            last["line_amount"] = flt(last["line_amount"] + delta)
            last["valuation_rate"] = flt(last["line_amount"] / qty)
            if last["valuation_rate"] < 0:
                last["valuation_rate"] = 0.0

    return {
        "total_input_cost": total_input_cost,
        "total_input_area_mm2": total_input_area,
        "unit_cost_per_mm2": unit_cost,
        "lines": lines,
    }

def allocate_mcp_repack_costs_from_stock_entry(doc, mcp_name: str) -> dict:
    """
    MCP wrapper around common area-based repack costing.
    Keeps MCP-specific behavior:
    - submitted MCP required
    - serial_dim_map from MCP result tree / incidents
    - skip destroyed rows
    - optionally skip waste rows
    """
    mcp = frappe.get_doc("Material Cutting Plan", mcp_name)
    mcp.check_permission("read")

    if mcp.docstatus != 1:
        frappe.throw("Material Cutting Plan must be submitted first.")

    if not mcp.source_item or not mcp.source_warehouse:
        frappe.throw("source_item and source_warehouse are required on MCP.")

    serial_dim_map = _get_mcp_serial_dimension_map(mcp)

    return _allocate_area_repack_costs_from_stock_entry(
        doc,
        serial_dim_map=serial_dim_map,
        skip_destroyed=True,
        skip_waste=(not flt(mcp.get("add_waiste_to_stock") or 0)),
    )

def allocate_sales_order_repack_costs_from_stock_entry(doc) -> dict:
    """
    Allocate costs for a Repack Stock Entry created from a Sales Order.

    Unlike MCP costing, which allocates cost based on the area of the
    produced pieces, Sales Order repack costing uses a quantity-based
    allocation: the total cost of the input rows is distributed across
    output rows in proportion to their quantities.  The valuation rate
    for each output row is therefore ``total_input_cost / total_output_qty``.

    Args:
        doc: The Stock Entry document being costed.

    Returns:
        dict: A result dict similar to the MCP costing function, with keys
        ``total_input_cost``, ``total_output_qty``, ``unit_rate`` (the
        valuation rate applied to each unit), and ``lines`` listing the
        per‑row cost allocations.  Each entry in ``lines`` contains
        ``row_index``, ``row_type``, ``item_code``, ``qty``, ``line_amount``,
        and ``valuation_rate``.  Additional fields ``length_mm``,
        ``width_mm`` and ``line_area_mm2`` are included for structural
        compatibility but are not used in the allocation.
    """
    items = doc.get("items") or []

    # 1) Total input cost: sum of absolute basic_amount on input rows
    total_input_cost = 0.0
    for it in items:
        if it.get("s_warehouse"):
            total_input_cost += abs(flt(it.get("basic_amount") or 0))

    if total_input_cost <= 0:
        frappe.throw("Input basic_amount is zero; cannot allocate repack costs.")

    # 2) Collect output rows and total output quantity
    output_rows = []
    total_output_qty = 0.0
    for idx, it in enumerate(items, start=1):
        if not it.get("t_warehouse"):
            continue
        qty = flt(it.get("qty") or 0)
        item_code = (it.get("item_code") or "").strip()
        if not item_code or qty <= 0:
            continue
        total_output_qty += qty
        output_rows.append((idx, it, qty))

    if total_output_qty <= 0:
        frappe.throw("Total output quantity is zero; cannot allocate repack costs.")

    # 3) Compute unit valuation rate
    unit_rate = total_input_cost / total_output_qty

    lines = []
    allocated_total = 0.0
    for idx, it, qty in output_rows:
        node_type = (it.get("custom_cutting_node_type") or "").strip() or "output"
        item_code = it.get("item_code")
        # compute line amount proportionally by quantity
        line_amount_total = unit_rate * qty
        valuation_rate = unit_rate
        allocated_total += line_amount_total
        # fetch dimensions for completeness; not used in allocation
        L = flt(it.get("custom_dimension_length_mm") or 0)
        W = flt(it.get("custom_dimension_width_mm") or 0)
        # if dimensions missing, attempt to derive from first serial
        if (L <= 0 or W <= 0):
            row_serials = _get_row_serials(it)
            if row_serials:
                sn = row_serials[0]
                # attempt to load from Serial No custom fields
                sn_doc = frappe.get_doc("Serial No", sn) if frappe.db.exists("Serial No", sn) else None
                if sn_doc:
                    L = flt(sn_doc.get("custom_dimension_length_mm") or 0)
                    W = flt(sn_doc.get("custom_dimension_width_mm") or 0)
        L, W = _norm_dims_key(L, W)
        # compute area (for compatibility; not used)
        line_area_total = _area_mm2(L, W) * qty
        lines.append(
            {
                "row_index": idx,
                "row_type": node_type,
                "item_code": item_code,
                "length_mm": L,
                "width_mm": W,
                "qty": qty,
                "line_area_mm2": line_area_total,
                "line_amount": line_amount_total,
                "valuation_rate": valuation_rate,
            }
        )

    # 4) Delta fix on last line to absorb rounding differences
    delta = flt(total_input_cost - allocated_total)
    if abs(delta) > DELTA_EPS and lines:
        last = lines[-1]
        qty = flt(last.get("qty") or 0)
        if qty > 0:
            last["line_amount"] = flt(last["line_amount"] + delta)
            last["valuation_rate"] = flt(last["line_amount"] / qty)
            if last["valuation_rate"] < 0:
                last["valuation_rate"] = 0.0

    return {
        "total_input_cost": total_input_cost,
        "total_output_qty": total_output_qty,
        "unit_rate": unit_rate,
        "lines": lines,
    }

def _extract_serials_from_text(value: str) -> list[str]:
    result = []
    for row in (value or "").splitlines():
        s = row.strip()
        if s:
            result.append(s)
    return list(dict.fromkeys(result))


def _extract_bundle_serials(bundle_doc) -> list[str]:
    serials = []
    for row in (bundle_doc.get("entries") or bundle_doc.get("items") or []):
        serial_no = (row.get("serial_no") or "").strip()
        if serial_no:
            serials.append(serial_no)
    return serials


def _get_row_serials(it) -> list[str]:
    bundle_name = _get_bundle_name(it)
    if bundle_name and frappe.db.exists("Serial and Batch Bundle", bundle_name):
        bundle_doc = frappe.get_doc("Serial and Batch Bundle", bundle_name)
        return _extract_bundle_serials(bundle_doc)

    return _extract_serials_from_text(it.get("serial_no") or "")

def _get_mcp_serial_dimension_map(mcp):
    """
    Map:
        serial_candidate -> (length_mm, width_mm)
    based on result_json + incidents
    """
    tree = _get_mcp_tree(mcp)
    nodes = (tree.get("nodes") or [])
    incident_map = {} if _tree_is_return_terrain_resolved(tree) else build_incident_map(mcp)
    result = {}

    for node in nodes:
        for child in (node.get("children") or []):
            serial_no = (child.get("id") or child.get("piece_uid") or "").strip()
            if not serial_no:
                continue

            incident = incident_map.get(serial_no)
            length_mm = flt(child.get("length_mm") or 0)
            width_mm = flt(child.get("width_mm") or 0)
            node_type = (child.get("node_type") or "").strip()

            if incident:
                action = (incident.get("incident_action") or "").strip()
                if action == "Destroy":
                    node_type = "destroyed"
                    length_mm = 0
                    width_mm = 0
                elif action == "Resize":
                    node_type = (incident.get("new_node_type") or node_type).strip()
                    length_mm = flt(incident.get("new_length_mm") or 0)
                    width_mm = flt(incident.get("new_width_mm") or 0)

            result[serial_no] = {
                "node_type": node_type,
                "length_mm": _norm_dims_key(length_mm, width_mm)[0],
                "width_mm": _norm_dims_key(length_mm, width_mm)[1],
            }

    return result

__all__ = [
    "allocate_mcp_repack_costs_from_stock_entry",
    "allocate_sales_order_repack_costs_from_stock_entry",
]