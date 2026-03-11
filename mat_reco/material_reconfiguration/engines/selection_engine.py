"""
Candidate selection logic for material reconfiguration.
"""

from typing import Iterable, Tuple, Optional

from mat_reco.material_reconfiguration.utils.dimensions import area
from mat_reco.material_reconfiguration.engines.cut_engine import plan_cut, CutPlan
from mat_reco.material_reconfiguration.utils.settings import get_reco_settings


def pick_best_candidate(
    candidates: Iterable[Tuple[str, Tuple[float, float]]],
    piece: Tuple[float, float],
    qty: int,
    kerf: float | None = None,
) -> Tuple[str, CutPlan]:
    settings = get_reco_settings()

    best_id: Optional[str] = None
    best_plan: Optional[CutPlan] = None
    best_area: Optional[float] = None

    for cid, dims in candidates:
        plan = plan_cut(
            source=dims,
            piece=piece,
            qty=qty,
            allow_rotation=settings.allow_rotation,
            kerf=kerf if kerf is not None else settings.kerf_mm,
            min_keep_dimension_mm=settings.min_keep_dimension_mm,
        )

        if plan.produced_qty <= 0:
            continue

        dims_area = area(*dims)

        if best_plan is None:
            best_id = cid
            best_plan = plan
            best_area = dims_area
            continue

        if plan.produced_qty > best_plan.produced_qty:
            best_id = cid
            best_plan = plan
            best_area = dims_area
            continue

        current_best_stats = best_plan.best_solution.get("statistics", {})
        new_stats = plan.best_solution.get("statistics", {})

        if plan.produced_qty == best_plan.produced_qty:
            if new_stats.get("kerf_loss_area", float("inf")) < current_best_stats.get("kerf_loss_area", float("inf")):
                best_id = cid
                best_plan = plan
                best_area = dims_area
                continue

            if new_stats.get("kerf_loss_area", float("inf")) == current_best_stats.get("kerf_loss_area", float("inf")):
                if len(plan.children) > len(best_plan.children):
                    best_id = cid
                    best_plan = plan
                    best_area = dims_area
                    continue

                if len(plan.children) == len(best_plan.children):
                    if best_area is None or dims_area < best_area:
                        best_id = cid
                        best_plan = plan
                        best_area = dims_area
                        continue

    if best_plan is None or best_id is None:
        raise ValueError(
            f"No valid candidate can produce piece {piece} with qty {qty}."
        )

    return best_id, best_plan


__all__ = ["pick_best_candidate"]