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


def _get_input_serial_names_from_mcp_sheets(doc):
    grouped = defaultdict(set)

    for row in (doc.get("mcp_sheets") or []):
        serial_no = cstr(row.get("source_serial_no") or "").strip()
        item_code = cstr(row.get("source_item_code") or "").strip()
        warehouse = cstr(doc.get("source_warehouse") or "").strip()

        if serial_no and item_code and warehouse:
            grouped[(item_code, warehouse)].add(serial_no)

    return grouped


def _ensure_input_serial_exists(
    serial_no: str,
    item_code: str | None = None,
    warehouse: str | None = None,
    *,
    material_cutting_plan: str | None = None,
    custom_stock_entry_row_name: str | None = None,
) -> dict:
    """Validate that an input serial exists and matches the given item and warehouse.

    If the serial exists, optionally update its custom fields to record the
    Material Cutting Plan and the Stock Entry row that consumed it. This
    provides traceability for input serials in MCP repack operations.

    Args:
        serial_no: Serial number to validate.
        item_code: Expected item code (optional).
        warehouse: Expected warehouse (optional).
        material_cutting_plan: Name of the Material Cutting Plan consuming this serial.
        custom_stock_entry_row_name: Name of the Stock Entry Detail row consuming this serial.

    Returns:
        dict: The existing serial record with keys ``name``, ``item_code`` and ``warehouse``.
    """
    existing = frappe.db.get_value(
        "Serial No",
        serial_no,
        ["name", "item_code", "warehouse"],
        as_dict=True,
    )
    if not existing:
        frappe.throw(_("Input Serial No {0} does not exist").format(serial_no))
    if item_code and existing.item_code and existing.item_code != item_code:
        frappe.throw(
            _("Input Serial No {0} belongs to item {1}, not {2}")
            .format(serial_no, existing.item_code, item_code)
        )
    if warehouse and existing.warehouse and existing.warehouse != warehouse:
        frappe.throw(
            _("Input Serial No {0} is in warehouse {1}, not {2}")
            .format(serial_no, existing.warehouse, warehouse)
        )
    # Update custom fields on the existing serial for traceability
    updates = {}
    if material_cutting_plan and frappe.db.has_column("Serial No", "custom_material_cutting_plan"):
        updates["custom_material_cutting_plan"] = material_cutting_plan
    if custom_stock_entry_row_name and frappe.db.has_column("Serial No", "custom_stock_entry_row_name"):
        updates["custom_stock_entry_row_name"] = custom_stock_entry_row_name
    if updates:
        frappe.db.set_value("Serial No", serial_no, updates, update_modified=False)
    return existing


def _ensure_output_serial_exists_or_create(
    serial_no,
    item_code,
    warehouse,
    material_cutting_plan=None,
    custom_stock_entry_row_name=None,
    length_mm=None,
    width_mm=None,
    node_type=None,
):
    existing = frappe.db.get_value(
        "Serial No",
        serial_no,
        ["name", "item_code", "warehouse"],
        as_dict=True,
    )

    if existing:
        if existing.item_code and existing.item_code != item_code:
            frappe.throw(
                _("Output Serial No {0} belongs to item {1}, not {2}")
                .format(serial_no, existing.item_code, item_code)
            )

        if existing.warehouse and existing.warehouse != warehouse:
            frappe.throw(
                _("Output Serial No {0} already exists in another warehouse: {1}")
                .format(serial_no, existing.warehouse)
            )

        updates = {}
        if frappe.db.has_column("Serial No", "custom_material_cutting_plan"):
            updates["custom_material_cutting_plan"] = material_cutting_plan
        if frappe.db.has_column("Serial No", "custom_stock_entry_row_name"):
            updates["custom_stock_entry_row_name"] = custom_stock_entry_row_name
        if frappe.db.has_column("Serial No", "custom_dimension_length_mm") and length_mm is not None:
            updates["custom_dimension_length_mm"] = flt(length_mm)
        if frappe.db.has_column("Serial No", "custom_dimension_width_mm") and width_mm is not None:
            updates["custom_dimension_width_mm"] = flt(width_mm)
        if frappe.db.has_column("Serial No", "custom_surface_mm2") and length_mm is not None and width_mm is not None:
            updates["custom_surface_mm2"] = flt(length_mm) * flt(width_mm)
        if frappe.db.has_column("Serial No", "custom_cutting_node_type") and node_type:
            updates["custom_cutting_node_type"] = node_type

        if updates:
            frappe.db.set_value("Serial No", serial_no, updates, update_modified=False)

        return {
            "serial_no": serial_no,
            "already_exists": True,
        }

    serial_doc = frappe.new_doc("Serial No")
    serial_doc.serial_no = serial_no
    serial_doc.item_code = item_code
    serial_doc.company = frappe.defaults.get_user_default("Company")

    # IMPORTANT:
    # Do NOT set warehouse on a newly created Serial No.
    # ERPNext will set it through Stock Entry / Purchase Receipt.

    if frappe.db.has_column("Serial No", "custom_material_cutting_plan"):
        serial_doc.custom_material_cutting_plan = material_cutting_plan
    if frappe.db.has_column("Serial No", "custom_stock_entry_row_name"):
        serial_doc.custom_stock_entry_row_name = custom_stock_entry_row_name
    if frappe.db.has_column("Serial No", "custom_dimension_length_mm") and length_mm is not None:
        serial_doc.custom_dimension_length_mm = flt(length_mm)
    if frappe.db.has_column("Serial No", "custom_dimension_width_mm") and width_mm is not None:
        serial_doc.custom_dimension_width_mm = flt(width_mm)
    if frappe.db.has_column("Serial No", "custom_surface_mm2") and length_mm is not None and width_mm is not None:
        serial_doc.custom_surface_mm2 = flt(length_mm) * flt(width_mm)
    if frappe.db.has_column("Serial No", "custom_cutting_node_type") and node_type:
        serial_doc.custom_cutting_node_type = node_type

    serial_doc.insert(ignore_permissions=True)

    return {
        "serial_no": serial_doc.name,
        "already_exists": False,
    }


def _bind_bundle_to_row(row, bundle_name):
    row.serial_and_batch_bundle = bundle_name
    row.serial_no = None
    row.use_serial_batch_fields = 1


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
    """
    Prepare input rows for a MCP repack Stock Entry.

    Rather than creating Serial and Batch Bundles at draft time, this
    function collects and attaches the expected serial numbers to each
    row.  Serial validation still occurs to ensure that all input
    serials exist and are located in the appropriate warehouse, but
    bundle creation is deferred until the Stock Entry is submitted.  The
    deterministic serial list is exposed on the ``serial_no`` field so
    that ERPNext does not auto‑fill arbitrary serials when editing the
    draft.  In addition, the list is recorded in
    ``custom_mcp_serial_nos_json`` and the row's ``use_serial_batch_fields``
    flag is set so that ERPNext will create the outgoing bundle using
    these serials during submission.
    """
    import json

    grouped_inputs = _get_input_serial_names_from_mcp_sheets(doc)

    if not grouped_inputs:
        for node in effective_nodes:
            item_code = node.get("item_code") or doc.get("source_item")
            warehouse = _target_input_warehouse(doc, node)
            serial_no = cstr(node.get("serial_no") or "").strip()

            if item_code and warehouse and serial_no:
                grouped_inputs[(item_code, warehouse)].add(serial_no)

    for (item_code, warehouse), serials in grouped_inputs.items():
        # Ensure a deterministic ordering and remove duplicates
        serials = list(dict.fromkeys(serials))
        if not serials:
            continue

        # Create the input row on the Stock Entry
        row = se.append("items", {})
        row.item_code = item_code
        row.s_warehouse = warehouse
        row.qty = len(serials)
        _set_item_uom_fields(row, item_code)

        validated_serials = []
        for serial_no in serials:
            # Validate that each input serial exists and belongs to the
            # correct item and warehouse. This does not create anything new.
            _ensure_input_serial_exists(
                serial_no=serial_no,
                item_code=item_code,
                warehouse=warehouse,
            )
            validated_serials.append(serial_no)

        # At draft time, do not create bundles.  Instead, expose the list of
        # expected serials on the ``serial_no`` field so that the user can
        # immediately see which serials are planned for this row.  Also
        # record the deterministic list in ``custom_mcp_serial_nos_json`` so
        # that the materialisation logic can read it later.  Finally, set
        # ``use_serial_batch_fields`` so that ERPNext will use these serials
        # during submission and create the outgoing bundle automatically.
        row.serial_no = "\n".join(validated_serials)
        try:
            row.custom_mcp_serial_nos_json = json.dumps(validated_serials)
        except Exception:
            pass
        # Mark row to use the serial/batch fields for input rows.  Assign even if
        # the property does not exist to ensure the flag is present on the document.
        try:
            row.use_serial_batch_fields = 1
        except Exception:
            setattr(row, "use_serial_batch_fields", 1)

        # Clear batch information; bundling will clear the batch later.
        if hasattr(row, "batch_no"):
            row.batch_no = ""

def _build_output_rows(se, doc, effective_nodes):
    """
    Prepare output rows for a MCP repack Stock Entry.

    In the draft phase, no Serial Nos or Serial and Batch Bundles are
    created.  This function defines the expected output rows and
    records the list of deterministic serial numbers for each row in both
    the ``serial_no`` display field and the ``custom_mcp_serial_nos_json``
    field.  The dimensions and node types are also stored on the row for
    later processing.  Creation of Serial Nos and bundles is deferred
    until ``before_submit``, when the Stock Entry has a full
    transactional context and a name.
    """
    import json

    fg_groups = defaultdict(list)
    other_rows = []

    # Group finished goods with identical characteristics
    for node in effective_nodes:
        for child in node.get("children") or []:
            if not _include_child_in_repack(doc, child):
                continue

            node_type = (child.get("node_type") or "").strip()
            item_code = _target_output_item_code(doc, node, child)
            warehouse = _target_output_warehouse(doc, node, child)
            serial_no = cstr(_target_serial_name(child) or "").strip()
            length_mm, width_mm = _get_effective_dims(child)

            if not item_code or not warehouse or not serial_no:
                continue

            if node_type == "finished_good":
                key = (item_code, warehouse, length_mm, width_mm, node_type)
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

    # Handle finished goods rows
    for (item_code, warehouse, length_mm, width_mm, node_type), serials in fg_groups.items():
        # Ensure deterministic ordering and remove duplicates
        serials = list(dict.fromkeys(serials))
        if not serials:
            continue

        row = se.append("items", {})
        row.item_code = item_code
        row.t_warehouse = warehouse
        row.is_finished_item = 1

        # Set manual rate flag if available
        if hasattr(row, "set_basic_rate_manually"):
            row.set_basic_rate_manually = 1

        _set_item_uom_fields(row, item_code)

        # At draft time, expose the deterministic serial list on
        # ``serial_no`` so the user can see which serials will be produced.
        # Also store the list in ``custom_mcp_serial_nos_json`` to be read
        # during materialisation.  Output rows do not need to set
        # use_serial_batch_fields because bundles are created manually.
        row.serial_no = "\n".join(serials)
        row.qty = len(serials)
        try:
            row.custom_mcp_serial_nos_json = json.dumps(serials)
        except Exception:
            pass

        # Append custom dimension and node type fields
        _append_custom_output_fields(row, length_mm, width_mm, node_type)

    # Handle leftovers, waste, and other node types one by one
    for out in other_rows:
        # Each leftover or waste output is represented by a separate row
        row = se.append("items", {})
        row.item_code = out["item_code"]
        row.t_warehouse = out["warehouse"]
        row.qty = 1
        _set_item_uom_fields(row, out["item_code"])

        # Set manual rate flag if available
        if hasattr(row, "set_basic_rate_manually"):
            row.set_basic_rate_manually = 1

        # Display the single deterministic serial number in serial_no so the
        # user can view it directly in the UI.  Also record it in
        # custom_mcp_serial_nos_json for later materialisation.  Output rows
        # do not use serial batch fields at draft time.
        row.serial_no = out["serial_no"]
        try:
            row.custom_mcp_serial_nos_json = json.dumps([out["serial_no"]])
        except Exception:
            pass

        # Append custom dimension and node type fields
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
    serial_nos = set()

    row_name = cstr(row.get("name") or "").strip()
    if row_name and frappe.db.has_column("Serial No", "custom_stock_entry_row_name"):
        linked_serials = frappe.get_all(
            "Serial No",
            filters={"custom_stock_entry_row_name": row_name},
            pluck="name",
        )
        if linked_serials:
            return set(linked_serials)

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

def _create_bundle(
    company,
    item_code,
    warehouse,
    serials,
    custom_stock_entry_row_name,
    material_cutting_plan=None,
    type_of_transaction=None,
    voucher_type=None,
    voucher_no=None,
    voucher_detail_no=None,
):
    if not serials:
        return None

    bundle = frappe.new_doc("Serial and Batch Bundle")
    bundle.company = company
    bundle.item_code = item_code
    bundle.warehouse = warehouse
    bundle.use_serial_batch_fields = 1

    bundle.type_of_transaction = type_of_transaction
    bundle.voucher_type = voucher_type
    bundle.voucher_no = voucher_no
    bundle.voucher_detail_no = voucher_detail_no

    if frappe.db.has_column("Serial and Batch Bundle", "custom_material_cutting_plan"):
        bundle.custom_material_cutting_plan = material_cutting_plan

    if frappe.db.has_column("Serial and Batch Bundle", "custom_stock_entry_row_name"):
        bundle.custom_stock_entry_row_name = custom_stock_entry_row_name

    for serial_no in list(dict.fromkeys(serials)):
        bundle.append("entries", {
            "serial_no": serial_no
        })

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

        row_name = cstr(it.name or "").strip()
        if row_name and frappe.db.has_column("Serial No", "custom_stock_entry_row_name"):
            linked_serials = frappe.get_all(
                "Serial No",
                filters={"custom_stock_entry_row_name": row_name},
                pluck="name",
            )
            if linked_serials:
                serials = linked_serials
            else:
                serials = _extract_serials_from_text(it.serial_no or "")
        else:
            serials = _extract_serials_from_text(it.serial_no or "")

        if not serials:
            continue

        for serial_no in serials:
            _ensure_input_serial_exists(serial_no=serial_no, item_code=item_code, warehouse=warehouse)

        bundle_name = _create_bundle(
            company=doc.company,
            item_code=item_code,
            warehouse=warehouse,
            serials=serials,
            custom_stock_entry_row_name=it.name,
            material_cutting_plan=doc.custom_material_cutting_plan or None,
        )

        _assert_bundle_matches_expected(bundle_name, serials)

        if bundle_name:
            _bind_bundle_to_row(it, bundle_name)
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
            _("Bundle {0} does not match expected MCP serials. Expected: {1} Actual: {2}")
            .format(
                bundle_name,
                ", ".join(sorted(expected_set)),
                ", ".join(sorted(actual_serials)),
            )
        )

def _get_planned_input_serials_by_item_warehouse(doc, effective_nodes):
    grouped = _get_input_serial_names_from_mcp_sheets(doc)
    if grouped:
        return grouped

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


# -----------------------------------------------------------------------------
# MCP bundling service
#
# When creating a draft Stock Entry from a Material Cutting Plan (MCP), the
# repack draft service records the expected output and input serial numbers on
# each row via the ``serial_no`` field.  No Serial No or bundle records are
# created at that time.  Once the user validates or submits the Stock Entry,
# the serials and bundles must be materialised.  The following function
# performs this materialisation in a transactional context, ensuring that
# deterministic serials and bundles are created and linked to the Stock Entry
# rows. It uses the same helper functions as the draft service for serial
# creation and bundle linking and respects ERPNext rules around serial and
# bundle creation.
def ensure_mcp_bundles_for_stock_entry(doc):
    """
    Materialise MCP serials and bundles for a Stock Entry.

    This function should be invoked during the ``before_submit`` event of a
    Stock Entry.  It reads the deterministic list of serial numbers from
    ``custom_mcp_serial_nos_json`` on each item row; if that field is
    missing or empty, it falls back to the ``serial_no`` display field.  For
    input rows (those with ``s_warehouse`` only), it validates that each
    listed Serial No exists in the correct item and warehouse, stamps the
    ``Serial No`` record with the MCP and Stock Entry row information, and
    then writes the newline‑separated list back to ``serial_no`` and sets
    ``use_serial_batch_fields = 1``.  No bundle is created for input rows;
    ERPNext will create the outgoing bundle automatically based on these
    fields when the Stock Entry is submitted.  For output rows (those
    with ``t_warehouse``), it ensures that each Serial No exists or
    creates it if missing, stamps custom fields for traceability, and
    creates an incoming ``Serial and Batch Bundle`` that links the serials
    to the Stock Entry.  After bundling, the row's ``serial_no`` is
    cleared (handled by ``_bind_bundle_to_row``) to satisfy ERPNext
    validation.

    Args:
        doc: The Stock Entry document to process.

    Returns:
        dict: A dictionary containing the names of any created serial numbers
        and bundles.  Keys are ``serial_nos`` and ``bundles``.
    """
    import json
    from frappe.utils import flt

    # Only apply to Repack entries linked to an MCP
    if (doc.stock_entry_type or "") != "Repack":
        return {"serial_nos": [], "bundles": []}

    mcp_name = cstr(doc.get("custom_material_cutting_plan") or "").strip()
    if not mcp_name:
        return {"serial_nos": [], "bundles": []}

    created_serials: list[str] = []
    created_bundles: list[str] = []

    for it in (doc.items or []):
        # Skip rows that are already bound to a bundle
        existing_bundle = (it.get("serial_and_batch_bundle") or it.get("serial_batch_bundle") or "").strip()
        if existing_bundle:
            continue

        # Determine row type
        is_input = bool(it.get("s_warehouse")) and not bool(it.get("t_warehouse"))
        is_output = bool(it.get("t_warehouse"))
        if not is_input and not is_output:
            continue

        # Parse serial list from custom_mcp_serial_nos_json if present; otherwise
        # fall back to serial_no display field.  Always remove duplicates
        # while preserving order.
        serials: list[str] = []
        json_text = cstr(it.get("custom_mcp_serial_nos_json") or "").strip()
        if json_text:
            try:
                loaded = json.loads(json_text)
                if isinstance(loaded, list):
                    for s in loaded:
                        s = cstr(s).strip()
                        if s:
                            serials.append(s)
            except Exception:
                # If JSON parsing fails, ignore and fall back to serial_no
                serials = []
        if not serials:
            # Fallback: parse serial_no lines
            serial_no_value = cstr(it.get("serial_no") or "").strip()
            if serial_no_value:
                for s in serial_no_value.splitlines():
                    s = cstr(s).strip()
                    if s:
                        serials.append(s)
        # Remove duplicates while preserving order
        if serials:
            serials = list(dict.fromkeys(serials))
        if not serials:
            continue

        item_code = (it.get("item_code") or "").strip()
        if not item_code:
            continue

        if is_input:
            warehouse = (it.get("s_warehouse") or "").strip()
            if not warehouse:
                continue

            validated_serials: list[str] = []
            for sn in serials:
                # Validate that the input serial exists and matches item and warehouse,
                # and stamp the Serial No with MCP and row information for traceability.
                _ensure_input_serial_exists(
                    serial_no=sn,
                    item_code=item_code,
                    warehouse=warehouse,
                    material_cutting_plan=mcp_name or None,
                    custom_stock_entry_row_name=it.name,
                )
                validated_serials.append(sn)

            # For input rows, do not create any bundle.  Instead, set the row's
            # serial_no field to the deterministic list and enable use_serial_batch_fields
            # so that ERPNext will create the outgoing bundle automatically.
            it.serial_no = "\n".join(validated_serials)
            # set custom_mcp_serial_nos_json as the canonical source if not already set
            try:
                it.custom_mcp_serial_nos_json = json.dumps(validated_serials)
            except Exception:
                pass
            # Flag ERPNext to use serial/batch fields during submission
            try:
                it.use_serial_batch_fields = 1
            except Exception:
                # attribute may not exist; assign anyway to document
                setattr(it, "use_serial_batch_fields", 1)
            # Clear batch information for consistency
            if hasattr(it, "batch_no"):
                it.batch_no = ""
            continue

        if is_output:
            warehouse = (it.get("t_warehouse") or "").strip()
            if not warehouse:
                continue

            # Gather dimension and node type information to stamp on Serial No
            length_mm = flt(it.get("custom_dimension_length_mm") or 0)
            width_mm = flt(it.get("custom_dimension_width_mm") or 0)
            node_type = (it.get("custom_cutting_node_type") or "").strip()

            newly_created: list[str] = []
            for sn in serials:
                result = _ensure_output_serial_exists_or_create(
                    serial_no=sn,
                    item_code=item_code,
                    warehouse=warehouse,
                    material_cutting_plan=mcp_name or None,
                    custom_stock_entry_row_name=it.name,
                    length_mm=length_mm,
                    width_mm=width_mm,
                    node_type=node_type,
                )
                if not result.get("already_exists"):
                    newly_created.append(result["serial_no"])
            # Create a bundle that references all serials (existing and newly created). Output
            # bundles are linked to the voucher for complete traceability.
            bundle_name = _create_bundle(
                company=doc.company,
                item_code=item_code,
                warehouse=warehouse,
                serials=serials,
                custom_stock_entry_row_name=it.name,
                material_cutting_plan=mcp_name or None,
                type_of_transaction="Inward",
                voucher_type="Stock Entry",
                voucher_no=doc.name,
                voucher_detail_no=it.name,
            )
            if bundle_name:
                _bind_bundle_to_row(it, bundle_name)
                # Do not set serial_no after binding; it must remain blank when a bundle is present.
                if hasattr(it, "batch_no"):
                    it.batch_no = ""
                created_bundles.append(bundle_name)
                created_serials.extend(newly_created)

    return {"serial_nos": created_serials, "bundles": created_bundles}