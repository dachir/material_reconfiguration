"""
Configuration loading for the material reconfiguration engine.

All tunable parameters used by the cutting algorithm live in the
Reconfiguration Settings doctype in ERPNext. When Frappe is available
we read from that single doctype. When running outside of ERPNext
the get_reco_settings function returns a simple fallback object with
reasonable defaults so that tests can run without Frappe.
"""

from dataclasses import dataclass
from typing import Any

try:
    import frappe  # type: ignore
except Exception:
    frappe = None  # noqa: N816 (lowercase to indicate optional import)


@dataclass
class DefaultRecoSettings:
    """Fallback settings when Frappe isn't available."""

    kerf_mm: float = 3.0
    """Thickness of the cut in millimetres."""

    min_keep_dimension_mm: float = 500.0
    """Minimum dimension of a rectangle to be considered worth keeping."""

    allow_rotation: bool = True
    """Whether pieces may be rotated when fitting into a rectangle."""

    split_policy: str = "Always Split"
    """Policy for splitting a residual L into separate rectangles.

    Possible values:
        - 'Always Split': always produce separate chutes when two rectangles are valid.
        - 'Never Split': never split a residual L.
        - 'Split If Both Valid': split only when both candidate chutes are above the minimum dimension threshold.
    """


def get_reco_settings() -> Any:
    """Return the current reconfiguration settings.

    At runtime under ERPNext this will fetch the single instance of
    the `Reconfiguration Settings` doctype. If Frappe isn't available
    or the document cannot be loaded, this function will return an
    instance of :class:`DefaultRecoSettings` with sensible defaults.

    :return: Settings object with attributes such as kerf_mm,
             min_keep_dimension_mm, allow_rotation and split_policy.
    """
    if frappe is not None:
        try:
            return frappe.get_single("Reconfiguration Settings")
        except Exception:
            # Frappe is present but the doctype isn't, fall back
            return DefaultRecoSettings()
    # Frappe isn't available at all
    return DefaultRecoSettings()


__all__ = ["get_reco_settings", "DefaultRecoSettings"]