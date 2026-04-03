import json
import frappe
from frappe.utils import flt

DEFAULT_CHILD_TABLE_FIELD = "mcp_sheets"
DEFAULT_SOURCE_JSON_FIELD = "result_json"


def _to_dict(raw):
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        raw = raw.strip()
        if not raw:
            return {}
        data = json.loads(raw)
        if isinstance(data, str):
            data = json.loads(data)
        return data
    return {}


def _get_root_nodes(result):
    tree = result.get("tree") or result
    return tree.get("nodes") or []


def _safe_area(length_mm, width_mm):
    return flt(length_mm) * flt(width_mm)


def _safe_perimeter(length_mm, width_mm):
    return 2 * (flt(length_mm) + flt(width_mm))


def build_sheet_rows_from_result_json(result_json):
    result = _to_dict(result_json)
    nodes = _get_root_nodes(result)

    rows = []
    sheet_no = 0

    for node in nodes:
        if (node.get("node_type") or "").strip() != "input_serial":
            continue

        sheet_no += 1

        sheet_node_id = (
            node.get("node_id")
            or node.get("id")
            or node.get("serial_no")
            or f"SHEET-{sheet_no}"
        )

        sheet_length = flt(node.get("length_mm") or node.get("length") or 0)
        sheet_width = flt(node.get("width_mm") or node.get("width") or 0)
        sheet_area = _safe_area(sheet_length, sheet_width)
        sheet_perimeter = _safe_perimeter(sheet_length, sheet_width)

        rows.append({
            "sheet_no": sheet_no,
            "sheet_label": f"Plaque {sheet_no}",
            "node_id": sheet_node_id,
            "parent_id": node.get("parent_id") or "",
            "node_type": "input_serial",
            "position_x": flt(node.get("x") or 0),
            "position_y": flt(node.get("y") or 0),
            "source_serial_no": node.get("serial_no") or "",
            "source_item_code": node.get("item_code") or "",
            "source_item_name": node.get("item_name") or "",
            "source_kind": node.get("source_kind") or "",
            "piece_item_code": "",
            "piece_item_name": "",
            "sales_order": "",
            "label": node.get("label") or "",
            "length_mm": sheet_length,
            "width_mm": sheet_width,
            "area_mm2": sheet_area,
            "area_m2": sheet_area / 1_000_000,
            "perimeter_mm": sheet_perimeter,
            "perimeter_m": sheet_perimeter / 1000,
        })

        for idx, child in enumerate(node.get("children") or [], start=1):
            child_node_id = (
                child.get("node_id")
                or child.get("id")
                or child.get("plan_ref_id")
                or f"{sheet_node_id}-CHILD-{idx}"
            )

            child_length = flt(child.get("length_mm") or child.get("length") or 0)
            child_width = flt(child.get("width_mm") or child.get("width") or 0)
            child_area = _safe_area(child_length, child_width)
            child_perimeter = _safe_perimeter(child_length, child_width)

            rows.append({
                "sheet_no": sheet_no,
                "sheet_label": f"Plaque {sheet_no}",
                "node_id": child_node_id,
                "parent_id": sheet_node_id,
                "node_type": child.get("node_type") or "",
                "position_x": flt(child.get("x") or 0),
                "position_y": flt(child.get("y") or 0),
                "source_serial_no": node.get("serial_no") or "",
                "source_item_code": node.get("item_code") or "",
                "source_item_name": node.get("item_name") or "",
                "source_kind": node.get("source_kind") or "",
                "piece_item_code": child.get("piece_item_code") or child.get("item_code") or "",
                "piece_item_name": child.get("piece_item_name") or child.get("item_name") or "",
                "sales_order": child.get("sales_order") or "",
                "label": child.get("label") or child.get("plan_ref_id") or "",
                "length_mm": child_length,
                "width_mm": child_width,
                "area_mm2": child_area,
                "area_m2": child_area / 1_000_000,
                "perimeter_mm": child_perimeter,
                "perimeter_m": child_perimeter / 1000,
            })

    return rows


def sync_mcp_sheets(
    doc,
    source_json_field=DEFAULT_SOURCE_JSON_FIELD,
    child_table_field=DEFAULT_CHILD_TABLE_FIELD,
    overwrite=True,
):
    raw_json = doc.get(source_json_field)

    if not raw_json:
        if overwrite:
            doc.set(child_table_field, [])
        return

    rows = build_sheet_rows_from_result_json(raw_json)

    if overwrite:
        doc.set(child_table_field, [])

    for row in rows:
        doc.append(child_table_field, row)