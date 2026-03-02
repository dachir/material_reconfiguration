"""
Geometry helper functions for the material reconfiguration engine.

These helpers operate on plain numbers (millimetres) and do not
depend on any ERPNext models. The goal is to encapsulate the
calculations used by the cutting algorithm so they can be unit tested
independently of the wider system.
"""

from typing import Iterable, List, Tuple


def norm_dims(length: float, width: float) -> Tuple[float, float]:
    """Return a pair (L, W) with L >= W.

    Many functions assume the first value is the larger dimension.

    :param length: First dimension.
    :param width: Second dimension.
    :return: Tuple (max(length, width), min(length, width)).
    """
    length = float(length)
    width = float(width)
    return (max(length, width), min(length, width))


def area(length: float, width: float) -> float:
    """Return the area of a rectangle.

    :param length: Length of the rectangle.
    :param width: Width of the rectangle.
    :return: Area = length * width.
    """
    return float(length) * float(width)


def can_fit(
    L: float,
    W: float,
    a: float,
    b: float,
    *,
    allow_rotation: bool = True,
) -> bool:
    """Determine if a piece (a, b) can fit inside a rectangle (L, W).

    If rotation is allowed then the piece may be swapped. Both
    dimensions must be positive.

    :param L: Length of the host rectangle.
    :param W: Width of the host rectangle.
    :param a: Length of the piece.
    :param b: Width of the piece.
    :param allow_rotation: Whether to consider rotation of the piece.
    :return: True if the piece can fit, False otherwise.
    """
    if a <= 0 or b <= 0:
        return False
    fits_no_rotate = L >= a and W >= b
    fits_rotate = L >= b and W >= a if allow_rotation else False
    return fits_no_rotate or fits_rotate


def strip_capacity(
    L: float, W: float, x: float, y: float, kerf_mm: float
) -> Tuple[int, int]:
    """Compute how many pieces of size (x,y) fit on (L,W) via strip cutting.

    Uses the formula n = floor((L + k) / (x + k)) and m = floor((W + k) / (y + k)),
    which assumes that between each adjacent piece a kerf of width k is removed.

    :param L: Length of the rectangle.
    :param W: Width of the rectangle.
    :param x: Length of the piece.
    :param y: Width of the piece.
    :param kerf_mm: Thickness of each cut in millimetres.
    :return: Tuple (n, m) giving the number of pieces per dimension.
    """
    L = float(L)
    W = float(W)
    x = float(x)
    y = float(y)
    k = float(kerf_mm)
    # Avoid division by zero
    if x + k <= 0 or y + k <= 0:
        return (0, 0)
    n = int((L + k) // (x + k))
    m = int((W + k) // (y + k))
    return n, m


def used_dims(n: int, m: int, x: float, y: float, kerf_mm: float) -> Tuple[float, float]:
    """Calculate the total length and width consumed by an n×m grid of pieces.

    If n or m is zero the used dimension is zero. Kerf is applied between
    adjacent pieces, so an n-piece line consumes n*x + (n-1)*kerf.

    :param n: Number of pieces along the length.
    :param m: Number of pieces along the width.
    :param x: Length of a single piece.
    :param y: Width of a single piece.
    :param kerf_mm: Thickness of the cut.
    :return: Tuple (used_length, used_width).
    """
    x = float(x)
    y = float(y)
    k = float(kerf_mm)
    if n <= 0 or m <= 0:
        return (0.0, 0.0)
    used_L = n * x + (n - 1) * k
    used_W = m * y + (m - 1) * k
    return used_L, used_W


def band_rest(
    L: float, W: float, used_L: float, used_W: float
) -> Tuple[Tuple[float, float], Tuple[float, float]]:
    """Compute the two potential residual rectangles after removing a grid.

    Assumes the grid occupies a corner of the rectangle with dimensions
    (used_L, used_W). The right-hand residual has dimensions (L - used_L, W)
    and the bottom residual has dimensions (used_L, W - used_W). Values are
    clamped to zero if negative.

    :param L: Length of the parent rectangle.
    :param W: Width of the parent rectangle.
    :param used_L: Length consumed by the grid.
    :param used_W: Width consumed by the grid.
    :return: Tuple of two residual rectangles: ((r1_L, r1_W), (r2_L, r2_W)).
    """
    r1_L = max(L - used_L, 0.0)
    r1_W = max(W, 0.0)
    r2_L = max(used_L, 0.0)
    r2_W = max(W - used_W, 0.0)
    return (r1_L, r1_W), (r2_L, r2_W)


def filter_keepable_rects(
    rects: Iterable[Tuple[float, float]], min_keep_mm: float
) -> List[Tuple[float, float]]:
    """Filter rectangles by minimum dimension.

    Given an iterable of (L,W) tuples, return a new list containing only
    those rectangles where both dimensions are at least min_keep_mm.

    :param rects: Iterable of (length,width) tuples.
    :param min_keep_mm: Minimum allowed dimension for a rectangle to be kept.
    :return: List of keepable rectangles.
    """
    min_dim = float(min_keep_mm)
    result: List[Tuple[float, float]] = []
    for L, W in rects:
        if L >= min_dim and W >= min_dim:
            result.append((float(L), float(W)))
    return result


__all__ = [
    "norm_dims",
    "area",
    "can_fit",
    "strip_capacity",
    "used_dims",
    "band_rest",
    "filter_keepable_rects",
]