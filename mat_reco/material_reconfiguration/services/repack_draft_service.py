import json
from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import cint, flt, cstr


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


def _extract_serials_from_text(value):
    serials = []
    for s in cstr(value or "").splitlines():
        s = s.strip()
        if s:
            serials.append(s)
    return list(dict.fromkeys(serials))


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
        serials = list(dict.fromkeys(serials))

        row = se.append("items", {})
        row.item_code = item_code
        row.s_warehouse = warehouse
        row.qty = len(serials)
        _set_item_uom_fields(row, item_code)

        # MCP source of truth: always write serial_no directly
        row.serial_no = "\n".join(serials)

        # Do not bind an input bundle here.
        row.serial_and_batch_bundle = None
        if hasattr(row, "batch_no"):
            row.batch_no = ""


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

def _extract_serial_nos_from_stock_entry_detail(row) -> set[str]:
    """Read actual serials attached to a Stock Entry Detail row.

    Priority:
    - input row: direct serial_no first
    - otherwise: bundle first, fallback to serial_no
    """
    serial_nos = set()

    is_input_row = bool(row.get("s_warehouse")) and not bool(row.get("t_warehouse"))

    if is_input_row:
        serial_no_value = cstr(row.get("serial_no") or "").strip()
        if serial_no_value:
            for s in serial_no_value.splitlines():
                s = s.strip()
                if s:
                    serial_nos.add(s)
            return serial_nos

    bundle_name = cstr(row.get("serial_and_batch_bundle") or "").strip()
    if bundle_name:
        try:
            bundle = frappe.get_doc("Serial and Batch Bundle", bundle_name)
            for entry in (bundle.get("entries") or bundle.get("items") or []):
                serial_no = cstr(entry.get("serial_no") or "").strip()
                if serial_no:
                    serial_nos.add(serial_no)
            if serial_nos:
                return serial_nos
        except Exception:
            frappe.log_error(
                frappe.get_traceback(),
                f"Failed to read bundle {bundle_name}"
            )

    serial_no_value = cstr(row.get("serial_no") or "").strip()
    if serial_no_value:
        for s in serial_no_value.splitlines():
            s = s.strip()
            if s:
                serial_nos.add(s)

    return serial_nos

def validate_all_expected_outputs_not_already_generated(doc, effective_nodes):
    """Check whether all expected MCP outputs (excluding destroyed ones)
    have already been generated in non-cancelled Stock Entries.
    """
    expected_output_ids = set()

    for node in effective_nodes or []:
        for child in node.get("children", []) or []:
            node_type = (child.get("node_type") or "").strip()

            if (
                node_type == "finished_good"
                or node_type == "leftover"
                or (node_type == "waste" and cint(doc.get("add_waiste_to_stock") or 0) == 1)
            ):
                output_id = cstr(_target_serial_name(child) or "").strip()
                if output_id:
                    expected_output_ids.add(output_id)

    if not expected_output_ids:
        return

    already_generated_output_ids = set()

    stock_entries = frappe.get_all(
        "Stock Entry",
        filters={
            "docstatus": ["<", 2],  # Draft or Submitted, but not Cancelled
            "custom_material_cutting_plan": doc.name,
        },
        fields=["name"],
    )

    for se_row in stock_entries:
        se_items = frappe.get_all(
            "Stock Entry Detail",
            filters={"parent": se_row.name},
            fields=[
                "name",
                "item_code",
                "serial_no",
                "serial_and_batch_bundle",
                "qty",
                "s_warehouse",
                "t_warehouse",
            ],
        )

        for item in se_items:
            if not item.get("t_warehouse"):
                continue
            row_serials = _extract_serial_nos_from_stock_entry_detail(item)
            already_generated_output_ids.update(row_serials)

    if expected_output_ids.issubset(already_generated_output_ids):
        frappe.throw(
            _("All planned outputs that were not destroyed have already been generated for Material Cutting Plan {0}.").format(doc.name)
        )

@frappe.whitelist()
def make_repack_draft(material_cutting_plan_name):
    doc = frappe.get_doc("Material Cutting Plan", material_cutting_plan_name)
    doc.check_permission("read")

    effective_nodes = build_effective_nodes(doc)

    validate_all_expected_outputs_not_already_generated(doc, effective_nodes)

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


"""
L’idée métier devient :
tant que tous les outputs ne sont pas encore générés, on laisse soumettre
dès que le submit courant fait que tous les outputs prévus sont désormais générés, alors on vérifie aussi que tous les inputs prévus ont bien été consommés
sinon on bloque le submit
"""
def _collect_expected_serials(effective_nodes, add_waiste_to_stock):
    expected_output_serials = set()
    destroyed_output_serials = set()
    expected_input_serials = set()

    for node in effective_nodes or []:
        input_serial = cstr(node.get("serial_no") or "").strip()
        if input_serial:
            expected_input_serials.add(input_serial)

        for child in node.get("children", []) or []:
            node_type = (child.get("node_type") or "").strip()
            serial = cstr(_target_serial_name(child) or "").strip()

            if not serial:
                continue

            if node_type in ("finished_good", "leftover") or (
                node_type == "waste" and add_waiste_to_stock
            ):
                expected_output_serials.add(serial)
            elif node_type == "destroyed":
                destroyed_output_serials.add(serial)

    expected_output_serials -= destroyed_output_serials
    return expected_output_serials, expected_input_serials


def _extract_serials_from_row(row):
    """Return a set of serial numbers from a Stock Entry Detail row."""
    serials = set()

    # Cas classique : champ texte
    if row.get("serial_no"):
        serials.update([s.strip() for s in row.serial_no.split("\n") if s.strip()])

    # Cas bundle
    if row.get("serial_and_batch_bundle"):
        bundle = frappe.get_doc("Serial and Batch Bundle", row.serial_and_batch_bundle)
        for entry in bundle.entries:
            if entry.serial_no:
                serials.add(entry.serial_no.strip())

    return serials

def _collect_generated_outputs_and_inputs_from_serials(mcp_name):
    generated_output_serials = set()
    consumed_input_serials = set()

    stock_entries = frappe.get_all(
        "Stock Entry",
        filters={
            "docstatus": 1,
            "custom_material_cutting_plan": mcp_name,
        },
        fields=["name"],
    )

    for se in stock_entries:
        items = frappe.get_all(
            "Stock Entry Detail",
            filters={"parent": se.name},
            fields=[
                "name",
                "serial_no",
                "serial_and_batch_bundle",
                "s_warehouse",
                "t_warehouse",
            ],
        )

        for row in items:
            serials = _extract_serial_nos_from_stock_entry_detail(row)

            if row.get("t_warehouse"):
                generated_output_serials.update(serials)
            elif row.get("s_warehouse"):
                consumed_input_serials.update(serials)

    return generated_output_serials, consumed_input_serials


def validate_mcp_completion_on_submit(stock_entry_doc):
    mcp_name = stock_entry_doc.get("custom_material_cutting_plan")
    if not mcp_name:
        return

    mcp = frappe.get_doc("Material Cutting Plan", mcp_name)
    effective_nodes = build_effective_nodes(mcp)

    expected_outputs, expected_inputs = _collect_expected_serials(effective_nodes, stock_entry_doc.add_waiste_to_stock)
    generated_outputs, consumed_inputs = _collect_generated_outputs_and_inputs_from_serials(mcp_name)

    # 1. Tant que outputs incomplets → OK
    if not expected_outputs.issubset(generated_outputs):
        return

    # 2. Si outputs complets → inputs doivent être complets
    missing_inputs = sorted(expected_inputs - consumed_inputs)

    if missing_inputs:
        frappe.throw(
            _(
                "All outputs are generated but some inputs are not fully consumed:\n{0}"
            ).format("\n".join(missing_inputs))
        )


def _get_serial_area_mm2(serial_no: str) -> float:
    """Return the area in mm² for a serial number."""
    if not serial_no:
        return 0.0

    area = frappe.db.get_value("Serial No", serial_no, "custom_surface_mm2")
    if area:
        return flt(area)

    # Fallbacks if needed
    length_mm = frappe.db.get_value("Serial No", serial_no, "custom_dimension_length_mm") or 0
    width_mm = frappe.db.get_value("Serial No", serial_no, "custom_dimension_width_mm") or 0
    return flt(length_mm) * flt(width_mm)


def _collect_expected_repack_limits(doc, effective_nodes):
    """Return the maximum authorized totals from the effective MCP."""
    expected_input_serials = set()
    expected_output_serials = set()

    expected_input_area_mm2 = 0.0
    expected_output_area_mm2 = 0.0

    # INPUTS = input serial nodes
    for node in effective_nodes or []:
        input_serial = cstr(node.get("serial_no") or node.get("id") or "").strip()
        if input_serial:
            if input_serial not in expected_input_serials:
                expected_input_serials.add(input_serial)
                expected_input_area_mm2 += flt(node.get("area_mm2") or 0)

        # OUTPUTS = finished_good + leftover + waste(if stock)
        for child in node.get("children") or []:
            node_type = (child.get("node_type") or "").strip()

            if (
                node_type == "finished_good"
                or node_type == "leftover"
                or (node_type == "waste" and cint(doc.get("add_waiste_to_stock") or 0) == 1)
            ):
                output_serial = cstr(child.get("id") or "").strip()
                if output_serial and output_serial not in expected_output_serials:
                    expected_output_serials.add(output_serial)
                    expected_output_area_mm2 += flt(
                        child.get("effective_area_mm2")
                        or child.get("area_mm2")
                        or (flt(child.get("effective_length_mm")) * flt(child.get("effective_width_mm")))
                        or (flt(child.get("length_mm")) * flt(child.get("width_mm")))
                    )

    return {
        "expected_input_count": len(expected_input_serials),
        "expected_input_area_mm2": expected_input_area_mm2,
        "expected_output_count": len(expected_output_serials),
        "expected_output_area_mm2": expected_output_area_mm2,
    }

def _collect_actual_repack_totals(mcp_doc, effective_nodes, current_stock_entry_doc=None):
    """Collect actual cumulative input/output totals for repacks linked to a given MCP.

    Important:
    - submitted stock entries: read actual rows from DB
    - current stock entry being submitted:
        for input rows, prefer MCP planned serials by item+warehouse
        because input bundles may have been auto-rewritten incorrectly
    """
    consumed_input_serials = set()
    generated_output_serials = set()

    mcp_name = mcp_doc.name
    planned_input_map = _get_planned_input_serials_by_item_warehouse(mcp_doc, effective_nodes)

    def absorb_stock_entry_items(items, is_current_doc=False):
        for row in items:
            is_output = bool(row.get("t_warehouse"))
            is_input = bool(row.get("s_warehouse")) and not bool(row.get("t_warehouse"))

            if is_input:
                # For the current doc being submitted, trust MCP planned inputs
                # instead of a possibly mutated bundle.
                if is_current_doc:
                    key = (row.get("item_code"), row.get("s_warehouse"))
                    planned_serials = planned_input_map.get(key) or set()
                    if planned_serials:
                        consumed_input_serials.update(planned_serials)
                        continue

                row_serials = _extract_serial_nos_from_stock_entry_detail(row)
                if row_serials:
                    consumed_input_serials.update(row_serials)
                continue

            if is_output:
                row_serials = _extract_serial_nos_from_stock_entry_detail(row)
                if row_serials:
                    generated_output_serials.update(row_serials)

    submitted_filters = {
        "docstatus": 1,
        "custom_material_cutting_plan": mcp_name,
    }

    if current_stock_entry_doc and current_stock_entry_doc.get("name"):
        submitted_filters["name"] = ["!=", current_stock_entry_doc.get("name")]

    submitted_ses = frappe.get_all(
        "Stock Entry",
        filters=submitted_filters,
        fields=["name"],
    )

    for se in submitted_ses:
        items = frappe.get_all(
            "Stock Entry Detail",
            filters={"parent": se.name},
            fields=[
                "name",
                "item_code",
                "serial_no",
                "serial_and_batch_bundle",
                "s_warehouse",
                "t_warehouse",
                "is_finished_item",
            ],
        )
        absorb_stock_entry_items(items, is_current_doc=False)

    if current_stock_entry_doc:
        absorb_stock_entry_items(current_stock_entry_doc.get("items") or [], is_current_doc=True)

    consumed_input_area_mm2 = sum(_get_serial_area_mm2(s) for s in consumed_input_serials)
    generated_output_area_mm2 = sum(_get_serial_area_mm2(s) for s in generated_output_serials)

    return {
        "actual_input_count": len(consumed_input_serials),
        "actual_input_area_mm2": consumed_input_area_mm2,
        "actual_output_count": len(generated_output_serials),
        "actual_output_area_mm2": generated_output_area_mm2,
    }


def validate_repack_totals_against_mcp_on_submit(stock_entry_doc):
    """Block submit if cumulative repack totals exceed MCP authorized totals."""
    mcp_name = stock_entry_doc.get("custom_material_cutting_plan")
    if not mcp_name:
        return

    if (stock_entry_doc.get("stock_entry_type") or "") != "Repack":
        return

    mcp = frappe.get_doc("Material Cutting Plan", mcp_name)
    effective_nodes = build_effective_nodes(mcp)

    expected = _collect_expected_repack_limits(mcp, effective_nodes)
    actual = _collect_actual_repack_totals(mcp, effective_nodes, current_stock_entry_doc=stock_entry_doc)

    errors = []

    if actual["actual_input_area_mm2"] > expected["expected_input_area_mm2"] + 0.001:
        errors.append(
            _("Total consumed input area ({0} m²) exceeds planned input area ({1} m²)").format(
                frappe.format_value(actual["actual_input_area_mm2"] / 1_000_000.0, {"fieldtype": "Float", "precision": 3}),
                frappe.format_value(expected["expected_input_area_mm2"] / 1_000_000.0, {"fieldtype": "Float", "precision": 3}),
            )
        )

    if actual["actual_output_area_mm2"] > expected["expected_output_area_mm2"] + 0.001:
        errors.append(
            _("Total generated output area ({0} m²) exceeds planned output area ({1} m²)").format(
                frappe.format_value(actual["actual_output_area_mm2"] / 1_000_000.0, {"fieldtype": "Float", "precision": 3}),
                frappe.format_value(expected["expected_output_area_mm2"] / 1_000_000.0, {"fieldtype": "Float", "precision": 3}),
            )
        )

    if actual["actual_input_count"] > expected["expected_input_count"]:
        errors.append(
            _("Total consumed input serial count ({0}) exceeds planned input serial count ({1})").format(
                actual["actual_input_count"],
                expected["expected_input_count"],
            )
        )

    if actual["actual_output_count"] > expected["expected_output_count"]:
        errors.append(
            _("Total generated output serial count ({0}) exceeds planned output serial count ({1})").format(
                actual["actual_output_count"],
                expected["expected_output_count"],
            )
        )

    if errors:
        frappe.throw("<br>".join(errors))

def _create_bundle(company, item_code, warehouse, serials, material_cutting_plan=None):
    if not serials:
        return None

    serials = _filter_valid_output_serials(serials, warehouse)

    if not serials:
        return None

    bundle = frappe.new_doc("Serial and Batch Bundle")
    bundle.company = company
    bundle.item_code = item_code
    bundle.warehouse = warehouse
    bundle.use_serial_batch_fields = 1  # 🔥 IMPORTANT

    if frappe.db.has_column("Serial and Batch Bundle", "custom_material_cutting_plan"):
        bundle.custom_material_cutting_plan = material_cutting_plan

    for serial_no in serials:
        bundle.append("entries", {
            "serial_no": serial_no
        })

    bundle.flags.ignore_validate = True
    bundle.flags.ignore_links = True
    bundle.insert(ignore_permissions=True)

    return bundle.name


def _ensure_mcp_input_bundles(doc):
    created_bundles = []

    for it in (doc.items or []):
        is_input = bool(it.s_warehouse) and not bool(it.t_warehouse)
        if not is_input:
            continue

        item_code = it.item_code
        warehouse = it.s_warehouse

        if not item_code or not warehouse:
            continue

        if cint(frappe.db.get_value("Item", item_code, "has_serial_no") or 0) != 1:
            continue

        serials = _extract_serials_from_text(it.serial_no or "")
        if not serials:
            continue

        serials = _filter_valid_output_serials(serials, warehouse)

        # Optional: validate every serial belongs to MCP planned inputs
        bundle_name = _create_bundle(
            company=doc.company,
            item_code=item_code,
            warehouse=warehouse,
            serials=serials,
            material_cutting_plan=doc.custom_material_cutting_plan or None,
        )

        _assert_bundle_matches_expected(bundle_name, serials)

        if bundle_name:
            it.serial_and_batch_bundle = bundle_name
            it.serial_no = None
            it.use_serial_batch_fields = 1
            created_bundles.append(bundle_name)

    return sorted(set(created_bundles))

def _assert_bundle_matches_expected(bundle_name: str, expected_serials: list[str]):
    if not bundle_name:
        return

    bundle_doc = frappe.get_doc("Serial and Batch Bundle", bundle_name)
    actual_serials = set(_extract_bundle_serials(bundle_doc))
    expected_set = set(expected_serials)

    if actual_serials != expected_set:
        frappe.throw(
            _("Bundle {0} does not match expected MCP serials.\nExpected: {1}\nActual: {2}")
            .format(
                bundle_name,
                ", ".join(sorted(expected_set)),
                ", ".join(sorted(actual_serials)),
            )
        )


def _get_planned_input_serials_by_item_warehouse(doc, effective_nodes):
    planned = defaultdict(set)

    for node in effective_nodes or []:
        item_code = node.get("item_code") or doc.get("source_item")
        warehouse = _target_input_warehouse(doc, node)
        serial_no = cstr(node.get("serial_no") or "").strip()

        if item_code and warehouse and serial_no:
            planned[(item_code, warehouse)].add(serial_no)

    return planned

def _filter_valid_output_serials(serials, warehouse):
    valid_serials = []

    for s in serials:
        existing = frappe.db.get_value("Serial No", s, ["warehouse"], as_dict=True)

        if not existing:
            # nouveau serial → OK
            valid_serials.append(s)
        elif existing.warehouse != warehouse:
            # déjà ailleurs → erreur métier
            frappe.throw(f"Serial {s} exists in another warehouse: {existing.warehouse}")
        else:
            # déjà présent → skip
            continue

    return valid_serials