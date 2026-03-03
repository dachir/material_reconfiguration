# mat_reco/material_reconfiguration/utils/costing.py
# Server-side helper to compute valuation_rate for Repack lines
# Option A: kerf cost is allocated to FG only.

from __future__ import annotations

import frappe
from frappe.utils import flt, cint


def _area_mm2(L: float, W: float) -> float:
    return max(flt(L), 0.0) * max(flt(W), 0.0)


def _norm_dims(L: float, W: float) -> tuple[float, float]:
    L = flt(L)
    W = flt(W)
    return (L, W) if L >= W else (W, L)


def allocate_repack_costs(
    mr_name: str,
    *,
    kerf_mm: float | None = None,
    planned_pieces_field: str = "planned_pieces",
    precision: int | None = None,
) -> dict:
    """
    Returns a dict describing valuation rates to apply on a Stock Entry (Repack)
    built from a submitted Material Reconfiguration.

    Costing model (Option A):
      - total input cost = sum(basic_amount of input serials)
      - unit cost per mm2 = total_input_cost / total_input_area_mm2
      - FG gets area = n*(L*W) + n*kerf*(L+W)
      - Chutes get area = sum(L*W) (no kerf)
      - Convert to valuation_rate per stock UOM "Nos" line:
          valuation_rate = (allocated_cost_for_line / qty)
      - Ensures total allocated cost == total input cost by applying rounding delta
        to the last output line (prefer last chute, else FG).

    Assumptions:
      - Inputs are Serial Nos of mr.source_item in mr.source_warehouse
      - Outputs:
          * FG is mr.fg_item_code with qty = mr.fg_total_qty (Nos)
          * By-products are mr.source_item (serials created on submit), qty = nb serials
      - Serial No has custom_dimension_length_mm/custom_dimension_width_mm for area.
      - Input serial "basic cost" is taken from Stock Ledger Entry valuation.
        We approximate per-serial cost as:
          incoming_rate * 1 (serial)  -> taken from latest SLE for that serial+warehouse.
        If you have another reliable source (e.g., Purchase Receipt item rate), swap it here.

    Returns:
      {
        "total_input_cost": ...,
        "total_input_area_mm2": ...,
        "unit_cost_per_mm2": ...,
        "lines": [
            {"row_type":"Input", "item_code":..., "qty":..., "valuation_rate": ...},
            {"row_type":"FG", "item_code":..., "qty":..., "valuation_rate": ...},
            {"row_type":"ByProduct", "item_code":..., "qty":..., "valuation_rate": ...},
        ],
      }
    """
    mr = frappe.get_doc("Material Reconfiguration", mr_name)
    mr.check_permission("read")
    if mr.docstatus != 1:
        frappe.throw("Material Reconfiguration must be submitted first.")

    if not mr.source_item or not mr.source_warehouse:
        frappe.throw("source_item and source_warehouse are required.")
    if not mr.fg_item_code or flt(mr.fg_total_qty) <= 0:
        frappe.throw("fg_item_code and fg_total_qty are required.")

    k = flt(kerf_mm) if kerf_mm is not None else flt(mr.get("kerf_mm") or 0)
    if k < 0:
        k = 0.0

    # -----------------------------
    # 1) Collect inputs & outputs
    # -----------------------------
    detail = mr.get("detail") or []
    input_rows = [d for d in detail if (d.get("line_type") or "").strip() == "Input" and (d.get("serial_no") or "").strip()]
    byp_rows = [d for d in detail if (d.get("categorie") or "").strip() == "By Product" and (d.get("serial_no") or "").strip()]
    fg_rows = [d for d in detail if (d.get("categorie") or "").strip() == "Finished Good"]

    input_serials: list[str] = []
    for r in input_rows:
        sn = (r.get("serial_no") or "").strip()
        if sn and sn not in input_serials:
            input_serials.append(sn)

    chute_serials: list[str] = []
    for r in byp_rows:
        sn = (r.get("serial_no") or "").strip()
        if sn and sn not in chute_serials:
            chute_serials.append(sn)

    fg_qty = flt(mr.fg_total_qty)

    # Determine FG dims from MR header, normalized
    fg_L, fg_W = _norm_dims(flt(mr.get("fg_length_mm") or 0), flt(mr.get("fg_width_mm") or 0))
    if fg_L <= 0 or fg_W <= 0:
        # fallback: try first FG row dims if present
        if fg_rows:
            fg_L, fg_W = _norm_dims(flt(fg_rows[0].get("length_mm") or 0), flt(fg_rows[0].get("width_mm") or 0))

    if fg_L <= 0 or fg_W <= 0:
        frappe.throw("FG dimensions are required (fg_length_mm, fg_width_mm).")

    # -----------------------------
    # 2) Input area + cost (basic_amount)
    # -----------------------------
    # Input area uses Serial No dimensions (more reliable than detail row)
    sn_dims = frappe.get_all(
        "Serial No",
        filters={"name": ["in", input_serials]},
        fields=["name", "custom_dimension_length_mm", "custom_dimension_width_mm"],
    )
    dims_map = {d["name"]: (flt(d.get("custom_dimension_length_mm") or 0), flt(d.get("custom_dimension_width_mm") or 0)) for d in sn_dims}

    total_input_area = 0.0
    for sn in input_serials:
        L, W = dims_map.get(sn, (0.0, 0.0))
        total_input_area += _area_mm2(L, W)

    if total_input_area <= 0:
        frappe.throw("Total input area is zero; check Serial No dimensions on inputs.")

    # Input cost: sum of latest incoming valuation per serial in that warehouse.
    # NOTE: Adjust this query if your valuation source differs.
    # We take the latest Stock Ledger Entry for the serial in warehouse and use
    # abs(stock_value_difference) when it is an inward entry, otherwise fallback
    # to abs(stock_value_difference) regardless of sign.
    # This is robust across stock valuation methods when serials represent distinct pieces.
    total_input_cost = 0.0
    if input_serials:
        # Fetch latest SLE per serial in warehouse
        # MariaDB: get latest by posting_date+posting_time+creation; we use creation as tie-breaker.
        rows = frappe.db.sql(
            """
            SELECT t.serial_no, t.stock_value_difference
            FROM `tabStock Ledger Entry` t
            INNER JOIN (
                SELECT serial_no, MAX(creation) AS max_creation
                FROM `tabStock Ledger Entry`
                WHERE warehouse=%s
                  AND serial_no IN %(serials)s
                  AND is_cancelled=0
                GROUP BY serial_no
            ) x ON x.serial_no=t.serial_no AND x.max_creation=t.creation
            """,
            {"serials": tuple(input_serials), "warehouse": mr.source_warehouse},
            as_dict=True,
        )
        cost_map = {r["serial_no"]: flt(r.get("stock_value_difference") or 0) for r in rows}
        for sn in input_serials:
            # Use absolute to represent "basic amount" magnitude tied to that serial acquisition.
            # If your flows store consistent positive for inward, you can remove abs().
            total_input_cost += abs(flt(cost_map.get(sn, 0.0)))

    if total_input_cost <= 0:
        frappe.throw(
            "Unable to compute total_input_cost from Stock Ledger Entry. "
            "Adjust allocate_repack_costs() to your valuation source."
        )

    unit_cost = total_input_cost / total_input_area

    # -----------------------------
    # 3) Allocate to FG (with kerf)
    # -----------------------------
    A_fg = fg_qty * _area_mm2(fg_L, fg_W)
    A_kerf = fg_qty * k * (fg_L + fg_W)  # per your rule
    A_fg_eff = A_fg + max(A_kerf, 0.0)

    C_fg = unit_cost * A_fg_eff
    vr_fg = (C_fg / fg_qty) if fg_qty else 0.0

    # -----------------------------
    # 4) Allocate to chutes (no kerf)
    # -----------------------------
    # Each chute serial has its own area from MR detail row (already normalized and accurate).
    chute_costs: list[float] = []
    for r in byp_rows:
        L, W = _norm_dims(flt(r.get("length_mm") or 0), flt(r.get("width_mm") or 0))
        chute_costs.append(unit_cost * _area_mm2(L, W) * max(flt(r.get(planned_pieces_field) or 1), 1.0))

    C_chutes = sum(chute_costs)

    # We'll group all by-products into one line (as your payload does)
    chute_qty = len(chute_serials) if chute_serials else 0
    vr_chutes = (C_chutes / chute_qty) if chute_qty else 0.0

    # -----------------------------
    # 5) Rounding and delta fix
    # -----------------------------
    def _round(x: float) -> float:
        if precision is None:
            # match ERPNext float precision; fallback 6
            return flt(x)
        return round(flt(x), int(precision))

    vr_fg_r = _round(vr_fg)
    vr_chutes_r = _round(vr_chutes)

    # Recompute allocated totals after rounding
    alloc_total = (vr_fg_r * fg_qty) + (vr_chutes_r * chute_qty)
    delta = _round(total_input_cost - alloc_total)

    # Apply delta to chutes if possible (keeps FG clean), else FG
    if abs(delta) > 0 and chute_qty:
        vr_chutes_r = _round(vr_chutes_r + (delta / chute_qty))
    elif abs(delta) > 0 and fg_qty:
        vr_fg_r = _round(vr_fg_r + (delta / fg_qty))

    # Inputs valuation_rate can be set to 0 on repack (they are outward),
    # but ERPNext sometimes expects valuation_rate for outward too.
    # We'll use average per input serial:
    in_qty = len(input_serials)
    vr_in = _round(total_input_cost / in_qty) if in_qty else 0.0

    return {
        "total_input_cost": total_input_cost,
        "total_input_area_mm2": total_input_area,
        "unit_cost_per_mm2": unit_cost,
        "lines": [
            {
                "row_type": "Input",
                "item_code": mr.source_item,
                "qty": in_qty,
                "valuation_rate": vr_in,
            },
            {
                "row_type": "FG",
                "item_code": mr.fg_item_code,
                "qty": fg_qty,
                "valuation_rate": vr_fg_r,
            },
            {
                "row_type": "ByProduct",
                "item_code": mr.source_item,
                "qty": chute_qty,
                "valuation_rate": vr_chutes_r,
            },
        ],
    }


__all__ = ["allocate_repack_costs"]