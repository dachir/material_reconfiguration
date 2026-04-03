import frappe
import json
from frappe.utils import flt, cint
from mat_reco.material_reconfiguration.doctype.item_variant_detail.item_variant_detail import (
    validate_variant_item_code,
)
from mat_reco.material_reconfiguration.services.stock_candidate_service import (
    get_available_cutting_bins,
)

def _coerce_variant_item_codes(item_variants) -> list[str]:
    """Accept list[str], list[dict], JSON string, or None."""
    if not item_variants:
        return []

    if isinstance(item_variants, str):
        item_variants = item_variants.strip()
        if not item_variants:
            return []
        try:
            item_variants = json.loads(item_variants)
        except Exception:
            item_variants = [x.strip() for x in item_variants.replace("\n", ",").split(",") if x.strip()]

    result = []
    for row in item_variants or []:
        code = ""
        if isinstance(row, str):
            code = row
        elif isinstance(row, dict):
            code = row.get("variant_item_code") or ""
        else:
            code = getattr(row, "variant_item_code", "") or ""

        code = (code or "").strip()
        if not code or code in result:
            continue
        result.append(code)

    return result


@frappe.whitelist()
def get_item_variants_for_mcp(source_item: str) -> list[dict[str, str]]:
    """Load the Item.custom_item_variant_detail rows into MCP.item_variant_detail."""
    source_item = (source_item or "").strip()
    if not source_item:
        return []

    source_type = (frappe.db.get_value("Item", source_item, "custom_item_types") or "").strip()
    if source_type != "PRIMAIRE":
        frappe.throw(_("Source Item must be of type PRIMAIRE."))

    item_doc = frappe.get_doc("Item", source_item)

    rows = []
    seen = set()
    for row in item_doc.get("custom_item_variant_detail", []) or []:
        code = validate_variant_item_code(row.variant_item_code, source_item=source_item)
        if not code or code in seen:
            continue
        seen.add(code)
        rows.append({"variant_item_code": code})

    return rows


@frappe.whitelist()
def get_stock_for_mcp(
    source_item: str,
    source_warehouse: str | None = None,
    item_variants=None,
) -> list[dict[str, object]]:
    """Return MCP stock candidates ordered by business priority."""
    source_item = (source_item or "").strip()
    source_warehouse = (source_warehouse or "").strip()

    if not source_item:
        frappe.throw(_("Source Item is required."))

    source_type = (frappe.db.get_value("Item", source_item, "custom_item_types") or "").strip()
    if source_type != "PRIMAIRE":
        frappe.throw(_("Source Item must be of type PRIMAIRE."))

    variant_codes = _coerce_variant_item_codes(item_variants)
    validated_variant_codes = []
    for code in variant_codes:
        code = validate_variant_item_code(code, source_item=source_item)
        if code and code not in validated_variant_codes:
            validated_variant_codes.append(code)

    bins = get_available_cutting_bins(
        item_code=source_item,
        warehouse=source_warehouse or None,
        variant_item_codes=validated_variant_codes,
    )

    candidates = []
    for b in bins:
        candidates.append(
            {
                "serial_no": b.get("serial_no"),
                "item_code": b.get("item_code"),
                "warehouse": b.get("warehouse"),
                "material_status": b.get("material_status"),
                "length_mm": b.get("length_mm"),
                "width_mm": b.get("width_mm"),
                "thickness_mm": b.get("thickness_mm"),
                "is_qualified": 1,
            }
        )

    return candidates

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
    fg_rows = [
        l for l in lines
        if (l.line_type or "") == "Output"
        and l.categorie == "Finished Good"
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
    fg_serials = []
    for l in fg_rows:
        if getattr(l, "serial_nos", None):
            parts = [s.strip() for s in l.serial_nos.replace("\n", ",").split(",") if s.strip()]
            for sn in parts:
                if sn not in fg_serials:
                    fg_serials.append(sn)
        elif l.serial_no:
            if l.serial_no not in fg_serials:
                fg_serials.append(l.serial_no)

    fg_qty = len(fg_serials) if fg_serials else sum(flt(l.planned_pieces) for l in fg_rows)

    repack_lines.append({
        "row_type": "FG",
        "item_code": mr.fg_item_code,
        "s_warehouse": None,
        "t_warehouse": mr.source_warehouse,   # as you requested
        "qty": fg_qty,
        "serials": fg_serials
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

@frappe.whitelist()
def get_orders_by_source_item(source_item: str) -> list[dict[str, object]]:
    """Return Sales Orders that contain decoupe items linked to the given source item.

    A Sales Order is included if it contains at least one item of type
    ``DECOUPE`` whose ``custom_parent_item`` field matches the
    provided ``source_item`` code.  Only orders with ``docstatus`` 1
    (submitted) are considered.  For each qualifying order, the
    function returns its name, customer and transaction date.

    Args:
        source_item: The code of the raw material to filter orders by.

    Returns:
        A list of dictionaries with keys ``name``, ``customer`` and
        ``transaction_date``.
    """
    if not source_item:
        return []

    # Retrieve submitted Sales Orders
    sales_orders = frappe.get_all(
        "Sales Order",
        filters={"docstatus": 1},
        fields=["name", "customer", "transaction_date"],
        order_by="transaction_date asc",
    )

    result: list[dict[str, object]] = []

    for so in sales_orders:
        # Fetch items for this Sales Order
        rows = frappe.get_all(
            "Sales Order Item",
            filters={"parent": so.name},
            fields=["item_code"],
        )

        keep = False
        for row in rows:
            item_code = row.item_code
            if not item_code:
                continue
            # Determine custom item type
            item_type = (frappe.db.get_value("Item", item_code, "custom_item_types") or "").strip()
            if item_type != "DECOUPE":
                continue
            # Check if this decoupe references the selected source item via custom_parent_item
            parent_raw = frappe.db.get_value("Item", item_code, "custom_parent_item")
            if parent_raw and parent_raw == source_item:
                keep = True
                break
        if keep:
            result.append(so)
    return result

# -----------------------------------------------------------------------------
# Order selection APIs
#
# The following functions expose helper endpoints to retrieve Sales Orders
# relevant for material reconfiguration.  They mirror functionality added in
# the Material Cutting Plan module but live in the material_reconfiguration
# namespace so that front-end scripts can call them without importing
# additional modules.  Both functions operate on submitted Sales Orders
# (docstatus = 1) and filter orders based on the items they contain.

@frappe.whitelist()
def get_non_processed_orders(source_item: str | None = None) -> list[dict[str, object]]:
    """
    Return submitted Sales Orders relevant for cutting.
    If source_item is provided, only keep orders whose DECOUPE descendants
    are linked to that raw material.
    """
    sales_orders = frappe.get_all(
        "Sales Order",
        filters={"docstatus": 1},
        fields=["name", "customer", "transaction_date"],
        order_by="transaction_date asc",
    )

    result = []

    for so in sales_orders:
        rows = frappe.get_all(
            "Sales Order Item",
            filters={"parent": so["name"]},
            fields=["item_code"],
        )

        keep = False

        for row in rows:
            item_code = row.get("item_code")
            if not item_code:
                continue

            item_type = (
                frappe.db.get_value("Item", item_code, "custom_item_types") or ""
            ).strip()

            if not source_item:
                if item_type in ("DECOUPE", "OUVRAGE"):
                    keep = True
                    break
                continue

            if item_type == "DECOUPE":
                if _is_descendant_of_raw(item_code=item_code, raw_item_code=source_item):
                    keep = True
                    break

            elif item_type == "OUVRAGE":
                if _ouvrage_has_decoupe_for_raw(
                    item_code=item_code,
                    raw_item_code=source_item
                ):
                    keep = True
                    break

        if keep:
            result.append(so)

    return result


@frappe.whitelist()
def get_orders_by_source_item(source_item: str) -> list[dict[str, object]]:
    """Return Sales Orders containing decoupe/ouvrage items linked to a given raw material.

    Excludes Sales Orders already linked to a non-cancelled Material Cutting Plan.
    Only Sales Orders with ``docstatus`` 1 are considered.  An order is
    included in the result if it contains at least one Sales Order Item
    whose associated Item has ``custom_item_types = 'DECOUPE'`` and a
    ``custom_parent_item`` field equal to the provided ``source_item``.  The
    returned dicts contain basic Sales Order information so that a client
    can populate a selection list.

    Args:
        source_item: The item code of the raw material used to filter
            decoupe items.  If empty, the function returns an empty list.

    Returns:
        A list of dicts with keys ``name``, ``customer`` and
        ``transaction_date`` for each qualifying Sales Order.
    """
    if not source_item:
        return []

    # Récupérer les Sales Orders déjà utilisés dans un MCP non annulé
    linked_sales_orders = set(
        frappe.db.sql(
            """
            select distinct mcp_so.sales_order
            from `tabMCP Sales Order` mcp_so
            inner join `tabMaterial Cutting Plan` mcp
                on mcp.name = mcp_so.parent
            where ifnull(mcp_so.sales_order, '') != ''
              and ifnull(mcp.docstatus, 0) < 2
              and ifnull(mcp.source_item, '') = %(source_item)s
              and ifnull(mcp.status, '') not in ('Closed', 'Completed', 'Cancelled')
            """,
            {"source_item": source_item},
            as_dict=False,
        )
    )
    linked_sales_orders = {row[0] for row in linked_sales_orders if row and row[0]}

    # Fetch all submitted Sales Orders
    sales_orders = frappe.get_all(
        "Sales Order",
        filters={"docstatus": 1},
        fields=["name", "customer", "transaction_date"],
        order_by="transaction_date asc",
    )

    result: list[dict[str, object]] = []

    for so in sales_orders:
        so_name = so.get("name")
        if not so_name:
            continue

        # Exclure les SO déjà liés à un MCP non annulé
        if so_name in linked_sales_orders:
            continue

        # Retrieve items for this Sales Order
        rows = frappe.get_all(
            "Sales Order Item",
            filters={"parent": so_name},
            fields=["item_code"],
        )

        keep = False
        for row in rows:
            item_code = row.get("item_code")
            if not item_code:
                continue

            item_type = (
                frappe.db.get_value("Item", item_code, "custom_item_types") or ""
            ).strip()

            if item_type == "DECOUPE":
                if _is_descendant_of_raw(item_code=item_code, raw_item_code=source_item):
                    keep = True
                    break

            elif item_type == "OUVRAGE":
                if _ouvrage_has_decoupe_for_raw(item_code=item_code, raw_item_code=source_item):
                    keep = True
                    break

        if keep:
            result.append(so)

    if not result:
        frappe.msgprint("No Sales Orders found for the selected source item.")

    return result

def _is_descendant_of_raw(item_code: str, raw_item_code: str, *, max_depth: int = 10) -> bool:
    """Return True if the given item descends from the specified raw material.

    The function traverses the ``custom_parent_item`` chain on the Item doctype to
    determine if the provided ``item_code`` has the given ``raw_item_code`` as
    one of its ancestors.  It stops when either the raw material is found, the
    chain terminates or a maximum depth is reached to prevent infinite loops.

    Args:
        item_code: Code of the item to start from (e.g. a DECOUPE).
        raw_item_code: Code of the raw material we are trying to match.
        max_depth: Maximum number of parents to traverse.

    Returns:
        True if ``raw_item_code`` is an ancestor of ``item_code``; False otherwise.
    """

    # Avoid trivial cases
    if not item_code or not raw_item_code:
        return False
    current = item_code
    for _ in range(max_depth):
        # Fetch the parent item of the current code
        parent = frappe.db.get_value("Item", current, "custom_parent_item") or ""
        parent = str(parent or "").strip()
        if not parent:
            # Reached top of chain without finding the raw material
            return False
        if parent == raw_item_code:
            return True
        # Move up the chain and continue searching
        current = parent
    # Maximum depth reached without a match
    return False


def _ouvrage_has_decoupe_for_raw(
    item_code: str,
    raw_item_code: str,
    *,
    depth: int = 0,
    max_depth: int = 10,
    visited: set[str] | None = None,
) -> bool:
    """Return True if an OUVRAGE item contains a decoupe linked to the raw material.

    This helper inspects the composition of an OUVRAGE item by traversing its
    ``custom_composite_items`` child table on the Item doctype.  It walks
    recursively through nested OUVRAGE and DECOUPE components, searching for
    at least one DECOUPE component that descends from the specified
    ``raw_item_code`` via the ``custom_parent_item`` chain.

    Args:
        item_code: The code of the OUVRAGE item to inspect.
        raw_item_code: The raw material code we are trying to match.
        depth: Current recursion depth (internal use).
        max_depth: Maximum allowed recursion depth to avoid infinite loops.
        visited: Set of already visited item codes to prevent cycles.

    Returns:
        True if a qualifying decoupe descendant is found; False otherwise.
    """
    # Prevent excessive recursion or cycles
    if not item_code or depth > max_depth:
        return False
    if visited is None:
        visited = set()
    if item_code in visited:
        return False
    visited.add(item_code)
    # Determine this item's type
    item_type = (
        frappe.db.get_value("Item", item_code, "custom_item_types") or ""
    ).strip()
    # If this is a DECOUPE, check if it descends from the raw material
    if item_type == "DECOUPE":
        return _is_descendant_of_raw(item_code=item_code, raw_item_code=raw_item_code)
    # If not an OUVRAGE, no further inspection needed
    if item_type != "OUVRAGE":
        return False
    # Load this item document to access its custom composite items
    try:
        item_doc = frappe.get_doc("Item", item_code)
    except Exception:
        return False
    # Iterate over components in the custom_composite_items child table
    for comp in item_doc.get("custom_composite_items", []) or []:
        comp_code = comp.get("component_item_code")
        if not comp_code:
            continue
        # Recursively check the component for matching decoupes or nested ouvrages
        if _ouvrage_has_decoupe_for_raw(
            item_code=comp_code,
            raw_item_code=raw_item_code,
            depth=depth + 1,
            max_depth=max_depth,
            visited=visited,
        ):
            return True
    # No qualifying decoupe found in this ouvrage's components
    return False
