"""Permission-scoped, read-only physical glass inventory.

Serial No.warehouse/status are maintained by ERPNext's submitted stock ledger
(SerialBatchBundle); drafts are never used as inventory inputs.
"""
from __future__ import annotations

import math
from collections import Counter

import frappe
from frappe.utils import cint, now_datetime

from mat_reco.material_reconfiguration.services.single_geometry import single_area


def _read_all(doctype, fields, filters=None):
    """Use permission-aware queries, including User Permissions, on every page."""
    result = []
    while True:
        page = frappe.get_list(doctype, fields=fields, filters=filters or {},
                               order_by="name asc", limit_start=len(result), limit_page_length=1000)
        result.extend(page)
        if len(page) < 1000:
            return result


def _check():
    for dt in ("Item", "Serial No", "Warehouse", "Stock Ledger Entry"):
        if not frappe.has_permission(dt, "read"):
            frappe.throw(f"Droit de lecture requis sur {dt}.", frappe.PermissionError)


def primary_for(code, items):
    seen, primary = set(), None
    while code:
        if code in seen or code not in items:
            return None
        seen.add(code)
        item = items[code]
        if item.get("custom_item_types") == "PRIMAIRE":
            primary = code
        code = item.get("custom_parent_item")
    return primary


def physical_rows(serials, items, warehouses, search=""):
    rows, issues, seen = [], Counter(), set()
    search = (search or "").strip().casefold()
    for sn in serials:
        if sn['name'] in seen or sn.get('warehouse') not in warehouses:
            continue
        seen.add(sn['name'])
        if sn.get('status') != 'Active' or sn.get('custom_material_status') == 'Consumed':
            continue
        code = sn['item_code']
        item = items.get(code)
        if not item or item.get('custom_item_types') not in ('PRIMAIRE', 'DECOUPE'):
            continue
        root = primary_for(code, items)
        if not root:
            issues['unresolved_lineage'] += 1
            continue
        item = items[code]
        kind = item.get('custom_item_types')
        if kind not in ('PRIMAIRE', 'DECOUPE'):
            continue
        haystack = ' '.join((code, item.get('item_name') or '', root,
                             items[root].get('item_name') or '', sn['name'])).casefold()
        if search and search not in haystack:
            continue
        status = sn.get('custom_material_status')
        # A cut Item is still a cut piece even when its default status is Full.
        classification = 'chutes' if kind == 'DECOUPE' or status == 'Partial' else 'volumes' if status == 'Full' else None
        if not classification:
            issues['unknown_classification'] += 1
            continue
        dims = [float(sn.get('custom_dimension_' + d + '_mm') or 0) for d in ('length','width','thickness')]
        area, error = None, None
        try:
            values = dims[:2] + [float(sn.get('custom_removed_length_mm') or 0), float(sn.get('custom_removed_width_mm') or 0)]
            if not all(math.isfinite(v) for v in values):
                raise ValueError('Non-finite geometry')
            area = single_area(*values) / 1_000_000
        except (ValueError, TypeError):
            error = 'Dimensions ou géométrie invalides'
            issues['invalid_geometry'] += 1
        rows.append(dict(serial_no=sn['name'], item_code=code, primary_item=root,
                         length_mm=dims[0], width_mm=dims[1], thickness_mm=dims[2],
                         area_m2=area, geometry_error=error, warehouse=sn['warehouse'], classification=classification,
                         removed_length_mm=sn.get('custom_removed_length_mm') or 0,
                         removed_width_mm=sn.get('custom_removed_width_mm') or 0))
    return sorted(rows, key=lambda r: r['serial_no']), dict(issues)


def _inventory(search=None, warehouse=None):
    _check()
    warehouses = {w['name'] for w in _read_all('Warehouse', ['name'], {'is_group': 0})}
    if warehouse and warehouse not in warehouses:
        frappe.throw('Warehouse non autorisé.', frappe.PermissionError)
    if warehouse:
        warehouses = {warehouse}
    items = {i['name']: i for i in _read_all('Item', ['name','item_name','custom_item_types','custom_parent_item'])}
    fields = ['name','item_code','warehouse','status','custom_material_status',
              'custom_dimension_length_mm','custom_dimension_width_mm','custom_dimension_thickness_mm',
              'custom_removed_length_mm','custom_removed_width_mm']
    if not warehouses:
        return [], {}, items
    serials = _read_all('Serial No', fields, {'warehouse': ['in', sorted(warehouses)], 'status': 'Active'})
    rows, issues = physical_rows(serials, items, warehouses, search)
    return rows, issues, items


def overview(rows, items):
    groups = {}
    for row in rows:
        code = row['primary_item']
        g = groups.setdefault(code, dict(item_code=code, item_name=items[code].get('item_name') or code,
                                        volumes=0, chutes=0, total=0, surface_m2=0, warehouses=set()))
        g[row['classification']] += 1
        g['total'] += 1
        g['surface_m2'] += row['area_m2'] or 0
        g['warehouses'].add(row['warehouse'])
    for g in groups.values():
        wh = g.pop('warehouses')
        g['warehouse'] = next(iter(wh)) if len(wh) == 1 else '—'
    groups = sorted(groups.values(), key=lambda g: g['item_code'])
    return dict(groups=groups, volumes=sum(g['volumes'] for g in groups),
                chutes=sum(g['chutes'] for g in groups), total=len(rows),
                surface_m2=sum(g['surface_m2'] for g in groups))


@frappe.whitelist()
def get_stock_overview(search=None, warehouse=None):
    rows, issues, items = _inventory(search, warehouse)
    return dict(**overview(rows, items), diagnostics=issues, as_of=str(now_datetime()),
                surface_basis='physical', reserved_m2=None, available_m2=None)


@frappe.whitelist()
def get_stock_serials(item_code, warehouse=None, search=None, cursor=None, page_size=100):
    rows, _, _ = _inventory(search, warehouse)
    # Whole primary sheets are summarized by the family; only cuts need serial detail.
    rows = [r for r in rows if r['primary_item'] == item_code and r['classification'] == 'chutes']
    total = len(rows)
    if cursor:
        rows = [r for r in rows if r['serial_no'] > cursor]
    size = max(1, min(cint(page_size) or 100, 200))
    page = rows[:size]
    return dict(rows=page, total=total, next_cursor=page[-1]['serial_no'] if len(rows) > size else None)


@frappe.whitelist()
def get_warehouses():
    _check()
    return [w['name'] for w in _read_all('Warehouse', ['name'], {'is_group': 0})]


def notify_stock_change(doc, method=None):
    """Invalidate only after a ledger transaction has committed; disclose no data."""
    frappe.publish_realtime("glass_stock_updated", {}, after_commit=True)
