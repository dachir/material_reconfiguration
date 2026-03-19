import json
from collections import defaultdict

import frappe
from frappe.utils import cint, flt


def _safe_json_load(value):
    if not value:
        return {}
    if isinstance(value, dict):
        return value
    try:
        return json.loads(value)
    except Exception:
        return {}


def _get_tree_from_doc(doc):
    result_json = doc.get("result_json") or doc.get("result_tree_json")
    parsed = _safe_json_load(result_json)
    if not parsed:
        return {}
    return parsed.get("tree") or parsed


def _build_incident_map(doc):
    rows = doc.get("material_plan_incidents") or []
    result = {}
    for row in rows:
        if cint(row.get("is_active") or 0) != 1:
            continue
        plan_node_id = (row.get("plan_node_id") or "").strip()
        if not plan_node_id:
            continue
        result[plan_node_id] = row
    return result


def _apply_incident_to_child(child, incident):
    out = dict(child)

    if not incident:
        return out

    action = (incident.get("incident_action") or "").strip()

    if action == "Destroy":
        out["node_type"] = "destroyed"
        out["effective_length_mm"] = 0.0
        out["effective_width_mm"] = 0.0
        out["effective_area_mm2"] = 0.0
        return out

    if action == "Resize":
        new_length = flt(incident.get("new_length_mm"))
        new_width = flt(incident.get("new_width_mm"))
        new_type = (incident.get("new_node_type") or "").strip()

        out["node_type"] = new_type or out.get("node_type")
        out["effective_length_mm"] = new_length
        out["effective_width_mm"] = new_width
        out["effective_area_mm2"] = new_length * new_width
        return out

    return out


def build_effective_nodes(doc):
    tree = _get_tree_from_doc(doc)
    nodes = tree.get("nodes") or []
    incident_map = _build_incident_map(doc)

    effective_nodes = []

    for node in nodes:
        node_copy = dict(node)
        children = []

        for child in node.get("children") or []:
            child_id = (child.get("id") or child.get("piece_uid") or "").strip()
            incident = incident_map.get(child_id)
            effective_child = _apply_incident_to_child(child, incident)

            if "effective_length_mm" not in effective_child:
                effective_child["effective_length_mm"] = flt(child.get("length_mm") or 0)

            if "effective_width_mm" not in effective_child:
                effective_child["effective_width_mm"] = flt(child.get("width_mm") or 0)

            if "effective_area_mm2" not in effective_child:
                effective_child["effective_area_mm2"] = (
                    flt(effective_child.get("effective_length_mm"))
                    * flt(effective_child.get("effective_width_mm"))
                )

            children.append(effective_child)

        node_copy["children"] = children
        effective_nodes.append(node_copy)

    return effective_nodes


def _include_child_in_repack(doc, child):
    node_type = (child.get("node_type") or "").strip()

    if node_type == "destroyed":
        return False

    if node_type == "finished_good":
        return True

    if node_type == "leftover":
        return True

    if node_type == "waste":
        return cint(doc.get("add_waiste_to_stock") or 0) == 1

    return False


def _target_output_item_code(doc, node, child):
    node_type = (child.get("node_type") or "").strip()

    if node_type == "finished_good":
        return child.get("piece_item_code") or child.get("item_code")

    return node.get("item_code") or doc.get("source_item")


def _target_output_warehouse(doc, node, child):
    return (
        doc.get("target_warehouse")
        or doc.get("source_warehouse")
        or node.get("warehouse")
    )


def _target_input_warehouse(doc, node):
    return doc.get("source_warehouse") or node.get("warehouse")


def _norm_dims(L, W):
    L = flt(L)
    W = flt(W)
    return (L, W) if L >= W else (W, L)


def _norm_dims_key(L, W, precision=3):
    L = round(flt(L), precision)
    W = round(flt(W), precision)
    return (L, W) if L >= W else (W, L)


def _get_effective_dims(child):
    L = flt(child.get("effective_length_mm") or child.get("length_mm") or 0)
    W = flt(child.get("effective_width_mm") or child.get("width_mm") or 0)
    return _norm_dims_key(L, W)


def _target_serial_name(child):
    return (child.get("id") or child.get("piece_uid") or "").strip()


def _get_stock_uom(item_code):
    if not item_code:
        return None
    return frappe.db.get_value("Item", item_code, "stock_uom")


def _set_item_uom_fields(row, item_code):
    stock_uom = _get_stock_uom(item_code)
    row.uom = stock_uom
    row.stock_uom = stock_uom
    row.conversion_factor = 1


def _append_custom_output_fields(item_row, length_mm, width_mm, node_type):
    length_mm, width_mm = _norm_dims_key(length_mm, width_mm)

    item_row.custom_dimension_length_mm = length_mm
    item_row.custom_dimension_width_mm = width_mm

    if hasattr(item_row, "custom_surface_mm2"):
        item_row.custom_surface_mm2 = flt(length_mm) * flt(width_mm)

    if hasattr(item_row, "custom_cutting_node_type"):
        item_row.custom_cutting_node_type = node_type

    if hasattr(item_row, "custom_material_status"):
        item_row.custom_material_status = (
            "Partial" if node_type in ("leftover", "waste") else "Full"
        )


def _extract_bundle_serials(bundle_doc):
    serials = []
    for row in (bundle_doc.get("entries") or bundle_doc.get("items") or []):
        serial_no = (row.get("serial_no") or "").strip()
        if serial_no:
            serials.append(serial_no)
    return serials


def _find_existing_bundle_for_exact_serials(item_code, warehouse, serials, material_cutting_plan):
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


def _find_bundle_name(item_code, warehouse, length_mm, width_mm, material_cutting_plan):
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

    for bundle_name in bundle_names:
        bundle_doc = frappe.get_doc("Serial and Batch Bundle", bundle_name)
        serials = _extract_bundle_serials(bundle_doc)

        if not serials:
            continue

        match = True
        for serial_no in serials:
            if not frappe.db.exists("Serial No", serial_no):
                match = False
                break

            s_len = flt(
                frappe.db.get_value("Serial No", serial_no, "custom_dimension_length_mm") or 0
            )
            s_wid = flt(
                frappe.db.get_value("Serial No", serial_no, "custom_dimension_width_mm") or 0
            )

            if _norm_dims_key(s_len, s_wid) != _norm_dims_key(length_mm, width_mm):
                match = False
                break

        if match:
            return bundle_name

    return None


def _build_input_rows(se, doc, effective_nodes):
    grouped_inputs = defaultdict(list)

    for node in effective_nodes:
        item_code = node.get("item_code") or doc.get("source_item")
        warehouse = _target_input_warehouse(doc, node)
        serial_no = (node.get("serial_no") or "").strip()

        if not item_code or not warehouse or not serial_no:
            continue

        grouped_inputs[(item_code, warehouse)].append(serial_no)

    for (item_code, warehouse), serials in grouped_inputs.items():
        row = se.append("items", {})
        row.item_code = item_code
        row.s_warehouse = warehouse
        row.qty = len(serials)
        _set_item_uom_fields(row, item_code)

        if len(serials) == 1:
            row.serial_no = serials[0]
        else:
            bundle_name = _find_existing_bundle_for_exact_serials(
                item_code=item_code,
                warehouse=warehouse,
                serials=serials,
                material_cutting_plan=doc.name,
            )
            if bundle_name:
                row.serial_and_batch_bundle = bundle_name
                row.serial_no = ""
                if hasattr(row, "batch_no"):
                    row.batch_no = ""
            else:
                row.serial_no = "\n".join(serials)


def _build_output_rows(se, doc, effective_nodes):
    fg_groups = defaultdict(list)
    other_rows = []

    for node in effective_nodes:
        for child in node.get("children") or []:
            if not _include_child_in_repack(doc, child):
                continue

            node_type = (child.get("node_type") or "").strip()
            item_code = _target_output_item_code(doc, node, child)
            warehouse = _target_output_warehouse(doc, node, child)
            serial_no = _target_serial_name(child)
            length_mm, width_mm = _get_effective_dims(child)

            if not item_code or not warehouse:
                continue

            if node_type == "finished_good":
                key = (
                    item_code,
                    warehouse,
                    length_mm,
                    width_mm,
                )
                fg_groups[key].append(serial_no)
            else:
                other_rows.append(
                    {
                        "item_code": item_code,
                        "warehouse": warehouse,
                        "serial_no": serial_no,
                        "length_mm": length_mm,
                        "width_mm": width_mm,
                        "node_type": node_type,
                    }
                )

    # FG grouped rows
    for (item_code, warehouse, length_mm, width_mm), serials in fg_groups.items():
        row = se.append("items", {})
        row.item_code = item_code
        row.t_warehouse = warehouse
        row.qty = len(serials)
        row.is_finished_item = 1

        if hasattr(row, "set_basic_rate_manually"):
            row.set_basic_rate_manually = 1
            
        _set_item_uom_fields(row, item_code)

        if len(serials) == 1:
            row.serial_no = serials[0]
        else:
            row.serial_no = "\n".join(serials)

        _append_custom_output_fields(row, length_mm, width_mm, "finished_good")

    # leftovers / waste
    for out in other_rows:
        row = se.append("items", {})
        row.item_code = out["item_code"]
        row.t_warehouse = out["warehouse"]
        row.qty = 1
        _set_item_uom_fields(row, out["item_code"])

        if hasattr(row, "set_basic_rate_manually"):
            row.set_basic_rate_manually = 1

        if out["serial_no"]:
            row.serial_no = out["serial_no"]

        _append_custom_output_fields(
            row,
            out["length_mm"],
            out["width_mm"],
            out["node_type"],
        )


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


@frappe.whitelist()
def make_repack_draft(material_cutting_plan_name):
    doc = frappe.get_doc("Material Cutting Plan", material_cutting_plan_name)
    doc.check_permission("read")

    effective_nodes = build_effective_nodes(doc)

    se = frappe.new_doc("Stock Entry")
    se.stock_entry_type = "Repack"
    se.company = doc.get("company")
    se.posting_date = frappe.utils.nowdate()
    se.set_posting_time = 1
    se.set_basic_rate_manually = 1
    se.remarks = f"Prepared from Material Cutting Plan {doc.name}"

    if hasattr(se, "custom_material_cutting_plan"):
        se.custom_material_cutting_plan = doc.name

    _build_input_rows(se, doc, effective_nodes)
    _build_output_rows(se, doc, effective_nodes)

    return se.as_dict()