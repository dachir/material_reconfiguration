"""
Candidate selection logic for material reconfiguration.

When multiple sheets or chutes are available to fulfil a cutting
operation, this module chooses which one to use. The selection
criteria aim to minimise waste and favour consuming smaller pieces
before larger ones. All functions in this module operate on plain
Python data structures and do not interact with the database.
"""

from typing import Iterable, List, Tuple, Optional

from mat_reco.material_reconfiguration.utils.dimensions import area
from mat_reco.material_reconfiguration.engines.cut_engine import plan_cut, CutPlan
from mat_reco.material_reconfiguration.utils.settings import get_reco_settings


def pick_best_candidate(
    candidates: Iterable[Tuple[str, Tuple[float, float]]],
    piece: Tuple[float, float],
    qty: int,
    kerf: float | None = None,
) -> Tuple[str, CutPlan]:
    """Choose the best candidate sheet/chute to cut.

    Each candidate is a tuple containing an identifier and its
    dimensions (L,W). The function uses the current settings to plan
    a cut for each candidate and returns the one that produces the
    largest number of pieces while minimising waste. Ties are broken
    by picking the candidate with the smallest area, encouraging
    consumption of smaller material first.

    :param candidates: Iterable of (id, (L,W)) tuples.
    :param piece: Dimensions of the piece to cut (a,b).
    :param qty: Quantity required.
    :return: Tuple (id, CutPlan) for the chosen candidate.
    """
    settings = get_reco_settings()
    best_id: Optional[str] = None
    best_plan: Optional[CutPlan] = None
    best_area: Optional[float] = None
    for cid, dims in candidates:
        # Plan the cut on this candidate
        plan = plan_cut(dims, piece, qty, allow_rotation=settings.allow_rotation, kerf=kerf)
        if plan.produced_qty <= 0:
            continue
        dims_area = area(*dims)
        # If no plan chosen yet, choose the first viable candidate
        if best_plan is None:
            best_id = cid
            best_plan = plan
            best_area = dims_area
            continue
        # Prefer the plan that produces more pieces
        if plan.produced_qty > best_plan.produced_qty:
            best_id = cid
            best_plan = plan
            best_area = dims_area
            continue
        # If equal pieces, prefer the one with more chutes kept
        if plan.produced_qty == best_plan.produced_qty:
            if len(plan.children) > len(best_plan.children):
                best_id = cid
                best_plan = plan
                best_area = dims_area
                continue
            # If equal chutes, prefer the candidate with smaller area
            if len(plan.children) == len(best_plan.children):
                if best_area is None or dims_area < best_area:
                    best_id = cid
                    best_plan = plan
                    best_area = dims_area
                    continue
    if best_plan is None or best_id is None:
        # Cannot produce any pieces with any candidate; return first candidate with zero plan
        try:
            cid, dims = next(iter(candidates))
        except StopIteration:
            raise ValueError("No candidates provided for selection.")
        return cid, plan_cut(dims, piece, qty, allow_rotation=settings.allow_rotation, kerf=kerf)
    return best_id, best_plan


__all__ = ["pick_best_candidate"]