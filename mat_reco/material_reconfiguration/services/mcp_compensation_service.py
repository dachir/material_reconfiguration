"""MCP compensation: reconciliation, preview and atomic server application.

A piece_uid identifies a commercial unit; a node id identifies an operation
(and its deterministic output Serial No). Neither is an execution receipt.
"""
from __future__ import annotations

from copy import deepcopy
import math


def _identity(row):
    return str(row.get("id") or row.get("piece_uid") or "").strip()


def _fits_demand(piece, demand):
    def dims(row, effective=False):
        values = []
        for key in ("length_mm", "width_mm"):
            value = row.get("effective_" + key, row.get(key)) if effective else row.get(key)
            number = float(value or 0)
            if not math.isfinite(number) or number <= 0:
                return None
            values.append(round(number, 3))
        return sorted(values)
    expected = dims(demand)
    required_thickness = float(demand.get("thickness_mm") or 0)
    actual_thickness = float(piece.get("thickness_mm") or 0)
    if required_thickness and (not math.isfinite(actual_thickness) or abs(required_thickness-actual_thickness)>0.001):
        return False
    return expected is not None and dims(piece, True) == expected and (
        piece.get("piece_item_code") or piece.get("item_code")) == demand.get("piece_item_code")


def reconcile_requirements(demands, effective_nodes, incidents=(), submitted_output_ids=()):
    """Reconcile unit needs without mutating inputs or treating plans as production.

    Healthy planned operations reserve a need, avoiding duplicate compensation.
    Only submitted Repack output serials prove production. A destroyed operation
    never covers a need, including when the operation is itself a replacement.
    """
    needs = {}
    for demand in demands:
        uid = str(demand.get("piece_uid") or "").strip()
        if not uid or uid in needs or float(demand.get("qty", 1)) != 1:
            raise ValueError("Commercial demands require unique unit piece_uid identifiers.")
        needs[uid] = deepcopy(demand)
    destroyed_ids = {str(row.get("plan_node_id") or "").strip() for row in incidents
                     if int(row.get("is_active") or 0) == 1 and row.get("incident_action") == "Destroy"}
    submitted = set(submitted_output_ids)
    operations = {uid: [] for uid in needs}
    warnings = []
    seen = set()
    broken = []
    replacements = []
    for sheet in effective_nodes:
        for child in sheet.get("children") or []:
            uid = str(child.get("piece_uid") or "").strip()
            if uid not in needs:
                if child.get("node_type") == "finished_good":
                    warnings.append(f"Unmatched commercial unit for operation {_identity(child)}.")
                continue
            op_id = _identity(child)
            if child.get("__generated_from_resize"):
                continue  # complementary destroyed strips are not unit failures
            if not op_id or op_id in seen:
                raise ValueError("Operation identities must be unique across all sheets.")
            seen.add(op_id)
            is_broken = child.get("node_type") == "destroyed" or op_id in destroyed_ids
            if not is_broken and child.get("node_type") != "finished_good":
                continue
            operation = {"operation_id": op_id, "requirement_id": uid,
                         "source_serial_no": sheet.get("serial_no") or sheet.get("id"),
                         "is_replacement": op_id != uid,
                         "state": "broken" if is_broken else "planned"}
            if is_broken:
                broken.append(deepcopy(operation))
                if op_id in submitted:
                    warnings.append(f"Destroyed operation {op_id} occurs in a submitted Repack; reconciliation required.")
            elif not _fits_demand(child, needs[uid]):
                operation["state"] = "nonconforming"
                warnings.append(f"Operation {op_id} does not match the commercial dimensions or item.")
            elif op_id in submitted:
                operation["state"] = "produced"
            if operation["is_replacement"]:
                replacements.append(deepcopy(operation))
            operations[uid].append(operation)
    requirements = []
    missing = []
    for uid, demand in needs.items():
        attempts = operations[uid]
        produced = [op for op in attempts if op["state"] == "produced"]
        planned = [op for op in attempts if op["state"] == "planned"]
        if len(produced) + len(planned) > 1:
            warnings.append(f"Multiple live operations cover commercial unit {uid}.")
        state = "produced" if produced else "replacement_planned" if any(op["is_replacement"] for op in planned) else "planned" if planned else "missing"
        row = {**demand, "requirement_id": uid, "state": state,
               "missing_qty": 0 if produced else 1,
               "compensation_qty": int(not produced and not planned),
               "broken_operation_ids": [op["operation_id"] for op in attempts if op["state"] == "broken"],
               "operations": attempts}
        requirements.append(row)
        if row["compensation_qty"]:
            missing.append(deepcopy(row))
    return {"requirements": requirements, "compensation_requirements": missing,
            "broken_pieces": broken, "replacement_pieces": replacements, "warnings": warnings,
            "summary": {"requested": len(needs),
                        "produced": sum(row["state"] == "produced" for row in requirements),
                        "planned": sum(row["state"] in ("planned", "replacement_planned") for row in requirements),
                        "broken_operations": len(broken), "to_compensate": len(missing),
                        "remaining_to_produce": sum(row["missing_qty"] for row in requirements)}}


def get_requirements_for_doc(doc):
    """Read authoritative demand, effective geometry and submitted Repack receipts."""
    import frappe
    from mat_reco.material_reconfiguration.services.order_explosion_service import explode_sales_orders_into_cutting_demands
    from mat_reco.material_reconfiguration.services.repack_draft_service import build_effective_nodes

    demands = explode_sales_orders_into_cutting_demands(
        sales_order_names=[row.get("sales_order") for row in doc.get("selected_sales_orders") or [] if row.get("sales_order")],
        source_item=doc.get("source_item"), max_depth=int(doc.get("max_depth") or 10))
    submitted, _ = submitted_receipts(doc)
    result = reconcile_requirements(demands, build_effective_nodes(doc),
                                    doc.get("material_plan_incidents") or [], submitted)
    result.update({"mcp": doc.name, "document_version": str(doc.modified)})
    return result


# Import Frappe only for the API; the reducer has no database dependencies.
import frappe


@frappe.whitelist()
def get_compensation_requirements(material_cutting_plan_name):
    doc = frappe.get_doc("Material Cutting Plan", material_cutting_plan_name)
    doc.check_permission("read")
    doc.check_permission("write")
    if int(doc.docstatus) != 0 or doc.get("mcp_mode") != "Retour Terrain":
        frappe.throw("La compensation exige un MCP brouillon en mode Retour Terrain.")
    if not (doc.get("effective_result_json") or doc.get("result_json")):
        frappe.throw("Enregistrez un plan de découpe avant de calculer les besoins.")
    return get_requirements_for_doc(doc)


def submitted_receipts(doc):
    from mat_reco.material_reconfiguration.services.repack_draft_service import _extract_serial_nos_from_stock_entry_detail
    outputs, inputs = set(), set()
    entries = frappe.get_all("Stock Entry", filters={"custom_material_cutting_plan": doc.name,
        "docstatus": 1, "stock_entry_type": "Repack"}, pluck="name")
    for name in entries:
        for row in frappe.get_doc("Stock Entry", name).get("items") or []:
            serials = _extract_serial_nos_from_stock_entry_detail(row)
            if row.get("t_warehouse"):
                outputs.update(serials)
            if row.get("s_warehouse"):
                inputs.update(serials)
    return outputs, inputs


def _compensation_doc(name, for_update=False):
    if not isinstance(name, str) or not name.strip():
        raise ValueError("Identifiant MCP obligatoire.")
    doc = frappe.get_doc("Material Cutting Plan", name, for_update=for_update)
    doc.check_permission("read")
    doc.check_permission("write")
    if int(doc.get("docstatus") or 0) != 0 or doc.get("mcp_mode") != "Retour Terrain":
        raise ValueError("La compensation exige un MCP brouillon en mode Retour Terrain.")
    if not (doc.get("effective_result_json") or doc.get("result_json")):
        raise ValueError("Enregistrez un plan de découpe avant de calculer la compensation.")
    if not doc.get("company") or not doc.get("source_warehouse"):
        raise ValueError("Société et dépôt source obligatoires.")
    warehouse = frappe.get_doc("Warehouse", doc.get("source_warehouse"))
    warehouse.check_permission("read")
    if warehouse.company != doc.company:
        raise ValueError("Le dépôt ne correspond pas à la société du MCP.")
    return doc


def _snapshot(doc):
    from mat_reco.material_reconfiguration.services.mcp_action_preview import _effective_tree, _document_version
    from mat_reco.material_reconfiguration.services.mcp_incident_service import apply_destroy_to_child
    tree = _effective_tree(doc)
    # Pending Destroy also excludes a leftover on an already resolved plan.
    active_destroy = {r.get("plan_node_id") for r in doc.get("material_plan_incidents") or []
                      if int(r.get("is_active") or 0) and r.get("incident_action") == "Destroy"}
    for sheet in tree["nodes"]:
        sheet["children"] = [apply_destroy_to_child(c) if c.get("id") in active_destroy and c.get("node_type") != "destroyed" else c for c in sheet.get("children") or []]
    needs = get_requirements_for_doc(doc)
    outputs, inputs = submitted_receipts(doc)
    inputs = set(inputs)
    for sheet in tree["nodes"]:
        serial = frappe.get_doc("Serial No", sheet.get("serial_no") or sheet.get("id"))
        if (not serial.has_permission("read") or serial.get("company") != doc.get("company")
            or serial.get("warehouse") != doc.get("source_warehouse") or serial.get("status") != "Active"
            or serial.get("custom_material_status") not in ("Full", "Partial")):
            inputs.add(sheet.get("serial_no") or sheet.get("id"))
        if not sheet.get("thickness_mm"):
            sheet["thickness_mm"] = _source_thickness(serial)
    return tree, needs, outputs, inputs, _document_version(doc)


def _eligible_stock(doc, nodes, requirements=()):
    from mat_reco.material_reconfiguration.services.stock_candidate_service import get_available_cutting_bins
    existing = {s.get("serial_no") or s.get("id") for s in nodes}
    bins = get_available_cutting_bins(doc.get("source_item"), warehouse=doc.get("source_warehouse"),
        variant_item_codes=[r.get("variant_item_code") for r in doc.get("item_variant_detail") or []])
    result = []
    for source in bins:
        if source["serial_no"] in existing:
            continue
        serial = frappe.get_doc("Serial No", source["serial_no"])
        if not serial.has_permission("read") or serial.get("status") != "Active" or serial.get("company") != doc.get("company"):
            continue
        if source.get("warehouse") != doc.get("source_warehouse"):
            continue
        # A Serial selected in another live MCP is not offered twice.
        claims = frappe.get_all("MCP Stock Candidate", filters={"serial_no": source["serial_no"], "is_active_input": 1,
            "parent": ["!=", doc.name], "parenttype": "Material Cutting Plan"}, fields=["parent"])
        if any(int(frappe.db.get_value("Material Cutting Plan", r.parent, "docstatus") or 0) < 2 for r in claims):
            continue
        source["thickness_mm"] = _source_thickness(serial)
        compatible = not requirements or any(_source_can_fit(source, r, bool(doc.get("allow_rotation"))) for r in requirements)
        result.append({**source, "compatible": compatible, "origin": "stock_leftover" if source["material_status"] == "Partial" else "stock_sheet",
                       "priority": 2 if source["material_status"] == "Partial" else 3, "status": "Disponible" if compatible else "Incompatible"})
    return result


def propose_compensation(tree, requirements, stock_sources=(), kerf_mm=0, allow_rotation=True,
                         frozen_ids=(), consumed_inputs=(), selected_sources=(), strategy="automatic", override_reason="", seed=""):
    """Server-side priority orchestration; selected unused stock never enters nodes."""
    from mat_reco.material_reconfiguration.services.mcp_compensation_geometry import propose_internal, internal_candidates, stock_sheet
    from mat_reco.material_reconfiguration.services.mcp_action_preview import _validate_nodes
    if strategy not in ("automatic", "manual"):
        raise ValueError("Stratégie de compensation invalide.")
    selected = set(selected_sources)
    if len(selected) > 100 or any(not isinstance(s, str) for s in selected):
        raise ValueError("Sélection de sources invalide.")
    nodes = deepcopy(tree["nodes"])
    eligible_nodes = [s for s in nodes if (s.get("serial_no") or s.get("id")) not in set(consumed_inputs)]
    candidates = internal_candidates(eligible_nodes, frozen_ids)
    available = {c["candidate_id"] for c in candidates} | {s["serial_no"] for s in stock_sources}
    if selected - available:
        raise ValueError("Une source sélectionnée n’est plus disponible. Actualisez les matières.")
    if strategy == "manual" and not selected:
        raise ValueError("Sélectionnez une source pour la stratégie manuelle.")
    automatic = None
    if selected and not str(override_reason).strip():
        automatic = propose_compensation(tree, requirements, stock_sources, kerf_mm, allow_rotation,
            frozen_ids, consumed_inputs, (), "automatic", "", seed)
    frozen = set(frozen_ids)
    frozen.update(c["source_node_id"] for c in internal_candidates(nodes, frozen_ids)
                  if c["source_serial_no"] in set(consumed_inputs))
    allowed_candidates = selected if strategy == "manual" else None
    result = propose_internal(nodes, requirements, kerf_mm, allow_rotation, frozen, seed,
                              allowed_candidate_ids=allowed_candidates)
    nodes, remaining, placements = result["nodes"], result["remaining"], result["placements"]
    warnings = result["warnings"]
    used = []
    for priority in (2, 3):
        pool = [s for s in stock_sources if s["priority"] == priority and s.get("compatible") is not False and (not selected or s["serial_no"] in selected)]
        while pool and remaining:
            scored = []
            for source in pool:
                attempt = propose_internal([stock_sheet(source)], remaining, kerf_mm, allow_rotation, seed=seed)
                if attempt["placements"]:
                    area_used = sum(p["length_mm"]*p["width_mm"] for p in attempt["placements"])
                    scored.append((-len(attempt["placements"]), source["area_mm2"]-area_used,
                                   source["serial_no"], source, attempt))
            if not scored:
                break
            _, _, _, source, attempt = min(scored, key=lambda entry:entry[:3])
            nodes.extend(attempt["nodes"])
            for p in attempt["placements"]:
                p["origin"] = source["origin"]
                for child in attempt["nodes"][0]["children"]:
                    if child.get("id") == p["id"]:
                        child["compensation_origin"] = source["origin"]
            placements.extend(attempt["placements"])
            remaining = attempt["remaining"]
            warnings.extend(attempt["warnings"])
            used.append(deepcopy(source))
            pool = [s for s in pool if s["serial_no"] != source["serial_no"]]
    _validate_nodes(nodes)
    for p in placements:
        p.setdefault("origin", "internal")
    if automatic is not None:
        ranks = {"internal":1, "stock_leftover":2, "stock_sheet":3}
        preferred = {p["piece_uid"]:ranks[p["origin"]] for p in automatic["placements"]}
        if any(preferred.get(p["piece_uid"],3) < ranks[p["origin"]] for p in placements):
            raise ValueError("Justifiez l’écartement des sources prioritaires pour ce choix de matière.")
    return {"effective_tree": {**deepcopy(tree), "nodes": nodes}, "placements": placements,
            "remaining_requirements": remaining, "used_stock_sources": used, "internal_candidates": candidates,
            "warnings": sorted(set(warnings)), "summary": {"replaced": len(placements), "remaining": len(remaining),
                "additional_materials": len(used), "used_area_mm2": sum(p["length_mm"]*p["width_mm"] for p in placements),
                "remaining_area_mm2": sum(c["length_mm"]*c["width_mm"] for c in internal_candidates([n for n in nodes if (n.get("serial_no") or n.get("id")) not in set(consumed_inputs)], frozen_ids))}}


def _parse_options(strategy, selected_sources, override_reason):
    import json
    selected = json.loads(selected_sources) if isinstance(selected_sources, str) else selected_sources or []
    if not isinstance(selected, list) or any(not isinstance(v, str) for v in selected):
        raise ValueError("La sélection doit être une liste de sources.")
    return {"strategy": strategy, "selected_sources": sorted(set(selected)), "override_reason": str(override_reason or "").strip()[:1000]}


def _preview(doc, options):
    from mat_reco.material_reconfiguration.services.mcp_compensation_geometry import signature
    tree, needs, outputs, inputs, version = _snapshot(doc)
    sources = _eligible_stock(doc, tree["nodes"], needs["compensation_requirements"])
    result = propose_compensation(tree, needs["compensation_requirements"], sources,
        kerf_mm=float(doc.get("kerf_mm") or 0), allow_rotation=bool(doc.get("allow_rotation")),
        frozen_ids=outputs, consumed_inputs=inputs, seed=signature([version, needs["requirements"]]), **options)
    result.update({"valid": True, "requirements": needs["requirements"], "broken_pieces": needs["broken_pieces"],
                   "replacement_pieces": needs["replacement_pieces"], "coverage": needs["summary"], "stock_candidates": sources,
                   "document_version": version, "options": options})
    result["warnings"].extend(needs["warnings"])
    result["proposal_id"] = signature([version, result["placements"], result["remaining_requirements"], result["used_stock_sources"], sorted(outputs), sorted(inputs), options])
    return result


@frappe.whitelist()
def preview_compensation(mcp_name, strategy="automatic", selected_sources=None, override_reason=""):
    try:
        return _preview(_compensation_doc(mcp_name), _parse_options(strategy, selected_sources, override_reason))
    except (ValueError, TypeError, frappe.ValidationError) as exc:
        return {"valid": False, "errors": [str(exc)], "document_modified": False}


@frappe.whitelist()
def load_compensation(mcp_name):
    from mat_reco.material_reconfiguration.services.mcp_compensation_geometry import internal_candidates
    try:
        doc = _compensation_doc(mcp_name)
        tree, needs, outputs, inputs, version = _snapshot(doc)
        eligible = [s for s in tree["nodes"] if (s.get("serial_no") or s.get("id")) not in inputs]
        return {"valid": True, **needs, "effective_tree": tree, "document_version": version,
                "internal_candidates": internal_candidates(eligible, outputs), "stock_candidates": _eligible_stock(doc, tree["nodes"], needs["compensation_requirements"])}
    except (ValueError, TypeError, frappe.ValidationError) as exc:
        return {"valid": False, "errors": [str(exc)]}


def _incident_state(rows):
    keys = ("plan_node_id", "source_serial_no", "original_node_type", "original_item_code",
        "original_length_mm", "original_width_mm", "original_area_mm2", "group_area_mm2", "new_area_mm2", "incident_action", "affected_node_ids_json",
        "new_node_type", "new_length_mm", "new_width_mm", "include_in_repack", "is_active", "remarks",
        "target_serial_no", "target_zone_id", "target_x_mm", "target_y_mm", "move_case")
    return [{k: r.get(k) for k in keys} for r in rows]


def preserve_compensated_plan(doc):
    """Save-hook integration for compensated plans and recorded UX20 moves.

    The database tree, never a client JSON, is the baseline. Only newly appended
    incidents are replayed; every former operation and journal event is retained.
    """
    import json
    from mat_reco.material_reconfiguration.services.mcp_incident_service import apply_incidents_to_nodes, build_incident_map
    from mat_reco.material_reconfiguration.services.mcp_action_preview import _validate_nodes, _unique_generated_ids, _effective_tree
    from mat_reco.material_reconfiguration.services.cutting_plan_service import update_active_input_flags
    from mat_reco.material_reconfiguration.doctype.material_cutting_plan.mcp_sheet_sync import sync_mcp_sheets
    previous = doc.get_doc_before_save()
    if previous is None and not doc.is_new():
        previous = frappe.get_doc("Material Cutting Plan", doc.name)
    prior_tree = json.loads(previous.get("effective_result_json") or "{}") if previous else {}
    prior_tree = prior_tree.get("tree") or prior_tree
    trusted = getattr(doc.flags, "compensation_tree", None)
    new_rows = (doc.get("material_plan_incidents") or [])[len(previous.get("material_plan_incidents") or []):] if previous else []
    incremental_move = any(r.get("incident_action")=="Move" and "move_rotation_degrees" in (r.get("remarks") or "") for r in new_rows)
    if trusted is None and not (prior_tree.get("compensation_events") or prior_tree.get("ux20_incidents_resolved") or incremental_move):
        return False
    if doc.get("mcp_mode") != "Retour Terrain":
        frappe.throw("Un MCP avec opérations enregistrées doit rester en mode Retour Terrain.")
    if previous:
        for field in ("source_item", "source_warehouse", "company", "kerf_mm", "result_json"):
            if doc.get(field) != previous.get(field):
                frappe.throw("Les paramètres historiques des découpes enregistrées ne peuvent plus être modifiés.")
    if trusted is not None:
        tree = deepcopy(trusted)
    else:
        if doc.get("effective_result_json") != previous.get("effective_result_json"):
            frappe.throw("Le plan enregistré doit être modifié par les opérations validées du serveur.")
        old_rows = _incident_state(previous.get("material_plan_incidents") or [])
        current_rows = _incident_state(doc.get("material_plan_incidents") or [])
        if current_rows[:len(old_rows)] != old_rows:
            frappe.throw("Les incidents historiques des découpes doivent être conservés.")
        tree = _effective_tree(previous) if incremental_move and not (prior_tree.get("compensation_events") or prior_tree.get("ux20_incidents_resolved")) else deepcopy(prior_tree)
        frozen, consumed = submitted_receipts(doc)
        before = _validate_nodes(tree["nodes"])
        locked = {c.get("id"):deepcopy(c) for s in tree["nodes"] for c in s.get("children") or []
                  if c.get("id") in frozen or (s.get("serial_no") or s.get("id")) in consumed}
        for row in (doc.get("material_plan_incidents") or [])[len(old_rows):]:
            tree["nodes"] = _unique_generated_ids(apply_incidents_to_nodes(tree["nodes"],
                build_incident_map({"mcp_mode":"Retour Terrain", "allow_rotation":doc.get("allow_rotation"), "material_plan_incidents":[row]})))
        current = {c.get("id"): c for s in tree["nodes"] for c in s.get("children") or []}
        if any(current.get(key) != value for key,value in locked.items()):
            frappe.throw("Une opération déjà enregistrée dans un Repack soumis reste figée.")
        after = _validate_nodes(tree["nodes"])
        if before.keys() != after.keys() or any(abs(before[k]-after[k])>0.001 for k in before):
            frappe.throw("Les incidents doivent conserver la surface physique du MCP.")
    _validate_nodes(tree["nodes"])
    tree["return_terrain_resolved"] = True
    tree["ux20_incidents_resolved"] = True
    # Action preparation must refer to the actual saved operations, including CP ids.
    tree.pop("base_tree", None)
    doc.effective_result_json = json.dumps(tree, ensure_ascii=False, default=str)
    update_active_input_flags(doc, tree)
    sync_mcp_sheets(doc, source_json_field="effective_result_json", child_table_field="effective_mcp_sheets")
    doc._apply_summary_to_fields(doc._build_summary_from_tree(tree))
    doc.flags.compensation_tree = None
    return True


def validate_compensation_coverage(doc):
    if doc.get("mcp_mode") != "Retour Terrain" or not (doc.get("result_json") or doc.get("effective_result_json")):
        return
    result = get_requirements_for_doc(doc)
    if result["summary"]["to_compensate"] or result["warnings"]:
        frappe.throw("Soumission impossible : besoins non couverts ou incohérences de production. Ouvrez la compensation des découpes.")


@frappe.whitelist()
def apply_compensation(mcp_name, proposal_id, document_version, strategy="automatic", selected_sources=None, override_reason=""):
    """Atomically recalculate under MCP/Serial locks; persist only server placements."""
    import json
    from mat_reco.material_reconfiguration.services.mcp_action_preview import _json, _document_version
    options = _parse_options(strategy, selected_sources, override_reason)
    savepoint = "mcp_compensation"
    frappe.db.savepoint(savepoint)
    try:
        # Global lock ordering: MCP first, then all candidate Serial Nos sorted.
        frappe.db.sql("SELECT name FROM `tabMaterial Cutting Plan` WHERE name=%s FOR UPDATE", (mcp_name,))
        doc = _compensation_doc(mcp_name, for_update=True)
        if _json(document_version, dict, "Version du MCP") != _document_version(doc):
            raise ValueError("Le MCP a changé. Rechargez la compensation avant de confirmer.")
        initial = _preview(doc, options)
        if initial["proposal_id"] != proposal_id:
            raise ValueError("Le stock, les commandes ou le MCP ont changé. Actualisez et recalculez la proposition.")
        serials = sorted({p["source_serial_no"] for p in initial.get("placements", [])})
        for serial in serials:
            frappe.db.sql("SELECT name FROM `tabSerial No` WHERE name=%s FOR UPDATE", (serial,))
        _validate_locked_sources(doc, initial)
        # Current DB reads are performed again after acquiring all material locks.
        result = _preview(doc, options)
        if result["proposal_id"] != proposal_id:
            raise ValueError("Le stock, les commandes ou le MCP ont changé. Actualisez et recalculez la proposition.")
        _validate_locked_sources(doc, result)
        if not result["placements"]:
            raise ValueError("Aucun placement à appliquer.")
        if result["warnings"]:
            # Thickness exclusions are informational. Historical identity/receipt
            # conflicts must be reconciled before recording additional operations.
            needs = get_requirements_for_doc(doc)
            if needs["warnings"]:
                raise ValueError("Incohérences de production à résoudre avant l’application : " + " ".join(needs["warnings"]))
        tree = result["effective_tree"]
        tree.setdefault("compensation_events", []).append({"id": proposal_id, "mcp": doc.name,
            "created_at": frappe.utils.now(), "operator": frappe.session.user, "reference_version": result["document_version"],
            "options": options, "placements": deepcopy(result["placements"]), "sources": deepcopy(result["used_stock_sources"])})
        existing = {r.get("serial_no"): r for r in doc.get("mcp_stock_candidate") or []}
        for source in result["used_stock_sources"]:
            row = existing.get(source["serial_no"])
            if row is None:
                row = doc.append("mcp_stock_candidate", {k:source.get(k) for k in
                    ("serial_no","item_code","warehouse","material_status","length_mm","width_mm","thickness_mm")})
            row.is_qualified = 1
            row.is_active_input = 1
        doc.flags.compensation_tree = tree
        doc.save()
        from mat_reco.material_reconfiguration.services.mcp_action_preview import load_mcp_effective_plan
        saved = load_mcp_effective_plan.__wrapped__(doc.name)
        return {**saved, "applied": True, "proposal_id": proposal_id,
                "coverage": get_requirements_for_doc(doc)["summary"]}
    except (ValueError, TypeError, frappe.ValidationError) as exc:
        frappe.db.rollback(save_point=savepoint)
        return {"valid": False, "conflict": True, "errors": [str(exc)], "document_modified": False}
    except Exception:
        frappe.db.rollback(save_point=savepoint)
        raise


def _validate_locked_sources(doc, preview):
    """Locking reads see current stock even under snapshot isolation."""
    from mat_reco.material_reconfiguration.services.single_geometry import normalize_single_dimensions
    used_internal = {p["source_serial_no"] for p in preview.get("placements", []) if p["origin"] == "internal"}
    sources = {s["serial_no"]:s for s in preview.get("used_stock_sources", [])}
    for sheet in preview["effective_tree"]["nodes"]:
        if sheet.get("serial_no") in used_internal:
            sources[sheet["serial_no"]] = sheet
    for serial, expected in sources.items():
        rows = frappe.db.sql("SELECT * FROM `tabSerial No` WHERE name=%s FOR UPDATE", (serial,), as_dict=True)
        if not rows:
            raise ValueError("La matière sélectionnée n’existe plus.")
        actual = rows[0]
        if actual.get("status") != "Active" or actual.get("company") != doc.get("company") or actual.get("warehouse") != doc.get("source_warehouse"):
            raise ValueError("La disponibilité de la matière a changé. Recalculez la compensation.")
        if expected.get("item_code") and actual.get("item_code") != expected.get("item_code"):
            raise ValueError("L’article source a changé.")
        l,w,rl,rw = normalize_single_dimensions(actual.get("custom_dimension_length_mm"),actual.get("custom_dimension_width_mm"),
            actual.get("custom_removed_length_mm"),actual.get("custom_removed_width_mm"))
        thickness = float(actual.get("custom_dimension_thickness_mm") or 0)
        if not thickness:
            items = frappe.db.sql("SELECT * FROM `tabItem` WHERE name=%s FOR UPDATE", (actual.get("item_code"),), as_dict=True)
            thickness = float(items[0].get("custom_thickness_mm") or 0) if items else 0
        values = {"length_mm":l,"width_mm":w,"removed_length_mm":rl,"removed_width_mm":rw,
                  "thickness_mm":thickness}
        if any(abs(float(expected.get(k) or 0)-v)>0.001 for k,v in values.items()):
            raise ValueError("La géométrie ou l’épaisseur de la matière a changé.")
        if serial not in used_internal and actual.get("custom_material_status") != expected.get("material_status"):
            raise ValueError("Le statut de la matière a changé.")
        claims = frappe.db.sql("""SELECT candidate.parent FROM `tabMCP Stock Candidate` candidate
            INNER JOIN `tabMaterial Cutting Plan` plan ON plan.name=candidate.parent
            WHERE candidate.serial_no=%s AND candidate.is_active_input=1 AND candidate.parent!=%s
            AND candidate.parenttype='Material Cutting Plan' AND plan.docstatus<2 FOR UPDATE""", (serial, doc.name))
        if claims:
            raise ValueError("Cette matière est engagée dans un autre MCP.")


def _source_thickness(serial):
    thickness = float(serial.get("custom_dimension_thickness_mm") or 0)
    if thickness:
        return thickness
    item = frappe.get_doc("Item", serial.get("item_code"))
    if not item.has_permission("read"):
        return 0
    return float(item.get("custom_thickness_mm") or 0)


def _source_can_fit(source, requirement, allow_rotation):
    from mat_reco.material_reconfiguration.services.single_geometry import available_regions
    thickness = float(requirement.get("thickness_mm") or 0)
    if thickness and abs(thickness-float(source.get("thickness_mm") or 0)) > 0.001:
        return False
    length, width = float(requirement["length_mm"]), float(requirement["width_mm"])
    for region in available_regions(source["length_mm"], source["width_mm"], source.get("removed_length_mm"), source.get("removed_width_mm")):
        if length <= region["length_mm"] and width <= region["width_mm"]:
            return True
        if allow_rotation and width <= region["length_mm"] and length <= region["width_mm"]:
            return True
    return False
