# mat_reco/stock_hooks.py
import frappe
from frappe.utils import flt
from mat_reco.material_reconfiguration.utils.costing import allocate_repack_costs_from_stock_entry


def _apply_rate_on_row(it, new_vr: float):
    new_vr = flt(new_vr)

    # 1) Champs visibles / usuels
    it.valuation_rate = new_vr
    it.basic_rate = new_vr
    it.rate = new_vr

    # 2) Champ clé utilisé au submit pour les lignes incoming
    # (sur Stock Entry Item, incoming_rate est déterminant pour les entrées)
    if hasattr(it, "incoming_rate"):
        it.incoming_rate = new_vr

    # 3) Quantités / montants
    stock_qty = flt(getattr(it, "stock_qty", 0)) or (flt(it.qty) * flt(it.conversion_factor or 1))
    it.stock_qty = stock_qty

    it.basic_amount = flt(it.basic_rate) * stock_qty
    it.amount = it.basic_amount

    # 4) Empêcher acceptation silencieuse du zero si tu veux
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

    result = allocate_repack_costs_from_stock_entry(doc, mr_name)
    lines = result.get("lines") or []

    fg = next((x for x in lines if x.get("row_type") == "FG"), None)
    byp = next((x for x in lines if x.get("row_type") == "ByProduct"), None)

    fg_item = fg.get("item_code") if fg else None
    fg_vr = flt(fg.get("valuation_rate")) if fg else None

    byp_item = byp.get("item_code") if byp else None
    byp_vr = flt(byp.get("valuation_rate")) if byp else None

    # Apply on outputs
    fg_applied = False
    byp_applied = False

    for it in (doc.items or []):
        # OUTPUT only: target warehouse filled
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

    # Fail fast: si on n'a pas trouvé les outputs attendus, on préfère bloquer que soumettre à 0
    if fg_item and not fg_applied:
        frappe.throw(f"FG output line not found in Stock Entry items for item_code: {fg_item}")

    if byp_item and not byp_applied:
        frappe.throw(f"ByProduct output line not found in Stock Entry items for item_code: {byp_item}")

    # Recompute totals (si tu vois que ça écrase, on enlèvera)
    if hasattr(doc, "set_total_amount"):
        doc.set_total_amount()
    if hasattr(doc, "set_total_incoming_outgoing_value"):
        doc.set_total_incoming_outgoing_value()


def stock_entry_validate(doc, method=None):
    _apply_mr_costing(doc)


def stock_entry_before_submit(doc, method=None):
    _apply_mr_costing(doc)