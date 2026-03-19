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


def get_available_cutting_bins(item_code: str, warehouse: str) -> list[dict[str, object]]:
    """Return a list of Serial No documents usable for cutting plans.

    Serial numbers must belong to the specified item and warehouse and
    have a custom material status of either "Full" or "Partial".
    Dimensions (length and width) are normalized such that length is
    the larger of the two values.  Entries with non-positive
    dimensions are excluded.  The result list is sorted first by
    increasing length and then by increasing width.

    Args:
        item_code: The code of the raw material item (PRIMAIRE).
        warehouse: The warehouse to search for available serials.

    Returns:
        A list of dictionaries describing candidate bins.  Each
        dictionary includes the serial number, normalized dimensions,
        area, material status, and a source kind ("Full Sheet" or
        "Leftover").
    """
    if not item_code or not warehouse:
        return []

    rows = frappe.get_all(
        "Serial No",
        filters={
            "item_code": item_code,
            "warehouse": warehouse,
            "custom_material_status": ["in", ["Full", "Partial"]],
        },
        fields=[
            "name",
            "item_code",
            "warehouse",
            "custom_dimension_length_mm",
            "custom_dimension_width_mm",
            "custom_material_status",
        ],
        order_by="custom_dimension_length_mm asc, custom_dimension_width_mm asc",
    )

    results: list[dict[str, object]] = []
    for row in rows:
        length_mm = float(row.custom_dimension_length_mm or 0)
        width_mm = float(row.custom_dimension_width_mm or 0)
        # Skip bins with invalid dimensions
        if length_mm <= 0 or width_mm <= 0:
            continue

        # Normalize so that length >= width
        l_norm = max(length_mm, width_mm)
        w_norm = min(length_mm, width_mm)
        # Extract thickness if available on the Serial No.  Fallback to 0.
        try:
            thickness_mm = float(getattr(row, "custom_dimension_thickness_mm", 0) or 0)
        except Exception:
            thickness_mm = 0.0
        results.append({
            "serial_no": row.name,
            "item_code": row.item_code,
            "warehouse": row.warehouse,
            "length_mm": l_norm,
            "width_mm": w_norm,
            "thickness_mm": thickness_mm,
            "area_mm2": l_norm * w_norm,
            "material_status": row.custom_material_status,
            "source_kind": "Full Sheet" if row.custom_material_status == "Full" else "Leftover",
        })

    return results

