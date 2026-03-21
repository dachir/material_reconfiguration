# mat_reco/stock_hooks.py
import frappe
from frappe.utils import flt, cint

from mat_reco.material_reconfiguration.utils.costing import (
    allocate_repack_costs_from_stock_entry,
)
from mat_reco.material_reconfiguration.utils.mcp_costing import (
    allocate_mcp_repack_costs_from_stock_entry,
    allocate_sales_order_repack_costs_from_stock_entry,
)
from mat_reco.material_reconfiguration.services.serial_creation_service import (
    ensure_mcp_serials_and_bundles_for_stock_entry,
    ensure_repack_output_serials_and_bundles_for_stock_entry,
)
from mat_reco.material_reconfiguration.services.repack_draft_service import (
    validate_repack_totals_against_mcp_on_submit,
)


def _norm_dims(L, W):
    L = flt(L)
    W = flt(W)
    return (L, W) if L >= W else (W, L)


def _norm_dims_key(L, W, precision=3):
    L = round(flt(L), precision)
    W = round(flt(W), precision)
    return (L, W) if L >= W else (W, L)


def _extract_serials_from_text(value):
    out = []
    for row in (value or "").splitlines():
        s = row.strip()
        if s:
            out.append(s)
    return out


def _extract_bundle_serials(bundle_doc):
    serials = []
    for row in (bundle_doc.get("entries") or bundle_doc.get("items") or []):
        serial_no = (row.get("serial_no") or "").strip()
        if serial_no:
            serials.append(serial_no)
    return serials


def _get_bundle_name(it):
    return (it.get("serial_and_batch_bundle") or it.get("serial_batch_bundle") or "").strip()


def _get_row_dims_from_serials(it):
    row_length = flt(it.get("custom_dimension_length_mm") or 0)
    row_width = flt(it.get("custom_dimension_width_mm") or 0)

    if row_length > 0 and row_width > 0:
        return _norm_dims_key(row_length, row_width)

    serials = []

    bundle_name = _get_bundle_name(it)
    if bundle_name and frappe.db.exists("Serial and Batch Bundle", bundle_name):
        bundle_doc = frappe.get_doc("Serial and Batch Bundle", bundle_name)
        serials = _extract_bundle_serials(bundle_doc)
    else:
        serials = _extract_serials_from_text(it.get("serial_no") or "")

    if not serials:
        return _norm_dims_key(0, 0)

    first_serial = serials[0]
    if not frappe.db.exists("Serial No", first_serial):
        return _norm_dims_key(0, 0)

    sn = frappe.get_doc("Serial No", first_serial)
    sn_length = flt(sn.get("custom_dimension_length_mm") or 0)
    sn_width = flt(sn.get("custom_dimension_width_mm") or 0)

    return _norm_dims_key(sn_length, sn_width)


def _cleanup_legacy_serial_fields_when_bundle_exists(doc):
    for it in (doc.items or []):
        bundle_name = (it.get("serial_and_batch_bundle") or it.get("serial_batch_bundle") or "").strip()
        if not bundle_name:
            continue

        it.serial_no = ""
        if hasattr(it, "batch_no"):
            it.batch_no = ""


def _apply_rate_on_row(it, new_vr: float):
    new_vr = flt(new_vr)

    if hasattr(it, "set_basic_rate_manually"):
        it.set_basic_rate_manually = 1

    it.valuation_rate = new_vr
    it.basic_rate = new_vr
    it.rate = new_vr

    if hasattr(it, "incoming_rate"):
        it.incoming_rate = new_vr

    stock_qty = flt(getattr(it, "stock_qty", 0)) or (
        flt(it.qty) * flt(it.conversion_factor or 1)
    )
    it.stock_qty = stock_qty

    it.basic_amount = flt(it.basic_rate) * stock_qty
    it.amount = it.basic_amount

    if hasattr(it, "allow_zero_valuation_rate") and new_vr > 0:
        it.allow_zero_valuation_rate = 0


def _apply_mr_costing(doc):
    mr_name = (doc.get("custom_material_reconfiguration") or "").strip()
    if not mr_name:
        return
    if (doc.stock_entry_type or "") != "Repack":
        return
    if doc.docstatus != 0:
        return

    doc.set_basic_rate_manually = 1

    result = allocate_repack_costs_from_stock_entry(doc, mr_name)
    lines = result.get("lines") or []

    fg = next((x for x in lines if x.get("row_type") == "FG"), None)
    byp = next((x for x in lines if x.get("row_type") == "ByProduct"), None)

    fg_item = fg.get("item_code") if fg else None
    fg_vr = flt(fg.get("valuation_rate")) if fg else None

    byp_item = byp.get("item_code") if byp else None
    byp_vr = flt(byp.get("valuation_rate")) if byp else None

    fg_applied = False
    byp_applied = False

    for it in (doc.items or []):
        if not it.t_warehouse:
            continue

        if fg_item and it.item_code == fg_item:
            _apply_rate_on_row(it, fg_vr)
            fg_applied = True
            continue

        if byp_item and it.item_code == byp_item:
            _apply_rate_on_row(it, byp_vr)
            byp_applied = True
            continue

    if fg_item and not fg_applied:
        frappe.throw(f"FG output line not found in Stock Entry items for item_code: {fg_item}")

    if byp_item and not byp_applied:
        frappe.throw(f"ByProduct output line not found in Stock Entry items for item_code: {byp_item}")

    if hasattr(doc, "set_total_amount"):
        doc.set_total_amount()
    if hasattr(doc, "set_total_incoming_outgoing_value"):
        doc.set_total_incoming_outgoing_value()


def _apply_mcp_costing(doc):
    mcp_name = (doc.get("custom_material_cutting_plan") or "").strip()
    if not mcp_name:
        return
    if (doc.stock_entry_type or "") != "Repack":
        return
    if doc.docstatus != 0:
        return

    doc.set_basic_rate_manually = 1

    ensure_mcp_serials_and_bundles_for_stock_entry(doc)
    _cleanup_legacy_serial_fields_when_bundle_exists(doc)

    result = allocate_mcp_repack_costs_from_stock_entry(doc, mcp_name)
    lines = result.get("lines") or []

    for it in (doc.items or []):
        if it.t_warehouse and hasattr(it, "set_basic_rate_manually"):
            it.set_basic_rate_manually = 1

    for line in lines:
        row_index = cint(line.get("row_index") or 0)
        valuation_rate = flt(line.get("valuation_rate"))

        if not row_index or row_index > len(doc.items):
            frappe.throw(f"Invalid row index returned by MCP costing: {row_index}")

        it = doc.items[row_index - 1]

        if not it.t_warehouse:
            frappe.throw(f"MCP costing returned non-output row index: {row_index}")

        _apply_rate_on_row(it, valuation_rate)

    if hasattr(doc, "set_total_amount"):
        doc.set_total_amount()
    if hasattr(doc, "set_total_incoming_outgoing_value"):
        doc.set_total_incoming_outgoing_value()

def _apply_so_repack_costing(doc):
    so_name = (doc.get("custom_sales_order") or "").strip()
    if not so_name:
        return
    if (doc.stock_entry_type or "") != "Repack":
        return
    if doc.docstatus != 0:
        return

    doc.set_basic_rate_manually = 1

    ensure_repack_output_serials_and_bundles_for_stock_entry(doc)
    _cleanup_legacy_serial_fields_when_bundle_exists(doc)

    result = allocate_sales_order_repack_costs_from_stock_entry(doc)
    lines = result.get("lines") or []

    for it in (doc.items or []):
        if it.t_warehouse and hasattr(it, "set_basic_rate_manually"):
            it.set_basic_rate_manually = 1

    for line in lines:
        row_index = cint(line.get("row_index") or 0)
        valuation_rate = flt(line.get("valuation_rate"))

        if not row_index or row_index > len(doc.items):
            frappe.throw(f"Invalid row index returned by SO repack costing: {row_index}")

        it = doc.items[row_index - 1]

        if not it.t_warehouse:
            frappe.throw(f"SO repack costing returned non-output row index: {row_index}")

        _apply_rate_on_row(it, valuation_rate)

    if hasattr(doc, "set_total_amount"):
        doc.set_total_amount()
    if hasattr(doc, "set_total_incoming_outgoing_value"):
        doc.set_total_incoming_outgoing_value()


def _apply_repack_costing(doc):
    _cleanup_legacy_serial_fields_when_bundle_exists(doc)

    mr_name = (doc.get("custom_material_reconfiguration") or "").strip()
    mcp_name = (doc.get("custom_material_cutting_plan") or "").strip()
    so_name = (doc.get("custom_sales_order") or "").strip()

    if mr_name and mcp_name:
        frappe.throw(
            "Stock Entry cannot be linked to both Material Reconfiguration and "
            "Material Cutting Plan at the same time."
        )

    # priorité inchangée : MR > MCP
    if mr_name:
        _apply_mr_costing(doc)
        return

    if mcp_name:
        _apply_mcp_costing(doc)
        return

    # nouveau cas : Repack créé depuis Sales Order
    if so_name:
        _apply_so_repack_costing(doc)
        return


def stock_entry_validate(doc, method=None):
    _hydrate_mcp_row_dimensions_from_serials(doc)
    _apply_repack_costing(doc)

def _already_costed(doc):
    return cint(doc.get("set_basic_rate_manually") or 0) == 1 and any(
        flt(d.get("basic_rate") or 0) > 0 for d in (doc.items or []) if d.get("t_warehouse")
    )

def stock_entry_before_submit(doc, method=None):
    _cleanup_legacy_serial_fields_when_bundle_exists(doc)
    validate_repack_totals_against_mcp_on_submit(doc)

    if _already_costed(doc):
        return


def _hydrate_mcp_row_dimensions_from_serials(doc):
    mcp_name = (doc.get("custom_material_cutting_plan") or "").strip()
    if not mcp_name:
        return

    if (doc.stock_entry_type or "") != "Repack":
        return

    for it in (doc.items or []):
        current_length = flt(it.get("custom_dimension_length_mm") or 0)
        current_width = flt(it.get("custom_dimension_width_mm") or 0)

        if current_length > 0 and current_width > 0:
            continue

        bundle_name = _get_bundle_name(it)
        serial_text = (it.get("serial_no") or "").strip()

        if not bundle_name and not serial_text:
            continue

        L, W = _get_row_dims_from_serials(it)
        if L <= 0 or W <= 0:
            continue

        it.custom_dimension_length_mm = L
        it.custom_dimension_width_mm = W

        if hasattr(it, "custom_surface_mm2"):
            it.custom_surface_mm2 = flt(L) * flt(W)

        if hasattr(it, "custom_perimeter_mm"):
            it.custom_perimeter_mm = 2 * (flt(L) + flt(W))


