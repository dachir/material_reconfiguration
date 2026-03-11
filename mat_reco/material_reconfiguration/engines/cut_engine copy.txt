"""
Cutting algorithm for material reconfiguration.

This module contains a high-level function that, given a source
rectangle and a demand for a number of identically sized pieces,
returns a plan describing how many pieces can be produced and
what chutes remain. The function delegates geometry calculations to
helpers in :mod:`mat_reco.material_reconfiguration.utils.dimensions` and consumes settings from
the reconfiguration settings document.

The implementation here is intentionally pure: it takes simple types
as input and produces plain dictionaries as output. This makes the
core logic easy to unit test and to reuse in different contexts
without pulling in Frappe.
"""

from dataclasses import dataclass
from typing import List, Tuple, Optional

from mat_reco.material_reconfiguration.utils.dimensions import (
    can_fit,
    strip_capacity,
    used_dims,
    band_rest,
    filter_keepable_rects,
    norm_dims,
)
# Settings for the cutting engine are retrieved from a module under
# `mat_reco.material_reconfiguration.utils` rather than the global utils
# to make the path explicit and configurable per application.
from mat_reco.material_reconfiguration.utils.settings import get_reco_settings


@dataclass
class CutPlan:
    """Represents a plan for cutting a single rectangle."""

    produced_qty: int
    """Number of pieces produced."""

    orientation: Tuple[float, float]
    """Orientation of the piece used for this plan (x,y)."""

    grid: Tuple[int, int]
    """Number of pieces along (n,m) directions."""

    used_dims: Tuple[float, float]
    """Dimensions consumed by the produced grid (used_L, used_W)."""

    children: List[Tuple[float, float]]
    """List of chutes to be kept (dimensions)."""

    waste: List[Tuple[float, float]]
    """List of waste pieces discarded (dimensions)."""


def plan_cut(
    source: Tuple[float, float],
    piece: Tuple[float, float],
    qty: int,
    allow_rotation: bool = True,
    kerf: float | None = None,
) -> CutPlan:
    """Plan how to cut a rectangle to produce as many pieces as possible.

    Given a source rectangle (L,W) and a demanded piece (a,b), this
    function determines the optimal orientation and grid size to cut
    up to ``qty`` pieces. It then calculates the dimensions of the
    resulting chutes after applying the minimum dimension filter from
    the current reconfiguration settings. The function does not
    recurse or chain cuts; it only plans a single cut operation.

    :param source: Dimensions of the source rectangle (L,W).
    :param piece: Dimensions of the demanded piece (a,b).
    :param qty: Requested quantity of pieces.
    :param allow_rotation: Whether the piece may be rotated.
    :return: A :class:`CutPlan` describing the cut.
    """
    settings = get_reco_settings()
    L, W = norm_dims(*source)
    a, b = piece

    # Try both orientations and pick the one with the highest capacity
    best_orientation: Optional[Tuple[float, float]] = None
    best_grid: Tuple[int, int] = (0, 0)
    best_production = 0
    best_chutes: List[Tuple[float, float]] = []
    best_waste: List[Tuple[float, float]] = []
    # Define candidate orientations
    orientations = [(a, b)]
    if allow_rotation:
        orientations.append((b, a))

    for x, y in orientations:
        # Skip impossible orientations
        if not can_fit(L, W, x, y, allow_rotation=False):
            continue
        n, m = strip_capacity(L, W, x, y, kerf or settings.kerf_mm)
        if n <= 0 or m <= 0:
            continue
        total_capacity = n * m
        produced = min(qty, total_capacity)
        # Compute how much of the rectangle will be used by the produced grid.
        used_L, used_W = used_dims(n, m, x, y, kerf or settings.kerf_mm)
        # Compute potential residual rectangles
        (r1_L, r1_W), (r2_L, r2_W) = band_rest(L, W, used_L, used_W)
        # ------------------------------------------------------------------
        # Adjust residual dimensions for kerf at the outer boundary.
        #
        # When cutting a grid of n columns and m rows from the top-left
        # corner of a sheet, we make a vertical cut along the right edge
        # of the grid and a horizontal cut along the bottom edge of the
        # grid.  Each of these boundary cuts consumes one kerf.  The
        # default ``band_rest`` computation subtracts only the consumed
        # dimensions from the grid (i.e. ``used_dims`` includes only
        # interior kerfs), so the residual rectangles are too large by
        # one kerf along the respective dimension.  Here we deduct the
        # kerf from the appropriate residual when there is at least one
        # piece along that dimension.
        r1_L_adj, r1_W_adj = r1_L, r1_W
        r2_L_adj, r2_W_adj = r2_L, r2_W
        # If at least one column (n > 0), subtract kerf from the band on
        # the right side of the grid (r1_L).  This accounts for the
        # boundary cut separating the grid from the remainder.
        if n > 0:
            r1_L_adj = max(r1_L - settings.kerf_mm, 0.0)
        # If at least one row (m > 0), subtract kerf from the band below
        # the grid (r2_W).  This accounts for the horizontal boundary cut.
        if m > 0:
            r2_W_adj = max(r2_W - settings.kerf_mm, 0.0)
        # Determine which residuals are worth keeping based on the
        # adjusted dimensions
        adjusted_rects = [(r1_L_adj, r1_W_adj), (r2_L_adj, r2_W_adj)]
        keep = filter_keepable_rects(adjusted_rects, settings.min_keep_dimension_mm)
        waste = []
        # Mark waste rectangles. Use the adjusted dimensions for
        # comparison but record the adjusted sizes in waste for clarity.
        if (r1_L_adj, r1_W_adj) not in keep:
            waste.append((r1_L_adj, r1_W_adj))
        if (r2_L_adj, r2_W_adj) not in keep:
            waste.append((r2_L_adj, r2_W_adj))
        # Prefer the plan that produces the most pieces; tie-break by keeping more useful chutes
        if produced > best_production or (
            produced == best_production and len(keep) > len(best_chutes)
        ):
            best_orientation = (x, y)
            best_grid = (n, m)
            best_production = produced
            best_chutes = keep
            best_waste = waste

    if best_orientation is None:
        # Cannot cut anything; return a plan with zero produced pieces
        return CutPlan(
            produced_qty=0,
            orientation=(0.0, 0.0),
            grid=(0, 0),
            used_dims=(0.0, 0.0),
            children=[],
            waste=[source],
        )

    # Recompute used dims for chosen orientation
    n, m = best_grid
    x, y = best_orientation
    used_L, used_W = used_dims(n, m, x, y, settings.kerf_mm)
    return CutPlan(
        produced_qty=best_production,
        orientation=best_orientation,
        grid=best_grid,
        used_dims=(used_L, used_W),
        children=best_chutes,
        waste=best_waste,
    )


__all__ = ["CutPlan", "plan_cut"]