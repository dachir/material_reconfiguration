"""Services for exploding Sales Orders into individual cutting demands.

This module provides functions to expand composite items (OUVRAGE) into
their component pieces (DECOUPE) and produce a flat list of unit
cutting demands.  Each demand includes the unique piece identifier,
dimensions, quantity, and contextual information such as the sales
order and customer.  The recursion depth can be limited to prevent
infinite loops when circular references exist.

The component structure is determined from custom fields on the Item
doctype.  Composite items list their components in the child table
``custom_composite_items`` with fields ``component_item_code`` and
``qty_factor``.  Piece items are identified by the custom item type
``DECOUPE`` and are treated as terminal nodes in the explosion.

Example usage::

    demands = explode_sales_orders_into_cutting_demands([
        "SO-0001", "SO-0002"
    ], max_depth=10)

    for d in demands:
        print(d["piece_uid"], d["length_mm"], d["width_mm"], d["qty"])

"""

from __future__ import annotations

import frappe
from frappe import _


# Custom field names defining the composite structure on Item
COMPONENT_TABLE_FIELD = "custom_composite_items"
COMPONENT_ITEM_FIELD = "component_item_code"
COMPONENT_QTY_FIELD = "qty_factor"


def explode_sales_orders_into_cutting_demands(
    sales_order_names: list[str], max_depth: int = 10
) -> list[dict[str, object]]:
    """Explode the given Sales Orders into unit cutting demands.

    For each Sales Order, iterate through its items.  Items of type
    ``DECOUPE`` or ``OUVRAGE`` are processed, while other item types
    are ignored.  Quantities less than or equal to zero are skipped.

    For ``DECOUPE`` items, the function verifies the presence of
    cutting dimensions (via custom fields on the Sales Order item) and
    creates one demand per unit quantity.  For ``OUVRAGE`` items, the
    explosion proceeds recursively into the composite structure using
    the helper :func:`explode_item_to_decoupes`.

    Args:
        sales_order_names: A list of Sales Order document names to
            explode.
        max_depth: The maximum recursion depth allowed when exploding
            composite items.  This prevents infinite loops due to
            circular references.

    Returns:
        A list of dictionaries describing unit cutting demands.  Each
        dictionary contains keys such as ``piece_uid``, ``length_mm``,
        ``width_mm``, ``qty``, and context fields.
    """
    results: list[dict[str, object]] = []

    for so_name in sales_order_names:
        so = frappe.get_doc("Sales Order", so_name)

        for row in so.items:
            item_code = row.item_code
            if not item_code:
                continue

            # Determine the custom item type from the Item document
            item_type = (frappe.db.get_value("Item", item_code, "custom_item_types") or "").strip()
            if item_type not in ("DECOUPE", "OUVRAGE"):
                # Skip non-cutting items
                continue

            so_qty = float(row.qty or 0)
            if so_qty <= 0:
                continue

            # Extract cutting dimensions from the Sales Order item.  The
            # fields used here should match your custom fields for
            # length and width on the SO item.  Fallbacks are provided
            # to support legacy naming conventions.
            length_mm = float(row.get("custom_client_length_mm") or 0)
            width_mm = float(row.get("custom_client_width_mm") or 0)

            # Extract thickness (épaisseur) if provided.  The field names
            # should align with your custom thickness fields on the
            # Sales Order item.  Fallback to zero if not found.
            thickness_mm = float(row.get("custom_client_thickness_mm") or 0)  

            # Build a context for downstream functions
            ctx = {
                "sales_order": so.name,
                "sales_order_item": row.name,
                "root_item_code": item_code,
                "root_item_name": row.item_name,
                "customer": so.customer,
                "delivery_date": so.delivery_date,
                "project": so.project,
                "base_length_mm": length_mm,
                "base_width_mm": width_mm,
                "base_thickness_mm": thickness_mm,
            }

            # Recursively explode the item into unit demands
            exploded = explode_item_to_decoupes(
                item_code=item_code,
                parent_qty=so_qty,
                context=ctx,
                path=[],
                path_labels=[],
                depth=0,
                max_depth=max_depth,
            )
            results.extend(exploded)

    return results


def explode_item_to_decoupes(
    item_code: str,
    parent_qty: float,
    context: dict[str, object],
    path: list[str] | None = None,
    path_labels: list[str] | None = None,
    depth: int = 0,
    max_depth: int = 10,
) -> list[dict[str, object]]:
    """Recursively explode an item into unit cutting demands.

    Given an ``item_code`` and the quantity of that item required,
    determine whether the item is a terminal piece (``DECOUPE``) or
    composite item (``OUVRAGE``).  For terminal pieces, call
    :func:`build_unit_cutting_demands` to create one demand per unit.
    For composite items, recurse into each component using the
    component table defined by the custom fields at the top of this
    module.  The recursion stops when the depth exceeds ``max_depth``
    or when a circular reference is detected.

    Args:
        item_code: The code of the item being exploded.
        parent_qty: The quantity of the parent item required.
        context: A dictionary carrying contextual information from the
            root Sales Order item, such as dimensions and customer.
        path: The list of item codes traversed so far.  Used to detect
            circular references.
        path_labels: The list of human-readable names corresponding to
            the ``path``.  Useful for error messages or audit.
        depth: The current recursion depth.
        max_depth: Maximum allowed recursion depth.

    Returns:
        A list of unit cutting demands.  See
        :func:`build_unit_cutting_demands` for field details.
    """
    if path is None:
        path = []
    if path_labels is None:
        path_labels = []

    # Detect cycles
    if item_code in path:
        raise frappe.ValidationError(
            _(
                "Recursive loop detected in OUVRAGE structure: {0}"
            ).format(" -> ".join(path + [item_code]))
        )

    if depth > max_depth:
        raise frappe.ValidationError(
            _(
                "Maximum explosion depth exceeded for item {0}."
            ).format(item_code)
        )

    if float(parent_qty or 0) <= 0:
        raise frappe.ValidationError(
            _(
                "Invalid quantity {0} for item {1}."
            ).format(parent_qty, item_code)
        )

    item_doc = frappe.get_doc("Item", item_code)
    item_type = (item_doc.get("custom_item_types") or "").strip()

    new_path = path + [item_code]
    new_path_labels = path_labels + [item_doc.item_name or item_code]

    if item_type == "DECOUPE":
        # Terminal node: build unit demands
        return build_unit_cutting_demands(
            piece_item=item_doc,
            qty=parent_qty,
            context=context,
            path=new_path,
            path_labels=new_path_labels,
            depth=depth,
        )

    if item_type == "OUVRAGE":
        # Recursively explode each component
        components = get_ouvrage_components(item_doc)
        if not components:
            raise frappe.ValidationError(
                _(
                    "OUVRAGE item {0} has no components in {1}."
                ).format(item_code, COMPONENT_TABLE_FIELD)
            )

        results: list[dict[str, object]] = []
        for comp in components:
            comp_item_code = comp["item_code"]
            comp_qty = comp["qty_factor"]

            if not comp_item_code:
                raise frappe.ValidationError(
                    _(
                        "A component in item {0} has no component item code."
                    ).format(item_code)
                )

            if float(comp_qty or 0) <= 0:
                raise frappe.ValidationError(
                    _(
                        "Invalid qty_factor for component {0} in parent {1}."
                    ).format(comp_item_code, item_code)
                )

            effective_qty = float(parent_qty) * float(comp_qty)
            results.extend(
                explode_item_to_decoupes(
                    item_code=comp_item_code,
                    parent_qty=effective_qty,
                    context=context,
                    path=new_path,
                    path_labels=new_path_labels,
                    depth=depth + 1,
                    max_depth=max_depth,
                )
            )

        return results

    # Non-cutting items produce no demands
    return []


def get_ouvrage_components(item_doc: frappe.model.document.Document) -> list[dict[str, object]]:
    """Return a list of components for the given OUVRAGE item.

    The child table defining the components resides in the field
    ``COMPONENT_TABLE_FIELD`` on the Item doctype.  Each row in the
    table should include a component item code and a quantity factor.

    Args:
        item_doc: The Item document representing an OUVRAGE.

    Returns:
        A list of dictionaries with keys ``item_code`` and
        ``qty_factor``.  The quantity factor is converted to float and
        defaults to zero if missing.
    """
    results: list[dict[str, object]] = []
    for row in item_doc.get(COMPONENT_TABLE_FIELD, []):
        results.append({
            "item_code": row.get(COMPONENT_ITEM_FIELD),
            "qty_factor": float(row.get(COMPONENT_QTY_FIELD) or 0),
        })
    return results


def build_unit_cutting_demands(
    piece_item: frappe.model.document.Document,
    qty: float,
    context: dict[str, object],
    path: list[str],
    path_labels: list[str],
    depth: int,
) -> list[dict[str, object]]:
    """Create unit cutting demands for a terminal DECOUPE item.

    This helper converts a quantity of a DECOUPE item into individual
    unit demands.  Each demand has a unique ``piece_uid`` that ties
    together the Sales Order, the Sales Order item row, the piece
    item code and the serial within the quantity.  Dimensions and
    contextual information are inherited from the original Sales Order
    item via ``context``.

    Args:
        piece_item: The Item document representing a DECOUPE.
        qty: The total quantity of this piece required.
        context: Context dictionary from the root Sales Order item.
        path: List of item codes traversed to reach this piece.
        path_labels: Human-readable names corresponding to ``path``.
        depth: Current recursion depth (for audit purposes).

    Returns:
        A list of dictionaries, one per unit quantity.
    """
    results: list[dict[str, object]] = []
    length_mm = float(context.get("base_length_mm") or 0)
    width_mm = float(context.get("base_width_mm") or 0)
    thickness_mm = float(context.get("base_thickness_mm") or 0)
    # Validate that all dimensions are positive
    if length_mm <= 0 or width_mm <= 0 or thickness_mm <= 0:
        raise frappe.ValidationError(
            _(
                "Missing cutting dimensions or thickness for Sales Order Item {0}."
            ).format(context.get("sales_order_item"))
        )

    # Verify that qty is an integer (cannot produce fractional units)
    int_qty = int(qty)
    if int_qty != qty:
        raise frappe.ValidationError(
            _(
                "Exploded quantity {0} is not an integer for item {1}."
            ).format(qty, piece_item.name)
        )

    for i in range(1, int_qty + 1):
        results.append({
            "piece_uid": f"{context['sales_order']}::{context['sales_order_item']}::{piece_item.name}::{i}",
            "sales_order": context["sales_order"],
            "sales_order_item": context["sales_order_item"],
            "root_item_code": context["root_item_code"],
            "root_item_name": context["root_item_name"],
            "piece_item_code": piece_item.name,
            "piece_item_name": piece_item.item_name,
            "length_mm": length_mm,
            "width_mm": width_mm,
            "thickness_mm": thickness_mm,
            "qty": 1,
            "uom": piece_item.stock_uom,
            "custom_item_types": "DECOUPE",
            "path": path,
            "path_labels": path_labels,
            "depth": depth,
            "source_context": {
                "customer": context.get("customer"),
                "delivery_date": context.get("delivery_date"),
                "project": context.get("project"),
            },
        })

    return results

