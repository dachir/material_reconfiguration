"""Compatibility import for integrations using the former B-only report path."""


def execute(filters=None):
    from mat_reco.material_reconfiguration.report.suivi_commandes.suivi_commandes import execute as current
    values = dict(filters or {})
    values.setdefault('order_type', 'B')
    return current(values)
