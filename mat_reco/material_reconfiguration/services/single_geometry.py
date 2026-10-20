"""Geometry shared by MCP Single leftovers, Serial Nos and cutting services.

A Single is one physical sheet with a rectangular cutout at the canonical
upper-left corner (x=0, y=0).  It is never two separate stock quantities.
"""

from __future__ import annotations


EPSILON = 0.001  # dimensions and areas are stored in millimetres / mm²


def normalize_single_dimensions(length, width, removed_length=0, removed_width=0):
    """Rotate exterior dimensions AND the cutout together, if required."""
    length, width = float(length or 0), float(width or 0)
    removed_length, removed_width = float(removed_length or 0), float(removed_width or 0)
    if width > length:
        return width, length, removed_width, removed_length
    return length, width, removed_length, removed_width


def single_area(length, width, removed_length=0, removed_width=0):
    """Actual area; ordinary rectangular stock is unchanged when cutout=0."""
    length, width = float(length or 0), float(width or 0)
    rl, rw = float(removed_length or 0), float(removed_width or 0)
    if length <= 0 or width <= 0:
        raise ValueError("Sheet dimensions must be greater than zero.")
    if rl < 0 or rw < 0 or (rl == 0) != (rw == 0):
        raise ValueError("Removed length and width must both be zero or both be positive.")
    if rl and (rl >= length or rw >= width):
        raise ValueError("The removed corner must be smaller than the sheet in both dimensions.")
    return length * width - rl * rw


def _overlap(a, b):
    return (
        max(a["x"], b["x"]) < min(a["x"] + a["length_mm"], b["x"] + b["length_mm"]) - EPSILON
        and max(a["y"], b["y"]) < min(a["y"] + a["width_mm"], b["y"] + b["width_mm"]) - EPSILON
    )


def single_from_rectangles(children):
    """Derive a canonical L from two adjacent, non-overlapping free regions.

    Coordinates are sheet-absolute.  The missing rectangle must be in the
    upper-left corner of the group's bounding box; we never silently rotate
    a real sheet or invent a missing region in another corner.
    """
    # Very small strips are currently classified as 'waste' by MCP even
    # though they are still physically attached to the other leftover.
    # Reclaiming such a strip must remain possible via Single.
    if len(children) != 2 or any(str(c.get("node_type") or "").strip() not in ("leftover", "waste") for c in children):
        raise ValueError("Single requires exactly two free rectangular zones.")
    if not any(str(c.get("node_type") or "").strip() == "leftover" for c in children):
        raise ValueError("Single requires at least one leftover zone.")
    if str(children[0].get("id") or children[0].get("piece_uid") or "") == str(children[1].get("id") or children[1].get("piece_uid") or ""):
        raise ValueError("Single requires two different leftovers.")

    rects = []
    for c in children:
        rect = {k: float(c.get(k) or 0) for k in ("x", "y", "length_mm", "width_mm")}
        if rect["length_mm"] <= 0 or rect["width_mm"] <= 0:
            raise ValueError("Single does not accept zero-area leftovers.")
        rects.append(rect)
    a, b = rects
    if _overlap(a, b):
        raise ValueError("Single leftovers must not overlap.")
    x = min(a["x"], b["x"])
    y = min(a["y"], b["y"])
    end_x = max(a["x"] + a["length_mm"], b["x"] + b["length_mm"])
    end_y = max(a["y"] + a["width_mm"], b["y"] + b["width_mm"])
    length, width = end_x - x, end_y - y
    area = sum(r["length_mm"] * r["width_mm"] for r in rects)
    missing_area = length * width - area
    if missing_area <= EPSILON:
        raise ValueError("These rectangles form a full rectangle: use Merge, not Single.")

    xs = sorted({x, end_x, *[r["x"] for r in rects], *[r["x"] + r["length_mm"] for r in rects]})
    ys = sorted({y, end_y, *[r["y"] for r in rects], *[r["y"] + r["width_mm"] for r in rects]})
    for hx in xs[1:-1]:
        for hy in ys[1:-1]:
            removed_length, removed_width = hx - x, hy - y
            hole = {"x": x, "y": y, "length_mm": removed_length, "width_mm": removed_width}
            if _overlap(a, hole) or _overlap(b, hole):
                continue
            if abs(removed_length * removed_width - missing_area) > EPSILON:
                continue
            return {
                "x": x, "y": y, "length_mm": length, "width_mm": width,
                "removed_length_mm": removed_length, "removed_width_mm": removed_width,
                "area_mm2": area,
            }
    raise ValueError("The selected leftovers cannot form a Single with one missing upper-left corner.")


def available_regions(length, width, removed_length=0, removed_width=0):
    """Two disjoint virtual bins; coordinates belong to the same physical serial."""
    length, width = float(length), float(width)
    rl, rw = float(removed_length or 0), float(removed_width or 0)
    single_area(length, width, rl, rw)  # validates geometry
    if not rl:
        return [{"x": 0.0, "y": 0.0, "length_mm": length, "width_mm": width}]
    return [
        {"x": rl, "y": 0.0, "length_mm": length - rl, "width_mm": width},
        {"x": 0.0, "y": rw, "length_mm": rl, "width_mm": width - rw},
    ]


def stock_area_or_zero(length, width, removed_length=0, removed_width=0):
    """Legacy non-MCP outputs may have unknown dimensions (zero)."""
    length, width = float(length or 0), float(width or 0)
    rl, rw = float(removed_length or 0), float(removed_width or 0)
    if length <= 0 or width <= 0:
        if rl or rw:
            raise ValueError("Single cutout requires valid exterior dimensions.")
        return max(length, 0.0) * max(width, 0.0)
    return single_area(length, width, rl, rw)
