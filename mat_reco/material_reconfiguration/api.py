import frappe
import json
from frappe.utils import flt, cint

@frappe.whitelist()
def get_repack_payload(mr_name: str) -> dict:
    mr = frappe.get_doc("Material Reconfiguration", mr_name)
    mr.check_permission("read")

    if mr.docstatus != 1:
        frappe.throw("Material Reconfiguration must be submitted first.")
    if not mr.source_item or not mr.source_warehouse:
        frappe.throw("source_item and source_warehouse are required.")
    if not mr.fg_item_code or flt(mr.fg_total_qty) <= 0:
        frappe.throw("fg_item_code and fg_total_qty are required.")

    fg_is_stock = cint(frappe.db.get_value("Item", mr.fg_item_code, "is_stock_item") or 0)
    if not fg_is_stock:
        frappe.throw("FG must be stock item for this flow.")

    lines = mr.get("detail") or []
    inputs = [l for l in lines if (l.line_type or "") == "Input" and l.serial_no]
    #outputs = [l for l in lines if (l.line_type or "") == "Output" and l.categorie != "Finished Goods" and l.serial_no]
    outputs = [
        l for l in lines
        if (l.line_type or "") == "Output"
        and l.categorie == "By Product"
        #and l.serial_no
    ]
    #frappe.throw(str(outputs))

    # ---- GROUP INPUTS: 1 line per raw material + source warehouse
    # Here raw item is always mr.source_item; if later you allow multiple raw items, group by l.item_code.
    input_serials = []
    for l in inputs:
        if l.serial_no not in input_serials:
            input_serials.append(l.serial_no)

    repack_lines = []
    if input_serials:
        repack_lines.append({
            "row_type": "Input",
            "item_code": mr.source_item,
            "s_warehouse": mr.source_warehouse,
            "t_warehouse": None,
            "qty": len(input_serials),          # important: qty = number of serials
            "serials": input_serials
        })

    # ---- FG OUTPUT: single line
    repack_lines.append({
        "row_type": "FG",
        "item_code": mr.fg_item_code,
        "s_warehouse": None,
        "t_warehouse": mr.source_warehouse,   # as you requested
        "qty": flt(mr.fg_total_qty),
        "serials": []
    })

    # ---- GROUP OUTPUTS (by-product): 1 line per (item_code + target_warehouse)
    # By-product item here is mr.source_item (remainders), but keep generic:
    out_groups = {}  # key = (item_code, t_warehouse)
    for l in outputs:
        item_code = mr.source_item
        t_wh = mr.source_warehouse
        key = (item_code, t_wh)
        out_groups.setdefault(key, [])
        if l.serial_no not in out_groups[key]:
            out_groups[key].append(l.serial_no)

    for (item_code, t_wh), serial_list in out_groups.items():
        repack_lines.append({
            "row_type": "ByProduct",
            "item_code": item_code,
            "s_warehouse": None,
            "t_warehouse": t_wh,
            "qty": len(serial_list),
            "serials": serial_list
        })

    return {
        "stock_entry_type": "Repack",
        "remarks": f"Prepared from Material Reconfiguration {mr.name}",
        "custom_material_reconfiguration": mr.name,
        "lines": repack_lines
    }


@frappe.whitelist()
def create_serial_batch_bundle(company: str, voucher_type: str, item_code: str, warehouse: str, serials, transaction_type: str = "Outward") -> str:
    if not (company and voucher_type and item_code and warehouse):
        frappe.throw("company, voucher_type, item_code, warehouse are required.")

    # serials can arrive as JSON string from JS
    if isinstance(serials, str):
        serials = serials.strip()
        try:
            serials = json.loads(serials) if serials else []
        except Exception:
            # fallback: comma/newline separated
            serials = [s.strip() for s in serials.replace("\n", ",").split(",") if s.strip()]

    serials = serials or []
    if not isinstance(serials, list):
        frappe.throw("serials must be a list (or a JSON list string).")

    if not serials:
        frappe.throw("serials is required.")

    b = frappe.new_doc("Serial and Batch Bundle")
    b.company = company
    b.voucher_type = voucher_type
    b.item_code = item_code
    b.warehouse = warehouse
    b.type_of_transaction = transaction_type

    for sn in serials:
        sn = (sn or "").strip()
        if not sn:
            continue
        e = b.append("entries", {})
        e.serial_no = sn
        e.qty = 1
        e.warehouse = warehouse

    b.insert(ignore_permissions=True)
    return b.name


@frappe.whitelist()
def get_available_serials_for_repack(item_codes: list[str] | None = None):
    """
    Return available serials for input items used in a Repack Stock Entry.
    Filters:
      - item_code in item_codes
      - custom_material_status != Consumed (and != Comsumed just in case)
    """
    if not item_codes:
        return []

    # Clean
    item_codes = [c for c in item_codes if c]
    if not item_codes:
        return []

    # We only want serialized items
    serialized = frappe.get_all(
        "Item",
        filters={"name": ["in", item_codes], "has_serial_no": 1},
        pluck="name",
    )
    if not serialized:
        return []

    # Serial No filter: status != Consumed
    rows = frappe.get_all(
        "Serial No",
        filters={
            "item_code": ["in", serialized],
            "custom_material_status": ["not in", ["Consumed", "Comsumed"]],
        },
        fields=[
            "name",
            "item_code",
            "custom_dimension_length_mm",
            "custom_dimension_width_mm",
            "custom_quality_rating",
            "custom_material_status",
        ],
        order_by="item_code asc, modified desc",
        limit_page_length=1000,
    )

    # Add item_name
    item_name_map = {}
    for code in set([r["item_code"] for r in rows]):
        item_name_map[code] = frappe.get_cached_value("Item", code, "item_name")

    for r in rows:
        r["item_name"] = item_name_map.get(r["item_code"])

    return rows

