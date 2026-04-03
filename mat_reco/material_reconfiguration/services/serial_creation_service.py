from __future__ import annotations

from collections import defaultdict
import json

import frappe

from mat_reco.material_reconfiguration.services.mcp_incident_service import (
    apply_incidents_to_nodes,
    build_incident_map,
)
from frappe.utils import cint, flt


def _extract_serials_from_text(value: str) -> list[str]:
    result = []
    for row in (value or "").splitlines():
        s = row.strip()
        if s:
            result.append(s)
    return list(dict.fromkeys(result))


def _extract_bundle_serials(bundle_doc) -> list[str]:
    serials = []
    for row in (bundle_doc.get("entries") or bundle_doc.get("items") or []):
        serial_no = (row.get("serial_no") or "").strip()
        if serial_no:
            serials.append(serial_no)
    return serials


def _get_bundle_name(it) -> str:
    return (it.get("serial_and_batch_bundle") or it.get("serial_batch_bundle") or "").strip()


def _serial_exists(serial_no: str) -> bool:
    if not serial_no:
        return False
    return bool(frappe.db.exists("Serial No", serial_no))


def _target_material_status(node_type: str) -> str:
    if node_type in ("leftover", "waste"):
        return "Partial"
    return "Full"


def _safe_json_load(value):
    if not value:
        return {}
    if isinstance(value, dict):
        return value
    try:
        return json.loads(value)
    except Exception:
        return {}


def _norm_dims(L, W):
    L = flt(L)
    W = flt(W)
    return (L, W) if L >= W else (W, L)


def _tree_is_return_terrain_resolved(tree):
    if not isinstance(tree, dict):
        return False
    if tree.get("return_terrain_resolved"):
        return True
    options = tree.get("options") or {}
    return bool(options.get("return_terrain_resolved"))


def _get_mcp_serial_dimension_map(mcp_name: str) -> dict:
    """
    Build a map:
        serial_candidate -> {
            item_code,
            node_type,
            length_mm,
            width_mm
        }
    from Material Cutting Plan result_json + incidents already reflected in draft serial naming.
    """
    if not mcp_name:
        return {}

    if not frappe.db.exists("Material Cutting Plan", mcp_name):
        return {}

    mcp = frappe.get_doc("Material Cutting Plan", mcp_name)

    parsed = _safe_json_load(mcp.get("effective_result_json") or mcp.get("result_json") or mcp.get("result_tree_json"))
    tree = parsed.get("tree") or parsed or {}
    nodes = tree.get("nodes") or []

    incident_map = {}
    if not _tree_is_return_terrain_resolved(tree):
        incident_map = build_incident_map(mcp)

    result = {}

    effective_nodes = nodes if _tree_is_return_terrain_resolved(tree) else apply_incidents_to_nodes(nodes, incident_map)

    for node in effective_nodes:
        source_item_code = node.get("item_code") or mcp.get("source_item")

        for child in (node.get("children") or []):
            serial_no = (child.get("id") or child.get("piece_uid") or "").strip()
            if not serial_no:
                continue

            node_type = (child.get("node_type") or "").strip()
            length_mm = flt(child.get("effective_length_mm") or child.get("length_mm") or 0)
            width_mm = flt(child.get("effective_width_mm") or child.get("width_mm") or 0)

            length_mm, width_mm = _norm_dims(length_mm, width_mm)

            if node_type == "finished_good":
                item_code = child.get("piece_item_code") or child.get("item_code")
            else:
                item_code = source_item_code

            result[serial_no] = {
                "item_code": item_code,
                "node_type": node_type,
                "length_mm": length_mm,
                "width_mm": width_mm,
            }

    return result


def _create_or_update_serial_no(
    serial_no: str,
    item_code: str,
    company: str,
    node_type: str,
    length_mm: float,
    width_mm: float,
    material_cutting_plan: str | None = None,
):
    if not serial_no or not item_code:
        return None

    exists = _serial_exists(serial_no)

    if exists:
        serial_doc = frappe.get_doc("Serial No", serial_no)
    else:
        serial_doc = frappe.new_doc("Serial No")
        serial_doc.name = serial_no
        serial_doc.serial_no = serial_no
        serial_doc.item_code = item_code
        serial_doc.company = company
        serial_doc.status = "Inactive"

    if hasattr(serial_doc, "custom_dimension_length_mm"):
        serial_doc.custom_dimension_length_mm = flt(length_mm)

    if hasattr(serial_doc, "custom_dimension_width_mm"):
        serial_doc.custom_dimension_width_mm = flt(width_mm)

    if hasattr(serial_doc, "custom_surface_mm2"):
        serial_doc.custom_surface_mm2 = flt(length_mm) * flt(width_mm)

    if hasattr(serial_doc, "custom_material_status"):
        serial_doc.custom_material_status = _target_material_status(node_type)

    if hasattr(serial_doc, "custom_material_cutting_plan"):
        serial_doc.custom_material_cutting_plan = material_cutting_plan

    if hasattr(serial_doc, "custom_cutting_node_type"):
        serial_doc.custom_cutting_node_type = node_type

    serial_doc.flags.ignore_permissions = True

    if serial_doc.is_new():
        serial_doc.insert()
    else:
        serial_doc.save()

    return serial_doc


def _find_existing_bundle_for_exact_serials(
    item_code: str,
    warehouse: str,
    serials: list[str],
    material_cutting_plan: str | None = None,
):
    if not serials:
        return None

    filters = {
        "item_code": item_code,
        "warehouse": warehouse,
    }

    if material_cutting_plan and frappe.db.has_column("Serial and Batch Bundle", "custom_material_cutting_plan"):
        filters["custom_material_cutting_plan"] = material_cutting_plan

    bundle_names = frappe.get_all(
        "Serial and Batch Bundle",
        filters=filters,
        pluck="name",
        order_by="creation desc",
    )

    target_set = set(serials)

    for bundle_name in bundle_names:
        bundle_doc = frappe.get_doc("Serial and Batch Bundle", bundle_name)
        bundle_serials = _extract_bundle_serials(bundle_doc)
        if set(bundle_serials) == target_set:
            return bundle_name

    return None


def _create_bundle(
    company: str,
    item_code: str,
    warehouse: str,
    serials: list[str],
    material_cutting_plan: str | None = None,
):
    if len(serials) < 1:
        return None

    existing = _find_existing_bundle_for_exact_serials(
        item_code=item_code,
        warehouse=warehouse,
        serials=serials,
        material_cutting_plan=material_cutting_plan,
    )
    if existing:
        return existing

    from mat_reco.material_reconfiguration.api import create_serial_batch_bundle

    bundle_name = create_serial_batch_bundle(
        company=company,
        voucher_type="Stock Entry",
        item_code=item_code,
        warehouse=warehouse,
        serials=serials,
        transaction_type="Inward",
    )

    if bundle_name and frappe.db.exists("Serial and Batch Bundle", bundle_name):
        bundle_doc = frappe.get_doc("Serial and Batch Bundle", bundle_name)
        if hasattr(bundle_doc, "custom_material_cutting_plan"):
            bundle_doc.custom_material_cutting_plan = material_cutting_plan
        bundle_doc.flags.ignore_permissions = True
        bundle_doc.save()

    return bundle_name


def _get_row_serials(it) -> list[str]:
    bundle_name = _get_bundle_name(it)
    if bundle_name:
        if frappe.db.exists("Serial and Batch Bundle", bundle_name):
            bundle_doc = frappe.get_doc("Serial and Batch Bundle", bundle_name)
            return _extract_bundle_serials(bundle_doc)
        return []

    return _extract_serials_from_text(it.get("serial_no") or "")


def _ensure_output_serials(doc, material_cutting_plan: str | None = None):
    created_serials = []
    mcp_name = (material_cutting_plan or "").strip()
    mcp_map = _get_mcp_serial_dimension_map(mcp_name) if mcp_name else {}

    for it in (doc.items or []):
        if not it.t_warehouse:
            continue

        item_code = it.item_code
        if not item_code:
            continue

        if cint(frappe.db.get_value("Item", item_code, "has_serial_no") or 0) != 1:
            continue

        serials = _get_row_serials(it)
        if not serials:
            continue

        for serial_no in serials:
            mcp_row = mcp_map.get(serial_no, {})

            serial_item_code = mcp_row.get("item_code") or item_code
            node_type = (mcp_row.get("node_type") or it.get("custom_cutting_node_type") or "").strip()
            length_mm = flt(mcp_row.get("length_mm") or it.get("custom_dimension_length_mm") or 0)
            width_mm = flt(mcp_row.get("width_mm") or it.get("custom_dimension_width_mm") or 0)

            serial_doc = _create_or_update_serial_no(
                serial_no=serial_no,
                item_code=serial_item_code,
                company=doc.company,
                node_type=node_type,
                length_mm=length_mm,
                width_mm=width_mm,
                material_cutting_plan=mcp_name or None,
            )
            if serial_doc:
                created_serials.append(serial_doc.name)

    return sorted(set(created_serials))


def _ensure_output_bundles(doc, material_cutting_plan: str | None = None):
    created_bundles = []
    mcp_name = (material_cutting_plan or "").strip()

    for it in (doc.items or []):
        if not it.t_warehouse:
            continue

        item_code = it.item_code
        warehouse = it.t_warehouse

        if not item_code or not warehouse:
            continue

        if cint(frappe.db.get_value("Item", item_code, "has_serial_no") or 0) != 1:
            continue

        if _get_bundle_name(it):
            bundle_name = _get_bundle_name(it)
            if mcp_name and frappe.db.exists("Serial and Batch Bundle", bundle_name):
                bundle_doc = frappe.get_doc("Serial and Batch Bundle", bundle_name)
                if hasattr(bundle_doc, "custom_material_cutting_plan"):
                    bundle_doc.custom_material_cutting_plan = mcp_name
                    bundle_doc.flags.ignore_permissions = True
                    bundle_doc.save()
            continue

        serials = _extract_serials_from_text(it.get("serial_no") or "")
        if len(serials) < 2:
            # pour qty=1, pas de bundle nécessaire
            continue

        bundle_name = _create_bundle(
            company=doc.company,
            item_code=item_code,
            warehouse=warehouse,
            serials=serials,
            material_cutting_plan=mcp_name or None,
        )

        if bundle_name:
            it.serial_and_batch_bundle = bundle_name
            it.serial_no = ""
            if hasattr(it, "batch_no"):
                it.batch_no = ""
            created_bundles.append(bundle_name)

    return sorted(set(created_bundles))

def ensure_repack_output_serials_and_bundles_for_stock_entry(
    doc,
    material_cutting_plan: str | None = None,
):
    if (doc.stock_entry_type or "") != "Repack":
        return {"serial_nos": [], "bundles": []}

    created_serials = _ensure_output_serials(doc, material_cutting_plan=material_cutting_plan)
    created_bundles = _ensure_output_bundles(doc, material_cutting_plan=material_cutting_plan)

    return {
        "serial_nos": created_serials,
        "bundles": created_bundles,
    }

def ensure_mcp_serials_and_bundles_for_stock_entry(doc):
    if (doc.stock_entry_type or "") != "Repack":
        return {"serial_nos": [], "bundles": []}

    mcp_name = (doc.get("custom_material_cutting_plan") or "").strip()
    if not mcp_name:
        return {"serial_nos": [], "bundles": []}

    return ensure_repack_output_serials_and_bundles_for_stock_entry(
        doc,
        material_cutting_plan=mcp_name,
    )

__all__ = [
    "ensure_mcp_serials_and_bundles_for_stock_entry",
    "ensure_repack_output_serials_and_bundles_for_stock_entry",
]