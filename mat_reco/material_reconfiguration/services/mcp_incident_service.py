from __future__ import annotations

from copy import deepcopy

from frappe.utils import flt


def _child_id(child) -> str:
    return str(child.get("id") or child.get("piece_uid") or "").strip()


def _node_serial(node) -> str:
    return str(node.get("serial_no") or node.get("id") or "").strip()


def _sort_children(children: list[dict]) -> list[dict]:
    return sorted(
        children or [],
        key=lambda row: (flt(row.get("y") or 0), flt(row.get("x") or 0), str(row.get("id") or row.get("piece_uid") or "")),
    )


def ensure_effective_fields(child: dict) -> dict:
    out = deepcopy(child)
    if "effective_length_mm" not in out:
        out["effective_length_mm"] = flt(out.get("length_mm") or 0)
    if "effective_width_mm" not in out:
        out["effective_width_mm"] = flt(out.get("width_mm") or 0)
    if "effective_area_mm2" not in out:
        out["effective_area_mm2"] = flt(out.get("effective_length_mm") or 0) * flt(out.get("effective_width_mm") or 0)
    return out


def build_incident_map(doc) -> dict:
    mode = (doc.get("mcp_mode") or "").strip()
    if mode and mode != "Retour Terrain":
        return {}

    rows = doc.get("material_plan_incidents") or []
    result = {}
    for row in rows:
        if flt(row.get("is_active") or 0) != 1:
            continue
        action = (row.get("incident_action") or "").strip()
        if action == "Merge":
            try:
                affected_ids = row.get("affected_node_ids_json") or "[]"
                import json
                ids = json.loads(affected_ids) if isinstance(affected_ids, str) else (affected_ids or [])
            except Exception:
                ids = []
            for node_id in ids:
                node_id = str(node_id or "").strip()
                if node_id:
                    result[node_id] = row
            continue
        plan_node_id = (row.get("plan_node_id") or "").strip()
        if not plan_node_id:
            continue
        result[plan_node_id] = row
    return result


def build_destroy_regions_from_complement(child, kept_length_mm, kept_width_mm):
    original_length = flt(child.get("length_mm"))
    original_width = flt(child.get("width_mm"))
    x = flt(child.get("x") or 0)
    y = flt(child.get("y") or 0)

    destroys = []

    if kept_length_mm >= original_length and kept_width_mm >= original_width:
        return destroys

    right_width = original_length - kept_length_mm
    if right_width > 0:
        destroy_right = deepcopy(child)
        destroy_right["node_type"] = "destroyed"
        destroy_right["x"] = x + kept_length_mm
        destroy_right["y"] = y
        destroy_right["length_mm"] = right_width
        destroy_right["width_mm"] = original_width
        destroy_right["effective_length_mm"] = 0.0
        destroy_right["effective_width_mm"] = 0.0
        destroy_right["effective_area_mm2"] = 0.0
        destroy_right["include_in_repack"] = 0
        destroy_right["__generated_from_resize"] = 1
        destroy_right["__destroy_region_kind"] = "right_strip"
        destroy_right["__original_length_mm"] = right_width
        destroy_right["__original_width_mm"] = original_width
        destroy_right["__kept_length_mm"] = kept_length_mm
        destroy_right["__kept_width_mm"] = kept_width_mm
        destroys.append(destroy_right)

    bottom_height = original_width - kept_width_mm
    if bottom_height > 0:
        destroy_bottom = deepcopy(child)
        destroy_bottom["node_type"] = "destroyed"
        destroy_bottom["x"] = x
        destroy_bottom["y"] = y + kept_width_mm
        destroy_bottom["length_mm"] = kept_length_mm
        destroy_bottom["width_mm"] = bottom_height
        destroy_bottom["effective_length_mm"] = 0.0
        destroy_bottom["effective_width_mm"] = 0.0
        destroy_bottom["effective_area_mm2"] = 0.0
        destroy_bottom["include_in_repack"] = 0
        destroy_bottom["__generated_from_resize"] = 1
        destroy_bottom["__destroy_region_kind"] = "bottom_strip"
        destroy_bottom["__original_length_mm"] = kept_length_mm
        destroy_bottom["__original_width_mm"] = bottom_height
        destroy_bottom["__kept_length_mm"] = kept_length_mm
        destroy_bottom["__kept_width_mm"] = kept_width_mm
        destroys.append(destroy_bottom)

    return destroys


def apply_destroy_to_child(child):
    """Transforme un enfant en zone détruite tout en conservant les dimensions d'origine."""
    out = deepcopy(child)

    # Marque le nœud comme détruit
    out["node_type"] = "destroyed"

    # Conserve les dimensions originales pour l’affichage (longueur et largeur)
    length_mm = flt(child.get("length_mm") or child.get("effective_length_mm") or 0)
    width_mm  = flt(child.get("width_mm")  or child.get("effective_width_mm")  or 0)
    out["__original_length_mm"] = length_mm
    out["__original_width_mm"]  = width_mm

    # Passe les dimensions effectives à zéro pour signaler que la zone est consommée
    out["effective_length_mm"] = 0.0
    out["effective_width_mm"]  = 0.0
    out["effective_area_mm2"]  = 0.0

    # N’inclut pas cette zone dans le repack
    out["include_in_repack"] = 0

    # Enregistre l’action pour l’interface
    out["__incident_action"] = "Destroy"

    return out


def apply_resize_to_child(child, incident):
    original_length = flt(child.get("length_mm"))
    original_width = flt(child.get("width_mm"))

    new_length = flt(incident.get("new_length_mm"))
    new_width = flt(incident.get("new_width_mm"))
    new_type = (incident.get("new_node_type") or child.get("node_type") or "").strip()

    if new_length <= 0 or new_width <= 0:
        raise ValueError("Resize dimensions must be greater than zero.")

    if new_length > original_length or new_width > original_width:
        raise ValueError("Resize dimensions cannot exceed original dimensions.")

    modified = deepcopy(child)
    modified["node_type"] = new_type or modified.get("node_type")
    modified["length_mm"] = new_length
    modified["width_mm"] = new_width
    modified["effective_length_mm"] = new_length
    modified["effective_width_mm"] = new_width
    modified["effective_area_mm2"] = new_length * new_width
    modified["include_in_repack"] = 1
    modified["__incident_action"] = "Resize"
    modified["__generated_from_resize"] = 0

    complement_regions = build_destroy_regions_from_complement(
        child=child,
        kept_length_mm=new_length,
        kept_width_mm=new_width,
    )
    generated_destroys = [apply_destroy_to_child(region) for region in complement_regions]
    for row in generated_destroys:
        row["__incident_action"] = "Resize"
    return [modified, *generated_destroys]


def apply_move_to_child(child, incident, *, source_serial_no: str, target_serial_no: str):
    out = ensure_effective_fields(child)
    out["x"] = flt(incident.get("target_x_mm") if incident.get("target_x_mm") is not None else child.get("x") or 0)
    out["y"] = flt(incident.get("target_y_mm") if incident.get("target_y_mm") is not None else child.get("y") or 0)
    out["__incident_action"] = "Move"
    out["__moved_from_serial_no"] = source_serial_no
    out["__moved_to_serial_no"] = target_serial_no
    out["source_serial_no"] = target_serial_no
    return out


def _is_free_zone(node_type: str) -> bool:
    return str(node_type or "").strip() in ("leftover", "waste")


def _rect_contains_rect(outer: dict, inner: dict) -> bool:
    return (
        flt(inner.get("x") or 0) >= flt(outer.get("x") or 0)
        and flt(inner.get("y") or 0) >= flt(outer.get("y") or 0)
        and (flt(inner.get("x") or 0) + flt(inner.get("length_mm") or 0)) <= (flt(outer.get("x") or 0) + flt(outer.get("length_mm") or 0))
        and (flt(inner.get("y") or 0) + flt(inner.get("width_mm") or 0)) <= (flt(outer.get("y") or 0) + flt(outer.get("width_mm") or 0))
    )


def _classify_free_zone(length_mm: float, width_mm: float) -> str:
    return "waste" if min(flt(length_mm), flt(width_mm)) < 500.0 else "leftover"


def _build_free_zone_from_rect(template_child: dict, *, x: float, y: float, length_mm: float, width_mm: float, suffix: str) -> dict | None:
    length_mm = flt(length_mm)
    width_mm = flt(width_mm)
    if length_mm <= 0 or width_mm <= 0:
        return None

    out = deepcopy(template_child)
    base_id = _child_id(template_child) or "zone"
    out["id"] = f"{base_id}{suffix}"
    out["node_type"] = _classify_free_zone(length_mm, width_mm)
    out["x"] = flt(x)
    out["y"] = flt(y)
    out["length_mm"] = length_mm
    out["width_mm"] = width_mm
    out["effective_length_mm"] = length_mm
    out["effective_width_mm"] = width_mm
    out["effective_area_mm2"] = length_mm * width_mm
    out["include_in_repack"] = 1
    out["__incident_action"] = "Move"
    out["__generated_from_move"] = 1
    out["__original_length_mm"] = length_mm
    out["__original_width_mm"] = width_mm
    return out


def _build_free_zone_from_child(child: dict, suffix: str = "__freed") -> dict | None:
    return _build_free_zone_from_rect(
        child,
        x=flt(child.get("x") or 0),
        y=flt(child.get("y") or 0),
        length_mm=flt(child.get("length_mm") or 0),
        width_mm=flt(child.get("width_mm") or 0),
        suffix=suffix,
    )


def _resolve_target_free_zone(target_node: dict | None, candidate: dict) -> dict | None:
    if not target_node:
        return None

    matches = []
    for child in (target_node.get("children") or []):
        if not _is_free_zone(child.get("node_type") or ""):
            continue
        zone_rect = {
            "x": flt(child.get("x") or 0),
            "y": flt(child.get("y") or 0),
            "length_mm": flt(child.get("length_mm") or child.get("effective_length_mm") or 0),
            "width_mm": flt(child.get("width_mm") or child.get("effective_width_mm") or 0),
        }
        if zone_rect["length_mm"] <= 0 or zone_rect["width_mm"] <= 0:
            continue
        if _rect_contains_rect(zone_rect, candidate):
            matches.append(child)

    matches.sort(key=lambda row: flt(row.get("length_mm") or 0) * flt(row.get("width_mm") or 0))
    return matches[0] if matches else None


def _build_target_zone_complements(target_zone: dict, candidate: dict) -> list[dict]:
    zone_x = flt(target_zone.get("x") or 0)
    zone_y = flt(target_zone.get("y") or 0)
    zone_l = flt(target_zone.get("length_mm") or target_zone.get("effective_length_mm") or 0)
    zone_w = flt(target_zone.get("width_mm") or target_zone.get("effective_width_mm") or 0)
    cand_x = flt(candidate.get("x") or 0)
    cand_y = flt(candidate.get("y") or 0)
    cand_l = flt(candidate.get("length_mm") or 0)
    cand_w = flt(candidate.get("width_mm") or 0)

    rows = []
    for row in [
        _build_free_zone_from_rect(target_zone, x=zone_x, y=zone_y, length_mm=cand_x - zone_x, width_mm=zone_w, suffix="__move_left"),
        _build_free_zone_from_rect(target_zone, x=cand_x + cand_l, y=zone_y, length_mm=(zone_x + zone_l) - (cand_x + cand_l), width_mm=zone_w, suffix="__move_right"),
        _build_free_zone_from_rect(target_zone, x=cand_x, y=zone_y, length_mm=cand_l, width_mm=cand_y - zone_y, suffix="__move_top"),
        _build_free_zone_from_rect(target_zone, x=cand_x, y=cand_y + cand_w, length_mm=cand_l, width_mm=(zone_y + zone_w) - (cand_y + cand_w), suffix="__move_bottom"),
    ]:
        if row:
            rows.append(row)
    return rows

# -----------------------------------------------------------------------------
# Backend helper: split a free rectangle around an inserted piece
#
# When a finished good is moved into a free zone (either a leftover or waste),
# the remaining free space must be decomposed into up to four rectangular
# subregions: left strip, right strip, top strip, and bottom strip.  This
# function performs the same calculation as `_build_target_zone_complements`
# but returns the subrectangles as plain dictionaries without promoting them
# into domain objects.  Each subrectangle has keys `x`, `y`, `length_mm` and
# `width_mm` measured in absolute sheet coordinates.  Only non-empty regions
# are returned.  Consumers can subsequently classify each subrectangle as a
# leftover or waste based on its minimum dimension.
def split_free_rectangle(zone: dict, piece: dict) -> list[dict]:
    """Split a free zone into residual rectangles around a placed piece.

    Args:
        zone: A dictionary describing the free zone with keys `x`, `y`,
            `length_mm` and `width_mm`.
        piece: A dictionary describing the placed piece with keys `x`, `y`,
            `length_mm` and `width_mm`.

    Returns:
        A list of dictionaries each with keys `x`, `y`, `length_mm`, `width_mm`
        representing the remaining free regions.
    """
    zx = flt(zone.get("x") or 0)
    zy = flt(zone.get("y") or 0)
    zl = flt(zone.get("length_mm") or zone.get("effective_length_mm") or 0)
    zw = flt(zone.get("width_mm") or zone.get("effective_width_mm") or 0)
    px = flt(piece.get("x") or 0)
    py = flt(piece.get("y") or 0)
    pl = flt(piece.get("length_mm") or 0)
    pw = flt(piece.get("width_mm") or 0)

    results: list[dict] = []
    # Left strip: to the left of the piece, full height of the zone
    left_length = px - zx
    if left_length > 0 and zw > 0:
        results.append({"x": zx, "y": zy, "length_mm": left_length, "width_mm": zw})
    # Right strip: to the right of the piece
    right_length = (zx + zl) - (px + pl)
    if right_length > 0 and zw > 0:
        results.append({"x": px + pl, "y": zy, "length_mm": right_length, "width_mm": zw})
    # Top strip: above the piece
    top_height = py - zy
    if top_height > 0 and pl > 0:
        results.append({"x": px, "y": zy, "length_mm": pl, "width_mm": top_height})
    # Bottom strip: below the piece
    bottom_height = (zy + zw) - (py + pw)
    if bottom_height > 0 and pl > 0:
        results.append({"x": px, "y": py + pw, "length_mm": pl, "width_mm": bottom_height})
    return results


def _build_merge_output_children(template_child: dict, incident: dict) -> list[dict]:
    merged = _build_free_zone_from_rect(
        template_child,
        x=flt(incident.get("target_x_mm") or 0),
        y=flt(incident.get("target_y_mm") or 0),
        length_mm=flt(incident.get("new_length_mm") or 0),
        width_mm=flt(incident.get("new_width_mm") or 0),
        suffix="__merged",
    )
    rows: list[dict] = []
    if merged:
        merged["node_type"] = str(incident.get("new_node_type") or merged.get("node_type") or "").strip() or merged.get("node_type")
        merged["__incident_action"] = "Merge"
        rows.append(merged)

    residuals = []
    remarks = incident.get("remarks")
    if remarks:
        try:
            import json
            parsed = json.loads(remarks) if isinstance(remarks, str) else (remarks or {})
            residuals = parsed.get("residual_rects") or []
        except Exception:
            residuals = []
    for idx, rect in enumerate(residuals):
        row = _build_free_zone_from_rect(
            template_child,
            x=flt((rect or {}).get("x") or 0),
            y=flt((rect or {}).get("y") or 0),
            length_mm=flt((rect or {}).get("length_mm") or 0),
            width_mm=flt((rect or {}).get("width_mm") or 0),
            suffix=f"__merge_residual_{idx}",
        )
        if row:
            row["__incident_action"] = "Merge"
            rows.append(row)
    return rows


def apply_incident_to_child_as_nodes(child, incident):
    if not incident:
        return [ensure_effective_fields(child)]

    action = (incident.get("incident_action") or "").strip()
    if action == "Destroy":
        return [apply_destroy_to_child(child)]
    if action == "Resize":
        return apply_resize_to_child(child, incident)
    if action == "Move":
        return [ensure_effective_fields(child)]
    if action == "Merge":
        return [ensure_effective_fields(child)]
    return [ensure_effective_fields(child)]


def apply_incidents_to_nodes(nodes: list[dict], incident_map: dict | None = None) -> list[dict]:
    incident_map = incident_map or {}

    original_node_by_serial = {_node_serial(node): node for node in (nodes or [])}
    source_move_ids: set[str] = set()
    consumed_target_zone_ids: dict[str, set[str]] = {}
    additions_by_serial: dict[str, list[dict]] = {}
    merge_consumed_ids: dict[str, set[str]] = {}
    processed_merge_keys: set[str] = set()

    for node in (nodes or []):
        source_serial_no = _node_serial(node)
        for child in (node.get("children") or []):
            child_id = _child_id(child)
            incident = incident_map.get(child_id)
            action = (incident.get("incident_action") or "").strip() if incident else ""
            if action == "Merge":
                merge_key = str(incident.get("name") or incident.get("plan_node_id") or child_id)
                target_serial_no = str(incident.get("source_serial_no") or source_serial_no).strip() or source_serial_no
                try:
                    import json
                    affected_ids = json.loads(incident.get("affected_node_ids_json") or "[]")
                except Exception:
                    affected_ids = []
                merge_consumed_ids.setdefault(target_serial_no, set()).update(str(v or "").strip() for v in affected_ids if str(v or "").strip())
                if merge_key not in processed_merge_keys:
                    processed_merge_keys.add(merge_key)
                    additions_by_serial.setdefault(target_serial_no, []).extend(_build_merge_output_children(child, incident))
                continue
            if action != "Move" or str(child.get("node_type") or "").strip() != "finished_good":
                continue

            source_move_ids.add(child_id)
            # Determine the target serial.  Default to the source serial when none is provided
            target_serial_no = str(incident.get("target_serial_no") or source_serial_no).strip() or source_serial_no
            additions_by_serial.setdefault(source_serial_no, [])

            # Only free the source zone if the piece is being moved to a new location.  When the
            # target serial and coordinates match the original, freeing the source would
            # result in a zero-sized leftover overlapping the moved piece.  Coordinates are
            # compared after coercing to floats via flt() to handle None values gracefully.
            try:
                target_x = incident.get("target_x_mm") if incident.get("target_x_mm") is not None else child.get("x") or 0
                target_y = incident.get("target_y_mm") if incident.get("target_y_mm") is not None else child.get("y") or 0
            except Exception:
                target_x = child.get("x") or 0
                target_y = child.get("y") or 0
            if not (
                target_serial_no == source_serial_no
                and flt(target_x) == flt(child.get("x") or 0)
                and flt(target_y) == flt(child.get("y") or 0)
            ):
                freed_zone = _build_free_zone_from_child(child, suffix="__freed")
                if freed_zone:
                    additions_by_serial[source_serial_no].append(freed_zone)

            # Apply the movement to the child
            target_node = original_node_by_serial.get(target_serial_no)
            moved_child = apply_move_to_child(
                child,
                incident,
                source_serial_no=source_serial_no,
                target_serial_no=target_serial_no,
            )
            additions_by_serial.setdefault(target_serial_no, []).append(moved_child)

            # Identify the containing free zone and split it into residual strips
            candidate = {
                "x": flt(moved_child.get("x") or 0),
                "y": flt(moved_child.get("y") or 0),
                "length_mm": flt(moved_child.get("length_mm") or 0),
                "width_mm": flt(moved_child.get("width_mm") or 0),
            }
            target_zone = _resolve_target_free_zone(target_node, candidate)
            if not target_zone:
                continue

            # Ensure the moving piece fits entirely inside the target free zone.
            # Although the client validates containment, enforce it on the backend
            # to guard against invalid payloads.  When the moving piece exceeds
            # the dimensions of the free zone, swapping cannot occur and we
            # terminate processing with an error.
            zone_length = flt(target_zone.get("length_mm") or target_zone.get("effective_length_mm") or 0)
            zone_width = flt(target_zone.get("width_mm") or target_zone.get("effective_width_mm") or 0)
            if candidate["length_mm"] > zone_length or candidate["width_mm"] > zone_width:
                raise ValueError("Moving piece is larger than the target free zone; swap cannot be performed.")

            consumed_target_zone_ids.setdefault(target_serial_no, set()).add(_child_id(target_zone))
            additions_by_serial[target_serial_no].extend(_build_target_zone_complements(target_zone, candidate))

    result_nodes = []
    for node in (nodes or []):
        serial_no = _node_serial(node)
        node_copy = deepcopy(node)
        new_children = []

        for child in (node.get("children") or []):
            child_id = _child_id(child)
            if child_id in source_move_ids:
                continue
            if child_id in merge_consumed_ids.get(serial_no, set()):
                continue
            if child_id in consumed_target_zone_ids.get(serial_no, set()):
                continue

            incident = incident_map.get(child_id)
            action = (incident.get("incident_action") or "").strip() if incident else ""
            effective_rows = apply_incident_to_child_as_nodes(child, None if action == "Move" else incident)
            new_children.extend(effective_rows)

        new_children.extend(additions_by_serial.get(serial_no, []))
        node_copy["children"] = _sort_children(new_children)
        result_nodes.append(node_copy)

    return result_nodes

