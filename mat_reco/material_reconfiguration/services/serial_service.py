"""
Bridge module for the serial service.

This file re-exports the `get_available_serials` function from the
internal serial service (`mat_reco.material_reconfiguration.services.serial_service`) to
the public-facing namespace `mat_reco.material_reconfiguration.services.serial_service`.
"""

from __future__ import annotations

from mat_reco.material_reconfiguration.services.serial_service_internal import (
    get_available_serials,
    generate_chute_serials,
)

__all__ = ["get_available_serials", "generate_chute_serials"]
