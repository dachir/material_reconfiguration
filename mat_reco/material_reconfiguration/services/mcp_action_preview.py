"""Server-authoritative MCP previews, incident preparation and explicit reset.

Previews and preparation never save. The reset endpoint alone restores the
planning snapshot and saves the draft document under its database lock.
Pending operations are revalidated in order by the existing incident engine.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math

import frappe
from frappe.utils import cint

from mat_reco.material_reconfiguration.services.mcp_incident_service import (
    apply_incidents_to_nodes,
    build_incident_map,
    split_free_rectangle,
    _classify_free_zone,
    move_target_slots,
    move_rotation_degrees,
    rotation_allowed,
)
from mat_reco.material_reconfiguration.services.repack_draft_service import build_effective_nodes
from mat_reco.material_reconfiguration.services.single_geometry import available_regions, single_from_rectangles

EPS = 0.001
ACTIONS = {"Move", "Merge", "Single", "Resize", "Destroy"}
FREE = {"leftover", "waste"}
MAX_PENDING = 50
MAX_REGIONS = 8


def _json(value, expected, label):
    try:
        parsed = json.loads(value) if isinstance(value, str) else value
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} : JSON invalide.") from exc
    if not isinstance(parsed, expected):
        raise ValueError(f"{label} : format invalide.")
    return parsed


def _number(value):
    try:
        result = float(value or 0)
    except (TypeError, ValueError) as exc:
        raise ValueError("Les coordonnées et dimensions doivent être numériques.") from exc
    if not math.isfinite(result):
        raise ValueError("Les coordonnées et dimensions doivent être finies.")
    return result


def _id(node):
    return str(node.get("id") or node.get("piece_uid") or "")


def _serial(node):
    return str(node.get("serial_no") or node.get("id") or "")


def _excluded(node):
    return any(node.get(k) for k in ("__preexisting_cutout", "is_preexisting_cutout", "is_single_cutout", "single_logical_cutout"))


def _rect(node):
    # A destroyed region has zero effective stock area, but keeps a real footprint.
    physical = node.get("node_type") in {"destroyed", "destroy"} or _excluded(node)
    return {"x": _number(node.get("x")), "y": _number(node.get("y")),
            "length_mm": _number(node.get("length_mm") if physical else node.get("effective_length_mm", node.get("length_mm"))),
            "width_mm": _number(node.get("width_mm") if physical else node.get("effective_width_mm", node.get("width_mm")))}


def _regions(node):
    r = _rect(node)
    if r["length_mm"] <= 0 or r["width_mm"] <= 0:
        raise ValueError("Une région possède des dimensions nulles ou négatives.")
    rl, rw = _number(node.get("removed_length_mm")), _number(node.get("removed_width_mm"))
    parts = available_regions(r["length_mm"], r["width_mm"], rl, rw)
    return [{**part, "x": part["x"] + r["x"], "y": part["y"] + r["y"]} for part in parts]


def _area(r):
    return r["length_mm"] * r["width_mm"]


def _overlap(a, b):
    return (min(a["x"] + a["length_mm"], b["x"] + b["length_mm"]) - max(a["x"], b["x"]) > EPS
            and min(a["y"] + a["width_mm"], b["y"] + b["width_mm"]) - max(a["y"], b["y"]) > EPS)


def _contains(a, b):
    return (b["x"] >= a["x"] - EPS and b["y"] >= a["y"] - EPS
            and b["x"] + b["length_mm"] <= a["x"] + a["length_mm"] + EPS
            and b["y"] + b["width_mm"] <= a["y"] + a["width_mm"] + EPS)


def _find(nodes, node_id):
    matches = [(sheet, child) for sheet in nodes for child in sheet.get("children") or []
               if (_id(child) == str(node_id) or str(child.get("node_id") or "")==str(node_id)) and not _excluded(child) and child.get("node_type") not in {"destroyed", "destroy"}]
    if len(matches) != 1:
        raise ValueError(f"Nœud {node_id} introuvable, indisponible ou ambigu dans le résultat serveur.")
    return matches[0]


def _validate_nodes(nodes):
    """Physical invariants missing from the historical incident dispatch itself."""
    totals = {}
    for sheet in nodes:
        serial = _serial(sheet)
        if not serial or serial in totals:
            raise ValueError("Identifiants des plaques physiques manquants ou dupliqués.")
        bounds = {**_rect(sheet), "x": 0.0, "y": 0.0}
        usable_sheet = _regions({**sheet, "x": 0, "y": 0})
        regions = []
        total = 0.0
        for child in sheet.get("children") or []:
            parts = _regions(child)
            if _excluded(child):
                # Logical cutouts occupy no available matter; the sheet geometry
                # or actual blocker still excludes their footprint below.
                continue
            for part in parts:
                if not _contains(bounds, part):
                    raise ValueError("Une pièce sort des limites physiques de sa plaque.")
                covered = sum(max(0, min(part["x"]+part["length_mm"], r["x"]+r["length_mm"])-max(part["x"],r["x"]))
                              * max(0, min(part["y"]+part["width_mm"], r["y"]+r["width_mm"])-max(part["y"],r["y"])) for r in usable_sheet)
                if abs(covered - _area(part)) > EPS:
                    raise ValueError("Une pièce empiète sur l’encoche historique de la plaque.")
                if any(_overlap(part, previous) for previous in regions):
                    raise ValueError("Chevauchement physique entre des pièces ou zones disponibles.")
                if any(_overlap(part, _rect(blocker)) for blocker in sheet.get("children") or []
                       if blocker.get("__preexisting_cutout") or blocker.get("is_preexisting_cutout")):
                    raise ValueError("Une zone déjà retirée ne peut pas être réutilisée.")
                regions.append(part)
                total += _area(part)
        totals[serial] = total
    return totals


def _merge_geometry(selected):
    """Largest covered rectangle containing the first selected rectangle.

    The historical Python engine already understands residual_rects but does
    not compute/validate them. This bounded grid validator fills that API gap.
    """
    anchor_node = next((n for n in selected if n.get("node_type")=="leftover"),selected[0])
    if len(_regions(anchor_node)) != 1:
        raise ValueError("Merge sur une chute source avec encoche n’est pas disponible.")
    rs = [r for node in selected for r in _regions(node)]
    if len(rs) > 2 * MAX_REGIONS:
        raise ValueError("Trop de régions sélectionnées pour cette fusion.")
    xs = sorted({r["x"] for r in rs} | {r["x"]+r["length_mm"] for r in rs})
    ys = sorted({r["y"] for r in rs} | {r["y"]+r["width_mm"] for r in rs})
    nx, ny = len(xs)-1, len(ys)-1
    prefix = [[0]*(nx+1) for _ in range(ny+1)]
    for j in range(ny):
        for i in range(nx):
            cell = {"x":xs[i], "y":ys[j], "length_mm":xs[i+1]-xs[i], "width_mm":ys[j+1]-ys[j]}
            occupied = any(_contains(r,cell) for r in rs)
            prefix[j+1][i+1] = int(occupied)+prefix[j][i+1]+prefix[j+1][i]-prefix[j][i]
    anchor = _regions(anchor_node)[0]
    best = anchor
    for y in range(ny):
        for x in range(nx):
            if xs[x] > anchor["x"]+EPS or ys[y] > anchor["y"]+EPS:
                continue
            for Y in range(y+1,ny+1):
                for X in range(x+1,nx+1):
                    cells = prefix[Y][X]-prefix[y][X]-prefix[Y][x]+prefix[y][x]
                    if cells != (Y-y)*(X-x):
                        continue
                    r = {"x":xs[x],"y":ys[y],"length_mm":xs[X]-xs[x],"width_mm":ys[Y]-ys[y]}
                    if _contains(r,anchor) and _area(r) > _area(best)+EPS:
                        best = r
    # All selected nodes must contribute real matter to the grown source.
    if _area(best) <= _area(anchor)+EPS or any(not any(_overlap(r,best) for r in _regions(n)) for n in selected if n is not anchor_node):
        raise ValueError("Les zones sélectionnées ne prolongent pas la chute source en rectangle.")
    residuals = []
    for r in rs:
        if not _overlap(r,best):
            residuals.append(r)
            continue
        cut = {"x":max(r["x"],best["x"]),"y":max(r["y"],best["y"])}
        cut["length_mm"] = min(r["x"]+r["length_mm"],best["x"]+best["length_mm"])-cut["x"]
        cut["width_mm"] = min(r["y"]+r["width_mm"],best["y"]+best["width_mm"])-cut["y"]
        residuals.extend(split_free_rectangle(r,cut))
    if abs(sum(map(_area,rs))-_area(best)-sum(map(_area,residuals))) > EPS:
        raise ValueError("La fusion ne conserve pas la surface disponible.")
    return best, residuals


def _intent(raw):
    raw = _json(raw, dict, "Intention")
    action = raw.get("action") or raw.get("incident_action")
    source = raw.get("source_node_id") or raw.get("sourceNodeId") or raw.get("plan_node_id")
    ids = raw.get("target_node_ids", raw.get("targetNodeIds"))
    if ids is None:
        ids = raw.get("affected_node_ids_json") or []
    ids = _json(ids, list, "Nœuds cibles")
    ids = [str(i) for i in ids if str(i) != str(source)]
    if action == "Move" and not ids and raw.get("target_zone_id"):
        ids = [str(raw["target_zone_id"])]
    if action not in ACTIONS or not isinstance(source, str) or not source.strip():
        raise ValueError("Action ou identifiant source invalide.")
    if len(ids) >= MAX_REGIONS or len(set(ids)) != len(ids):
        raise ValueError("Les régions cibles sont dupliquées ou trop nombreuses.")
    parameters = raw.get("parameters")
    if parameters is None:
        parameters = {k: raw[k] for k in ("new_length_mm", "new_width_mm", "target_x_mm", "target_y_mm") if k in raw}
    if raw.get("parameters") is None and action == "Move":
        parameters["rotation_degrees"] = move_rotation_degrees(raw)
    return action, source, ids, _json(parameters, dict, "Paramètres")


def _build_incident(nodes, raw, allow_rotation=False):
    action, source_id, ids, params = _intent(raw)
    sheet, source = _find(nodes, source_id)
    source_type = source.get("node_type")
    if source_type not in {"finished_good", "leftover", "waste"}:
        raise ValueError("Cette région n’est pas modifiable.")
    r = _rect(source)
    incident = {"plan_node_id":_id(source),"source_serial_no":_serial(sheet),"incident_action":action,
                "original_node_type":source_type,"original_item_code":source.get("piece_item_code") or source.get("item_code") or "",
                "original_length_mm":r["length_mm"],"original_width_mm":r["width_mm"],
                "original_area_mm2":sum(map(_area,_regions(source))),"new_node_type":source_type,
                "new_length_mm":r["length_mm"],"new_width_mm":r["width_mm"],"new_area_mm2":sum(map(_area,_regions(source))),
                "include_in_repack":1,"is_active":1,"remarks":"",
                "affected_node_ids_json":json.dumps([_id(source)]),"group_area_mm2":sum(map(_area,_regions(source)))}
    if action in {"Resize","Destroy"}:
        if ids:
            raise ValueError("Cette action n’accepte pas de cible.")
        if action == "Destroy":
            incident.update(new_node_type="destroyed",new_length_mm=0,new_width_mm=0,new_area_mm2=0,include_in_repack=0)
        else:
            if len(_regions(source)) != 1:
                raise ValueError("Resize d’une chute en L n’est pas disponible.")
            length = _number(params.get("length_mm", params.get("new_length_mm")))
            width = _number(params.get("width_mm", params.get("new_width_mm")))
            # The existing incident engine enforces positive, reducing dimensions.
            incident.update(new_length_mm=length,new_width_mm=width,new_area_mm2=length*width)
            if source_type in FREE:
                incident["new_node_type"]=_classify_free_zone(length,width)
    elif action in {"Merge","Single"}:
        if not ids or source_type not in FREE:
            raise ValueError("Sélectionnez plusieurs zones libres d’une même plaque.")
        selected = [source]
        for target_id in ids:
            target_sheet, target = _find(nodes,target_id)
            if target_sheet is not sheet or target.get("node_type") not in FREE:
                raise ValueError("Toutes les régions doivent être libres et appartenir à une seule plaque physique.")
            selected.append(target)
        if action == "Single":
            if any(len(_regions(n)) != 1 or n.get("geometry_type") == "single" for n in selected):
                raise ValueError("Single nécessite deux régions rectangulaires sans encoche existante.")
            geometry = single_from_rectangles(selected)
            incident["remarks"] = json.dumps({k:geometry[k] for k in ("removed_length_mm","removed_width_mm")})
        else:
            geometry, residuals = _merge_geometry(selected)
            incident["remarks"] = json.dumps({"residual_rects":residuals})
        incident.update(affected_node_ids_json=json.dumps([_id(n) for n in selected]),
                        group_area_mm2=sum(sum(map(_area,_regions(n))) for n in selected),new_node_type="leftover" if action=="Single" else _classify_free_zone(geometry["length_mm"],geometry["width_mm"]),
                        new_length_mm=geometry["length_mm"],new_width_mm=geometry["width_mm"],
                        new_area_mm2=geometry.get("area_mm2",_area(geometry)),target_x_mm=geometry["x"],target_y_mm=geometry["y"])
    else:
        if source_type != "finished_good" or len(ids) != 1:
            raise ValueError("Move nécessite un produit fini et une seule destination libre.")
        target_sheet, target = _find(nodes, ids[0])
        if target.get("node_type") not in FREE:
            raise ValueError("La destination n’est pas une région disponible.")
        requested = params.get("rotation_degrees", "auto")
        if isinstance(requested, bool) or requested not in ("auto", 0, 90):
            raise ValueError("Choisissez une orientation automatique, 0° ou 90°.")
        if requested == 90 and not allow_rotation:
            raise ValueError("La rotation à 90° est désactivée sur ce MCP.")
        orientations = [0, 90] if requested == "auto" and allow_rotation else [0] if requested == "auto" else [requested]
        desired = None
        degrees = 0
        for orientation in orientations:
            length, width = (r["width_mm"], r["length_mm"]) if orientation == 90 else (r["length_mm"], r["width_mm"])
            for slot in move_target_slots(target):
                candidate = {"x":_number(params.get("target_x_mm",slot["x"])), "y":_number(params.get("target_y_mm",slot["y"])),
                             "length_mm":length,"width_mm":width}
                if _contains(slot, candidate):
                    desired, degrees = candidate, orientation
                    break
            if desired is not None:
                break
        if desired is None:
            raise ValueError("La découpe ne tient pas dans la destination, même à 90° si la rotation est autorisée.")
        if sheet is target_sheet and all(abs(desired[k]-r[k]) <= EPS for k in ("x","y","length_mm","width_mm")):
            raise ValueError("La pièce occupe déjà cette position.")
        exact = all(abs(desired[k]-_rect(target)[k]) <= EPS for k in ("length_mm","width_mm")) and len(_regions(target)) == 1
        incident.update(target_serial_no=_serial(target_sheet),target_zone_id=_id(target),target_x_mm=desired["x"],target_y_mm=desired["y"],
                        new_length_mm=desired["length_mm"],new_width_mm=desired["width_mm"],new_area_mm2=_area(desired),
                        remarks=json.dumps({"move_rotation_degrees":degrees,"move_result_rotation":bool(source.get("rotation")) ^ (degrees == 90)}),move_case="swap" if exact else "swing")
    return incident


def _unique_generated_ids(nodes):
    """Give displayable/generated remnants stable identities without changing geometry.

    Historical Resize copies the source ID onto destroyed strips. Keep the live
    source identity intact so a subsequent intention cannot target those strips.
    """
    used = {_id(child) for sheet in nodes for child in sheet.get("children") or []
            if child.get("node_type") not in {"destroyed","destroy"}}
    for sheet in nodes:
        for child in sheet.get("children") or []:
            if child.get("node_type") not in {"destroyed","destroy"}:
                continue
            original = _id(child)
            if original not in used:
                used.add(original)
                continue
            physical = json.dumps(_rect(child),sort_keys=True)
            suffix = hashlib.sha256(physical.encode()).hexdigest()[:12]
            generated_id = f"{original}__destroyed_{suffix}"
            while generated_id in used:
                generated_id += "x"
            child["__source_node_id"] = original
            child["id"] = generated_id
            if "node_id" in child:
                child["__original_node_id"]=child["node_id"]
                child["node_id"]=generated_id
            used.add(generated_id)
    return nodes


def preview_intentions(nodes, intentions, allow_rotation=False):
    """Pure memory operation shared by API tests and the future save adapter."""
    current = _unique_generated_ids(deepcopy(nodes))
    before = _validate_nodes(current)
    incidents = []
    for intent in intentions:
        incident = _build_incident(current,intent,allow_rotation=allow_rotation)
        # One step at a time: do not lose consecutive operations by flattening
        # them into a map keyed only by their original source identifier.
        doc = frappe._dict(mcp_mode="Retour Terrain",allow_rotation=int(allow_rotation),material_plan_incidents=[incident])
        if incident["incident_action"] == "Merge":
            source_sheet, source_node = _find(current,incident["plan_node_id"])
            source_sheet["children"] = [source_node,*[n for n in source_sheet["children"] if n is not source_node]]
        current = _unique_generated_ids(apply_incidents_to_nodes(current,build_incident_map(doc)))
        after = _validate_nodes(current)
        if before.keys() != after.keys() or any(abs(before[k]-after[k]) > EPS for k in before):
            raise ValueError("L’opération ne conserve pas la surface physique des plaques.")
        incidents.append(incident)
    return current, incidents


def _document_version(doc):
    data = doc.as_dict() if callable(getattr(doc,"as_dict",None)) else doc
    state = {k:data.get(k) for k in ("modified","docstatus","mcp_mode","result_json","effective_result_json","kerf_mm","allow_rotation","material_plan_incidents")}
    signature = hashlib.sha256(json.dumps(state,sort_keys=True,default=str,ensure_ascii=False).encode()).hexdigest()
    return {"modified":str(doc.get("modified") or ""),"signature":signature}


def _load_doc(mcp_name, editing=False):
    if not isinstance(mcp_name,str) or not mcp_name.strip():
        raise ValueError("Identifiant MCP obligatoire.")
    doc = frappe.get_doc("Material Cutting Plan",mcp_name)
    doc.check_permission("read")
    if editing:
        doc.check_permission("write")
        if cint(doc.get("docstatus")) != 0:
            raise ValueError("Un MCP soumis ou annulé ne peut pas être modifié.")
        if doc.get("mcp_mode") != "Retour Terrain":
            raise ValueError("Les incidents nécessitent un MCP Retour Terrain ; la Planification reste consultable.")
    return doc


def _effective_tree(doc):
    raw = doc.get("effective_result_json") or doc.get("result_json") or doc.get("result_tree_json") or {}
    tree = _json(raw,dict,"Plan MCP")
    tree = deepcopy(tree.get("tree") or tree)
    if not isinstance(tree.get("nodes"),list) or not tree["nodes"]:
        raise ValueError("Ce MCP ne possède pas de plan de découpe enregistré.")
    tree["nodes"] = _unique_generated_ids(deepcopy(build_effective_nodes(doc)))
    return tree


def _summary(nodes):
    result = {"sheet_count":len(nodes),"finished_good_count":0,"leftover_area_mm2":0.0,"waste_area_mm2":0.0,"destroyed_area_mm2":0.0}
    for sheet in nodes:
        for child in sheet.get("children") or []:
            if _excluded(child):
                continue
            typ = child.get("node_type")
            if typ == "finished_good":
                result["finished_good_count"] += 1
            key = f"{typ}_area_mm2"
            if key in result:
                result[key] += sum(map(_area,_regions(child)))
    return result


@frappe.whitelist()
def load_mcp_effective_plan(mcp_name):
    doc = _load_doc(mcp_name)
    tree = _effective_tree(doc)
    return {"valid":True,"effective_tree":tree,"effective_nodes":tree["nodes"],"summary":_summary(tree["nodes"]),
            "document_version":_document_version(doc),"editable":cint(doc.get("docstatus"))==0 and doc.get("mcp_mode")=="Retour Terrain" and doc.has_permission("write"),
            "allow_rotation":rotation_allowed(doc),"warnings":[],"errors":[],"document_modified":False}


@frappe.whitelist()
def preview_mcp_action(mcp_name, action, source_node_id, target_node_ids=None, parameters=None, pending_incidents=None, document_version=None):
    """Validate an intention and previous unsaved intentions; never save a doc."""
    response = {"valid":False,"effective_nodes":[],"summary":{},"warnings":[],"errors":[],"document_modified":False}
    # Permission failures intentionally propagate as Frappe PermissionError.
    try:
        doc = _load_doc(mcp_name,editing=True)
        version = _json(document_version,dict,"Version du MCP")
        current_version = _document_version(doc)
        if version != current_version:
            response.update(conflict=True,document_version=current_version,errors=["Le MCP a été modifié. Rechargez le plan avant de poursuivre."])
            return response
        pending = _json(pending_incidents or [],list,"Incidents en attente")
        if len(pending) >= MAX_PENDING:
            raise ValueError("La session est limitée à 50 opérations en attente.")
        tree = _effective_tree(doc)
        intent = {"action":action,"source_node_id":source_node_id,"target_node_ids":target_node_ids or [],"parameters":parameters or {}}
        nodes, incidents = preview_intentions(tree["nodes"],[*pending,intent],allow_rotation=rotation_allowed(doc))
        tree["nodes"] = nodes
        response.update(valid=True,effective_nodes=nodes,effective_tree=tree,summary=_summary(nodes),
                        incident=incidents[-1],pending_incidents=incidents,document_version=current_version,
                        warnings=["Prévisualisation non enregistrée. Confirmez puis appliquez pour enregistrer les incidents."])
    except (ValueError,TypeError) as exc:
        response["errors"] = [str(exc)]
    return response


def _geometry_signature(nodes):
    """Compare real stock outputs across the historical regeneration's ID changes."""
    return sorted((_serial(sheet), child.get("node_type"),
                   *[round(_rect(child)[key],3) for key in ("x","y","length_mm","width_mm")],
                   round(_number(child.get("removed_length_mm")),3),round(_number(child.get("removed_width_mm")),3))
                  for sheet in nodes for child in sheet.get("children") or []
                  if not _excluded(child) and child.get("node_type") not in {"destroyed","destroy"})


def _incident_rows_for_base(doc, tree, rows):
    """Persist identifiers used by the historical planner, not transient RTL IDs.

    Return Terrain can rename unchanged free rectangles L1 -> RTL1 while
    before_save continues to apply incidents to base_tree. Only an unambiguous
    physical match is allowed; geometry is never changed to make a match fit.
    """
    base = tree.get("base_tree") or tree
    bases = {_serial(sheet):sheet for sheet in base.get("nodes") or []}
    currents = {_serial(sheet):sheet for sheet in tree.get("nodes") or []}
    def translate(serial,node_id):
        historical=bases.get(serial,{}).get("children") or []
        if any(_id(n)==node_id for n in historical):
            return node_id
        current=[n for n in currents.get(serial,{}).get("children") or [] if _id(n)==node_id]
        if len(current)!=1:
            raise ValueError("La région sélectionnée est introuvable dans le plan courant.")
        source=current[0]
        matches=[n for n in historical if n.get("node_type") in FREE and source.get("node_type") in FREE
                 and len(_regions(n))==len(_regions(source))
                 and all(abs(_rect(n)[k]-_rect(source)[k])<=EPS for k in ("x","y","length_mm","width_mm"))
                 and all(abs(_number(n.get(k))-_number(source.get(k)))<=EPS for k in ("removed_length_mm","removed_width_mm"))]
        if len(matches)!=1:
            raise ValueError("La région sélectionnée ne correspond pas de façon unique à la base historique. Enregistrez les opérations précédentes et rechargez le plan.")
        return _id(matches[0])
    result=[]
    for original in rows:
        row=deepcopy(original);aliases={};serial=row["source_serial_no"]
        def mapped(node_id,target_serial=serial):
            resolved=translate(target_serial,node_id)
            if resolved!=node_id:aliases[node_id]=resolved
            return resolved
        row["plan_node_id"]=mapped(row["plan_node_id"])
        if row.get("affected_node_ids_json"):
            row["affected_node_ids_json"]=json.dumps([mapped(str(i)) for i in json.loads(row["affected_node_ids_json"])])
        if row.get("target_zone_id"):
            row["target_zone_id"]=mapped(row["target_zone_id"],row.get("target_serial_no") or serial)
        if aliases:
            metadata=json.loads(row.get("remarks") or "{}")
            metadata["ux20_node_aliases"]=aliases
            row["remarks"]=json.dumps(metadata)
        result.append(row)
    return result


def _prepare_mcp_incidents(mcp_name, pending_incidents, document_version):
    """Canonical child rows for the standard Frappe save, with a memory-only preflight.

    Calling the real before_save on an independent Document verifies that its
    historical regeneration can materialize these rows without losing an action.
    No document is saved here. Actual persistence uses the standard form save.
    """
    doc = _load_doc(mcp_name,editing=True)
    if _json(document_version,dict,"Version du MCP") != _document_version(doc):
        raise ValueError("Le MCP a été modifié. Rechargez-le avant d’appliquer les incidents.")
    pending = _json(pending_incidents,list,"Incidents en attente")
    if not pending or len(pending)>MAX_PENDING:
        raise ValueError("Sélectionnez entre une et cinquante opérations confirmées.")
    baseline = _effective_tree(doc)
    expected, rows = preview_intentions(baseline["nodes"],pending,allow_rotation=rotation_allowed(doc))
    if not (baseline.get("compensation_events") or baseline.get("ux20_incidents_resolved") or any(r["incident_action"]=="Move" for r in rows)):
        rows = _incident_rows_for_base(doc,baseline,rows)
    # Existing active rows must not be silently replaced by an overlapping batch.
    probe = frappe.get_doc(deepcopy(doc.as_dict()))
    for row in rows:
        probe.append("material_plan_incidents",row)
    probe.before_save()
    actual = _effective_tree(probe)
    _validate_nodes(actual["nodes"])
    if _geometry_signature(expected) != _geometry_signature(actual["nodes"]):
        raise ValueError("Le recalcul historique ne restitue pas toutes les opérations. Appliquez-les séparément et rechargez le résultat serveur avant la suivante.")
    return {"valid":True,"incidents":rows,"effective_tree":actual,"document_version":_document_version(doc),"document_modified":False}


@frappe.whitelist()
def prepare_mcp_incidents(mcp_name, pending_incidents, document_version):
    try:
        return _prepare_mcp_incidents(mcp_name,pending_incidents,document_version)
    except (ValueError,TypeError,frappe.ValidationError) as exc:
        return {"valid":False,"errors":[str(exc)],"document_modified":False}


def restore_planning_state(doc):
    """Restore the stored planning snapshot; never rerun the packing algorithm."""
    from mat_reco.material_reconfiguration.services.cutting_plan_service import update_active_input_flags
    from mat_reco.material_reconfiguration.doctype.material_cutting_plan.mcp_sheet_sync import sync_mcp_sheets
    tree = _json(doc.get("result_json"), dict, "Plan de planification")
    tree = deepcopy(tree.get("tree") or tree)
    if not isinstance(tree.get("nodes"), list) or not tree["nodes"]:
        raise ValueError("Aucun état de planification enregistré à restaurer.")
    _validate_nodes(tree["nodes"])
    doc.set("material_plan_incidents", [])
    doc.effective_result_json = json.dumps(tree, ensure_ascii=False)
    update_active_input_flags(doc, tree)
    sync_mcp_sheets(doc, source_json_field="effective_result_json", child_table_field="effective_mcp_sheets")
    doc._apply_summary_to_fields(doc._build_summary_from_tree(tree))
    return tree


@frappe.whitelist()
def reset_mcp_incidents(mcp_name, document_version):
    """Delete draft incidents and restore exactly the persisted planning snapshot."""
    from mat_reco.material_reconfiguration.services.mcp_compensation_service import submitted_receipts
    savepoint = "mcp_reset_incidents"
    frappe.db.savepoint(savepoint)
    try:
        frappe.db.sql("SELECT name FROM `tabMaterial Cutting Plan` WHERE name=%s FOR UPDATE", (mcp_name,))
        doc = _load_doc(mcp_name, editing=True)
        if _json(document_version, dict, "Version du MCP") != _document_version(doc):
            return {"valid":False, "conflict":True, "errors":["Le MCP a changé. Rechargez le plan avant de réinitialiser."]}
        outputs, inputs = submitted_receipts(doc)
        if outputs or inputs:
            raise ValueError("Réinitialisation impossible : des découpes sont déjà enregistrées dans un Repack soumis.")
        # This flag is server-owned, never taken from the client document.
        doc.flags.reset_to_planning = True
        restore_planning_state(doc)
        doc.save()
        return {"valid":True, "reset":True, "effective_tree":_json(doc.get("effective_result_json"), dict, "Plan restauré"),
                "document_version":_document_version(doc), "allow_rotation":rotation_allowed(doc),
                "editable":True, "warnings":[], "errors":[]}
    except (ValueError, TypeError) as exc:
        frappe.db.rollback(save_point=savepoint)
        return {"valid":False, "errors":[str(exc)]}
    except Exception:
        frappe.db.rollback(save_point=savepoint)
        raise
