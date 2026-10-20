"""
Material Reconfiguration document construction from cutting JSON.
"""

import json
from typing import List, Dict, Any

from mat_reco.material_reconfiguration.engines.cut_engine import CutPlan
from mat_reco.material_reconfiguration.utils.dimensions import norm_dims
from mat_reco.material_reconfiguration.utils.settings import get_reco_settings


def _is_keepable_leftover(length: float, width: float, min_keep_dimension_mm: float) -> bool:
    return min(length, width) >= min_keep_dimension_mm


def build_mr_lines(
    source_serial: str,
    plan: CutPlan,
    target_warehouse: str,
    fg_item_code: str,
    quality_rating: int = 5,
) -> List[Dict[str, Any]]:
    settings = get_reco_settings()
    lines: List[Dict[str, Any]] = []

    best_solution = plan.best_solution or {}
    placements = best_solution.get("placements", [])
    leftovers = best_solution.get("leftovers", [])

    piece_ids = [p["piece_id"] for p in placements]

    # INPUT
    lines.append(
        {
            "line_type": "Input",
            "categorie": "Raw Material",
            "serial_no": source_serial,
            "length_mm": None,
            "width_mm": None,
            "quality_rating": None,
            "material_status": "Consumed",
            "plan_decoupe": json.dumps(plan.raw_result, ensure_ascii=False),
            "plan_ref_id": None,
        }
    )

    # FG CONSOLIDE
    if placements:
        fg_len, fg_wid = norm_dims(placements[0]["length"], placements[0]["width"])
    else:
        fg_len, fg_wid = norm_dims(plan.orientation[0], plan.orientation[1])

    lines.append(
        {
            "line_type": "Output",
            "categorie": "Finished Good",
            "related_input_serial_no": source_serial,
            "length_mm": fg_len,
            "width_mm": fg_wid,
            "target_warehouse": target_warehouse,
            "material_status": "Full" if plan.produced_qty > 0 else None,
            "item_code": fg_item_code,
            "planned_pieces": len(placements),
            "quality_rating": quality_rating,
            "plan_decoupe": None,
            "plan_ref_id": json.dumps(piece_ids, ensure_ascii=False),
        }
    )

    # LEFTOVERS
    for lf in leftovers:
        cL, cW = norm_dims(lf["length"], lf["width"])
        keepable = _is_keepable_leftover(cL, cW, settings.min_keep_dimension_mm)

        lines.append(
            {
                "line_type": "Output",
                "categorie": "By Product",
                "related_input_serial_no": source_serial,
                "length_mm": cL,
                "width_mm": cW,
                "target_warehouse": target_warehouse,
                "planned_pieces": 1,
                "quality_rating": quality_rating,
                "material_status": "Partial",
                "plan_decoupe": None,
                "plan_ref_id": lf["leftover_id"],
            }
        )

    return lines


__all__ = ["build_mr_lines"]