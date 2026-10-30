"""Compatibility for existing Python callers; the visible report was renamed."""
from mat_reco.material_reconfiguration.services import special_b as b
from mat_reco.material_reconfiguration.report.situation_des_comptes_clients.situation_des_comptes_clients import execute as _execute


def execute(filters=None):
    values = dict(filters or {})
    values.setdefault('order_type', 'B')
    return _execute(values)
