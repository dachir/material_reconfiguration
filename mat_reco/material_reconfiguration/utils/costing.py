# mat_reco/material_reconfiguration/utils/costing.py
from __future__ import annotations

import frappe
from frappe.utils import flt

PLANNED_PIECES_FIELD = "planned_pieces"
DELTA_EPS = 1e-6


def _area_mm2(L: float, W: float) -> float:
    return max(flt(L), 0.0) * max(flt(W), 0.0)


def _norm_dims(L: float, W: float) -> tuple[float, float]:
    L = flt(L)
    W = flt(W)
    return (L, W) if L >= W else (W, L)


def _get_bundle_name(it) -> str:
    # ERPNext versions / custom fieldnames variations
    return (it.get("serial_and_batch_bundle") or it.get("serial_batch_bundle") or "").strip()


def allocate_repack_costs_from_stock_entry(doc, mr_name: str) -> dict:
    """
    Compute valuation_rate for OUTPUT lines of a Repack Stock Entry created from a submitted MR.

    Source of truth for total cost:
      - total_input_cost = sum(abs(basic_amount)) of INPUT lines (s_warehouse filled)

    Allocation model:
      - unit_cost_per_mm2 = total_input_cost / total_input_area_mm2
      - FG effective area = fg_qty*(L*W) + fg_qty*kerf*(L+W)
      - Chutes area = sum(length*width*planned_pieces) from MR detail (no kerf)
      - Outputs valuation_rate:
          FG: (unit_cost * FG_eff_area) / fg_qty
          ByProduct: (unit_cost * total_chute_area) / chute_qty
      - Apply rounding delta to ByProduct if possible else FG.
    """
    mr = frappe.get_doc("Material Reconfiguration", mr_name)
    mr.check_permission("read")
    if mr.docstatus != 1:
        frappe.throw("Material Reconfiguration must be submitted first.")

    if not mr.source_item or not mr.source_warehouse:
        frappe.throw("source_item and source_warehouse are required.")
    if not mr.fg_item_code or flt(mr.fg_total_qty) <= 0:
        frappe.throw("fg_item_code and fg_total_qty are required.")

    items = doc.get("items") or []

    # --- 1) Total input cost: sum(abs(basic_amount)) on input rows
    total_input_cost = 0.0
    for it in items:
        if it.get("s_warehouse"):  # input line
            total_input_cost += abs(flt(it.get("basic_amount") or 0))

    if total_input_cost <= 0:
        frappe.throw("Input basic_amount is zero; cannot allocate repack costs.")

    # --- 2) Total input area from input bundles -> serials -> Serial No dimensions
    input_serials: list[str] = []

    for it in items:
        if not it.get("s_warehouse"):
            continue

        bundle_name = _get_bundle_name(it)
        if not bundle_name:
            continue

        if not frappe.db.exists("Serial and Batch Bundle", bundle_name):
            frappe.throw(f"Serial and Batch Bundle not found: {bundle_name}")

        b = frappe.get_doc("Serial and Batch Bundle", bundle_name)
        for e in (b.get("entries") or []):
            sn = (e.get("serial_no") or "").strip()
            if sn:
                input_serials.append(sn)

    # unique, preserve order
    input_serials = list(dict.fromkeys(input_serials))

    if not input_serials:
        frappe.throw("No input serials found in bundles; cannot compute input area.")

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

    missing_dims = []
    total_input_area = 0.0
    for sn in input_serials:
        L, W = dims_map.get(sn, (0.0, 0.0))
        a = _area_mm2(L, W)
        if a <= 0:
            missing_dims.append(sn)
        total_input_area += a

    if total_input_area <= 0:
        frappe.throw("Total input area is zero; check Serial No dimensions for input serials.")

    if missing_dims:
        # On préfère être strict : sinon tu “sous-estimes” l’aire et tu gonfles le coût/mm²
        frappe.throw(
            "Some input serials have missing/zero dimensions on Serial No: "
            + ", ".join(missing_dims[:20])
            + (" ..." if len(missing_dims) > 20 else "")
        )

    unit_cost = total_input_cost / total_input_area

    # --- 3) FG effective area (with kerf)
    fg_qty = flt(mr.fg_total_qty)
    fg_L, fg_W = _norm_dims(flt(mr.get("fg_length_mm") or 0), flt(mr.get("fg_width_mm") or 0))
    if fg_L <= 0 or fg_W <= 0:
        frappe.throw("FG dimensions are required on MR (fg_length_mm, fg_width_mm).")

    k = flt(mr.get("kerf_mm") or 0)
    if k < 0:
        k = 0.0

    A_fg = fg_qty * _area_mm2(fg_L, fg_W)
    A_kerf = fg_qty * k * (fg_L + fg_W)
    A_fg_eff = A_fg + max(A_kerf, 0.0)

    C_fg = unit_cost * A_fg_eff
    vr_fg = (C_fg / fg_qty) if fg_qty else 0.0

    # --- 4) Chutes from MR detail (no kerf)
    detail = mr.get("detail") or []
    byp_rows = []
    for d in detail:
        cat = (d.get("categorie") or d.get("category") or "").strip()
        if cat == "By Product":
            byp_rows.append(d)

    total_chute_area = 0.0
    for r in byp_rows:
        L, W = _norm_dims(flt(r.get("length_mm") or 0), flt(r.get("width_mm") or 0))
        pcs = flt(r.get(PLANNED_PIECES_FIELD) or r.get("planned_pieces") or 1)
        if pcs <= 0:
            pcs = 1
        total_chute_area += _area_mm2(L, W) * pcs

    C_chutes = unit_cost * total_chute_area

    # chute_qty = qty of OUTPUT rows that represent chutes
    chute_qty = 0.0
    for it in items:
        if it.get("t_warehouse") and (it.get("item_code") == mr.source_item):
            chute_qty += flt(it.get("qty") or 0)

    vr_chutes = (C_chutes / chute_qty) if chute_qty else 0.0

    # --- 5) Delta fix: ensure allocated totals match input total
    alloc_total = (vr_fg * fg_qty) + (vr_chutes * chute_qty)
    delta = flt(total_input_cost - alloc_total)

    if abs(delta) > DELTA_EPS:
        if chute_qty > 0:
            vr_chutes = flt(vr_chutes + (delta / chute_qty))
        elif fg_qty > 0:
            vr_fg = flt(vr_fg + (delta / fg_qty))

    # safety: no negative valuation rates
    if vr_fg < 0:
        vr_fg = 0.0
    if vr_chutes < 0:
        vr_chutes = 0.0

    return {
        "total_input_cost": total_input_cost,
        "total_input_area_mm2": total_input_area,
        "unit_cost_per_mm2": unit_cost,
        "lines": [
            {"row_type": "FG", "item_code": mr.fg_item_code, "valuation_rate": vr_fg},
            {"row_type": "ByProduct", "item_code": mr.source_item, "valuation_rate": vr_chutes},
        ],
    }


__all__ = ["allocate_repack_costs_from_stock_entry"]