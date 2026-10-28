"""Reserve final manufactured glass, release it atomically for B stock issues."""
from contextlib import contextmanager

import frappe
from frappe.utils import flt

from .ug_warehouse import COMPANY

SRE = 'Stock Reservation Entry'
SOURCE = 'custom_ug_production_entry'


@contextmanager
def exact_serials():
    previous = frappe.flags.get('ug_exact_production_reservation')
    frappe.flags.ug_exact_production_reservation = True
    try:
        yield
    finally:
        frappe.flags.ug_exact_production_reservation = previous


def active_reservations(serials):
    if not serials:
        return []
    names = frappe.db.sql('''SELECT DISTINCT r.name FROM `tabStock Reservation Entry` r
        JOIN `tabSerial and Batch Entry` e ON e.parent=r.name
        WHERE r.docstatus=1 AND r.reserved_qty>r.delivered_qty
        AND e.serial_no IN %s FOR UPDATE''', (tuple(sorted(serials)),), as_dict=True)
    return [frappe.get_doc(SRE, row.name, for_update=True) for row in names]


def reserve_order(order, serials=None, production_entry=None):
    """Called only after an authorized production/stock cancellation, no commits."""
    if order.company != COMPANY or order.docstatus != 1:
        return []
    from .workshop_service import _receipts, _output_matches_line
    from erpnext.stock.doctype.stock_reservation_entry.stock_reservation_entry import (
        get_available_qty_to_reserve, get_sre_reserved_qty_for_voucher_detail_no,
    )
    frappe.db.get_value('Company', order.company, 'name', for_update=True)
    _, _, _, owners = _receipts([order], lock=True)
    selected = set(serials) if serials is not None else None
    from .order_b_stock import issued_quantities
    issued = issued_quantities(order) if order.get('custom_ug_order_type') == 'B' else {}
    result = []
    for row in order.items:
        item = frappe.get_cached_doc('Item', row.item_code)
        if item.get('custom_item_types') not in ('OUVRAGE', 'DECOUPE') or not item.has_serial_no:
            continue
        candidates = [name for name, owner in owners.items() if owner == row.name and not name.startswith('batch:')
                      and (selected is None or name in selected)]
        pending = flt(row.stock_qty or row.qty * (row.conversion_factor or 1)) - max(
            flt(row.delivered_qty) * (flt(row.conversion_factor) or 1), issued.get(row.name, 0))
        for name in sorted(candidates):
            sn = frappe.get_doc('Serial No', name, for_update=True)
            if sn.item_code != row.item_code or sn.status != 'Active' or not sn.warehouse or not _output_matches_line(sn, row):
                continue
            if active_reservations({name}):
                continue
            if pending - get_sre_reserved_qty_for_voucher_detail_no('Sales Order', order.name, row.name) < 1:
                break
            if not frappe.db.get_single_value('Stock Settings', 'enable_stock_reservation'):
                frappe.throw('Activer les réservations de stock ERPNext avant la fabrication Univers Glass.')
            available = get_available_qty_to_reserve(row.item_code, sn.warehouse)
            if available < 1:
                continue  # A reservation by quantity may already withhold this stock.
            source = production_entry or frappe.db.sql('''SELECT r.custom_ug_production_entry
                FROM `tabStock Reservation Entry` r JOIN `tabSerial and Batch Entry` e ON e.parent=r.name
                WHERE r.voucher_no=%s AND r.voucher_detail_no=%s AND e.serial_no=%s
                ORDER BY r.creation DESC LIMIT 1''', (order.name, row.name, name))
            if isinstance(source, (list, tuple)):
                source = source[0][0] if source else None
            reservation = frappe.get_doc(dict(doctype=SRE, company=order.company, item_code=row.item_code,
                warehouse=sn.warehouse, voucher_type='Sales Order', voucher_no=order.name,
                voucher_detail_no=row.name, voucher_qty=flt(row.stock_qty or row.qty * (row.conversion_factor or 1)),
                stock_uom=item.stock_uom, has_serial_no=1, has_batch_no=item.has_batch_no,
                available_qty=available, reserved_qty=1, reservation_based_on='Serial and Batch',
                custom_ug_production_entry=source,
                sb_entries=[dict(serial_no=name, batch_no=sn.get('batch_no'), qty=1, warehouse=sn.warehouse)]))
            with exact_serials():
                reservation.insert(ignore_permissions=True)
                reservation.flags.ignore_permissions = True
                reservation.submit()
            result.append(reservation.name)
    return result


def release_for_issue(order, selections):
    """Only reservations of the selected SO line can be reduced/released."""
    if order.company != COMPANY:
        return
    for selection in selections:
        chosen = set(selection.get('serials') or [])
        for reservation in active_reservations(chosen):
            if reservation.voucher_type != 'Sales Order' or reservation.voucher_no != order.name or reservation.voucher_detail_no != selection['sales_order_item']:
                continue  # Native stock validation will reject another order's reservation.
            removed = [r for r in reservation.sb_entries if r.serial_no in chosen]
            if any(flt(r.delivered_qty) for r in removed) or flt(reservation.delivered_qty):
                frappe.throw('Cette réservation a déjà servi à une livraison ERPNext. Vérifier les documents associés.')
            remaining = [r.as_dict() for r in reservation.sb_entries if r.serial_no not in chosen]
            reservation.flags.ignore_permissions = True
            if not remaining:
                reservation.cancel()
            else:
                reservation.set('sb_entries', remaining)
                reservation.reserved_qty -= sum(flt(r.qty) for r in removed)
                reservation.save()


def before_cancel_production(doc, method=None):
    if doc.get('company') != COMPANY or doc.get('purpose') != 'Repack':
        return
    names = frappe.get_all(SRE, filters={SOURCE: doc.name, 'docstatus': 1}, pluck='name')
    for name in names:
        reservation = frappe.get_doc(SRE, name, for_update=True)
        if flt(reservation.delivered_qty):
            frappe.throw('Annuler les livraisons liées avant la fabrication réservée.')
        reservation.flags.ignore_permissions = True
        reservation.cancel()


def stock_updated(doc, method=None):
    if doc.get('company') != COMPANY:
        return
    produced = doc.docstatus == 1 and doc.get('purpose') == 'Repack'
    restored = doc.docstatus == 2 and bool(doc.get('custom_ug_b_sales_order'))
    if not (produced or restored):
        return
    from .workshop_service import _serials
    serials = {serial for row in doc.items if (row.t_warehouse if produced else row.s_warehouse) for serial in _serials(row)}
    line_ids = {r.get('custom_sales_order_item') for r in doc.items} - {None, ''}
    allocations = frappe.parse_json(doc.get('custom_workshop_allocations_json') or '{}')
    line_ids.update(v.get('sales_order_item') for v in allocations.values() if isinstance(v, dict) and v.get('sales_order_item'))
    orders = set(frappe.get_all('Sales Order Item', filters={'name': ['in', list(line_ids)]}, pluck='parent')) if line_ids else set()
    orders.update({doc.get('custom_sales_order'), doc.get('custom_ug_b_sales_order')} - {None, ''})
    for name in sorted(orders):
        reserve_order(frappe.get_doc('Sales Order', name), serials, doc.name if produced else None)


def fill_delivery(doc):
    if doc.get('adopt_existing_stock') or doc.get('stock_entry'):
        return
    pending = [row for row in doc.items if not (row.serial_no or '').strip()
               or row.serial_no == row.get('auto_serial_no')]
    if not pending:
        return
    from .order_b_stock import get_issue_data
    from .order_b_stock import get_order
    order = get_order(doc.sales_order)
    sources = {r.name: r for r in order.items}
    data = get_issue_data(order.name)
    available = {r['sales_order_item']: r for r in data['rows']}
    pending_names = {id(row) for row in pending}
    used = {n.strip() for r in doc.items if id(r) not in pending_names
            for n in (r.serial_no or '').splitlines() if n.strip()}
    for row in pending:
        source = sources.get(row.sales_order_item)
        info = available.get(row.sales_order_item)
        if not source or not info or not info.get('has_serial_no'):
            continue
        if frappe.get_cached_value('Item', source.item_code, 'custom_item_types') not in ('OUVRAGE', 'DECOUPE'):
            continue
        needed = flt(row.qty) * (flt(source.conversion_factor) or 1)
        if needed <= 0 or not needed.is_integer():
            continue
        candidates = sorted((s for s in info['serials'] if s['warehouse'] == row.warehouse and s['name'] not in used), key=lambda s: s['name'])
        eligible = []
        for serial in candidates:
            reservations = active_reservations({serial['name']})
            if any(r.voucher_no != order.name or r.voucher_detail_no != row.sales_order_item for r in reservations):
                continue
            eligible.append(serial['name'])
        if len(eligible) >= needed:
            selected = eligible[:int(needed)]
            row.serial_no = '\n'.join(selected)
            row.auto_serial_no = row.serial_no
            used.update(selected)
        elif row.serial_no == row.get('auto_serial_no'):
            row.serial_no = ''
            row.auto_serial_no = ''


def install():
    from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
    create_custom_fields({SRE: [dict(fieldname=SOURCE, label='Fabrication Univers Glass', fieldtype='Link',
        options='Stock Entry', read_only=1, no_copy=1, module='Material Reconfiguration')]}, update=True)
    if not frappe.db.exists('Company', COMPANY):
        return
    settings = frappe.get_doc('Stock Settings')
    if not settings.enable_stock_reservation:
        settings.enable_stock_reservation = 1
        settings.save(ignore_permissions=True)
