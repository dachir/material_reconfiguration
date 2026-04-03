"""Service functions to fetch available stock bins for cutting.

This module provides a helper to retrieve Serial No documents that can
be used as input material for cutting plans.  Only serials in the
specified warehouse and with a material status of "Full" or "Partial"
are returned.  Dimensions are normalized so that length is always the
greater of the two dimensions and width the lesser.  The result is
sorted by length then width ascending to aid in deterministic packing.

Example usage::

    bins = get_available_cutting_bins(
        item_code="RAW-MAT-01",
        warehouse="Finished Goods - WH",
    )

    for b in bins:
        print(b["serial_no"], b["length_mm"], b["width_mm"], b["material_status"])

"""

from __future__ import annotations

import frappe


VALID_MATERIAL_STATUSES = ("Full", "Partial")


def _unique_codes(values: list[str] | None) -> list[str]:
    seen = set()
    out = []
    for value in values or []:
        code = (value or "").strip()
        if not code or code in seen:
            continue
        seen.add(code)
        out.append(code)
    return out


def _normalize_bin_dimensions(length_mm: float, width_mm: float) -> tuple[float, float]:
    """Always keep length >= width for the cutting engine."""
    return max(length_mm, width_mm), min(length_mm, width_mm)


def _build_sort_key(
    *,
    row_item_code: str,
    row_material_status: str,
    row_length_mm: float,
    row_width_mm: float,
    row_name: str,
    source_item: str,
    variant_item_codes: list[str],
    serial_order: dict[str, int] | None = None,
) -> tuple:
    """Business ordering:
    1. leftovers of source_item
    2. leftovers of variants
    3. full sheets of source_item
    4. full sheets of variants

    If serial_order is provided, preserve explicit order from the MCP table.
    """
    if serial_order is not None and row_name in serial_order:
        return (serial_order[row_name],)

    is_leftover = (row_material_status or "").strip() == "Partial"
    is_source = row_item_code == source_item

    if is_source and is_leftover:
        group_rank = 0
    elif (not is_source) and is_leftover:
        group_rank = 1
    elif is_source and not is_leftover:
        group_rank = 2
    else:
        group_rank = 3

    item_rank_map = {source_item: 0}
    for idx, code in enumerate(variant_item_codes or [], start=1):
        item_rank_map[code] = idx

    return (
        group_rank,
        item_rank_map.get(row_item_code, 999),
        row_length_mm,
        row_width_mm,
        row_name,
    )


def get_available_cutting_bins(
    item_code: str,
    warehouse: str | None = None,
    variant_item_codes: list[str] | None = None,
    serial_nos: list[str] | None = None,
) -> list[dict[str, object]]:
    """Return cutting bins for MCP.

    Args:
        item_code: source raw material item.
        warehouse: optional warehouse filter.
        variant_item_codes: optional variant items to include.
        serial_nos: optional explicit list of serial numbers to return.
            When supplied, output order follows the given serial order.

    Returns:
        A list of normalized cutting bins usable by the cutting engine.
    """
    source_item = (item_code or "").strip()
    if not source_item:
        return []

    variant_item_codes = [c for c in _unique_codes(variant_item_codes) if c != source_item]
    eligible_items = _unique_codes([source_item] + variant_item_codes)
    if not eligible_items:
        return []

    serial_nos = _unique_codes(serial_nos)
    serial_order = {sn: idx for idx, sn in enumerate(serial_nos)} if serial_nos else None

    filters: dict[str, object] = {
        "item_code": ["in", eligible_items],
        "custom_material_status": ["in", list(VALID_MATERIAL_STATUSES)],
    }
    if warehouse:
        filters["warehouse"] = warehouse
    if serial_nos:
        filters["name"] = ["in", serial_nos]

    rows = frappe.get_all(
        "Serial No",
        filters=filters,
        fields=[
            "name",
            "item_code",
            "warehouse",
            "custom_dimension_length_mm",
            "custom_dimension_width_mm",
            "custom_dimension_thickness_mm",
            "custom_material_status",
        ],
        limit_page_length=2000,
    )

    results: list[dict[str, object]] = []
    seen_serials = set()

    for row in rows:
        serial_no = row.name
        if not serial_no or serial_no in seen_serials:
            continue

        length_mm = float(row.custom_dimension_length_mm or 0)
        width_mm = float(row.custom_dimension_width_mm or 0)
        thickness_mm = float(row.custom_dimension_thickness_mm or 0)

        if length_mm <= 0 or width_mm <= 0:
            continue

        l_norm, w_norm = _normalize_bin_dimensions(length_mm, width_mm)
        material_status = (row.custom_material_status or "").strip()

        results.append(
            {
                "serial_no": serial_no,
                "item_code": row.item_code,
                "warehouse": row.warehouse,
                "length_mm": l_norm,
                "width_mm": w_norm,
                "thickness_mm": thickness_mm,
                "area_mm2": l_norm * w_norm,
                "material_status": material_status,
                "source_kind": "Full Sheet" if material_status == "Full" else "Leftover",
            }
        )
        seen_serials.add(serial_no)

    results.sort(
        key=lambda d: _build_sort_key(
            row_item_code=str(d.get("item_code") or ""),
            row_material_status=str(d.get("material_status") or ""),
            row_length_mm=float(d.get("length_mm") or 0),
            row_width_mm=float(d.get("width_mm") or 0),
            row_name=str(d.get("serial_no") or ""),
            source_item=source_item,
            variant_item_codes=variant_item_codes,
            serial_order=serial_order,
        )
    )
    return results


