from __future__ import annotations

import math
from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import flt, cint

from mat_reco.material_reconfiguration.services.order_explosion_service import (
    explode_item_to_decoupes,
)
from mat_reco.material_reconfiguration.services.serial_creation_service import (
    ensure_repack_output_serials_and_bundles_for_stock_entry,
)

CUTTING_TYPES = ("DECOUPE", "OUVRAGE")


def _norm_dims(L, W):
    L = flt(L)
    W = flt(W)
    return (L, W) if L >= W else (W, L)


def _get_item_type(item_code: str) -> str:
    return (frappe.db.get_value("Item", item_code, "custom_item_types") or "").strip()


def _get_item_name(item_code: str) -> str:
    return frappe.db.get_value("Item", item_code, "item_name") or item_code


def _get_stock_uom(item_code: str) -> str | None:
    return frappe.db.get_value("Item", item_code, "stock_uom")


def _set_stock_uom_fields(row, item_code: str, qty: float):
    stock_uom = frappe.db.get_value("Item", item_code, "stock_uom")
    row.uom = stock_uom
    row.stock_uom = stock_uom
    row.conversion_factor = 1
    row.qty = qty
    row.transfer_qty = qty
    row.stock_qty = qty


def _get_default_target_warehouse(item_code: str, company: str | None = None) -> str | None:
    if company:
        val = frappe.db.get_value("Item Default", {"parent": item_code, "company": company}, "default_warehouse")
        if val:
            return val
    return frappe.db.get_value("Item", item_code, "default_warehouse")


def _get_default_source_warehouse_for_piece(piece_item_code: str, company: str | None = None) -> str | None:
    """
    Ici on prend l'entrepôt par défaut de l'article feuille.
    Si vous avez une logique plus fine par matière/source warehouse, remplacez cette méthode.
    """
    return _get_default_target_warehouse(piece_item_code, company)


def _get_generated_qty_by_so_item(so_item_name: str) -> float:
    if not so_item_name:
        return 0

    rows = frappe.db.sql(
        """
        SELECT COALESCE(SUM(sed.qty), 0)
        FROM `tabStock Entry Detail` sed
        INNER JOIN `tabStock Entry` se ON se.name = sed.parent
        WHERE se.stock_entry_type = 'Repack'
          AND se.docstatus < 2
          AND COALESCE(sed.t_warehouse, '') != ''
          AND COALESCE(sed.custom_sales_order_item, '') = %s
        """,
        (so_item_name,),
    )
    return flt(rows[0][0]) if rows else 0


def _build_context_from_so_row(so, row) -> dict:
    return {
        "sales_order": so.name,
        "sales_order_item": row.name,
        "root_item_code": row.item_code,
        "root_item_name": row.item_name,
        "customer": so.customer,
        "delivery_date": so.delivery_date,
        "project": so.project,
        "base_length_mm": flt(row.get("custom_client_length_mm") or 0),
        "base_width_mm": flt(row.get("custom_client_width_mm") or 0),
        "base_thickness_mm": flt(row.get("custom_client_thickness_mm") or 0),
    }


def _explode_so_row_to_piece_requirements(so, row, qty: float) -> list[dict]:
    item_type = _get_item_type(row.item_code)
    if item_type not in CUTTING_TYPES:
        return []

    if qty <= 0:
        return []

    ctx = _build_context_from_so_row(so, row)

    exploded = explode_item_to_decoupes(
        item_code=row.item_code,
        parent_qty=qty,
        context=ctx,
        path=[],
        path_labels=[],
        depth=0,
        max_depth=20,
    )

    return exploded or []


def _aggregate_piece_requirements(unit_demands: list[dict]) -> list[dict]:
    bucket = defaultdict(lambda: {
        "item_code": "",
        "item_name": "",
        "length_mm": 0,
        "width_mm": 0,
        "thickness_mm": 0,
        "qty": 0,
    })

    for d in unit_demands:
        item_code = d.get("piece_item_code")
        if not item_code:
            continue

        key = (
            item_code,
            flt(d.get("length_mm") or 0),
            flt(d.get("width_mm") or 0),
        )

        bucket[key]["item_code"] = item_code
        bucket[key]["item_name"] = d.get("piece_item_name") or _get_item_name(item_code)
        bucket[key]["length_mm"] = flt(d.get("length_mm") or 0)
        bucket[key]["width_mm"] = flt(d.get("width_mm") or 0)
        bucket[key]["thickness_mm"] = flt(d.get("thickness_mm") or 0)
        bucket[key]["qty"] += flt(d.get("qty") or 0)

    return list(bucket.values())


def _get_available_piece_qty(piece_item_code: str, warehouse: str | None, length_mm: float, width_mm: float, thickness_mm: float = 0) -> float:
    if not piece_item_code or not warehouse:
        return 0

    L, W = _norm_dims(length_mm, width_mm)

    rows = frappe.get_all(
        "Serial No",
        filters={
            "item_code": piece_item_code,
            "warehouse": warehouse,
            "custom_material_status": ["in", ["Full", "Partial"]],
        },
        fields=[
            "name",
            "custom_dimension_length_mm",
            "custom_dimension_width_mm",
            "custom_dimension_thickness_mm",
        ],
        limit_page_length=10000,
    )

    count = 0
    for r in rows:
        rL, rW = _norm_dims(
            flt(r.get("custom_dimension_length_mm") or 0),
            flt(r.get("custom_dimension_width_mm") or 0),
        )

        if rL == L and rW == W:
            count += 1

    return count


def _compute_max_satisfiable_qty_for_so_row(so, row) -> float:
    unit_requirements = _aggregate_piece_requirements(
        _explode_so_row_to_piece_requirements(so, row, 1)
    )

    if not unit_requirements:
        return 0

    ratios = []
    for req in unit_requirements:
        available = _get_available_piece_qty_all_warehouses(
            req["item_code"],
            so.company,
            req["length_mm"],
            req["width_mm"],
            req.get("thickness_mm"),
        )

        needed = flt(req["qty"])
        if needed <= 0:
            continue

        ratios.append(math.floor(available / needed))

    if not ratios:
        return 0

    return min(ratios)


@frappe.whitelist()
def get_pending_sales_order_lines_for_repack(company=None, sales_order=None, customer=None):
    so_filters = {"docstatus": 1}
    if company:
        so_filters["company"] = company
    if sales_order:
        so_filters["name"] = sales_order
    if customer:
        so_filters["customer"] = customer

    sales_orders = frappe.get_all(
        "Sales Order",
        filters=so_filters,
        fields=["name", "customer", "company", "transaction_date", "delivery_date"],
        order_by="transaction_date asc",
        limit_page_length=500,
    )

    results = []

    for so_meta in sales_orders:
        so = frappe.get_doc("Sales Order", so_meta.name)

        for row in so.items:
            if not row.item_code:
                continue

            item_type = _get_item_type(row.item_code)
            if item_type not in CUTTING_TYPES:
                continue

            qty_ordered = flt(row.qty)
            if qty_ordered <= 0:
                continue

            qty_generated = _get_generated_qty_by_so_item(row.name)
            qty_pending = max(0, qty_ordered - qty_generated)
            if qty_pending <= 0:
                continue

            length_mm = flt(row.get("custom_client_length_mm") or 0)
            width_mm = flt(row.get("custom_client_width_mm") or 0)
            thickness_mm = flt(row.get("custom_client_thickness_mm") or 0)

            try:
                qty_satisfiable = flt(_compute_max_satisfiable_qty_for_so_row(so, row))
            except Exception:
                qty_satisfiable = 0

            qty_generable = min(qty_pending, qty_satisfiable)

            results.append({
                "sales_order": so.name,
                "sales_order_item": row.name,
                "item_code": row.item_code,
                "item_name": row.item_name,
                "length_mm": length_mm,
                "width_mm": width_mm,
                "thickness_mm": thickness_mm,
                "qty_ordered": qty_ordered,
                "qty_generated": qty_generated,
                "qty_pending": qty_pending,
                "qty_satisfiable": qty_satisfiable,
                "qty_generable": qty_generable,
                "customer": so.customer,
                "transaction_date": str(so.transaction_date) if so.transaction_date else "",
            })

    results.sort(key=lambda d: (
        d.get("sales_order") or "",
        d.get("item_code") or "",
        -(flt(d.get("qty_generable") or 0)),
    ))

    return results


def _pick_exact_serials(piece_item_code: str, warehouse: str | None, length_mm: float, width_mm: float, thickness_mm: float, needed_qty: float) -> list[str]:
    if not piece_item_code or not warehouse or needed_qty <= 0:
        return []

    L, W = _norm_dims(length_mm, width_mm)

    rows = frappe.get_all(
        "Serial No",
        filters={
            "item_code": piece_item_code,
            "warehouse": warehouse,
            "custom_material_status": ["in", ["Full", "Partial"]],
        },
        fields=[
            "name",
            "custom_dimension_length_mm",
            "custom_dimension_width_mm",
            "custom_dimension_thickness_mm",
            "creation",
        ],
        order_by="creation asc",
        limit_page_length=10000,
    )

    out = []
    for r in rows:
        rL, rW = _norm_dims(
            flt(r.get("custom_dimension_length_mm") or 0),
            flt(r.get("custom_dimension_width_mm") or 0),
        )

        if rL == L and rW == W:
            out.append(r.name)
            if len(out) >= cint(needed_qty):
                break

    return out


def _clear_existing_repack_rows(doc):
    doc.set("items", [])


def _append_input_row(doc, req: dict, so_item_name: str):
    row = doc.append("items", {})
    row.item_code = req["item_code"]
    row.item_name = req["item_name"]
    row.s_warehouse = req["warehouse"]

    _set_stock_uom_fields(row, req["item_code"], req["qty"])

    row.custom_sales_order_item = so_item_name

    if hasattr(row, "custom_dimension_length_mm"):
        row.custom_dimension_length_mm = req["length_mm"]
    if hasattr(row, "custom_dimension_width_mm"):
        row.custom_dimension_width_mm = req["width_mm"]
    if hasattr(row, "custom_dimension_thickness_mm"):
        row.custom_dimension_thickness_mm = req.get("thickness_mm")

    serials = req.get("serials") or []
    if serials:
        row.serial_no = "\n".join(serials)

    return row

def _make_sales_order_output_serials(so, so_row, qty: float) -> list[str]:
    qty = cint(qty or 0)
    if qty <= 0:
        return []

    base = f"SOREP-{so.name}-{so_row.name}"
    serials = []

    for i in range(1, qty + 1):
        serials.append(f"{base}-{i}")

    return serials

def _make_sales_order_output_serials_with_offset(so, so_row, start_index: int, qty: float) -> list[str]:
    qty = cint(qty or 0)
    if qty <= 0:
        return []

    base = f"SOREP-{so.name}-{so_row.name}"
    serials = []

    for i in range(1, qty + 1):
        serials.append(f"{base}-{start_index + i}")

    return serials

def _append_output_row(doc, so, so_row, generate_qty: float, already_generated_qty: float = 0):
    row = doc.append("items", {})
    row.item_code = so_row.item_code
    row.item_name = so_row.item_name
    row.t_warehouse = doc.to_warehouse or _get_default_target_warehouse(so_row.item_code, so.company)

    _set_stock_uom_fields(row, so_row.item_code, generate_qty)

    row.custom_sales_order_item = so_row.name

    if hasattr(row, "custom_dimension_length_mm"):
        row.custom_dimension_length_mm = flt(so_row.get("custom_client_length_mm") or 0)
    if hasattr(row, "custom_dimension_width_mm"):
        row.custom_dimension_width_mm = flt(so_row.get("custom_client_width_mm") or 0)
    if hasattr(row, "custom_dimension_thickness_mm"):
        row.custom_dimension_thickness_mm = flt(so_row.get("custom_client_thickness_mm") or 0)

    if hasattr(row, "set_basic_rate_manually"):
        row.set_basic_rate_manually = 1

    has_serial_no = cint(frappe.db.get_value("Item", so_row.item_code, "has_serial_no") or 0)
    if has_serial_no == 1:
        serials = _make_sales_order_output_serials_with_offset(
            so,
            so_row,
            start_index=cint(already_generated_qty),
            qty=generate_qty,
        )
        if serials:
            row.serial_no = "\n".join(serials)

    return row


@frappe.whitelist()
def generate_repack_from_sales_order_item(stock_entry_name, sales_order_item_name, generate_qty=None):
    doc = frappe.get_doc("Stock Entry", stock_entry_name)

    if doc.docstatus != 0:
        frappe.throw(_("Only draft Stock Entry can be populated."))

    if doc.stock_entry_type != "Repack":
        frappe.throw(_("Stock Entry must be of type Repack."))

    if not sales_order_item_name:
        frappe.throw(_("sales_order_item_name is required."))

    so_row_meta = frappe.db.get_value(
        "Sales Order Item",
        sales_order_item_name,
        ["name", "parent", "item_code", "item_name", "qty", "custom_client_length_mm", "custom_client_width_mm", "custom_client_thickness_mm"],
        as_dict=True,
    )
    if not so_row_meta:
        frappe.throw(_("Sales Order Item not found: {0}").format(sales_order_item_name))

    so = frappe.get_doc("Sales Order", so_row_meta.parent)
    so_row = None
    for r in so.items:
        if r.name == sales_order_item_name:
            so_row = r
            break

    if not so_row:
        frappe.throw(_("Sales Order row not found in parent order."))

    qty_generated = _get_generated_qty_by_so_item(so_row.name)
    qty_pending = max(0, flt(so_row.qty) - qty_generated)
    if qty_pending <= 0:
        frappe.throw(_("This Sales Order line is already fully generated in Repack."))

    qty_satisfiable = flt(_compute_max_satisfiable_qty_for_so_row(so, so_row))
    if qty_satisfiable <= 0:
        frappe.throw(_("No satisfiable quantity found from available cutting stock."))

    if generate_qty is None or flt(generate_qty) <= 0:
        generate_qty = min(qty_pending, qty_satisfiable)

    generate_qty = flt(generate_qty)

    if generate_qty > qty_pending:
        frappe.throw(_("Generate Qty cannot exceed pending quantity ({0}).").format(qty_pending))

    if generate_qty > qty_satisfiable:
        frappe.throw(_("Generate Qty cannot exceed stock-satisfiable quantity ({0}).").format(qty_satisfiable))

    exploded = _explode_so_row_to_piece_requirements(so, so_row, generate_qty)
    piece_requirements = _aggregate_piece_requirements(exploded)

    input_rows = []
    shortages = []

    for req in piece_requirements:
        serial_allocations = _pick_exact_serials_all_warehouses(
            req["item_code"],
            so.company,
            req["length_mm"],
            req["width_mm"],
            req.get("thickness_mm"),
            req["qty"],
        )

        if len(serial_allocations) < cint(req["qty"]):
            shortages.append({
                "item_code": req["item_code"],
                "required_qty": req["qty"],
                "available_qty": len(serial_allocations),
                "warehouses": list({d["warehouse"] for d in serial_allocations}),
            })
            continue

        by_wh = _group_serial_allocations_by_warehouse(serial_allocations)

        for wh, serials in by_wh.items():
            input_rows.append({
                "item_code": req["item_code"],
                "item_name": req["item_name"],
                "warehouse": wh,
                "qty": len(serials),
                "length_mm": req["length_mm"],
                "width_mm": req["width_mm"],
                "thickness_mm": req.get("thickness_mm"),
                "serials": serials,
            })

    if shortages:
        frappe.throw(_("Unable to allocate full inputs from stock. Please refresh the candidate list and retry."))

    _clear_existing_repack_rows(doc)

    doc.custom_sales_order = so.name
    doc.custom_sales_order_item = so_row.name

    for req in input_rows:
        _append_input_row(doc, req, so_row.name)

    _append_output_row(doc, so, so_row, generate_qty, already_generated_qty=qty_generated)

    if hasattr(doc, "set_basic_rate_manually"):
        doc.set_basic_rate_manually = 1

    doc.save(ignore_permissions=True)

    frappe.throw(_("Stock Entry {0} generated successfully.").format(doc.name), title=_("Success"))
    return {
        "stock_entry": doc.name,
        "sales_order": so.name,
        "sales_order_item": so_row.name,
        "generated_qty": generate_qty,
        "input_count": len(input_rows),
    }

@frappe.whitelist()
def create_repack_from_sales_order_item(company, sales_order_item_name, generate_qty=None):
    if not sales_order_item_name:
        frappe.throw(_("sales_order_item_name is required."))

    so_row_meta = frappe.db.get_value(
        "Sales Order Item",
        sales_order_item_name,
        ["name", "parent", "item_code", "item_name", "qty", "custom_client_length_mm", "custom_client_width_mm", "custom_client_thickness_mm"],
        as_dict=True,
    )
    if not so_row_meta:
        frappe.throw(_("Sales Order Item not found: {0}").format(sales_order_item_name))

    so = frappe.get_doc("Sales Order", so_row_meta.parent)
    so_row = None
    for r in so.items:
        if r.name == sales_order_item_name:
            so_row = r
            break

    if not so_row:
        frappe.throw(_("Sales Order row not found in parent order."))

    qty_generated = _get_generated_qty_by_so_item(so_row.name)
    qty_pending = max(0, flt(so_row.qty) - qty_generated)
    if qty_pending <= 0:
        frappe.throw(_("This Sales Order line is already fully generated in Repack."))

    qty_satisfiable = flt(_compute_max_satisfiable_qty_for_so_row(so, so_row))
    if qty_satisfiable <= 0:
        frappe.throw(_("No satisfiable quantity found from available cutting stock."))

    if generate_qty is None or flt(generate_qty) <= 0:
        generate_qty = min(qty_pending, qty_satisfiable)

    generate_qty = flt(generate_qty)

    if generate_qty > qty_pending:
        frappe.throw(_("Generate Qty cannot exceed pending quantity ({0}).").format(qty_pending))

    if generate_qty > qty_satisfiable:
        frappe.throw(_("Generate Qty cannot exceed stock-satisfiable quantity ({0}).").format(qty_satisfiable))

    exploded = _explode_so_row_to_piece_requirements(so, so_row, generate_qty)
    piece_requirements = _aggregate_piece_requirements(exploded)

    input_rows = []
    shortages = []

    for req in piece_requirements:
        serial_allocations = _pick_exact_serials_all_warehouses(
            req["item_code"],
            so.company,
            req["length_mm"],
            req["width_mm"],
            req.get("thickness_mm"),
            req["qty"],
        )

        if len(serial_allocations) < cint(req["qty"]):
            shortages.append({
                "item_code": req["item_code"],
                "required_qty": req["qty"],
                "available_qty": len(serial_allocations),
                "warehouses": list({d["warehouse"] for d in serial_allocations}),
            })
            continue

        by_wh = _group_serial_allocations_by_warehouse(serial_allocations)

        for wh, serials in by_wh.items():
            input_rows.append({
                "item_code": req["item_code"],
                "item_name": req["item_name"],
                "warehouse": wh,
                "qty": len(serials),
                "length_mm": req["length_mm"],
                "width_mm": req["width_mm"],
                "thickness_mm": req.get("thickness_mm"),
                "serials": serials,
            })

    if shortages:
        frappe.throw(_("Unable to allocate full inputs from stock. Please refresh the candidate list and retry."))

    doc = frappe.new_doc("Stock Entry")
    doc.stock_entry_type = "Repack"
    doc.company = company or so.company
    doc.custom_sales_order = so.name

    # si vous avez un to_warehouse par défaut, vous pouvez le renseigner ici
    # doc.to_warehouse = ...

    for req in input_rows:
        _append_input_row(doc, req, so_row.name)

    _append_output_row(doc, so, so_row, generate_qty, already_generated_qty=qty_generated)

    for d in doc.items:
        if d.item_code and not d.uom:
            stock_uom = frappe.db.get_value("Item", d.item_code, "stock_uom")
            d.uom = stock_uom
            d.stock_uom = stock_uom
        if not d.conversion_factor:
            d.conversion_factor = 1
        if d.qty and not d.transfer_qty:
            d.transfer_qty = d.qty
        if d.qty and not d.stock_qty:
            d.stock_qty = d.qty

        if hasattr(d, "set_basic_rate_manually"):
            if d.t_warehouse:
                d.set_basic_rate_manually = 1

    ensure_repack_output_serials_and_bundles_for_stock_entry(doc)
    doc.insert(ignore_permissions=True)

    return {
        "stock_entry": doc.name,
        "sales_order": so.name,
        "sales_order_item": so_row.name,
        "generated_qty": generate_qty,
    }

def _get_candidate_warehouses_for_piece(piece_item_code: str, company: str | None = None) -> list[str]:
    rows = frappe.get_all(
        "Bin",
        filters={
            "item_code": piece_item_code,
            "actual_qty": [">", 0],
        },
        fields=["warehouse"],
        limit_page_length=1000,
    )

    warehouses = [r.warehouse for r in rows if r.warehouse]

    if company:
        filtered = []
        for wh in warehouses:
            wh_company = frappe.db.get_value("Warehouse", wh, "company")
            if not wh_company or wh_company == company:
                filtered.append(wh)
        warehouses = filtered

    return list(dict.fromkeys(warehouses))


def _get_available_piece_qty_all_warehouses(
    piece_item_code: str,
    company: str | None,
    length_mm: float,
    width_mm: float,
    thickness_mm: float = 0
) -> float:
    warehouses = _get_candidate_warehouses_for_piece(piece_item_code, company)
    total = 0

    for wh in warehouses:
        total += _get_available_piece_qty(
            piece_item_code,
            wh,
            length_mm,
            width_mm,
            thickness_mm,
        )

    return total

def _pick_exact_serials_all_warehouses(
    piece_item_code: str,
    company: str | None,
    length_mm: float,
    width_mm: float,
    thickness_mm: float,
    needed_qty: float
) -> list[dict]:
    if not piece_item_code or needed_qty <= 0:
        return []

    warehouses = _get_candidate_warehouses_for_piece(piece_item_code, company)
    out = []
    remaining = cint(needed_qty)

    for wh in warehouses:
        serials = _pick_exact_serials(
            piece_item_code,
            wh,
            length_mm,
            width_mm,
            thickness_mm,
            remaining,
        )

        for sn in serials:
            out.append({
                "serial_no": sn,
                "warehouse": wh,
            })

        remaining = cint(needed_qty) - len(out)
        if remaining <= 0:
            break

    return out

def _group_serial_allocations_by_warehouse(serial_allocations: list[dict]) -> dict:
    bucket = defaultdict(list)

    for d in serial_allocations:
        bucket[d["warehouse"]].append(d["serial_no"])

    return dict(bucket)

