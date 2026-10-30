"""Read-only, permission-scoped commercial view of the existing A/B documents.

Parent documents are always selected with get_list. Child rows are read only
inside those visible parents. No controller, lockful financial helper or stock
operation is invoked while rendering this dashboard.
"""
from collections import defaultdict

import frappe
from frappe.utils import flt, getdate, now_datetime

MAX_PARENTS = 500
MAX_CHILDREN = 20000
EPS = .000001
DT = dict(order='Sales Order', quotation='Quotation', project='Chantier',
    study='Chantier Technical Study', delivery='Bordereau Special', payment='Reglement Special',
    native_delivery='Delivery Note', invoice='Sales Invoice', native_payment='Payment Entry',
    opening='Solde Initial Client B')
CAP = dict(order='orders', quotation='quotations', project='projects', study='studies',
    delivery='deliveries', payment='payments', native_delivery='native_deliveries',
    invoice='invoices', native_payment='native_payments', opening='openings')


def _id(doctype, name):
    return doctype + '::' + name


def _normalise(filters):
    value = frappe.parse_json(filters or '{}') if isinstance(filters, str) else filters or {}
    if not isinstance(value, dict):
        frappe.throw('Filtres du cockpit commercial invalides.')
    result = {key: str(value.get(key) or '').strip()[:140] for key in
              ('search', 'customer', 'company', 'currency', 'from_date', 'to_date')}
    result['circuit'] = str(value.get('circuit') or 'all')
    result['state'] = str(value.get('state') or 'all')
    result['followup'] = str(value.get('followup') or 'all')
    if result['circuit'] not in ('all', 'A', 'B') or result['state'] not in ('all', 'open') or result['followup'] not in ('all', 'unpaid', 'undelivered'):
        frappe.throw('Choisir un circuit et un état valides.')
    for key in ('from_date', 'to_date'):
        if result[key]:
            try:
                result[key] = str(getdate(result[key]))
            except (ValueError, TypeError):
                frappe.throw('Date de filtre invalide.')
    if result['from_date'] and result['to_date'] and result['from_date'] > result['to_date']:
        frappe.throw('La date de début doit précéder la date de fin.')
    return result


def _capabilities():
    values = {'can_read_' + CAP[kind]: bool(frappe.has_permission(doctype, 'read'))
              for kind, doctype in DT.items()}
    for key, doctype in (('delivery', DT['delivery']), ('payment', DT['payment']), ('customer', 'Customer')):
        allowed = bool(frappe.has_permission(doctype, 'create'))
        values['can_create_' + key] = allowed
        values['can_create_' + {'delivery': 'deliveries', 'payment': 'payments', 'customer': 'customers'}[key]] = allowed
    values['can_open_workshop'] = bool(frappe.db.exists('Page', 'workshop-cockpit') and
        frappe.get_doc('Page', 'workshop-cockpit').is_permitted())
    return values


def _read_fields(doctype, wanted, parenttype=None):
    meta = frappe.get_meta(doctype)
    permitted = set(meta.get_permitted_fieldnames(parenttype=parenttype, permission_type='read',
        with_virtual_fields=False))
    permitted.update(('name', 'docstatus', 'creation', 'modified', 'owner', 'parent', 'idx'))
    return [field for field in wanted if field in permitted and
            (field in ('name', 'docstatus', 'creation', 'modified', 'owner', 'parent', 'idx') or meta.has_field(field))]


def _parents(snapshot, kind, fields, filters=None, or_filters=None):
    if not snapshot['capabilities'].get('can_read_' + CAP[kind]):
        return []
    doctype = DT[kind]
    fields = _read_fields(doctype, fields)
    rows = frappe.get_list(doctype, fields=fields, filters=filters or {}, or_filters=or_filters or [],
        order_by=f'`tab{doctype}`.modified desc, `tab{doctype}`.name desc', limit_page_length=MAX_PARENTS + 1, distinct=True)
    if len(rows) > MAX_PARENTS:
        snapshot['truncated'] = True
        snapshot.setdefault('incomplete_parents', set()).add(kind)
        snapshot['warnings'].append('La consultation est limitée à ' + str(MAX_PARENTS) + ' documents de type ' + doctype + '. Affiner les filtres.')
    snapshot[kind] = [dict(row) for row in rows[:MAX_PARENTS]]
    return snapshot[kind]


def _children(snapshot, key, doctype, parent_kind, tablefield, fields):
    parents = snapshot.get(parent_kind, [])
    if not parents:
        snapshot[key] = []
        return
    parenttype = DT[parent_kind]
    meta = frappe.get_meta(parenttype)
    table = meta.get_field(tablefield)
    # Table fields are excluded from get_permitted_fieldnames (no scalar value).
    # Their permlevel still controls access to all child rows.
    if not table or (table.permlevel or 0) not in meta.get_permlevel_access('read'):
        snapshot[key] = []
        snapshot['incomplete_children'].add(key)
        return
    # get_all is intentional for children only: the parent set above was selected
    # with get_list, including user permissions and permission_query_conditions.
    readable = _read_fields(doctype, fields, parenttype=parenttype)
    required = {'order_items': ('qty', 'uom', 'delivered_qty'),
        'delivery_items': ('sales_order_item', 'qty'), 'allocations': ('bordereau', 'amount'),
        'invoice_items': ('sales_order',), 'payment_references': ('reference_doctype', 'reference_name', 'allocated_amount'),
        'native_delivery_items': ('against_sales_order',)}.get(key, ())
    if set(required) - set(readable):
        snapshot['incomplete_children'].add(key)
    rows = frappe.get_all(doctype, filters={'parent': ['in', [row['name'] for row in parents]],
        'parenttype': parenttype, 'parentfield': tablefield},
        fields=readable, order_by='parent, idx',
        limit_page_length=MAX_CHILDREN + 1)
    if len(rows) > MAX_CHILDREN:
        snapshot['truncated'] = True
        snapshot['incomplete_children'].add(key)
        snapshot['warnings'].append('Des lignes dépassent la limite de consultation. Certains indicateurs sont indisponibles ; affiner les filtres.')
    snapshot[key] = [dict(row) for row in rows[:MAX_CHILDREN]]


def _base(filters, customer_field='customer'):
    values = {}
    for field in ('company', 'currency'):
        if filters.get(field):
            values[field] = filters[field]
    if filters.get('customer'):
        values[customer_field] = filters['customer']
    return values


def _period(values, field, filters):
    if filters.get('from_date') and filters.get('to_date'):
        values[field] = ['between', [filters['from_date'], filters['to_date']]]
    elif filters.get('from_date'):
        values[field] = ['>=', filters['from_date']]
    elif filters.get('to_date'):
        values[field] = ['<=', filters['to_date']]


def _snapshot(filters, capabilities):
    data = dict(capabilities=capabilities, warnings=[], truncated=False, incomplete_children=set(), incomplete_parents=set())
    for key in DT:
        data[key] = []
    data['companies'] = [dict(row) for row in frappe.get_list('Company', fields=['name', 'default_currency'],
        limit_page_length=200, order_by='name')] if frappe.has_permission('Company', 'read') else []
    order_filters = _base(filters)
    _period(order_filters, 'transaction_date', filters)
    if filters['circuit'] != 'all':
        order_filters['custom_ug_order_type'] = filters['circuit']
    search = filters.get('search')
    order_or = [[field, 'like', '%' + search + '%'] for field in ('name', 'customer', 'customer_name', 'po_no')] if search else []
    orders = _parents(data, 'order', ['name', 'customer', 'customer_name', 'company', 'currency', 'transaction_date',
        'delivery_date', 'status', 'docstatus', 'grand_total', 'rounded_total', 'net_total', 'total_qty',
        'custom_ug_order_type', 'custom_chantier', 'custom_technical_study', 'conversion_rate', 'disable_rounded_total'], order_filters, order_or)
    _children(data, 'order_items', 'Sales Order Item', 'order', 'items', ['name', 'parent', 'idx', 'item_code',
        'item_name', 'qty', 'delivered_qty', 'stock_qty', 'conversion_factor', 'uom', 'net_amount', 'amount',
        'prevdoc_docname', 'custom_ug_work_type_name', 'stock_uom', 'is_stock_item'])
    order_names = [row['name'] for row in orders]
    scoped = bool(filters.get('from_date') or filters.get('to_date') or search or filters['circuit'] != 'all')

    for kind in ('delivery', 'payment'):
        values = _base(filters)
        if kind == 'delivery' and filters['circuit'] != 'all':
            values['order_type'] = filters['circuit']
        if kind == 'delivery' and scoped and capabilities['can_read_orders']:
            values['sales_order'] = ['in', order_names or ['']]
        if not capabilities['can_read_orders']:
            _period(values, 'posting_date', filters)
        fields = ['name', 'company', 'customer', 'currency', 'posting_date', 'status', 'docstatus', 'order_type', 'sales_order']
        fields += ['net_total', 'grand_total', 'delivery_note', 'sales_invoice'] if kind == 'delivery' else [
            'amount', 'allocated_amount', 'unallocated_amount', 'payment_entry', 'reference', 'mode_of_payment']
        _parents(data, kind, fields, values)
    _children(data, 'delivery_items', 'Bordereau Special Item', 'delivery', 'items',
        ['name', 'parent', 'idx', 'sales_order_item', 'item_code', 'item_name', 'qty', 'uom', 'amount'])
    _children(data, 'allocations', 'Reglement Special Allocation', 'payment', 'allocations',
        ['parent', 'idx', 'bordereau', 'amount'])
    # An allocation to an invisible BL is never used to look up that BL's order,
    # circuit or amount. It will be marked incomplete by the pure projection.

    delivery_or = []
    if order_names:
        delivery_or.append(['Delivery Note Item', 'against_sales_order', 'in', order_names])
    linked = [row['delivery_note'] for row in data['delivery'] if row.get('delivery_note')]
    if linked:
        delivery_or.append(['Delivery Note', 'name', 'in', linked])
    if delivery_or:
        _parents(data, 'native_delivery', ['name', 'company', 'customer', 'currency', 'posting_date', 'status',
            'docstatus', 'net_total', 'grand_total', 'rounded_total', 'disable_rounded_total', 'custom_ug_special_delivery'], _base(filters), delivery_or)
        _children(data, 'native_delivery_items', 'Delivery Note Item', 'native_delivery', 'items',
            ['parent', 'idx', 'against_sales_order', 'so_detail', 'qty', 'amount', 'net_amount'])
    invoice_or = []
    if order_names:
        invoice_or.append(['Sales Invoice Item', 'sales_order', 'in', order_names])
    linked = [row['sales_invoice'] for row in data['delivery'] if row.get('sales_invoice')]
    if linked:
        invoice_or.append(['Sales Invoice', 'name', 'in', linked])
    if invoice_or:
        _parents(data, 'invoice', ['name', 'company', 'customer', 'currency', 'party_account_currency', 'conversion_rate',
            'posting_date', 'due_date', 'status', 'docstatus', 'net_total', 'grand_total', 'rounded_total',
            'outstanding_amount', 'disable_rounded_total', 'custom_ug_special_delivery'], _base(filters), invoice_or)
        _children(data, 'invoice_items', 'Sales Invoice Item', 'invoice', 'items',
            ['parent', 'idx', 'sales_order', 'so_detail', 'delivery_note', 'qty', 'net_amount'])
    pe_or = []
    references = order_names + [row['name'] for row in data['invoice']]
    if references:
        pe_or.append(['Payment Entry Reference', 'reference_name', 'in', references])
    special_names = [row['name'] for row in data['payment']]
    if special_names:
        pe_or.append(['Payment Entry', 'custom_ug_special_payment', 'in', special_names])
    if pe_or:
        values = {'party_type': 'Customer'}
        if filters.get('customer'):
            values['party'] = filters['customer']
        if filters.get('company'):
            values['company'] = filters['company']
        _parents(data, 'native_payment', ['name', 'company', 'party', 'posting_date', 'status', 'docstatus', 'paid_amount',
            'paid_from_account_currency', 'paid_to_account_currency', 'unallocated_amount', 'custom_ug_special_payment'], values, pe_or)
        _children(data, 'payment_references', 'Payment Entry Reference', 'native_payment', 'references',
            ['parent', 'idx', 'reference_doctype', 'reference_name', 'allocated_amount'])
        # The query's child-name OR may match an unrelated document with the
        # same name. Keep only exact doctype/name references or explicit links.
        references = _group(data.get('payment_references', []))
        invoices = {row['name'] for row in data['invoice']}
        data['native_payment'] = [row for row in data['native_payment']
            if row.get('custom_ug_special_payment') in special_names or any(
                ref.get('reference_doctype') == 'Sales Order' and ref.get('reference_name') in order_names or
                ref.get('reference_doctype') == 'Sales Invoice' and ref.get('reference_name') in invoices
                for ref in references[row['name']])]
        visible_payments = {row['name'] for row in data['native_payment']}
        data['payment_references'] = [row for row in data.get('payment_references', []) if row['parent'] in visible_payments]

    _parents(data, 'opening', ['name', 'company', 'customer', 'currency', 'sales_order', 'posting_date', 'docstatus', 'amount'], _base(filters))
    quote_filters = _base(filters, customer_field='party_name')
    quote_filters['quotation_to'] = 'Customer'
    _period(quote_filters, 'transaction_date', filters)
    quote_or = [[field, 'like', '%' + search + '%'] for field in ('name', 'party_name', 'customer_name')] if search else []
    # Proposal-only clients must also be discoverable in the overview.
    _parents(data, 'quotation', ['name', 'company', 'party_name', 'customer_name', 'currency', 'transaction_date',
        'status', 'docstatus', 'grand_total', 'rounded_total', 'disable_rounded_total', 'custom_chantier'], quote_filters, quote_or)
    _add_visible_sources(data, 'quotation', {row.get('prevdoc_docname') for row in data.get('order_items', [])},
        ['name', 'company', 'party_name', 'customer_name', 'currency', 'transaction_date', 'status', 'docstatus',
         'grand_total', 'rounded_total', 'disable_rounded_total', 'custom_chantier'])
    project_filters = _base(filters)
    _period(project_filters, 'creation', filters)
    project_or = [[field, 'like', '%' + search + '%'] for field in ('name', 'customer', 'designation')] if search else []
    _parents(data, 'project', ['name', 'company', 'customer', 'currency', 'creation', 'designation', 'status',
        'docstatus', 'technical_study'], project_filters, project_or)
    _add_visible_sources(data, 'project', {row.get('custom_chantier') for row in orders + data['quotation']},
        ['name', 'company', 'customer', 'currency', 'creation', 'designation', 'status', 'docstatus', 'technical_study'])
    if filters.get('customer'):
        study_or = []
        if order_names:
            study_or.append(['sales_order', 'in', order_names])
        project_names = [row['name'] for row in data['project']]
        if project_names:
            study_or.append(['chantier', 'in', project_names])
        study_names = {row.get('custom_technical_study') for row in orders} | {row.get('technical_study') for row in data['project']}
        study_names.discard(None); study_names.discard('')
        if study_names:
            study_or.append(['name', 'in', sorted(study_names)])
        if study_or:
            _parents(data, 'study', ['name', 'sales_order', 'chantier', 'docstatus', 'modified'], {}, study_or)
    customer_names = {row.get('customer') for row in orders + data['project'] + data['delivery'] + data['payment']}
    customer_names.update(row.get('party_name') for row in data['quotation'])
    customer_names.discard(None); customer_names.discard('')
    data['customers'] = [dict(row) for row in frappe.get_list('Customer', fields=_read_fields('Customer', ['name', 'customer_name']),
        filters={'name': ['in', list(customer_names)]}, limit_page_length=MAX_PARENTS)] if customer_names and frappe.has_permission('Customer', 'read') else []
    return data


def _add_visible_sources(snapshot, kind, names, fields):
    names = set(names) - {None, ''}
    known = {row['name'] for row in snapshot[kind]}
    remaining = sorted(names - known)
    if not remaining or not snapshot['capabilities'].get('can_read_' + CAP[kind]):
        return
    rows = frappe.get_list(DT[kind], fields=_read_fields(DT[kind], fields),
        filters={'name': ['in', remaining]}, limit_page_length=MAX_PARENTS + 1)
    snapshot[kind].extend(dict(row) for row in rows[:max(0, MAX_PARENTS - len(snapshot[kind]))])
    if len(rows) + len(known) > MAX_PARENTS:
        snapshot['truncated'] = True
        snapshot.setdefault('incomplete_parents', set()).add(kind)


def _group(rows, field='parent'):
    result = defaultdict(list)
    for row in rows:
        result[row.get(field)].append(row)
    return result


def _kind(row):
    return row.get('order_type') or row.get('custom_ug_order_type') or 'A'


def _amount(row, kind):
    field = 'amount' if kind in ('payment', 'opening') else 'paid_amount' if kind == 'native_payment' else 'net_total' if kind in ('delivery', 'order') and _kind(row) == 'B' else 'grand_total'
    value = row.get(field)
    if field == 'grand_total' and not row.get('disable_rounded_total') and row.get('rounded_total'):
        value = row['rounded_total']
    return None if value is None else flt(value)


def _party_value(value, account_currency, document, companies):
    currency = document.get('currency')
    if value is None:
        return None
    if account_currency == currency:
        return flt(value)
    if account_currency and account_currency == companies.get(document.get('company')) and flt(document.get('conversion_rate')) > 0:
        return flt(value) / flt(document['conversion_rate'])
    return None


def _receipt_parts(receipt, allocations, deliveries, orders):
    """The same split as special_b.payment_share, without DB lookups per row."""
    kind = receipt.get('order_type') or 'B'
    amount = receipt.get('amount')
    if amount is None:
        return dict(A=None, B=None, by_order={}, allocations_by_order={}, advances_by_order={}, incomplete=True)
    parts = dict(A=0., B=0., by_order=defaultdict(float), allocations_by_order=defaultdict(float),
        advances_by_order=defaultdict(float), incomplete=False)
    total = 0
    for allocation in allocations:
        if allocation.get('amount') is None:
            parts['incomplete'] = True
            continue
        total += flt(allocation['amount'])
        delivery = deliveries.get(allocation.get('bordereau'))
        if not delivery:
            parts['incomplete'] = True
            continue
        circuit = delivery.get('order_type') or 'B'
        parts[circuit] += flt(allocation.get('amount'))
        if delivery.get('sales_order') in orders:
            parts['by_order'][delivery['sales_order']] += flt(allocation.get('amount'))
            parts['allocations_by_order'][delivery['sales_order']] += flt(allocation['amount'])
    remainder = flt(receipt['unallocated_amount']) if receipt.get('unallocated_amount') is not None else flt(amount) - total
    source = orders.get(receipt.get('sales_order'))
    source_kind = _kind(source) if source else kind
    if source_kind in ('A', 'B'):
        parts[source_kind] += remainder
        if source:
            parts['by_order'][source['name']] += remainder
            parts['advances_by_order'][source['name']] += remainder
    elif abs(remainder) > EPS:
        parts['incomplete'] = True
    if kind in ('A', 'B'):
        parts[kind] = flt(amount)
        parts['B' if kind == 'A' else 'A'] = 0
    elif parts['incomplete']:
        parts['A'] = parts['B'] = None
    return parts


def _balances(values, unavailable=()):
    unknown = set(unavailable)
    return [dict(company=company, currency=currency, amount=None if (company, currency) in unknown else flt(amount),
        incomplete=(company, currency) in unknown) for (company, currency), amount in sorted(values.items())]


def _quantities(order, lines, deliveries, delivery_lines, caps, incomplete):
    unknown = dict(ordered_qty=None, delivered_qty=None, remaining_qty=None, remaining_all=None,
        can_deliver=None, quantities_by_uom=[], qty_basis='PC')
    if 'order_items' in incomplete or not lines or any(row.get('qty') is None or not row.get('uom') for row in lines):
        return unknown
    booking = defaultdict(float)
    if _kind(order) == 'B':
        if not caps.get('can_read_deliveries') or 'delivery_items' in incomplete:
            return unknown
        for delivery in deliveries:
            for row in delivery_lines[delivery['name']]:
                if row.get('qty') is None:
                    return unknown
                booking[row.get('sales_order_item')] += flt(row['qty'])
    elif any(row.get('delivered_qty') is None for row in lines):
        return unknown
    units = defaultdict(lambda: dict(ordered=0., delivered=0., remaining=0.))
    pieces = dict(ordered=0., delivered=0., remaining=0.)
    pieces_unknown = False
    for row in lines:
        ordered = flt(row['qty'])
        delivered = flt(row['delivered_qty']) if _kind(order) == 'A' else booking[row['name']]
        current = units[row['uom']]
        current['ordered'] += ordered; current['delivered'] += delivered
        current['remaining'] += max(0, ordered - delivered)
        if row.get('uom') == 'PC' or row.get('stock_uom') == 'PC':
            if row.get('is_stock_item') is None:
                pieces_unknown = True
            elif row['is_stock_item']:
                if row.get('stock_uom') == 'PC' and row.get('stock_qty') is not None and flt(row.get('conversion_factor')) > 0:
                    physical = flt(row['stock_qty'])
                    delivered_physical = delivered * flt(row['conversion_factor'])
                elif row['uom'] == 'PC':
                    physical, delivered_physical = ordered, delivered
                else:
                    pieces_unknown = True
                    continue
                pieces['ordered'] += physical; pieces['delivered'] += delivered_physical
                pieces['remaining'] += max(0, physical - delivered_physical)
    return dict(ordered_qty=None if pieces_unknown else pieces['ordered'],
        delivered_qty=None if pieces_unknown else pieces['delivered'], remaining_qty=None if pieces_unknown else pieces['remaining'],
        remaining_all=sum(row['remaining'] for row in units.values()),
        can_deliver=any(row['remaining'] > EPS for row in units.values()) and order.get('docstatus') == 1 and
            order.get('status') not in ('Closed', 'On Hold', 'Completed', 'Cancelled'),
        quantities_by_uom=[dict(uom=unit, **value) for unit, value in sorted(units.items())], qty_basis='PC')


def _order_finances(name, order, active, invoices, rows, allocations, pe_references, parts,
                    outstanding, companies, caps, incomplete, ambiguous_orders):
    delivery_known = False
    account_known = False
    advances = opening = 0.
    paid = balance = 0.
    if _kind(order) == 'A':
        delivery_known = bool(caps.get('can_read_invoices') and name not in ambiguous_orders and
            'invoice_items' not in incomplete and all(outstanding[row['name']] is not None and
                _amount(row, 'invoice') is not None for row in invoices) and all(
                rows['invoice'].get(row.get('sales_invoice'), {}).get('docstatus') == 1 for row in active))
        due = sum(outstanding[row['name']] or 0 for row in invoices)
        billed = sum(_amount(row, 'invoice') or 0 for row in invoices)
        paid = billed - due
        account_known = bool(delivery_known and caps.get('can_read_native_payments') and
            'payment_references' not in incomplete)
        for pe in rows['native_payment'].values():
            if pe.get('docstatus') != 1:
                continue
            receipt = rows['payment'].get(pe.get('custom_ug_special_payment'))
            if receipt and receipt.get('sales_order') == name:
                part_a = parts[receipt['name']]['A']
                if part_a is None or pe.get('unallocated_amount') is None or flt(pe.get('paid_amount')) <= 0:
                    account_known = False
                elif receipt.get('currency') == order.get('currency'):
                    # The PE amount is in its receivable currency; this ratio
                    # recovers the receipt's recorded (not today's) conversion.
                    advances += flt(pe['unallocated_amount']) * part_a / flt(pe['paid_amount'])
                else:
                    account_known = False
            for ref in pe_references[pe['name']]:
                if ref.get('reference_doctype') == 'Sales Order' and ref.get('reference_name') == name:
                    value = _party_value(ref.get('allocated_amount'), pe.get('paid_from_account_currency'), order, companies)
                    if value is None:
                        account_known = False
                    else:
                        advances += value
        balance = due - advances
    else:
        delivery_known = bool(caps.get('can_read_deliveries') and caps.get('can_read_payments') and
            'allocations' not in incomplete and all(row.get('net_total') is not None for row in active))
        target_names = {row['name'] for row in active}
        for payment_name, values in allocations.items():
            if rows['payment'].get(payment_name, {}).get('docstatus') != 1:
                continue
            for allocation in values:
                if allocation.get('bordereau') in target_names:
                    if allocation.get('amount') is None:
                        delivery_known = False
                    else:
                        paid += flt(allocation['amount'])
        due = sum(flt(row.get('net_total')) for row in active) - paid
        account_known = bool(delivery_known and caps.get('can_read_openings') and all(
            row.get('amount') is not None for row in rows['opening'].values()
            if row.get('docstatus') == 1 and row.get('sales_order') == name))
        opening = sum(flt(row.get('amount')) for row in rows['opening'].values()
            if row.get('docstatus') == 1 and row.get('sales_order') == name)
        advances = sum(part.get('advances_by_order', {}).get(name, 0) for payment_name, part in parts.items()
            if rows['payment'][payment_name].get('docstatus') == 1)
        if any(part['incomplete'] for payment_name, part in parts.items()
                if rows['payment'][payment_name].get('docstatus') == 1 and
                rows['payment'][payment_name].get('sales_order') == name):
            account_known = False
        balance = opening + due - advances
    amounts = [_amount(row, 'delivery') for row in active]
    delivery_amount = sum(amounts) if caps.get('can_read_deliveries') and all(value is not None for value in amounts) else None
    return dict(order_amount=_amount(order, 'order'), delivery_amount=delivery_amount,
        received=paid if delivery_known else None, balance=due if delivery_known else None,
        delivery_balance=due if delivery_known else None, order_balance=balance if account_known else None,
        balance_state='known' if delivery_known else 'unavailable',
        order_balance_state='known' if account_known else 'unavailable', advances=advances if account_known else None,
        opening=opening if account_known else None)


def project(snapshot, filters):
    """Pure projection, separately testable without ERPNext or transaction writes."""
    caps = snapshot['capabilities']
    rows = {kind: {row['name']: row for row in snapshot.get(kind, [])} for kind in DT}
    items = _group(snapshot.get('order_items', []))
    delivery_items = _group(snapshot.get('delivery_items', []))
    allocations = _group(snapshot.get('allocations', []))
    invoice_items = _group(snapshot.get('invoice_items', []))
    pe_references = _group(snapshot.get('payment_references', []))
    native_delivery_items = _group(snapshot.get('native_delivery_items', []))
    companies = {row['name']: row.get('default_currency') for row in snapshot.get('companies', [])}
    warnings = list(snapshot.get('warnings', []))
    incomplete = snapshot.get('incomplete_children', set())
    parts = {name: _receipt_parts(row, allocations[name], rows['delivery'], rows['order']) for name, row in rows['payment'].items()}
    order_metrics = {}
    by_order_deliveries = _group(rows['delivery'].values(), 'sales_order')
    by_order_invoices = defaultdict(list)
    ambiguous_orders = set()
    outstanding = {}
    for name, invoice in rows['invoice'].items():
        outstanding[name] = _party_value(invoice.get('outstanding_amount'), invoice.get('party_account_currency'), invoice, companies)
        sources = {row.get('sales_order') for row in invoice_items[name]}
        visible = sources.intersection(rows['order'])
        if len(sources) != 1 or not sources or 'invoice_items' in incomplete:
            ambiguous_orders.update(visible)
        for source in visible:
            by_order_invoices[source].append(invoice)
    for name, order in rows['order'].items():
        active = [row for row in by_order_deliveries[name] if row.get('docstatus') == 1]
        invoices = [row for row in by_order_invoices[name] if row.get('docstatus') == 1]
        order_metrics[name] = dict(_quantities(order, items[name], active, delivery_items, caps, incomplete),
            **_order_finances(name, order, active, invoices, rows, allocations, pe_references, parts,
                outstanding, companies, caps, incomplete, ambiguous_orders))
        order_metrics[name]['technical_study'] = order.get('custom_technical_study') if order.get('custom_technical_study') in rows['study'] else None
    financial_scope_incomplete = bool(set(snapshot.get('incomplete_parents', ())) &
        {'order', 'delivery', 'payment', 'invoice', 'native_payment', 'opening'})
    if financial_scope_incomplete:
        warnings.append('Les documents financiers dépassent la limite de consultation. Les soldes sont indisponibles ; affiner les filtres.')
        for metric in order_metrics.values():
            for key in ('delivery_amount', 'received', 'balance', 'delivery_balance', 'order_balance', 'advances', 'opening'):
                metric[key] = None
            metric['balance_state'] = metric['order_balance_state'] = 'unavailable'

    selected_orders = {}
    for name, order in rows['order'].items():
        metric = order_metrics[name]
        if filters.get('state') == 'open' and (order.get('docstatus') == 2 or order.get('status') in ('Closed', 'Completed', 'Cancelled')):
            continue
        if filters.get('followup') == 'unpaid' and (metric['balance'] is None or metric['balance'] <= EPS):
            continue
        if filters.get('followup') == 'undelivered' and not metric['can_deliver']:
            continue
        selected_orders[name] = order

    clients = {}
    visible_labels = {row['name']: row.get('customer_name') for row in snapshot.get('customers', [])}
    def client(customer, label=None):
        if not customer:
            return None
        label = visible_labels.get(customer) or label or customer
        return clients.setdefault(customer, dict(name=customer, customer=customer, customer_name=label,
            label=label or customer, orders=0, remaining_qty=0., _a=defaultdict(float), _b=defaultdict(float),
            _account_a=defaultdict(float), _account_b=defaultdict(float), _advance_a=defaultdict(float),
            _advance_b=defaultdict(float), _opening_b=defaultdict(float), _unknown_a=set(), _unknown_b=set(),
            _unknown_account_a=set(), _unknown_account_b=set(), _unknown_qty=False))

    for name, order in selected_orders.items():
        account = client(order.get('customer'), order.get('customer_name'))
        if not account:
            continue
        if order.get('docstatus') != 2:
            account['orders'] += 1
            if order_metrics[name]['remaining_qty'] is not None:
                account['remaining_qty'] += order_metrics[name]['remaining_qty']
            else:
                account['_unknown_qty'] = True
        key = order.get('company'), order.get('currency')
        kind = _kind(order).lower()
        if key[1] and order.get('docstatus') == 1 and kind == 'b':
            account['_' + kind][key] += order_metrics[name]['balance'] or 0
            if order_metrics[name]['balance'] is None:
                account['_unknown_' + kind].add(key)
        if key[1] and order.get('docstatus') == 1:
            metric = order_metrics[name]
            account['_advance_' + kind][key] += metric['advances'] or 0
            account['_opening_b'][key] += (metric['opening'] or 0) if kind == 'b' else 0
            if metric['order_balance'] is None:
                account['_unknown_account_' + kind].add(key)
    for kind in ('quotation', 'project'):
        for row in rows[kind].values():
            if filters.get('state') == 'open' and (row.get('docstatus') == 2 or row.get('status') in ('Lost', 'Closed', 'Completed', 'Cancelled')):
                continue
            client(row.get('customer') or row.get('party_name'), row.get('customer_name'))
    for kind in ('delivery', 'payment'):
        for row in rows[kind].values():
            if row.get('sales_order') not in selected_orders and not caps.get('can_read_orders'):
                client(row.get('customer'))
    if not caps.get('can_read_orders'):
        for name, row in rows['delivery'].items():
            if row.get('docstatus') != 1 or _kind(row) != 'B' or not row.get('currency'):
                continue
            account = client(row.get('customer'))
            if account is None:
                continue
            key = row.get('company'), row['currency']
            matching = [allocation for payment_name, values in allocations.items()
                if rows['payment'].get(payment_name, {}).get('docstatus') == 1
                for allocation in values if allocation.get('bordereau') == name]
            account['_b'][key] += flt(row.get('net_total')) - sum(flt(a.get('amount')) for a in matching)
            if row.get('net_total') is None or not caps.get('can_read_payments') or 'allocations' in incomplete or any(
                    a.get('amount') is None for a in matching):
                account['_unknown_b'].add(key)
    for name, invoice in rows['invoice'].items():
        if invoice.get('docstatus') != 1:
            continue
        source_orders = {row.get('sales_order') for row in invoice_items[name]}
        linked_delivery = any(row.get('sales_invoice') == name and row.get('docstatus') == 1
            for row in rows['delivery'].values())
        visible_a_orders = {source for source in source_orders if source in selected_orders and _kind(selected_orders[source]) == 'A'}
        if not visible_a_orders and not (not caps.get('can_read_orders') and linked_delivery):
            continue
        account = client(invoice.get('customer'))
        if account is not None and invoice.get('currency'):
            key = invoice.get('company'), invoice['currency']
            account['_a'][key] += outstanding[name] or 0
            if outstanding[name] is None:
                account['_unknown_a'].add(key)
    # No invoice permissions is an unknown balance, never a reassuring zero.
    for name, order in selected_orders.items():
        if _kind(order) == 'A' and order.get('docstatus') == 1:
            key = order.get('company'), order.get('currency')
            if key[1]:
                clients[order['customer']]['_a'][key] += 0
                if not caps.get('can_read_invoices') or 'invoice_items' in incomplete:
                    clients[order['customer']]['_unknown_a'].add(key)
    # A visible BL explicitly points at its invoice. Read permission on the
    # doctype does not mean the linked invoice passes record/user permissions.
    # Its absence must never turn an existing delivery into a zero balance.
    for row in rows['delivery'].values():
        if row.get('docstatus') != 1 or _kind(row) != 'A' or not row.get('currency'):
            continue
        if row.get('sales_order') not in selected_orders and caps.get('can_read_orders'):
            continue
        if rows['invoice'].get(row.get('sales_invoice'), {}).get('docstatus') != 1:
            account = client(row.get('customer'))
            if account is not None:
                key = row.get('company'), row['currency']
                account['_a'][key] += 0
                account['_unknown_a'].add(key)
                account['_unknown_account_a'].add(key)
    # Global B openings/advances belong to the client once, rather than to each
    # of their orders. They affect the account balance, never the BL balance.
    if filters.get('circuit') in ('all', 'B', None):
        for row in rows['opening'].values():
            if row.get('docstatus') != 1 or row.get('sales_order') or not row.get('currency'):
                continue
            account = client(row.get('customer'))
            if account is not None:
                key = row.get('company'), row['currency']
                account['_opening_b'][key] += flt(row.get('amount'))
                if row.get('amount') is None:
                    account['_unknown_account_b'].add(key)
        for name, row in rows['payment'].items():
            if row.get('docstatus') != 1 or row.get('sales_order') or not row.get('currency'):
                continue
            account = client(row.get('customer'))
            if account is None:
                continue
            key = row.get('company'), row['currency']
            unallocated = row.get('unallocated_amount')
            if unallocated is None or _kind(row) == 'Mixte' and abs(flt(unallocated)) > EPS:
                account['_unknown_account_b'].add(key)
            elif _kind(row) == 'B':
                account['_advance_b'][key] += flt(unallocated)
    client_rows = []
    total_a, total_b = defaultdict(float), defaultdict(float)
    unknown_a, unknown_b = set(), set()
    for account in clients.values():
        if account['_unknown_qty']:
            account['remaining_qty'] = None
        if financial_scope_incomplete:
            account['_unknown_a'].update(account['_a'])
            account['_unknown_b'].update(account['_b'])
            account['_unknown_account_a'].update(account['_advance_a'])
            account['_unknown_account_b'].update(set(account['_advance_b']) | set(account['_opening_b']))
        account['balances_a'] = _balances(account['_a'], account['_unknown_a'])
        account['balances_b'] = _balances(account['_b'], account['_unknown_b'])
        for kind in ('a', 'b'):
            keys = set(account['_' + kind]) | set(account['_advance_' + kind])
            if kind == 'b':
                keys.update(account['_opening_b'])
                if not caps.get('can_read_openings') or not caps.get('can_read_payments'):
                    account['_unknown_account_b'].update(keys)
            for key in keys:
                account['_account_' + kind][key] = account['_' + kind][key] - account['_advance_' + kind][key]
                if kind == 'b':
                    account['_account_b'][key] += account['_opening_b'][key]
            account['_unknown_account_' + kind].update(account['_unknown_' + kind])
            account['account_balances_' + kind] = _balances(account['_account_' + kind], account['_unknown_account_' + kind])
            account['advances_' + kind] = _balances(account['_advance_' + kind], account['_unknown_account_' + kind])
        account['openings_b'] = _balances(account['_opening_b'], account['_unknown_account_b'])
        for key, value in account['_a'].items(): total_a[key] += value
        for key, value in account['_b'].items(): total_b[key] += value
        unknown_a.update(account['_unknown_a']); unknown_b.update(account['_unknown_b'])
        client_rows.append({key: value for key, value in account.items() if not key.startswith('_')})
    client_rows.sort(key=lambda row: (row['label'].casefold(), row['customer']))

    result = dict(capabilities=caps, permissions=caps, filters=filters,
        clients=client_rows, kpis=dict(orders=sum(row['orders'] for row in client_rows),
            remaining_qty=None if any(row['remaining_qty'] is None for row in client_rows) else sum(row['remaining_qty'] for row in client_rows),
            balances_a=_balances(total_a, unknown_a),
            balances_b=_balances(total_b, unknown_b)), documents=[], edges=[], orders=[], details={},
        companies=snapshot.get('companies', []), currencies=sorted({row.get('currency') for row in selected_orders.values() if row.get('currency')}),
        truncated=bool(snapshot.get('truncated')), warnings=warnings, as_of=snapshot.get('as_of') or str(now_datetime()),
        meta=dict(date_scope='orders', financial_scope='visible_documents', parent_limit=MAX_PARENTS))
    if not filters.get('customer'):
        return result
    documents, edges = {}, {}
    def add(kind, row, metrics=None):
        doctype = DT[kind]
        customer = row.get('customer') or row.get('party_name') or row.get('party')
        if customer and customer != filters['customer']:
            return None
        name = row['name']; identity = _id(doctype, name)
        amount = _amount(row, kind)
        document = dict(id=identity, doctype=doctype, name=name, kind=kind, title=row.get('designation') or name,
            subtitle=row.get('customer_name') or customer or '', customer=customer, company=row.get('company'),
            currency=row.get('currency') or row.get('paid_from_account_currency'), amount=amount,
            basis=('HT' if _kind(row) == 'B' else 'TTC') if kind in ('delivery', 'order') else
                'TTC' if kind in ('quotation', 'native_delivery', 'invoice') else '',
            status=row.get('status') or {0:'Brouillon', 1:'Validé', 2:'Annulé'}.get(row.get('docstatus'), ''),
            docstatus=row.get('docstatus'), order_type=_kind(row) if kind in ('order', 'delivery', 'payment') else None,
            sales_order=row.get('sales_order') if row.get('sales_order') in selected_orders else name if kind == 'order' else None,
            date=row.get('posting_date') or row.get('transaction_date') or row.get('creation'), metrics=metrics or {})
        if kind == 'order' and _kind(row) == 'B':
            document['amount'] = row.get('net_total')
        documents[identity] = document
        result['details'][identity] = dict(document, linked_documents=[], tasks=[])
        return identity

    for name, row in selected_orders.items():
        add('order', row, order_metrics[name])
    active_order_names = set(selected_orders)
    delivery_names = set()
    for name, row in rows['delivery'].items():
        if row.get('sales_order') in active_order_names or not caps.get('can_read_orders'):
            delivery_names.add(name)
            paid = None
            due = None
            if row.get('docstatus') == 1:
                if _kind(row) == 'A' and row.get('sales_invoice') in rows['invoice']:
                    due = outstanding[row['sales_invoice']]
                    invoice_amount = _amount(rows['invoice'][row['sales_invoice']], 'invoice')
                    paid = invoice_amount - due if due is not None and invoice_amount is not None else None
                elif _kind(row) == 'B' and row.get('net_total') is not None and caps.get('can_read_payments') and 'allocations' not in incomplete:
                    matching = [a for p, values in allocations.items() if rows['payment'].get(p, {}).get('docstatus') == 1
                        for a in values if a.get('bordereau') == name]
                    if all(a.get('amount') is not None for a in matching):
                        paid = sum(flt(a['amount']) for a in matching)
                        due = flt(row['net_total']) - paid
            if financial_scope_incomplete:
                paid = due = None
            add('delivery', row, dict(received=paid, balance=due, delivery_balance=due, basis='HT' if _kind(row) == 'B' else 'TTC'))
    payment_names = set()
    for name, row in rows['payment'].items():
        if row.get('sales_order') in active_order_names or any(a.get('bordereau') in delivery_names for a in allocations[name]) or not caps.get('can_read_orders'):
            if filters.get('circuit') not in ('all', None) and not parts[name].get(filters['circuit']) and not any(
                    a.get('bordereau') in delivery_names for a in allocations[name]):
                continue
            payment_names.add(name)
            add('payment', row, dict(amount_a=parts[name]['A'], amount_b=parts[name]['B'], allocated_amount=row.get('allocated_amount'),
                unallocated_amount=row.get('unallocated_amount'), allocations_complete=not parts[name]['incomplete']))
    project_names = {row.get('custom_chantier') for row in selected_orders.values()}
    for kind in ('quotation', 'project'):
        for row in rows[kind].values():
            if filters.get('state') == 'open' and (row.get('docstatus') == 2 or row.get('status') in ('Lost', 'Closed', 'Completed', 'Cancelled')):
                continue
            if add(kind, row) and kind == 'quotation':
                project_names.add(row.get('custom_chantier'))
    for row in rows['study'].values():
        if row.get('sales_order') in active_order_names or row.get('chantier') in project_names:
            add('study', row)
    for kind in ('native_delivery', 'invoice', 'native_payment'):
        for row in rows[kind].values():
            if kind == 'native_delivery':
                linked = any(line.get('against_sales_order') in active_order_names for line in native_delivery_items[row['name']]) or row.get('custom_ug_special_delivery') in delivery_names
            elif kind == 'invoice':
                linked = any(line.get('sales_order') in active_order_names for line in invoice_items[row['name']]) or row.get('custom_ug_special_delivery') in delivery_names
            else:
                linked = row.get('custom_ug_special_payment') in payment_names or any(
                    line.get('reference_doctype') == DT['order'] and line.get('reference_name') in active_order_names or
                    line.get('reference_doctype') == DT['invoice'] and _id(DT['invoice'], line.get('reference_name') or '') in documents
                    for line in pe_references[row['name']])
            if linked:
                add(kind, row, dict(balance=outstanding.get(row['name'])) if kind == 'invoice' else {})

    def edge(source_kind, source_name, target_kind, target_name, relation, amount=None, currency=None):
        if not source_name or not target_name:
            return
        source, target = _id(DT[source_kind], source_name), _id(DT[target_kind], target_name)
        if source not in documents or target not in documents:
            return
        key = source, target, relation
        if key not in edges:
            edges[key] = dict(source=source, target=target, kind=relation)
            if amount is not None:
                edges[key].update(amount=amount, currency=currency)
        elif amount is not None:
            edges[key]['amount'] += amount

    for order in selected_orders.values():
        visible_quotes = {row.get('prevdoc_docname') for row in items[order['name']]
            if _id(DT['quotation'], row.get('prevdoc_docname') or '') in documents}
        if not visible_quotes:
            edge('project', order.get('custom_chantier'), 'order', order['name'], 'commercial')
        edge('order', order['name'], 'study', order.get('custom_technical_study'), 'technical')
    for row in snapshot.get('order_items', []):
        edge('quotation', row.get('prevdoc_docname'), 'order', row.get('parent'), 'quotation_order')
    for row in rows['quotation'].values():
        edge('project', row.get('custom_chantier'), 'quotation', row['name'], 'quotation')
    for row in rows['study'].values():
        has_order = _id(DT['order'], row.get('sales_order') or '') in documents or any(
            order.get('custom_technical_study') == row['name'] for order in selected_orders.values())
        if has_order:
            edge('order', row.get('sales_order'), 'study', row['name'], 'technical')
        else:
            edge('project', row.get('chantier'), 'study', row['name'], 'technical')
    for row in rows['delivery'].values():
        edge('order', row.get('sales_order'), 'delivery', row['name'], 'delivery')
        edge('delivery', row['name'], 'native_delivery', row.get('delivery_note'), 'native_delivery')
        edge('delivery', row['name'], 'invoice', row.get('sales_invoice'), 'billing')
    for row in snapshot.get('allocations', []):
        receipt = rows['payment'].get(row.get('parent'), {})
        edge('delivery', row.get('bordereau'), 'payment', row.get('parent'), 'allocation',
            flt(row['amount']) if row.get('amount') is not None else None, receipt.get('currency'))
    for row in rows['payment'].values():
        edge('payment', row['name'], 'native_payment', row.get('payment_entry'), 'accounting')
        if row.get('docstatus') == 1 and flt(row.get('unallocated_amount')) > EPS:
            edge('order', row.get('sales_order'), 'payment', row['name'], 'advance', flt(row['unallocated_amount']), row.get('currency'))
    for row in snapshot.get('native_delivery_items', []):
        edge('order', row.get('against_sales_order'), 'native_delivery', row.get('parent'), 'native_delivery')
    for row in snapshot.get('invoice_items', []):
        edge('native_delivery', row.get('delivery_note'), 'invoice', row.get('parent'), 'billing')
        edge('order', row.get('sales_order'), 'invoice', row.get('parent'), 'billing')
    for row in snapshot.get('payment_references', []):
        if row.get('reference_doctype') in ('Sales Invoice', 'Sales Order'):
            kind = 'invoice' if row['reference_doctype'] == 'Sales Invoice' else 'order'
            edge(kind, row.get('reference_name'), 'native_payment', row.get('parent'), 'reconciliation', flt(row.get('allocated_amount')),
                rows['native_payment'].get(row.get('parent'), {}).get('paid_from_account_currency'))
    def associate(origin_id, linked_id):
        if origin_id not in documents or linked_id not in documents:
            return
        linked = documents[linked_id]
        links = result['details'][origin_id]['linked_documents']
        if not any(row['doctype'] == linked['doctype'] and row['name'] == linked['name'] for row in links):
            links.append(dict(doctype=linked['doctype'], name=linked['name'], label=linked['title'], kind=linked['kind']))

    for value in edges.values():
        source, target = documents[value['source']], documents[value['target']]
        for origin, linked in ((source, target), (target, source)):
            associate(origin['id'], linked['id'])
    # A shared mixed receipt must not lead a graph traversal into another
    # order's branch. Associate descendants by exact source relationships.
    for name in selected_orders:
        identity = _id(DT['order'], name)
        deliveries = {row['name'] for row in by_order_deliveries[name]}
        invoice_names = {row['name'] for row in by_order_invoices[name]}
        receipts = {payment_name for payment_name, row in rows['payment'].items()
            if row.get('sales_order') == name or any(a.get('bordereau') in deliveries for a in allocations[payment_name])}
        for kind, names in (('delivery', deliveries), ('invoice', invoice_names), ('payment', receipts)):
            for linked in names:
                associate(identity, _id(DT[kind], linked))
        for pe_name, row in rows['native_payment'].items():
            if row.get('custom_ug_special_payment') in receipts or any(
                    ref.get('reference_doctype') == DT['order'] and ref.get('reference_name') == name or
                    ref.get('reference_doctype') == DT['invoice'] and ref.get('reference_name') in invoice_names
                    for ref in pe_references[pe_name]):
                associate(identity, _id(DT['native_payment'], pe_name))
    for identity, detail in result['details'].items():
        if detail['kind'] == 'order':
            detail['items'] = items[detail['name']]
    result['documents'] = list(documents.values())
    result['orders'] = [doc for doc in result['documents'] if doc['kind'] == 'order']
    result['edges'] = list(edges.values())
    return result


@frappe.whitelist()
def get_dashboard(filters=None):
    capabilities = _capabilities()
    if not (capabilities['can_read_deliveries'] or capabilities['can_read_payments']):
        frappe.throw('Accès en lecture aux bordereaux spéciaux ou règlements spéciaux requis.', frappe.PermissionError)
    filters = _normalise(filters)
    snapshot = _snapshot(filters, capabilities)
    result = project(snapshot, filters)
    if filters.get('customer'):
        # Keep the client rail stable while displaying the selected client's
        # graph and KPIs. Every index document is independently permissioned.
        overview_filters = dict(filters, customer='')
        overview = project(_snapshot(overview_filters, capabilities), overview_filters)
        result['clients'] = overview['clients']
        result['truncated'] = result['truncated'] or overview['truncated']
        result['warnings'] = list(dict.fromkeys(result['warnings'] + overview['warnings']))
    if result['documents'] and frappe.has_permission('ToDo', 'read'):
        names = {doc['name'] for doc in result['documents']}
        types = {doc['doctype'] for doc in result['documents']}
        tasks = frappe.get_list('ToDo', fields=['name', 'description', 'status', 'reference_type', 'reference_name'],
            filters={'reference_type': ['in', list(types)], 'reference_name': ['in', list(names)]}, limit_page_length=MAX_PARENTS)
        for task in tasks:
            identity = _id(task.reference_type, task.reference_name)
            if identity in result['details']:
                result['details'][identity]['tasks'].append(dict(task))
    return result
