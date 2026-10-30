"""Modal adapters for the existing special documents; never save or submit here.

The commercial_actions facade owns the request journal, source version, company
lock, savepoint, native workflow and special_a.operation transaction guard.
Controllers remain the authority for rates, taxes, stock, series and accounting.
"""
import math
from datetime import date

import frappe
from frappe.utils import flt, getdate, nowdate, strip_html

from . import special_b as special

DELIVERY = special.DELIVERY
PAYMENT = special.PAYMENT
MAX_ROWS = 500
EPS = special.EPS
DELIVERY_VALUES = {'posting_date', 'warehouse', 'accounting_dimensions'}
PAYMENT_VALUES = {'posting_date', 'amount', 'mode_of_payment', 'reference', 'sales_order'}
ROW_FIELDS = {'id', 'selected', 'qty', 'amount', 'warehouse', 'serial_no', 'serials', 'batch_no'}


def _fields(doctype, names, permission='read', parenttype=None):
    """Check every value exposed/changed here against native field permlevels.

    A get_doc permission check does not apply field-level permissions. Reject
    an incomplete modal instead of exposing a price/series from a hidden field
    or letting Document.save silently reset a protected user modification.
    """
    meta = frappe.get_meta(doctype)
    required = {name for name in names if meta.has_field(name)}
    allowed = set(meta.get_permitted_fieldnames(parenttype=parenttype, permission_type=permission))
    if required - allowed:
        _fail('Autorisation de ' + ('lecture' if permission == 'read' else 'modification') +
            ' des champs du document requise.', permission=True)


def _table(doctype, tablefield, names, permission='read'):
    meta = frappe.get_meta(doctype)
    field = meta.get_field(tablefield)
    if not field or field.fieldtype != 'Table':
        _fail('La structure des lignes du document est indisponible.')
    # Frappe's get_permitted_fieldnames contains value fields, not Tables.
    # Check the Table DocField's level explicitly before its child fields.
    if (field.get('permlevel') or 0) not in meta.get_permlevel_access(permission):
        _fail('Autorisation de ' + ('lecture' if permission == 'read' else 'modification') +
            ' des lignes du document requise.', permission=True)
    _fields(field.options, names, permission, parenttype=doctype)


def _read_context(source, kind, existing, order):
    _fields(source.doctype, ['company', 'customer', 'currency', 'sales_order', 'order_type', 'custom_ug_order_type'])
    target = DELIVERY if kind == 'delivery' else PAYMENT
    _fields(target, ['company', 'customer', 'currency', 'sales_order', 'order_type', 'posting_date'])
    if kind == 'delivery':
        _fields('Item', ['has_serial_no', 'has_batch_no', 'stock_uom', 'custom_item_types', 'is_stock_item'])
        _fields('Sales Order', ['company', 'customer', 'currency', 'set_warehouse', 'custom_ug_order_type'])
        _table('Sales Order', 'items', ['item_code', 'item_name', 'description', 'qty', 'uom', 'net_amount',
            'warehouse', 'conversion_factor', 'custom_parent_row', 'custom_is_service_row',
            'custom_is_accessory_row', 'custom_client_length_mm', 'custom_client_width_mm',
            'custom_client_thickness_mm'])
        _fields(DELIVERY, ['warehouse', 'accounting_dimensions_json'])
        _table(DELIVERY, 'items', ['sales_order_item', 'qty', 'warehouse', 'serial_no', 'auto_serial_no',
            'batch_no', 'rate', 'amount', 'length_mm', 'width_mm', 'thickness_mm'])
    else:
        _fields(PAYMENT, PAYMENT_VALUES)
        _table(PAYMENT, 'allocations', ['bordereau', 'amount'])


def _write_context(kind, existing, values):
    target = DELIVERY if kind == 'delivery' else PAYMENT
    if kind == 'delivery':
        _fields(target, ['posting_date', 'warehouse', 'accounting_dimensions_json'], 'write')
        _table(target, 'items', ['qty', 'warehouse', 'serial_no', 'batch_no'], 'write')
    else:
        # A submitted receipt changes allocations only; all immutable header
        # values sent by the UI are compared with the original, never assigned.
        if not existing or existing.docstatus != 1:
            _fields(target, values, 'write')
        _table(target, 'allocations', ['bordereau', 'amount'], 'write')


def _fail(message, permission=False):
    frappe.throw(message, frappe.PermissionError if permission else frappe.ValidationError)


def _number(value, *, positive=False):
    if isinstance(value, bool):
        _fail('Saisir une quantité ou un montant numérique valide.')
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        _fail('Saisir une quantité ou un montant numérique valide.')
    if not math.isfinite(result) or result < 0 or (positive and result <= 0):
        _fail('La quantité ou le montant doit être fini et positif.')
    return result


def _text(value, limit=140):
    if value is None:
        return ''
    if not isinstance(value, str) or len(value) > limit:
        _fail('Valeur de formulaire invalide.')
    return value.strip()


def _date(value):
    if type(value) is date:  # Existing Date fields loaded by the DB driver.
        return value.isoformat()
    value = _text(value, 30)
    if not value:
        _fail('Saisir une date valide.')
    try:
        return date.fromisoformat(value).isoformat()
    except (ValueError, TypeError, OverflowError):
        _fail('Saisir une date valide.')


def _serials(value):
    if isinstance(value, str):
        value = value.splitlines()
    if not isinstance(value, list) or len(value) > 20000:
        _fail('Liste de numéros de série invalide.')
    result = [_text(row) for row in value if row != '']
    if any(not row for row in result) or len(result) != len(set(result)):
        _fail('Les numéros de série doivent être distincts.')
    return result


def _rows(selections):
    if not isinstance(selections, list) or len(selections) > MAX_ROWS:
        _fail('Sélection de lignes invalide.')
    result = {}
    for row in selections:
        if not isinstance(row, dict) or set(row) - ROW_FIELDS:
            _fail('Les champs de la sélection ne sont pas autorisés.')
        identity = _text(row.get('id'))
        if not identity or identity in result:
            _fail('Une ligne est inconnue ou sélectionnée plusieurs fois.')
        selected = row.get('selected', True)
        if selected not in (True, False, 0, 1):
            _fail('État de sélection invalide.')
        result[identity] = dict(row, selected=bool(selected))
    return result


def _action(source, action):
    if action in ('delivery', 'create_delivery') and source.doctype == 'Sales Order':
        return 'delivery'
    if action in ('payment', 'create_payment') and source.doctype in ('Sales Order', DELIVERY):
        return 'payment'
    if action in ('edit', 'update', 'validate', 'submit') and source.doctype in (DELIVERY, PAYMENT):
        if source.docstatus != 0:
            _fail('Modifier ou valider uniquement un document en brouillon.')
        return 'delivery' if source.doctype == DELIVERY else 'payment'
    if action == 'allocate' and source.doctype == PAYMENT and source.docstatus == 1:
        return 'payment'
    _fail('Cette action ne correspond pas au document source.')


def _context(source, action):
    source.check_permission('read')
    kind = _action(source, action)
    existing = source if source.doctype == (DELIVERY if kind == 'delivery' else PAYMENT) else None
    _fields(source.doctype, ['company', 'customer', 'currency', 'sales_order', 'order_type'])
    if existing:
        source.check_permission('write')
    else:
        frappe.has_permission(DELIVERY if kind == 'delivery' else PAYMENT, 'create', throw=True)
    for doctype, name in (('Company', source.company), ('Customer', source.customer)):
        frappe.get_doc(doctype, name).check_permission('read')
    if kind == 'delivery':
        order = source if source.doctype == 'Sales Order' else special.get_order(source.sales_order)
        order.check_permission('read')
        if order.docstatus != 1 or order.status in ('Closed', 'On Hold', 'Cancelled'):
            _fail('Une commande validée et active est requise.')
        if (order.get('custom_ug_order_type') or 'A') not in ('A', 'B'):
            _fail('Type de commande invalide.')
        _read_context(source, kind, existing, order)
        return kind, existing, order
    if source.doctype == 'Sales Order':
        # Reuse the shared A/B order permission and document-state checks.
        special.get_order(source.name)
    if source.doctype == DELIVERY and source.docstatus != 1:
        _fail('Valider le bordereau avant de préparer son règlement.')
    _read_context(source, kind, existing, None)
    return kind, existing, None


def _warehouse(name, company):
    name = _text(name)
    if not name:
        return None
    warehouse = frappe.get_doc('Warehouse', name)
    warehouse.check_permission('read')
    if warehouse.company != company or warehouse.is_group or warehouse.get('disabled'):
        _fail('Choisir un dépôt actif de la société du document.')
    return name


def _dimensions(values, company):
    from mat_reco.material_reconfiguration.utils.accounting_dimensions import get_active_accounting_dimension_fields
    if not isinstance(values, dict):
        _fail('Dimensions comptables invalides.')
    allowed = set(get_active_accounting_dimension_fields())
    if set(values) - allowed:
        _fail('Dimension comptable inconnue.')
    result = {}
    meta = frappe.get_meta('Stock Entry')
    for key, value in values.items():
        _fields('Stock Entry', [key], 'write')
        value = _text(value)
        field = meta.get_field(key)
        if not field:
            _fail('Dimension comptable inconnue.')
        if value and field.fieldtype == 'Link':
            linked = frappe.get_doc(field.options, value)
            linked.check_permission('read')
            if linked.meta.has_field('company') and linked.get('company') and linked.company != company:
                _fail('La dimension comptable appartient à une autre société.')
        result[key] = value
    return result


def _delivery_data(order, existing=None):
    """Read available lines without validating an unselected/full delivery."""
    booked = special.delivered(order, exclude=existing.name if existing else None)
    stock = special.get_delivery_data(order.name)
    info = {row['sales_order_item']: row for row in stock.get('rows', [])}
    old = {r.sales_order_item: r for r in existing.items} if existing else {}
    from .ug_warehouse import operational_warehouse, is_glass
    stores = operational_warehouse(order.company)
    other_stock = any(not is_glass(row.item_code) and frappe.get_cached_value('Item', row.item_code, 'is_stock_item') for row in order.items)
    default = (stores if any(is_glass(row.item_code) for row in order.items) and not other_stock else None)
    default = (existing.get('warehouse') if existing else None) or default or order.get('set_warehouse') or next((r.warehouse for r in order.items if r.get('warehouse')), None)
    result = []
    for row in order.items:
        remaining = max(0, flt(row.qty) - flt(booked.get(row.name)))
        if remaining <= EPS:
            continue
        saved = old.get(row.name)
        qty = flt(saved.qty) if saved else remaining
        selection = info.get(row.name, {})
        warehouse = (saved.warehouse if saved else None) or (stores if is_glass(row.item_code) else None) or row.get('warehouse') or default
        rate = flt(row.get('net_amount')) / flt(row.qty) if row.qty else 0
        parent = row.get('custom_parent_row') if row.get('custom_is_service_row') or row.get('custom_is_accessory_row') else None
        result.append(dict(id=row.name, label=row.item_name or row.item_code, description=strip_html(row.get('description') or row.item_name or ''),
            item_code=row.item_code, ordered_qty=row.qty, processed_qty=flt(booked.get(row.name)), remaining_qty=remaining,
            qty=qty, uom=row.uom, rate=rate, amount=rate * qty, currency=order.currency, parent_id=parent,
            selected=bool(saved) if existing else True, warehouse=warehouse,
            serial_no=(saved.get('serial_no') or '') if saved else '', auto_serial_no=(saved.get('auto_serial_no') or '') if saved else '', batch_no=saved.get('batch_no') if saved else None,
            has_serial_no=bool(selection.get('has_serial_no')), has_batch_no=bool(selection.get('has_batch_no')),
            conversion_factor=flt(row.get('conversion_factor')) or 1,
            serials=selection.get('serials', []), length_mm=row.get('custom_client_length_mm'),
            width_mm=row.get('custom_client_width_mm'), thickness_mm=row.get('custom_client_thickness_mm')))
    # Available candidates come from the existing ownership/dimension matcher.
    # Do not disclose reservation owners; simply omit foreign-reserved series.
    names = {serial['name'] for row in result for serial in row['serials']}
    if names:
        from .production_reservations import active_reservations
        reservations = active_reservations(names)
        denied = {}
        for reservation in reservations:
            for entry in reservation.sb_entries:
                denied.setdefault(entry.serial_no, set()).add((reservation.voucher_no, reservation.voucher_detail_no))
        used_suggestions = {name for row in result for name in row['serial_no'].splitlines() if name}
        for row in result:
            own = (order.name, row['id'])
            row['serials'] = [serial for serial in row['serials'] if not (denied.get(serial['name'], set()) - {own})]
            if row['selected'] and not row['serial_no'] and row['has_serial_no']:
                needed = row['qty'] * row['conversion_factor']
                available = [s['name'] for s in row['serials'] if s['warehouse'] == row['warehouse'] and s['name'] not in used_suggestions]
                if needed > 0 and float(needed).is_integer() and len(available) >= needed:
                    chosen = sorted(available)[:int(needed)]
                    used_suggestions.update(chosen)
                    row['serial_no'] = '\n'.join(chosen)
                    row['auto_serial_no'] = row['serial_no']
    return result, stock, default


def _payment_doc(source, existing):
    if existing:
        return frappe.get_doc(existing.as_dict())
    if source.doctype == DELIVERY:
        _payment_delivery_fields(source)
        return frappe.get_doc(special.make_payment(bordereau=source.name))
    return frappe.get_doc(special.make_payment(sales_order=source.name))


def _payment_delivery_fields(delivery, payment=None):
    _fields(DELIVERY, ['company', 'customer', 'currency', 'sales_order', 'posting_date',
        'net_total', 'grand_total', 'order_type', 'sales_invoice'])
    if delivery.get('order_type') == 'A':
        # payment_limit legitimately reads the native invoice and existing
        # reconciliation; do not expose their balance through hidden fields.
        _fields('Sales Invoice', ['outstanding_amount', 'party_account_currency', 'currency', 'conversion_rate', 'debit_to'])
        if payment and payment.get('payment_entry'):
            _fields(PAYMENT, ['payment_entry'])
            _table('Payment Entry', 'references', ['reference_doctype', 'reference_name', 'allocated_amount'])


def _payment_rows(doc, warnings=None):
    fields = ['name', 'sales_order', 'posting_date', 'net_total', 'grand_total', 'order_type']
    names = frappe.get_list(DELIVERY, filters=dict(company=doc.company, customer=doc.customer,
        currency=doc.currency, docstatus=1), fields=fields, order_by='posting_date,name', limit_page_length=MAX_ROWS + 1)
    if len(names) > MAX_ROWS:
        _fail('Plus de 500 bordereaux disponibles. Utiliser le formulaire natif pour choisir les affectations.')
    prior = {row.bordereau: flt(row.amount) for row in doc.allocations}
    if set(prior) - {row.name for row in names}:
        # An edit replaces the allocation table. Never silently drop an old
        # allocation because its linked BL is no longer readable/in scope.
        _fail('Lecture de tous les bordereaux déjà affectés requise pour modifier ce règlement.', permission=True)
    result = []
    for row in names:
        # A broken historical BL must not prevent an advance or payment for a
        # different BL. Silence only optional-candidate validation messages so
        # a private native invoice reference cannot enter _server_messages.
        previous_mute = frappe.flags.get('mute_messages')
        if row.name not in prior:
            frappe.flags.mute_messages = True
        try:
            delivery = frappe.get_doc(DELIVERY, row.name)
            delivery.check_permission('read')
            _payment_delivery_fields(delivery, doc)
            if (delivery.get('order_type') or 'B') == 'A':
                from .special_a import payment_limit
                balance = payment_limit(delivery, doc)
            else:
                balance = max(0, flt(delivery.net_total) - special.allocated(delivery.name, doc.name))
        except (frappe.PermissionError, frappe.ValidationError):
            if row.name in prior:
                raise
            if warnings is not None:
                warnings.append('Bordereau à vérifier.')
            continue
        finally:
            frappe.flags.mute_messages = previous_mute
        selected = row.name in prior or (not doc.allocations and doc.sales_order and delivery.sales_order == doc.sales_order)
        if balance <= EPS and row.name not in prior:
            continue
        result.append(dict(id=row.name, label=row.name, description=delivery.sales_order, sales_order=delivery.sales_order,
            order_type=delivery.get('order_type') or 'B', currency=doc.currency, balance=balance,
            remaining_amount=balance, remaining_qty=balance, amount=prior.get(row.name, balance if selected else 0), selected=bool(selected)))
    return result


def prepare_special(source, action):
    kind, existing, order = _context(source, action)
    if kind == 'delivery':
        rows, stock, warehouse = _delivery_data(order, existing)
        dimensions = stock.get('dimensions', [])
        for dimension in dimensions:
            _fields('Stock Entry', [dimension['fieldname']])
            _fields('Sales Order', [dimension['fieldname']])
        values = dict(posting_date=existing.posting_date if existing else nowdate(), warehouse=warehouse,
            accounting_dimensions=frappe.parse_json(existing.get('accounting_dimensions_json') or '{}') if existing else
            {field['fieldname']: field.get('default') or '' for field in dimensions})
        fields = [dict(fieldname='posting_date', label='Date de livraison', fieldtype='Date', reqd=1),
            dict(fieldname='warehouse', label='Dépôt par défaut', fieldtype='Link', options='Warehouse')]
        return dict(target_doctype=DELIVERY, fields=fields, rows=rows, values=values,
            dimensions=dimensions, warehouses=stock.get('warehouses', []), action=action, service_policy='independent',
            company=order.company, customer=order.customer, currency=order.currency)
    doc = _payment_doc(source, existing)
    warnings = []
    rows = _payment_rows(doc, warnings)
    amount = doc.get('amount')
    if not existing and source.doctype == 'Sales Order':
        amount = sum(row['amount'] for row in rows if row['selected'])
    values = {field: doc.get(field) for field in PAYMENT_VALUES}
    values['amount'] = amount or 0
    locked = action == 'allocate'
    fields = [dict(fieldname='posting_date', label='Date du règlement', fieldtype='Date', reqd=1, read_only=int(locked)),
        dict(fieldname='amount', label='Montant encaissé', fieldtype='Currency', reqd=1, read_only=int(locked)),
        dict(fieldname='mode_of_payment', label='Mode de règlement', fieldtype='Link', options='Mode of Payment', reqd=1, read_only=int(locked)),
        dict(fieldname='reference', label='Référence du règlement', fieldtype='Data', reqd=1, read_only=int(locked)),
        dict(fieldname='sales_order', label='Commande source de l’avance', fieldtype='Link', options='Sales Order', read_only=int(locked))]
    return dict(target_doctype=PAYMENT, fields=fields, rows=rows, values=values, action=action,
        company=doc.company, customer=doc.customer, currency=doc.currency, unavailable_count=len(warnings),
        notice=(str(len(warnings)) + ' bordereau(x) à vérifier, indisponible(s) pour cette affectation.') if warnings else '')


def _delivery_selections(order, available, selections):
    """Every partial-delivery line remains independently selectable, as native."""
    selected = _rows(selections)
    by_id = {row['id']: row for row in available}
    if set(selected) - set(by_id):
        _fail('Une ligne sélectionnée n’appartient pas aux lignes livrables de la commande.')
    result = {}
    for identity, choice in selected.items():
        if not choice['selected']:
            continue
        qty = _number(choice.get('qty'), positive=True)
        if qty > by_id[identity]['remaining_qty'] + EPS:
            _fail('La quantité demandée dépasse le reste à livrer.')
        result[identity] = dict(choice, qty=qty)
    if not result:
        _fail('Sélectionner au moins une ligne à livrer.')
    return result


def _apply_delivery(source, existing, order, selections, values):
    available, stock, default = _delivery_data(order, existing)
    choices = _delivery_selections(order, available, selections)
    source_rows = {r.name: r for r in order.items}
    old_rows = {r.sales_order_item: r for r in existing.items} if existing else {}
    doc = frappe.get_doc(existing.as_dict()) if existing else frappe.new_doc(DELIVERY)
    if not existing:
        doc.update(dict(company=order.company, customer=order.customer, currency=order.currency,
            sales_order=order.name, order_type=order.get('custom_ug_order_type') or 'A'))
    header_warehouse = _warehouse(values.get('warehouse', default), order.company)
    doc.posting_date = _date(values.get('posting_date') or doc.get('posting_date') or nowdate())
    doc.warehouse = header_warehouse
    if 'accounting_dimensions' in values:
        doc.accounting_dimensions_json = frappe.as_json(_dimensions(values['accounting_dimensions'], doc.company))
    elif not existing:
        doc.accounting_dimensions_json = frappe.as_json({field['fieldname']: field.get('default') or '' for field in stock.get('dimensions', [])})
    doc.set('items', [])
    used = set()
    for row in available:
        choice = choices.get(row['id'])
        if not choice:
            continue
        prior = old_rows.get(row['id'])
        item = source_rows[row['id']]
        warehouse = _warehouse(choice.get('warehouse') or header_warehouse or row['warehouse'], order.company)
        names = _serials(choice.get('serial_no', choice.get('serials', prior.get('serial_no') if prior else row['serial_no'])) or '')
        needed = choice['qty'] * row['conversion_factor']
        # A partial quantity may replace a full automatic suggestion. Never trim
        # manually selected series; only the server's own unchanged suggestion.
        automatic = bool(row.get('auto_serial_no') and '\n'.join(names) == row['auto_serial_no'])
        if automatic and abs(needed - len(names)) > EPS:
            candidates = sorted(serial['name'] for serial in row['serials'] if serial['warehouse'] == warehouse and serial['name'] not in used)
            names = candidates[:int(needed)] if needed > 0 and float(needed).is_integer() and len(candidates) >= needed else []
        if used.intersection(names):
            _fail('Une série ne peut être utilisée sur plusieurs lignes.')
        used.update(names)
        if names:
            allowed = {serial['name'] for serial in row['serials'] if serial['warehouse'] == warehouse}
            if set(names) - allowed:
                _fail('Une série choisie n’est plus disponible pour cette ligne et ce dépôt.')
            count = choice['qty'] * row['conversion_factor']
            if abs(count - len(names)) > EPS:
                _fail('Le nombre de séries doit correspondre à la quantité de stock sélectionnée.')
        batch = _text(choice.get('batch_no', prior.get('batch_no') if prior else '') or '')
        if batch:
            document = frappe.get_doc('Batch', batch)
            document.check_permission('read')
            if document.item != item.item_code:
                _fail('Le lot ne correspond pas à l’article.')
        payload = dict(sales_order_item=row['id'], qty=choice['qty'], warehouse=warehouse,
            serial_no='\n'.join(names), batch_no=batch, auto_serial_no='\n'.join(names) if automatic else '')
        if prior:
            payload['name'] = prior.name
        doc.append('items', payload)
    return doc


def _apply_payment(source, existing, selections, values, action):
    doc = _payment_doc(source, existing)
    choices = _rows(selections)
    permitted = {row['id']: row for row in _payment_rows(doc)}
    if set(choices) - set(permitted):
        _fail('Une affectation ne correspond pas à un bordereau accessible du compte client.')
    if action == 'allocate':
        # Header facts of a submitted receipt are immutable; update allocations
        # on this same receipt so native reconciliation never counts new cash.
        for field, incoming in values.items():
            current = doc.get(field)
            same = (_number(incoming) == flt(current)) if field == 'amount' else (
                _date(incoming) == str(getdate(current)) if field == 'posting_date' else (incoming or '') == (current or ''))
            if not same:
                _fail('Les données du règlement validé sont immuables ; modifier uniquement ses affectations.')
    else:
        for field, incoming in values.items():
            if field == 'amount':
                doc.amount = _number(incoming, positive=True)
            elif field == 'posting_date':
                doc.posting_date = _date(incoming)
            elif field in ('mode_of_payment', 'reference', 'sales_order'):
                doc.set(field, _text(incoming))
        if doc.get('sales_order'):
            order = special.get_order(doc.sales_order)
            if (order.company, order.customer, order.currency) != (doc.company, doc.customer, doc.currency):
                _fail('La commande source doit correspondre au compte client du règlement.')
        if doc.get('mode_of_payment'):
            frappe.get_doc('Mode of Payment', doc.mode_of_payment).check_permission('read')
    total = 0
    doc.set('allocations', [])
    for identity, choice in choices.items():
        if not choice['selected']:
            continue
        amount = _number(choice.get('amount'), positive=True)
        if amount > permitted[identity]['remaining_amount'] + EPS:
            _fail('L’affectation dépasse le solde actuel du bordereau.')
        total += amount
        doc.append('allocations', dict(bordereau=identity, amount=amount))
    if total > _number(doc.get('amount'), positive=True) + EPS:
        _fail('Les affectations dépassent le montant encaissé.')
    return doc


def build_special(source, action, selections, values):
    """Return an unsaved document; the facade alone performs the native action."""
    kind, existing, order = _context(source, action)
    if not isinstance(values, dict) or set(values) - (DELIVERY_VALUES if kind == 'delivery' else PAYMENT_VALUES):
        _fail('Les champs du formulaire ne sont pas autorisés.')
    _write_context(kind, existing, values)
    if kind == 'delivery':
        return _apply_delivery(source, existing, order, selections, values)
    return _apply_payment(source, existing, selections, values, action)
