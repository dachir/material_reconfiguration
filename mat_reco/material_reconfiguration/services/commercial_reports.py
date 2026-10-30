"""Shared filters and metadata migration for the existing commercial reports."""
import json

import frappe
from frappe.model.rename_doc import rename_doc
from frappe.utils import getdate

REPORTS = {
    'orders': ('Suivi commandes B', 'Suivi commandes', 'suivi_commandes', 'ug-orders-b'),
    'accounts': ('Situation des comptes clients B', 'Situation des comptes clients',
                 'situation_des_comptes_clients', 'ug-b-balances'),
}


def report_access():
    from .special_b import access
    access()


def normalise(filters=None):
    values = frappe.parse_json(filters) if isinstance(filters, str) else filters or {}
    if not isinstance(values, dict):
        frappe.throw('Filtres de rapport invalides.')
    result = frappe._dict(values)
    kind = str(result.get('order_type') or 'All').strip()
    if kind in ('all', 'A + B', 'Les deux'):
        kind = 'All'
    if kind not in ('A', 'B', 'All'):
        frappe.throw('Choisir le type de commande A, B ou les deux.')
    result.order_type = kind
    for field in ('from_date', 'to_date'):
        if result.get(field):
            try:
                result[field] = str(getdate(result[field]))
            except (ValueError, TypeError, OverflowError):
                frappe.throw('Date de filtre invalide.')
    if result.from_date and result.to_date and result.from_date > result.to_date:
        frappe.throw('La date de début doit précéder la date de fin.')
    if result.sales_order:
        order = frappe.get_doc('Sales Order', result.sales_order)
        order.check_permission('read')
        if kind != 'All' and (order.get('custom_ug_order_type') or 'A') != kind:
            frappe.throw('La commande sélectionnée ne correspond pas au type demandé.')
        for field in ('company', 'customer', 'currency'):
            if result.get(field) and result[field] != order.get(field):
                frappe.throw('La commande sélectionnée ne correspond pas aux filtres du rapport.')
    return result


def selected_types(filters):
    kind = filters.get('order_type') or 'All'
    return ('A', 'B') if kind in ('All', 'all', 'A + B', 'Les deux') else (kind,)


def _rename_content(value, old, new):
    if isinstance(value, str):
        return new if value == old else value
    if isinstance(value, list):
        return [_rename_content(item, old, new) for item in value]
    if isinstance(value, dict):
        return {key: _rename_content(item, old, new) for key, item in value.items()}
    return value


def install_report(key):
    """Rename rather than duplicate the reports; preserve native linked metadata."""
    old, new, module, shortcut_id = REPORTS[key]
    # During migrate the new JSON may already have been synced. Merging updates
    # Report links (prepared reports, shortcuts, custom roles) before removing old.
    if frappe.db.exists('Report', old):
        rename_doc('Report', old, new, force=True,
            merge=bool(frappe.db.exists('Report', new)), ignore_permissions=True,
            show_alert=False, rebuild_search=False)
    # Custom Report.reference_report is Data rather than Link in Frappe v15.
    frappe.db.set_value('Report', {'reference_report': old}, 'reference_report', new, update_modified=False)
    frappe.reload_doc('material_reconfiguration', 'report', module)
    report = frappe.get_doc('Report', new)
    from .commercial_cockpit_setup import readable_roles
    roles = sorted(set(readable_roles()) | {'UG COMMANDES B'})
    if sorted(row.role for row in report.roles) != roles:
        report.set('roles', [{'role': role} for role in roles])
        report.flags.do_not_update_json = True
        report.save(ignore_permissions=True)
    if frappe.db.exists('Workspace', 'Univers Glass'):
        workspace = frappe.get_doc('Workspace', 'Univers Glass')
        changed = False
        shortcuts = []
        found = False
        for row in workspace.shortcuts:
            if row.type == 'Report' and row.link_to in (old, new):
                if found:
                    changed = True
                    continue
                found = True
                if row.link_to != new or row.label != new:
                    row.link_to = new
                    row.label = new
                    changed = True
            shortcuts.append(row)
        if len(shortcuts) != len(workspace.shortcuts):
            workspace.set('shortcuts', shortcuts)
        if not found:
            workspace.append('shortcuts', dict(label=new, type='Report', link_to=new, color='Orange'))
            changed = True
        content = json.loads(workspace.content or '[]')
        renamed = _rename_content(content, old, new)
        seen = False
        unique = []
        for row in renamed:
            if row.get('type') == 'shortcut' and row.get('data', {}).get('shortcut_name') == new:
                if seen:
                    continue
                seen = True
            unique.append(row)
        renamed = unique
        if not any(row.get('type') == 'shortcut' and row.get('data', {}).get('shortcut_name') == new for row in renamed):
            renamed.append(dict(id=shortcut_id, type='shortcut', data=dict(shortcut_name=new, col=4)))
        if renamed != content:
            workspace.content = json.dumps(renamed, ensure_ascii=False)
            changed = True
        if changed:
            workspace.save(ignore_permissions=True)
    frappe.clear_cache(doctype='Report')
