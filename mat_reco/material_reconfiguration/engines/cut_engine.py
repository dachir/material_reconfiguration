"""
Cutting engine based on explicit layout generation.

This engine computes a cutting plan with coordinates, leftovers,
indicative cuts and statistics. It is designed to be stored as JSON
on the Input line of Material Reconfiguration Line.
"""

from dataclasses import dataclass
from typing import List, Tuple, Optional, Dict, Any
from copy import deepcopy


@dataclass
class CutPlan:
    produced_qty: int
    orientation: Tuple[float, float]
    grid: Tuple[int, int]
    used_dims: Tuple[float, float]
    children: List[Tuple[float, float]]
    waste: List[Tuple[float, float]]
    raw_result: Dict[str, Any]
    best_solution: Dict[str, Any]


def build_layout(sheet_length, sheet_width, kerf, piece_length, piece_width, qty):
    """
    Construit un plan simple de découpe guillotine indicatif.

    Règle métier:
    - on place autant de pièces que possible, jusqu'à qty
    - si toute la quantité ne rentre pas, on retourne quand même un plan partiel
    - on retourne None seulement si aucune pièce ne peut être placée
    """

    placements = []

    x = 0
    y = 0
    placed = 0
    row_height = piece_width

    while placed < qty:
        # Si la pièce ne rentre pas sur la ligne courante
        if x + piece_length > sheet_length:
            # Si on est déjà au début d'une ligne vide,
            # alors elle ne rentre nulle part en longueur
            if x == 0:
                break

            # Sinon on passe à la ligne suivante
            x = 0
            y += row_height + kerf
            continue

        # Si la pièce ne rentre plus en hauteur, on s'arrête
        if y + piece_width > sheet_width:
            break

        placements.append({
            "piece_id": f"A{placed + 1}",
            "x": x,
            "y": y,
            "length": piece_length,
            "width": piece_width,
            "rotation": False
        })

        placed += 1
        x += piece_length + kerf

    # Si aucune pièce n'a pu être placée, échec réel
    if not placements:
        return None

    leftovers = compute_leftovers_from_row_layout(
        sheet_length=sheet_length,
        sheet_width=sheet_width,
        kerf=kerf,
        placements=placements
    )

    cuts = build_indicative_cuts(placements, kerf)

    sheet_area = sheet_length * sheet_width
    used_area = sum(p["length"] * p["width"] for p in placements)
    leftover_area = sum(l["area"] for l in leftovers)
    kerf_loss_area = sheet_area - used_area - leftover_area

    result = {
        "sheet": {
            "length": sheet_length,
            "width": sheet_width,
            "kerf": kerf,
            "origin": [0, 0]
        },
        "placements": placements,
        "cuts": cuts,
        "leftovers": leftovers,
        "statistics": {
            "sheet_area": sheet_area,
            "used_area": used_area,
            "leftover_area": leftover_area,
            "kerf_loss_area": kerf_loss_area,
            "utilization_ratio": used_area / sheet_area if sheet_area else 0,
            "leftover_count": len(leftovers)
        }
    }

    return result


def compute_leftovers_from_row_layout(sheet_length, sheet_width, kerf, placements):
    if not placements:
        return []

    rows = {}
    for p in placements:
        rows.setdefault(p["y"], []).append(p)

    sorted_rows_y = sorted(rows.keys())
    leftovers = []
    leftover_index = 1

    normalized_rows = []
    for y in sorted_rows_y:
        row_pieces = sorted(rows[y], key=lambda p: p["x"])
        normalized_rows.append((y, row_pieces))

    for y, row_pieces in normalized_rows:
        last_piece = row_pieces[-1]
        right_start = last_piece["x"] + last_piece["length"] + kerf

        if right_start < sheet_length:
            length = sheet_length - right_start
            width = row_pieces[0]["width"]
            leftovers.append({
                "leftover_id": f"L{leftover_index}",
                "x": right_start,
                "y": y,
                "length": length,
                "width": width,
                "shape": "rectangle",
                "area": length * width
            })
            leftover_index += 1

    last_y, last_row = normalized_rows[-1]
    top_start = last_y + last_row[0]["width"] + kerf
    if top_start < sheet_width:
        leftovers.append({
            "leftover_id": f"L{leftover_index}",
            "x": 0,
            "y": top_start,
            "length": sheet_length,
            "width": sheet_width - top_start,
            "shape": "rectangle",
            "area": sheet_length * (sheet_width - top_start)
        })

    return leftovers


def build_indicative_cuts(placements, kerf):
    cuts = []
    cut_index = 1

    horizontal_positions = sorted(set(
        p["y"] + p["width"] for p in placements
    ))
    vertical_positions = sorted(set(
        p["x"] + p["length"] for p in placements
    ))

    for pos in horizontal_positions:
        cuts.append({
            "cut_id": f"C{cut_index}",
            "type": "horizontal",
            "position": pos,
            "kerf": kerf
        })
        cut_index += 1

    for pos in vertical_positions:
        cuts.append({
            "cut_id": f"C{cut_index}",
            "type": "vertical",
            "position": pos,
            "kerf": kerf
        })
        cut_index += 1

    return cuts


def score_solution(result):
    stats = result["statistics"]
    leftovers = result["leftovers"]
    placements = result.get("placements", [])

    produced_qty = len(placements)
    largest_leftover = max((l["area"] for l in leftovers), default=0)

    return (
        -produced_qty,                    # priorité absolue : produire plus
        stats["kerf_loss_area"],          # puis moins de perte
        -largest_leftover,                # puis plus grande chute
        stats["leftover_count"],          # puis moins de chutes
        -stats["leftover_area"],          # puis plus de surface récupérable
    )


def optimize_cutting(
    sheet_length,
    sheet_width,
    kerf,
    piece_length,
    piece_width,
    qty,
    piece_rotation_allowed=True
):
    candidates = []

    sheet_variants = [
        {
            "sheet_length": sheet_length,
            "sheet_width": sheet_width,
            "sheet_rotated": False
        },
        {
            "sheet_length": sheet_width,
            "sheet_width": sheet_length,
            "sheet_rotated": True
        }
    ]

    piece_variants = [
        {
            "piece_length": piece_length,
            "piece_width": piece_width,
            "piece_rotated": False
        }
    ]

    if piece_rotation_allowed and (piece_length != piece_width):
        piece_variants.append({
            "piece_length": piece_width,
            "piece_width": piece_length,
            "piece_rotated": True
        })

    for s in sheet_variants:
        for p in piece_variants:
            layout = build_layout(
                sheet_length=s["sheet_length"],
                sheet_width=s["sheet_width"],
                kerf=kerf,
                piece_length=p["piece_length"],
                piece_width=p["piece_width"],
                qty=qty
            )

            if layout is None:
                continue

            candidate = deepcopy(layout)
            candidate["comparison"] = {
                "sheet_rotated_90": s["sheet_rotated"],
                "piece_rotated_90": p["piece_rotated"],
                "original_sheet": {
                    "length": sheet_length,
                    "width": sheet_width
                },
                "original_piece": {
                    "length": piece_length,
                    "width": piece_width
                }
            }

            for placement in candidate["placements"]:
                placement["rotation"] = p["piece_rotated"]

            candidates.append(candidate)

    if not candidates:
        return {
            "best_solution": None,
            "all_candidates": [],
            "message": "No valid layout found."
        }

    best = min(candidates, key=score_solution)

    for idx, c in enumerate(candidates, start=1):
        c["candidate_id"] = f"OPTION_{idx}"

    best["selected"] = True

    return {
        "best_solution": best,
        "all_candidates": candidates
    }


def _is_keepable_leftover(length: float, width: float, min_keep_dimension_mm: float) -> bool:
    return min(length, width) >= min_keep_dimension_mm


def plan_cut(
    source: Tuple[float, float],
    piece: Tuple[float, float],
    qty: int,
    allow_rotation: bool = True,
    kerf: float = 0,
    min_keep_dimension_mm: float = 0,
) -> CutPlan:
    sheet_length, sheet_width = source
    piece_length, piece_width = piece

    raw_result = optimize_cutting(
        sheet_length=sheet_length,
        sheet_width=sheet_width,
        kerf=kerf,
        piece_length=piece_length,
        piece_width=piece_width,
        qty=qty,
        piece_rotation_allowed=allow_rotation,
    )

    best_solution = raw_result.get("best_solution")
    if not best_solution:
        return CutPlan(
            produced_qty=0,
            orientation=(0.0, 0.0),
            grid=(0, 0),
            used_dims=(0.0, 0.0),
            children=[],
            waste=[source],
            raw_result=raw_result,
            best_solution={},
        )

    placements = best_solution.get("placements", [])
    leftovers = best_solution.get("leftovers", [])

    produced_qty = len(placements)

    orientation = (piece_length, piece_width)
    if placements:
        first = placements[0]
        orientation = (first["length"], first["width"])

    used_area = sum(p["length"] * p["width"] for p in placements)
    used_dims = (
        best_solution["statistics"].get("used_area", used_area),
        0.0,
    )

    children = []
    waste = []

    for lf in leftovers:
        dims = (lf["length"], lf["width"])
        if _is_keepable_leftover(lf["length"], lf["width"], min_keep_dimension_mm):
            children.append(dims)
        else:
            waste.append(dims)

    unique_x = sorted(set(p["x"] for p in placements))
    unique_y = sorted(set(p["y"] for p in placements))
    grid = (len(unique_x), len(unique_y))

    return CutPlan(
        produced_qty=produced_qty,
        orientation=orientation,
        grid=grid,
        used_dims=used_dims,
        children=children,
        waste=waste,
        raw_result=raw_result,
        best_solution=best_solution,
    )


__all__ = ["CutPlan", "plan_cut", "optimize_cutting"]