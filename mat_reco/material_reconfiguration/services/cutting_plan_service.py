"""Service for generating optimized material cutting plans.

This module orchestrates the packing of unit cutting demands into
available stock bins.  It attempts to use the ``rectpack`` library
when available to perform two-dimensional rectangle packing.  If
``rectpack`` is not installed, a simple greedy fallback is used which
assigns demands sequentially to bins without optimization.  The
resulting placements are assembled into a hierarchical tree that
captures the relationship between each piece and the serial number of
the bin from which it will be cut.

The top-level function :func:`generate_material_cutting_plan` is
called by the Material Cutting Plan DocType.  It handles invoking
the packing algorithm and building both a tree representation and a
summary of the plan.  The summary includes counts of requested,
planned and missing pieces as well as the number of bins used.

"""

from __future__ import annotations

import frappe
from frappe import _
import logging
from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Tuple

from mat_reco.material_reconfiguration.services.mcp_incident_service import (
    apply_incidents_to_nodes,
    build_incident_map,
    ensure_effective_fields,
)

# Minimum dimension (in mm) for a free area to be considered a leftover rather than waste.
# Any free rectangle whose smaller side is strictly less than this threshold will be
# classified as waste. Larger or equal will be classified as leftover.
LEFTOVER_MIN_DIMENSION_MM = 500.0

# A helper type alias for clarity when representing rectangles. Each rectangle
# is described by its origin (x, y) and its extents (width, height). All
# coordinates and dimensions are expressed in millimetres.
Rectangle = Tuple[float, float, float, float]

def _compute_free_rectangles(
    sheet_length: float, sheet_width: float, placements: List[dict[str, object]]
) -> List[Rectangle]:
    """Compute free rectangular areas inside a sheet.

    Given the dimensions of a stock sheet (length along the X axis and width
    along the Y axis) and a list of placed rectangles (each with x, y,
    length_mm and width_mm), this function returns a list of maximal free
    rectangles remaining in the sheet. A free rectangle is defined as an
    area not occupied by any placed piece. The returned rectangles are
    non-overlapping and cover all free space.

    Args:
        sheet_length: Total length of the stock sheet along the X axis.
        sheet_width: Total width of the stock sheet along the Y axis.
        placements: A list of dictionaries describing placed pieces. Each
            dict must have keys ``x``, ``y``, ``length_mm`` and ``width_mm``.

    Returns:
        A list of tuples (x, y, width, height) representing free rectangles.
    """
    # Collect unique cut lines along X and Y axes: sheet borders and piece edges.
    x_lines: List[float] = [0.0, float(sheet_length)]
    y_lines: List[float] = [0.0, float(sheet_width)]

    for p in placements:
        try:
            px = float(p.get("x") or 0.0)
            py = float(p.get("y") or 0.0)
            w = float(p.get("length_mm") or 0.0)
            h = float(p.get("width_mm") or 0.0)
            x_lines.append(px)
            x_lines.append(px + w)
            y_lines.append(py)
            y_lines.append(py + h)
        except Exception:
            continue

    # Deduplicate and sort cut lines
    x_lines = sorted(set(x_lines))
    y_lines = sorted(set(y_lines))

    # Build a grid of free/occupied cells. Each cell is defined by
    # x_lines[i] -> x_lines[i+1] and y_lines[j] -> y_lines[j+1].
    num_x = len(x_lines) - 1
    num_y = len(y_lines) - 1
    # Initialize all cells as free
    free_grid = [[True for _ in range(num_x)] for _ in range(num_y)]

    # Mark cells that overlap with any placement as occupied
    for p in placements:
        try:
            px = float(p.get("x") or 0.0)
            py = float(p.get("y") or 0.0)
            w = float(p.get("length_mm") or 0.0)
            h = float(p.get("width_mm") or 0.0)
            # rectangle extents
            px2 = px + w
            py2 = py + h
        except Exception:
            continue
        # Determine grid cell indices overlapped by this piece
        for yi in range(num_y):
            y1, y2 = y_lines[yi], y_lines[yi + 1]
            # Skip rows not intersecting piece
            if y2 <= py or y1 >= py2:
                continue
            for xi in range(num_x):
                x1, x2 = x_lines[xi], x_lines[xi + 1]
                if x2 <= px or x1 >= px2:
                    continue
                # Overlaps piece -> mark cell occupied
                free_grid[yi][xi] = False

    # Now merge free cells into maximal rectangles. We'll use a visited grid to
    # avoid processing cells multiple times.
    visited = [[False for _ in range(num_x)] for _ in range(num_y)]
    free_rectangles: List[Rectangle] = []

    for yi in range(num_y):
        for xi in range(num_x):
            if not free_grid[yi][xi] or visited[yi][xi]:
                continue
            # Determine maximal horizontal span starting at (xi, yi)
            end_x = xi
            while end_x + 1 < num_x and free_grid[yi][end_x + 1] and not visited[yi][end_x + 1]:
                end_x += 1
            # Determine maximal vertical span for this horizontal band
            end_y = yi
            expand = True
            while expand:
                next_row = end_y + 1
                if next_row >= num_y:
                    break
                # Check if the entire horizontal span [xi, end_x] is free in next_row and not visited
                for xk in range(xi, end_x + 1):
                    if not free_grid[next_row][xk] or visited[next_row][xk]:
                        expand = False
                        break
                if expand:
                    end_y = next_row
            # Mark cells in this rectangle as visited
            for yk in range(yi, end_y + 1):
                for xk in range(xi, end_x + 1):
                    visited[yk][xk] = True
            # Append the free rectangle using boundary coordinates
            x1 = x_lines[xi]
            y1 = y_lines[yi]
            x2 = x_lines[end_x + 1]
            y2 = y_lines[end_y + 1]
            rect_width = x2 - x1
            rect_height = y2 - y1
            # Only consider rectangles with positive dimensions
            if rect_width > 0 and rect_height > 0:
                free_rectangles.append((x1, y1, rect_width, rect_height))

    return free_rectangles


logger = logging.getLogger(__name__)


def generate_material_cutting_plan(
    plan_name: str,
    demands: List[dict[str, object]],
    bins: List[dict[str, object]],
    kerf_mm: float = 0.0,
    allow_rotation: bool = True,
    packing_algorithm: str = "maxrects",
    packing_heuristic: str = "best_area_fit",
) -> Dict[str, object]:
    """Generate an optimized cutting plan.

    Uses rectpack only. If rectpack fails, we stop instead of generating
    a mathematically invalid fallback plan.
    """
    placements_info = _run_rectpack_plan(
        demands=demands,
        bins=bins,
        allow_rotation=allow_rotation,
    )

    tree = _build_tree_result(
        plan_name=plan_name,
        demands=demands,
        bins=bins,
        placements_by_bin=placements_info,
        kerf_mm=kerf_mm,
        allow_rotation=allow_rotation,
        packing_algorithm=packing_algorithm,
        packing_heuristic=packing_heuristic,
    )
    summary = tree.get("summary", {})
    return {"tree": tree, "summary": summary}


def _run_rectpack_plan(
    demands: List[dict[str, object]],
    bins: List[dict[str, object]],
    allow_rotation: bool = True,
) -> Dict[str, object]:
    """Pack demands into bins using rectpack.

    IMPORTANT:
    rectpack may reorder bins during packing, and rect_list() returns
    bin indexes, not a stable business identifier. So we assign each bin
    a stable bid=serial_no and then iterate over packed bins directly.
    """
    try:
        from rectpack import newPacker
    except Exception as exc:
        frappe.throw(
            _("The Python package 'rectpack' is required for Material Cutting Plan. Error: {0}").format(exc)
        )

    if not bins:
        return {
            "placements_by_bin": defaultdict(list),
            "bin_index_map": {},
        }

    packer = newPacker(rotation=allow_rotation)

    # Stable business mapping by serial_no
    bin_index_map: Dict[str, dict[str, object]] = {}
    demand_map: Dict[str, dict[str, object]] = {}

    # Add bins with explicit stable bid
    for b in bins:
        serial_no = (b.get("serial_no") or "").strip()
        bin_length = int(float(b.get("length_mm") or 0))
        bin_width = int(float(b.get("width_mm") or 0))

        if not serial_no or bin_length <= 0 or bin_width <= 0:
            continue

        packer.add_bin(bin_length, bin_width, bid=serial_no)
        bin_index_map[serial_no] = b

    # Add piece demands
    for d in demands:
        piece_uid = d.get("piece_uid")
        piece_length = int(float(d.get("length_mm") or 0))
        piece_width = int(float(d.get("width_mm") or 0))

        if not piece_uid or piece_length <= 0 or piece_width <= 0:
            continue

        demand_map[piece_uid] = d
        packer.add_rect(piece_length, piece_width, rid=piece_uid)

    try:
        packer.pack()
    except Exception as exc:
        frappe.throw(
            _("Rectpack failed while generating Material Cutting Plan: {0}").format(exc)
        )

    placements_by_bin: Dict[str, List[dict[str, object]]] = defaultdict(list)

    # IMPORTANT:
    # iterate over actual packed bins and use abin.bid, not rect_list() bin index
    for abin in packer:
        serial_no = getattr(abin, "bid", None)
        if not serial_no:
            continue

        if serial_no not in bin_index_map:
            logger.warning("Packed bin bid %s not found in bin_index_map", serial_no)
            continue

        for rect in abin:
            rid = getattr(rect, "rid", None)
            if not rid:
                continue

            d = demand_map.get(rid, {})
            orig_len = float(d.get("length_mm") or 0)
            orig_wid = float(d.get("width_mm") or 0)

            placed_len = float(getattr(rect, "width", 0) or 0)
            placed_wid = float(getattr(rect, "height", 0) or 0)

            rotation = False
            if allow_rotation and orig_len and orig_wid and orig_len != orig_wid:
                if placed_len == orig_wid and placed_wid == orig_len:
                    rotation = True

            placements_by_bin[serial_no].append({
                "piece_uid": rid,
                "x": float(getattr(rect, "x", 0) or 0),
                "y": float(getattr(rect, "y", 0) or 0),
                "length_mm": placed_len,
                "width_mm": placed_wid,
                "rotation": rotation,
            })

    logger.warning(
        "RECTPACK USED BINS: %s",
        {
            k: {
                "serial_no": v.get("serial_no"),
                "length_mm": v.get("length_mm"),
                "width_mm": v.get("width_mm"),
            }
            for k, v in bin_index_map.items()
            if k in placements_by_bin
        }
    )

    return {
        "placements_by_bin": placements_by_bin,
        "bin_index_map": bin_index_map,
    }


def _run_greedy_plan(
    demands: List[dict[str, object]],
    bins: List[dict[str, object]],
    allow_rotation: bool = True,
) -> Dict[str, object]:
    """Fallback packing algorithm when rectpack is unavailable.

    This simple greedy algorithm iterates through demands and assigns
    each piece to the first bin in which it fits.  It does not
    perform any sophisticated placement and sets ``x`` and ``y`` to
    zero for all placements.  Pieces that do not fit in any bin are
    skipped.

    Args:
        demands: List of unit cutting demands.
        bins: List of candidate bins.
        allow_rotation: Whether rotation is allowed (unused).

    Returns:
        A structure similar to the rectpack output with
        ``placements_by_bin`` and ``bin_index_map``.
    """
    bin_index_map: Dict[int, dict[str, object]] = {}
    for i, b in enumerate(bins):
        bin_index_map[i] = b

    placements_by_bin: Dict[int, List[dict[str, object]]] = defaultdict(list)

    for d in demands:
        placed = False
        l = d["length_mm"]
        w = d["width_mm"]
        # Attempt to fit into first bin with sufficient area
        for bin_id, b in bin_index_map.items():
            # Simple area check; real packing would consider remaining space
            if b["length_mm"] >= l and b["width_mm"] >= w:
                placements_by_bin[bin_id].append({
                    "piece_uid": d["piece_uid"],
                    "x": 0,
                    "y": 0,
                    "length_mm": l,
                    "width_mm": w,
                    "rotation": False,
                })
                placed = True
                break
        if not placed:
            # Piece could not be placed; skip it
            logger.info(
                "Greedy packing: could not place piece %s (%s x %s)",
                d["piece_uid"], l, w
            )
            continue

    return {
        "placements_by_bin": placements_by_bin,
        "bin_index_map": bin_index_map,
    }


def _build_tree_result(
    plan_name: str,
    demands: List[dict[str, object]],
    bins: List[dict[str, object]],
    placements_by_bin: Dict[str, object],
    kerf_mm: float,
    allow_rotation: bool,
    packing_algorithm: str,
    packing_heuristic: str,
) -> Dict[str, object]:
    """Construct a hierarchical tree and summary from packing results."""
    demand_map: Dict[str, dict[str, object]] = {d["piece_uid"]: d for d in demands}

    placements_map = placements_by_bin["placements_by_bin"]
    bin_index_map = placements_by_bin["bin_index_map"]

    planned_piece_count = sum(len(v) for v in placements_map.values())
    requested_piece_count = len(demands)
    missing_piece_count = requested_piece_count - planned_piece_count

    total_required_area_mm2 = 0.0
    for d in demands:
        try:
            lval = float(d.get("length_mm") or 0)
            wval = float(d.get("width_mm") or 0)
            total_required_area_mm2 += lval * wval
        except Exception:
            continue

    total_used_input_area_mm2 = 0.0
    total_planned_area_mm2 = 0.0

    nodes: List[dict[str, object]] = []
    leftover_count_total = 0
    total_leftover_area_mm2 = 0.0
    total_waste_area_mm2 = 0.0

    for bin_id, placements in placements_map.items():
        source_bin = bin_index_map.get(bin_id)
        if not source_bin:
            continue

        try:
            sheet_len = float(source_bin.get("length_mm") or 0.0)
            sheet_wid = float(source_bin.get("width_mm") or 0.0)
            bin_area = sheet_len * sheet_wid
            total_used_input_area_mm2 += bin_area
        except Exception:
            sheet_len = 0.0
            sheet_wid = 0.0
            bin_area = 0.0

        children: List[dict[str, object]] = []
        bin_planned_area_mm2 = 0.0

        for idx, p in enumerate(placements, start=1):
            d = demand_map.get(p["piece_uid"])
            if not d:
                continue

            placed_len = float(p.get("length_mm") or 0)
            placed_wid = float(p.get("width_mm") or 0)
            rotation = bool(p.get("rotation", False))

            piece_area = placed_len * placed_wid
            bin_planned_area_mm2 += piece_area
            total_planned_area_mm2 += piece_area

            children.append({
                "node_type": "finished_good",
                "id": d["piece_uid"],
                "label": f"FG P{idx} ({placed_len:g} x {placed_wid:g})",
                "is_real": False,
                "plan_ref_id": f"P{idx}",
                "piece_uid": d["piece_uid"],
                "sales_order": d.get("sales_order"),
                "sales_order_item": d.get("sales_order_item"),
                "root_item_code": d.get("root_item_code"),
                "root_item_name": d.get("root_item_name"),
                "piece_item_code": d.get("piece_item_code"),
                "piece_item_name": d.get("piece_item_name"),
                "length_mm": placed_len,
                "width_mm": placed_wid,
                "thickness_mm": d.get("thickness_mm"),
                "x": float(p.get("x") or 0),
                "y": float(p.get("y") or 0),
                "rotation": rotation,
                "path": d.get("path"),
                "path_labels": d.get("path_labels"),
            })

        # Safety check: a bin must never contain more planned area than its own area
        if bin_area > 0 and bin_planned_area_mm2 > bin_area + 0.001:
            frappe.throw(
                _("Invalid cutting plan for serial {0}: planned area {1} mm² exceeds available area {2} mm².").format(
                    source_bin.get("serial_no"),
                    round(bin_planned_area_mm2, 3),
                    round(bin_area, 3),
                )
            )

        try:
            free_rects = _compute_free_rectangles(sheet_len, sheet_wid, placements)
        except Exception:
            free_rects = []

        leftover_index = 1
        waste_index = 1
        for (fx, fy, fw, fh) in free_rects:
            if fw <= 0.0 or fh <= 0.0:
                continue

            min_dim = min(fw, fh)
            area_free = fw * fh

            if min_dim < LEFTOVER_MIN_DIMENSION_MM:
                classification = "waste"
                node_id = f"{source_bin.get('serial_no')}::W{waste_index}"
                waste_index += 1
                total_waste_area_mm2 += area_free
            else:
                classification = "leftover"
                node_id = f"{source_bin.get('serial_no')}::L{leftover_index}"
                leftover_index += 1
                leftover_count_total += 1
                total_leftover_area_mm2 += area_free

            children.append({
                "node_type": classification,
                "id": node_id,
                "label": f"{classification.capitalize()} ({fw:g} x {fh:g})",
                "is_real": False,
                "serial_no": source_bin.get("serial_no"),
                "source_kind": source_bin.get("source_kind"),
                "item_code": source_bin.get("item_code"),
                "length_mm": fw,
                "width_mm": fh,
                "thickness_mm": None,
                "x": fx,
                "y": fy,
                "rotation": False,
                "area_mm2": area_free,
                "classification": classification,
            })

        nodes.append({
            "node_type": "input_serial",
            "id": source_bin["serial_no"],
            "label": f'{source_bin["serial_no"]} ({source_bin["length_mm"]} x {source_bin["width_mm"]})',
            "is_real": True,
            "serial_no": source_bin["serial_no"],
            "source_kind": source_bin.get("source_kind"),
            "item_code": source_bin.get("item_code"),
            "length_mm": source_bin["length_mm"],
            "width_mm": source_bin["width_mm"],
            "area_mm2": source_bin.get("area_mm2"),
            "material_status": source_bin.get("material_status"),
            "children": children,
        })

    if total_leftover_area_mm2 > 0.0 or total_waste_area_mm2 > 0.0:
        leftover_area_mm2 = total_leftover_area_mm2
        waste_area_mm2 = total_waste_area_mm2
    else:
        leftover_area_mm2 = max(0.0, total_used_input_area_mm2 - total_planned_area_mm2)
        waste_area_mm2 = 0.0

    summary = {
        "requested_piece_count": requested_piece_count,
        "planned_piece_count": planned_piece_count,
        "missing_piece_count": missing_piece_count,
        "used_input_serial_count": len(nodes),
        "leftover_count": leftover_count_total,
        "total_required_area_m2": total_required_area_mm2 / 1_000_000.0,
        "total_used_input_area_m2": total_used_input_area_mm2 / 1_000_000.0,
        "total_leftover_area_m2": leftover_area_mm2 / 1_000_000.0,
        "total_waste_area_m2": waste_area_mm2 / 1_000_000.0,
    }

    return {
        "plan_id": plan_name,
        "plan_status": "Draft",
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "options": {
            "kerf_mm": kerf_mm,
            "allow_rotation": allow_rotation,
            "packing_algorithm": packing_algorithm,
            "packing_heuristic": packing_heuristic,
        },
        "summary": summary,
        "nodes": nodes,
    }

def update_active_input_flags(doc, tree):
    """
    After plan generation:
    - set is_active_input = 1 for serials actually used in the plan
    - reset others to 0

    Args:
        doc: Material Cutting Plan document
        tree: generated plan tree (result["tree"])
    """
    nodes = (tree or {}).get("nodes") or []

    active_serials = set()
    for node in nodes:
        serial_no = str(node.get("serial_no") or "").strip()
        if serial_no:
            active_serials.add(serial_no)

    for row in (doc.get("mcp_stock_candidate") or []):
        row.is_active_input = 0

    for row in (doc.get("mcp_stock_candidate") or []):
        row_serial = str(row.serial_no or "").strip()
        if row_serial and row_serial in active_serials:
            row.is_active_input = 1




def _safe_tree_dict(tree_or_json) -> Dict[str, object]:
    if not tree_or_json:
        return {}
    if isinstance(tree_or_json, dict):
        return tree_or_json
    try:
        import json
        return json.loads(tree_or_json)
    except Exception:
        return {}


def _get_return_terrain_base_tree(tree: Dict[str, object]) -> Dict[str, object]:
    if not isinstance(tree, dict):
        return {}
    base_tree = tree.get("base_tree")
    if isinstance(base_tree, dict) and base_tree.get("nodes") is not None:
        return base_tree
    return tree


def _is_return_terrain_resolved_tree(tree: Dict[str, object]) -> bool:
    if not isinstance(tree, dict):
        return False
    if tree.get("return_terrain_resolved"):
        return True
    options = tree.get("options") or {}
    return bool(options.get("return_terrain_resolved"))


def _ensure_effective_fields(child: dict[str, object]) -> dict[str, object]:
    out = dict(child)
    if "effective_length_mm" not in out:
        out["effective_length_mm"] = float(out.get("length_mm") or 0.0)
    if "effective_width_mm" not in out:
        out["effective_width_mm"] = float(out.get("width_mm") or 0.0)
    if "effective_area_mm2" not in out:
        out["effective_area_mm2"] = float(out.get("effective_length_mm") or 0.0) * float(out.get("effective_width_mm") or 0.0)
    return out


def _classify_free_region(length_mm: float, width_mm: float) -> str:
    return "waste" if min(length_mm, width_mm) < LEFTOVER_MIN_DIMENSION_MM else "leftover"


def _make_final_free_child(*, serial_no: str, source_bin: dict[str, object], idx: int, classification: str, x: float, y: float, length_mm: float, width_mm: float) -> dict[str, object]:
    area_mm2 = float(length_mm or 0.0) * float(width_mm or 0.0)
    prefix = "L" if classification == "leftover" else "W"
    return {
        "node_type": classification,
        "id": f"{serial_no}::RT{prefix}{idx}",
        "label": f"{classification.capitalize()} ({length_mm:g} x {width_mm:g})",
        "is_real": False,
        "serial_no": serial_no,
        "source_kind": source_bin.get("source_kind"),
        "item_code": source_bin.get("item_code"),
        "length_mm": length_mm,
        "width_mm": width_mm,
        "thickness_mm": source_bin.get("thickness_mm"),
        "x": x,
        "y": y,
        "rotation": False,
        "area_mm2": area_mm2,
        "classification": classification,
        "effective_length_mm": length_mm,
        "effective_width_mm": width_mm,
        "effective_area_mm2": area_mm2,
    }


def generate_return_terrain_cutting_plan(
    *,
    plan_name: str,
    demands: List[dict[str, object]],
    bins: List[dict[str, object]],
    existing_tree: Dict[str, object] | str | None,
    mcp_doc,
    kerf_mm: float = 0.0,
    allow_rotation: bool = True,
    packing_algorithm: str = "maxrects",
    packing_heuristic: str = "best_area_fit",
) -> Dict[str, object]:
    """Return-terrain planner.

    Strategy retained from the memo:
    - keep the original input bin as the geometric reference
    - consider original finished_good zones as already consumed and therefore not reusable
    - reuse only original leftover/waste zones (optionally incidented) plus any newly activated input serials
    - produce missing pieces inside those still-available regions
    """
    parsed_tree = _safe_tree_dict(existing_tree)
    base_tree = _get_return_terrain_base_tree(parsed_tree)
    base_nodes = base_tree.get("nodes") or []
    base_node_map = {str(n.get("serial_no") or n.get("id") or "").strip(): n for n in base_nodes}

    incident_map = build_incident_map(mcp_doc)
    demand_map = {str(d.get("piece_uid") or "").strip(): d for d in demands}

    fulfilled_piece_uids: set[str] = set()
    locked_children_by_serial: dict[str, list[dict[str, object]]] = defaultdict(list)
    usable_regions_by_serial: dict[str, list[dict[str, object]]] = defaultdict(list)

    effective_base_nodes = apply_incidents_to_nodes(base_nodes, incident_map)
    effective_base_node_map = {str(n.get("serial_no") or n.get("id") or "").strip(): n for n in effective_base_nodes}

    for source_bin in bins:
        serial_no = str(source_bin.get("serial_no") or "").strip()
        if not serial_no:
            continue

        effective_node = effective_base_node_map.get(serial_no)
        if not effective_node:
            usable_regions_by_serial[serial_no].append({
                "id": f"{serial_no}::FULL",
                "node_type": _classify_free_region(float(source_bin.get("length_mm") or 0.0), float(source_bin.get("width_mm") or 0.0)),
                "serial_no": serial_no,
                "item_code": source_bin.get("item_code"),
                "length_mm": float(source_bin.get("length_mm") or 0.0),
                "width_mm": float(source_bin.get("width_mm") or 0.0),
                "thickness_mm": source_bin.get("thickness_mm"),
                "x": 0.0,
                "y": 0.0,
            })
            continue

        for child in (effective_node.get("children") or []):
            row = ensure_effective_fields(child)
            node_type = str(row.get("node_type") or "").strip()

            if node_type == "finished_good":
                locked_children_by_serial[serial_no].append(row)
                piece_uid = str(row.get("piece_uid") or child.get("piece_uid") or "").strip()
                if piece_uid:
                    fulfilled_piece_uids.add(piece_uid)
                continue

            if node_type in ("leftover", "waste"):
                usable_regions_by_serial[serial_no].append(row)
                continue

            locked_children_by_serial[serial_no].append(row)

    remaining_demands = [
        d for d in demands
        if str(d.get("piece_uid") or "").strip() not in fulfilled_piece_uids
    ]

    virtual_bins: list[dict[str, object]] = []
    virtual_meta: dict[str, dict[str, object]] = {}

    for source_bin in bins:
        serial_no = str(source_bin.get("serial_no") or "").strip()
        region_index = 1
        for region in usable_regions_by_serial.get(serial_no, []):
            length_mm = float(region.get("length_mm") or 0.0)
            width_mm = float(region.get("width_mm") or 0.0)
            if length_mm <= 0 or width_mm <= 0:
                continue

            virtual_serial_no = f"{serial_no}::FREE{region_index}"
            region_index += 1

            virtual_bin = {
                "serial_no": virtual_serial_no,
                "parent_serial_no": serial_no,
                "item_code": source_bin.get("item_code"),
                "warehouse": source_bin.get("warehouse"),
                "length_mm": length_mm,
                "width_mm": width_mm,
                "thickness_mm": source_bin.get("thickness_mm"),
                "area_mm2": length_mm * width_mm,
                "material_status": "Partial",
                "source_kind": "Return Terrain Free Region",
            }
            virtual_bins.append(virtual_bin)
            virtual_meta[virtual_serial_no] = {
                "parent_serial_no": serial_no,
                "offset_x": float(region.get("x") or 0.0),
                "offset_y": float(region.get("y") or 0.0),
                "source_bin": source_bin,
                "region": region,
            }

    placements_info = _run_rectpack_plan(
        demands=remaining_demands,
        bins=virtual_bins,
        allow_rotation=allow_rotation,
    )
    placements_map = placements_info.get("placements_by_bin") or {}

    final_nodes: list[dict[str, object]] = []
    global_rt_fg_index = 1

    for source_bin in bins:
        serial_no = str(source_bin.get("serial_no") or "").strip()
        if not serial_no:
            continue

        children: list[dict[str, object]] = []
        children.extend(locked_children_by_serial.get(serial_no, []))

        leftover_idx = 1
        waste_idx = 1

        for virtual_serial_no, meta in virtual_meta.items():
            if meta["parent_serial_no"] != serial_no:
                continue

            offset_x = float(meta["offset_x"] or 0.0)
            offset_y = float(meta["offset_y"] or 0.0)
            region = meta["region"]
            region_length = float(region.get("length_mm") or 0.0)
            region_width = float(region.get("width_mm") or 0.0)
            local_placements = list(placements_map.get(virtual_serial_no) or [])

            for p in local_placements:
                d = demand_map.get(str(p.get("piece_uid") or "").strip())
                if not d:
                    continue

                placed_len = float(p.get("length_mm") or 0.0)
                placed_wid = float(p.get("width_mm") or 0.0)
                rotation = bool(p.get("rotation", False))
                piece_uid = str(d.get("piece_uid") or "").strip()

                children.append({
                    "node_type": "finished_good",
                    "id": f"{piece_uid}::RT{global_rt_fg_index}",
                    "label": f"FG RT P{global_rt_fg_index} ({placed_len:g} x {placed_wid:g})",
                    "is_real": False,
                    "plan_ref_id": f"RTP{global_rt_fg_index}",
                    "piece_uid": piece_uid,
                    "sales_order": d.get("sales_order"),
                    "sales_order_item": d.get("sales_order_item"),
                    "root_item_code": d.get("root_item_code"),
                    "root_item_name": d.get("root_item_name"),
                    "piece_item_code": d.get("piece_item_code"),
                    "piece_item_name": d.get("piece_item_name"),
                    "length_mm": placed_len,
                    "width_mm": placed_wid,
                    "thickness_mm": d.get("thickness_mm"),
                    "x": offset_x + float(p.get("x") or 0.0),
                    "y": offset_y + float(p.get("y") or 0.0),
                    "rotation": rotation,
                    "path": d.get("path"),
                    "path_labels": d.get("path_labels"),
                    "effective_length_mm": placed_len,
                    "effective_width_mm": placed_wid,
                    "effective_area_mm2": placed_len * placed_wid,
                })
                fulfilled_piece_uids.add(piece_uid)
                global_rt_fg_index += 1

            free_rects = _compute_free_rectangles(region_length, region_width, local_placements)
            for fx, fy, fw, fh in free_rects:
                if fw <= 0 or fh <= 0:
                    continue
                classification = _classify_free_region(fw, fh)
                idx = leftover_idx if classification == "leftover" else waste_idx
                child = _make_final_free_child(
                    serial_no=serial_no,
                    source_bin=source_bin,
                    idx=idx,
                    classification=classification,
                    x=offset_x + fx,
                    y=offset_y + fy,
                    length_mm=fw,
                    width_mm=fh,
                )
                children.append(child)
                if classification == "leftover":
                    leftover_idx += 1
                else:
                    waste_idx += 1

        children.sort(key=lambda row: (float(row.get("y") or 0.0), float(row.get("x") or 0.0), str(row.get("id") or "")))

        final_nodes.append({
            "node_type": "input_serial",
            "id": serial_no,
            "label": f'{serial_no} ({source_bin["length_mm"]} x {source_bin["width_mm"]})',
            "is_real": True,
            "serial_no": serial_no,
            "source_kind": source_bin.get("source_kind"),
            "item_code": source_bin.get("item_code"),
            "length_mm": source_bin.get("length_mm"),
            "width_mm": source_bin.get("width_mm"),
            "area_mm2": source_bin.get("area_mm2"),
            "material_status": source_bin.get("material_status"),
            "children": children or [],
        })

    total_required_area_mm2 = 0.0
    for d in demands:
        try:
            total_required_area_mm2 += float(d.get("length_mm") or 0.0) * float(d.get("width_mm") or 0.0)
        except Exception:
            continue

    total_used_input_area_mm2 = 0.0
    total_leftover_area_mm2 = 0.0
    total_waste_area_mm2 = 0.0
    leftover_count = 0
    planned_piece_uids: set[str] = set()

    for node in final_nodes:
        total_used_input_area_mm2 += float(node.get("length_mm") or 0.0) * float(node.get("width_mm") or 0.0)
        for child in node.get("children") or []:
            node_type = str(child.get("node_type") or "").strip()
            if node_type == "finished_good":
                piece_uid = str(child.get("piece_uid") or "").strip()
                if piece_uid:
                    planned_piece_uids.add(piece_uid)
            elif node_type == "leftover":
                total_leftover_area_mm2 += float(child.get("length_mm") or 0.0) * float(child.get("width_mm") or 0.0)
                leftover_count += 1
            elif node_type == "waste":
                total_waste_area_mm2 += float(child.get("length_mm") or 0.0) * float(child.get("width_mm") or 0.0)

    planned_piece_count = len(planned_piece_uids)
    requested_piece_count = len(demands)
    missing_piece_count = max(0, requested_piece_count - planned_piece_count)

    resolved_tree = {
        "plan_id": plan_name,
        "plan_status": "Draft",
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "return_terrain_resolved": True,
        "base_tree": base_tree,
        "options": {
            "kerf_mm": kerf_mm,
            "allow_rotation": allow_rotation,
            "packing_algorithm": packing_algorithm,
            "packing_heuristic": packing_heuristic,
            "return_terrain_resolved": True,
        },
        "summary": {
            "requested_piece_count": requested_piece_count,
            "planned_piece_count": planned_piece_count,
            "missing_piece_count": missing_piece_count,
            "used_input_serial_count": len(final_nodes),
            "leftover_count": leftover_count,
            "total_required_area_m2": total_required_area_mm2 / 1_000_000.0,
            "total_used_input_area_m2": total_used_input_area_mm2 / 1_000_000.0,
            "total_leftover_area_m2": total_leftover_area_mm2 / 1_000_000.0,
            "total_waste_area_m2": total_waste_area_mm2 / 1_000_000.0,
        },
        "nodes": final_nodes,
    }
    return {"tree": resolved_tree, "summary": resolved_tree["summary"]}
