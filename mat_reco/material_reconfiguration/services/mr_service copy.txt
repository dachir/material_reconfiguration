"""
Material Reconfiguration document construction.

This module converts cut plans into Material Reconfiguration Line
records suitable for insertion into the ERP system. It does not
execute any stock transfers or serial bundle creation; instead it
focuses on translating the pure cut plan into the specific format
expected by the Material Reconfiguration doctype. Use the functions
here to prepare lines, and then let the DocType code handle the
persistence.
"""

from typing import List, Dict, Any, Tuple
from mat_reco.material_reconfiguration.engines.cut_engine import CutPlan
from mat_reco.material_reconfiguration.utils.dimensions import norm_dims


def build_mr_lines(
    source_serial: str,
    plan: CutPlan,
    target_warehouse: str,
    fg_item_code: str,
    quality_rating: int = 5,
) -> List[Dict[str, Any]]:
    """Convert a cut plan into Material Reconfiguration lines.

    The resulting list can be assigned to the ``detail`` table field
    of a Material Reconfiguration document. Each line dictionary
    includes fields such as ``categorie``, ``line_type``, ``serial_no``,
    ``length_mm`` and ``width_mm``. Finished goods are assigned the
    target warehouse while chutes and waste inherit the source
    warehouse.

    :param source_serial: Name of the Serial No used as input.
    :param plan: Cut plan produced by :func:`mat_reco.material_reconfiguration.engines.cut_engine.plan_cut`.
    :param target_warehouse: Warehouse for finished goods and chutes.
    :param fg_item_code: Item code of the finished good.
    :param quality_rating: Quality rating assigned to outputs.
    :return: List of dicts for the MR detail table.
    """
    lines: List[Dict[str, Any]] = []
    # Input line
    # Input line represents the raw material consumed by this operation.
    # Set material_status="Consumed" and omit dimensions, as the input
    # dimensions are tracked on the Serial No itself.  Quality rating is
    # not relevant for inputs and remains unset.
    lines.append(
        {
            "line_type": "Input",
            "categorie": "Raw Material",
            "serial_no": source_serial,
            "length_mm": None,
            "width_mm": None,
            "quality_rating": None,
            "material_status": "Consumed",
        }
    )
    # Finished good line
    # Ensure that length_mm >= width_mm for display consistency
    fg_len, fg_wid = norm_dims(plan.orientation[0], plan.orientation[1])
    lines.append(
        {
            "line_type": "Output",
            "categorie": "Finished Good",
            "related_input_serial_no": source_serial,
            # Use normalized orientation for FG dimensions
            "length_mm": fg_len,
            "width_mm": fg_wid,
            "target_warehouse": target_warehouse,
            "material_status": "Full" if plan.produced_qty > 0 else None,
            "item_code": fg_item_code,
            "planned_pieces": plan.produced_qty,
            "quality_rating": quality_rating,
        }
    )
    # Include both keepable and waste chutes in the output lines.
    #
    # Prior to this change, only chutes whose smallest dimension met the
    # minimum keep threshold were added to the detail table, while smaller
    # pieces were silently discarded or marked as waste.  However, users
    # want to see all resulting rectangles after the cut when the document
    # is saved.  They will decide which chutes to keep when the document
    # is submitted.  To support this workflow, we now append all
    # residual rectangles—both ``plan.children`` (above threshold) and
    # ``plan.waste`` (below threshold)—to the MR detail table.  We mark
    # every chute with ``material_status = "Partial"`` so that it
    # appears in the UI.  Later, during submission, code can inspect
    # ``length_mm`` and ``width_mm`` to determine whether to create a
    # Serial No for that chute (e.g. by skipping those whose minimum
    # dimension falls below ``settings.min_keep_dimension_mm``).
    for ch in plan.children + plan.waste:
        L, W = ch
        # Normalize dimensions so that length_mm >= width_mm
        cL, cW = norm_dims(L, W)
        lines.append(
            {
                "line_type": "Output",
                "categorie": "By Product",
                "related_input_serial_no": source_serial,
                "length_mm": cL,
                "width_mm": cW,
                "target_warehouse": target_warehouse,
                # Always set planned_pieces=1 for chutes
                "planned_pieces": 1,
                "quality_rating": quality_rating,
                # We mark all chutes as "Partial" here.  Chutes below the
                # threshold can be detected and skipped during submission.
                "material_status": "Partial",
            }
        )
    return lines


__all__ = ["build_mr_lines"]