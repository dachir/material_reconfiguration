"""Complementary placements using the existing rectpack and physical validators.

Only explicit leftover nodes are reusable. Waste, destroyed footprints and
submitted leftover outputs are never offered as internal material.
"""
from copy import deepcopy
import hashlib
import json
import math

from mat_reco.material_reconfiguration.services.cutting_plan_service import _run_rectpack_plan, _compute_free_rectangles, _classify_free_region
from mat_reco.material_reconfiguration.services.mcp_action_preview import _validate_nodes, _regions
from mat_reco.material_reconfiguration.services.single_geometry import available_regions

SCALE = 1000
EPS = 0.001


def number(value):
    result = float(value or 0)
    if not math.isfinite(result) or result < 0:
        raise ValueError("Dimensions et paramètres de découpe invalides.")
    return result


def signature(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str, ensure_ascii=False).encode()).hexdigest()


def internal_candidates(nodes, frozen_ids=()):
    frozen = set(frozen_ids)
    candidates = []
    _validate_nodes(nodes)
    for sheet in nodes:
        serial = sheet.get("serial_no") or sheet.get("id")
        for child in sheet.get("children") or []:
            if child.get("node_type") != "leftover" or child.get("id") in frozen or child.get("include_in_repack") == 0:
                continue
            for index, rect in enumerate(_regions(child)):
                candidates.append({**rect, "candidate_id": f'{serial}/{child["id"]}/{index}',
                    "source_serial_no": serial, "source_node_id": child["id"], "origin": "internal",
                    "priority": 1, "item_code": sheet.get("item_code"),
                    "thickness_mm": sheet.get("thickness_mm") or child.get("thickness_mm"),
                    "warehouse": sheet.get("warehouse"), "region_index": index})
    return candidates


def stock_sheet(source):
    serial = source["serial_no"]
    regions = available_regions(number(source["length_mm"]), number(source["width_mm"]),
                                number(source.get("removed_length_mm")), number(source.get("removed_width_mm")))
    children = [{**rect, "id": f"{serial}::COMP_FREE{i}", "node_type": "leftover",
                 "include_in_repack": 1} for i, rect in enumerate(regions)]
    return {**deepcopy(source), "id": serial, "node_type": "input_serial", "children": children}


def propose_internal(nodes, requirements, kerf_mm=0, allow_rotation=True, frozen_ids=(), seed="", allowed_candidate_ids=None):
    """Pack remaining units in internal leftovers, preserving every other node.

    Millimetres are scaled before calling the legacy integer rectpack adapter;
    demand dimensions round upward and bin dimensions downward. Kerf is reserved
    between pieces, represented as waste, and never remains reusable.
    """
    original = deepcopy(nodes)
    before = _validate_nodes(original)
    candidates = internal_candidates(original, frozen_ids)
    demands = {r["piece_uid"]: deepcopy(r) for r in requirements}
    if len(demands) != len(requirements):
        raise ValueError("Besoins unitaires dupliqués.")
    kerf = number(kerf_mm)
    placements = []
    used_candidates = set()
    # Thickness groups prevent rectpack from interchanging incompatible sheets.
    groups = sorted({number(r.get("thickness_mm")) for r in requirements})
    sheet_map = {s.get("serial_no") or s.get("id"): s for s in original}
    touched = {}
    warnings = []
    for thickness in groups:
        group_demands = [r for r in requirements if number(r.get("thickness_mm")) == thickness]
        eligible = [c for c in candidates if (allowed_candidate_ids is None or c["candidate_id"] in allowed_candidate_ids)
                    and (not thickness or (c.get("thickness_mm") and abs(number(c["thickness_mm"])-thickness) <= EPS))]
        if thickness and len(eligible) < len(candidates):
            warnings.append("Certaines chutes ont une épaisseur inconnue ou incompatible et sont exclues.")
        virtual_bins = [{"serial_no": c["candidate_id"],
                         "length_mm": math.floor((c["length_mm"] + kerf) * SCALE),
                         "width_mm": math.floor((c["width_mm"] + kerf) * SCALE)}
                        for c in sorted(eligible, key=lambda c: (c["length_mm"]*c["width_mm"], c["candidate_id"]))]
        inflated = [{**r, "length_mm": math.ceil((number(r["length_mm"])+kerf)*SCALE),
                     "width_mm": math.ceil((number(r["width_mm"])+kerf)*SCALE)} for r in group_demands]
        packed = _run_rectpack_plan(inflated, virtual_bins, allow_rotation=allow_rotation)["placements_by_bin"]
        candidate_map = {c["candidate_id"]: c for c in eligible}
        for key, rectangles in packed.items():
            region = candidate_map[key]
            sheet = sheet_map[region["source_serial_no"]]
            region_placements = []
            for packed_piece in rectangles:
                demand = demands[packed_piece["piece_uid"]]
                rotated = bool(packed_piece["rotation"])
                length = number(demand["width_mm"] if rotated else demand["length_mm"])
                width = number(demand["length_mm"] if rotated else demand["width_mm"])
                x, y = packed_piece["x"]/SCALE, packed_piece["y"]/SCALE
                if x + length > region["length_mm"] + EPS or y + width > region["width_mm"] + EPS:
                    raise ValueError("Le placement dépasse la chute disponible.")
                operation_id = "CP-" + signature([seed, demand["piece_uid"], key, x, y])[:32]
                child = {k: deepcopy(v) for k,v in demand.items() if k not in ("operations", "state", "missing_qty", "compensation_qty")}
                child.update({"id": operation_id, "node_type": "finished_good", "label": "Remplacement",
                    "x": region["x"]+x, "y": region["y"]+y, "length_mm": length, "width_mm": width,
                    "effective_length_mm": length, "effective_width_mm": width, "effective_area_mm2": length*width,
                    "rotation": rotated, "include_in_repack": 1, "is_real": False,
                    "replacement_for": demand["piece_uid"], "broken_operation_ids": demand.get("broken_operation_ids") or [],
                    "compensation_source_node_id": region["source_node_id"], "compensation_source_serial_no": region["source_serial_no"]})
                sheet["children"].append(child)
                placement = {**deepcopy(child), "source_serial_no": region["source_serial_no"], "candidate_id": key,
                             "origin": region.get("origin", "internal")}
                placements.append(placement)
                region_placements.append({"x": x, "y": y, "length_mm": length, "width_mm": width})
            if not region_placements:
                continue
            used_candidates.add(key)
            touched.setdefault((region["source_serial_no"], region["source_node_id"]), []).append(key)
            # Split both actual piece footprint and its reserved kerf envelope.
            envelopes = [{**p, "length_mm": min(p["length_mm"]+kerf, region["length_mm"]-p["x"]),
                          "width_mm": min(p["width_mm"]+kerf, region["width_mm"]-p["y"])} for p in region_placements]
            free = _compute_free_rectangles(region["length_mm"], region["width_mm"], envelopes)
            residual = []
            for index, (x,y,l,w) in enumerate(free):
                residual.append({"id": "CF-"+signature([seed,key,index])[:32], "node_type": _classify_free_region(l,w),
                    "x": region["x"]+x, "y": region["y"]+y, "length_mm": l, "width_mm": w,
                    "effective_length_mm": l, "effective_width_mm": w, "effective_area_mm2": l*w,
                    "include_in_repack": 1, "compensation_residual": True})
            if kerf:
                for index, (piece, env) in enumerate(zip(region_placements,envelopes)):
                    strips = []
                    if env["length_mm"] > piece["length_mm"]:
                        strips.append((piece["x"]+piece["length_mm"],piece["y"],env["length_mm"]-piece["length_mm"],env["width_mm"]))
                    if env["width_mm"] > piece["width_mm"]:
                        strips.append((piece["x"],piece["y"]+piece["width_mm"],piece["length_mm"],env["width_mm"]-piece["width_mm"]))
                    for j,(x,y,l,w) in enumerate(strips):
                        residual.append({"id":"CK-"+signature([seed,key,index,j])[:32], "node_type":"destroyed",
                            "x":region["x"]+x,"y":region["y"]+y,"length_mm":l,"width_mm":w,
                            "effective_length_mm":0,"effective_width_mm":0,"effective_area_mm2":0,
                            "include_in_repack":0,"compensation_kerf":True})
            sheet["children"].extend(residual)
    # Remove a used Single only once, keeping its untouched disjoint arm intact.
    for (serial, node_id), keys in touched.items():
        sheet = sheet_map[serial]
        sheet["children"] = [c for c in sheet["children"] if c.get("id") != node_id]
        for c in candidates:
            if c["source_serial_no"] == serial and c["source_node_id"] == node_id and c["candidate_id"] not in used_candidates:
                sheet["children"].append({k:v for k,v in c.items() if k in ("x","y","length_mm","width_mm") } | {
                    "id":"CF-"+signature([seed,c["candidate_id"],"untouched"])[:32], "node_type":"leftover","include_in_repack":1})
    after = _validate_nodes(original)
    if before.keys() != after.keys() or any(abs(before[k]-after[k]) > EPS for k in before):
        raise ValueError("La compensation ne conserve pas la surface physique.")
    covered = {p["piece_uid"] for p in placements}
    return {"nodes": original, "placements": placements, "remaining": [deepcopy(r) for r in requirements if r["piece_uid"] not in covered],
            "internal_candidates": candidates, "warnings": sorted(set(warnings))}
