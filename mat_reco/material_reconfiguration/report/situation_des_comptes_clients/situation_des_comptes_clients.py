"""Order-linked customer movements: native accounting A, operational subledger B.

These are separate ledgers. A native invoice/payment is never added again through
its special form. No allocation of a multi-order invoice total is invented.
"""
from collections import defaultdict

import frappe
from frappe.utils import flt, getdate

from mat_reco.material_reconfiguration.services import commercial_reports as reports
from mat_reco.material_reconfiguration.services import special_b as b

EPS = .000001


def _scope(filters, date_field='posting_date'):
    result = {'docstatus': 1, date_field: ['<=', filters.to_date]}
    for field in ('company', 'customer', 'currency'):
        if filters.get(field):
            result[field] = filters[field]
    return result


def _require_fields(doc, fields, table=None, child_fields=()):
    """A readable parent must not disclose fields hidden by a higher permlevel."""
    permitted = set(doc.meta.get_permitted_fieldnames(permission_type='read', with_virtual_fields=False))
    if any(doc.meta.has_field(field) and field not in permitted for field in fields):
        frappe.throw('Droits de lecture insuffisants sur les montants de ' + doc.doctype + '.', frappe.PermissionError)
    if table:
        field = doc.meta.get_field(table)
        if not field or (field.permlevel or 0) not in doc.meta.get_permlevel_access('read'):
            frappe.throw('Droits de lecture insuffisants sur les lignes de ' + doc.doctype + '.', frappe.PermissionError)
        child = frappe.get_meta(field.options)
        allowed = set(child.get_permitted_fieldnames(parenttype=doc.doctype, permission_type='read', with_virtual_fields=False))
        if any(child.has_field(fieldname) and fieldname not in allowed for fieldname in child_fields):
            frappe.throw('Droits de lecture insuffisants sur les lignes de ' + doc.doctype + '.', frappe.PermissionError)


def _read(doctype, name):
    doc = frappe.get_doc(doctype, name)
    doc.check_permission('read')
    return doc


def _event(doc, amount, description, sales_order=None, is_opening=False):
    return dict(posting_date=doc.posting_date, reference_doctype=doc.doctype, reference_name=doc.name,
        sales_order=sales_order, description=description, debit=max(0, amount), credit=max(0, -amount),
        delta=amount, creation=doc.creation or '', is_opening=is_opening)


def _collect_b(filters, groups):
    base = _scope(filters)
    for doctype, sign in ((b.OPENING, 1), (b.DELIVERY, 1), (b.PAYMENT, -1)):
        scoped = dict(base)
        if doctype == b.PAYMENT:
            scoped['order_type'] = ['in', ['B', 'Mixte']]
        elif doctype == b.DELIVERY:
            scoped['order_type'] = 'B'
        for name in frappe.get_list(doctype, filters=scoped, pluck='name', limit_page_length=0):
            doc = _read(doctype, name)
            _require_fields(doc, ('company', 'customer', 'currency', 'posting_date', 'sales_order',
                'order_type', 'amount' if doctype != b.DELIVERY else 'net_total'))
            related_order = doc.sales_order
            if doctype == b.PAYMENT:
                _require_fields(doc, (), 'allocations', ('bordereau', 'amount'))
                b_orders = set()
                # payment_share reads source metadata; verify linked parents first.
                for allocation in doc.allocations:
                    delivery = _read(b.DELIVERY, allocation.bordereau)
                    _require_fields(delivery, ('order_type', 'sales_order'))
                    if (delivery.get('order_type') or 'B') == 'B':
                        b_orders.add(delivery.sales_order)
                if related_order:
                    order = _read('Sales Order', related_order)
                    _require_fields(order, ('custom_ug_order_type',))
                    if order.get('custom_ug_order_type') == 'B':
                        b_orders.add(related_order)
                amount = b.payment_share(doc, filters.sales_order)
                related_order = filters.sales_order or (next(iter(b_orders)) if len(b_orders) == 1 else None)
            elif filters.sales_order and doc.sales_order != filters.sales_order:
                continue
            else:
                amount = flt(doc.amount if doctype == b.OPENING else doc.net_total)
            if not amount and doctype != b.DELIVERY:
                continue
            description = ('Reprise du solde initial' if doctype == b.OPENING else
                'BL validé HT' if doctype == b.DELIVERY else 'Règlement reçu')
            key = (doc.company, doc.customer, doc.currency, 'B')
            groups[key].append(_event(doc, sign * amount, description, related_order, doctype == b.OPENING))


def _order_rows(filters, kind):
    scope = {'docstatus': 1}
    for field in ('company', 'customer', 'currency'):
        if filters.get(field):
            scope[field] = filters[field]
    if filters.sales_order:
        scope['name'] = filters.sales_order
    # A also covers older orders created before the explicit A/B field existed.
    optional = []
    if kind == 'B':
        scope['custom_ug_order_type'] = 'B'
    else:
        optional = [['custom_ug_order_type', '=', 'A'], ['custom_ug_order_type', '=', ''],
            ['custom_ug_order_type', 'is', 'not set']]
    rows = frappe.get_list('Sales Order', filters=scope, or_filters=optional,
        fields=['name', 'company', 'customer', 'currency', 'custom_ug_order_type'], limit_page_length=0)
    if rows:
        _require_fields(_read('Sales Order', rows[0].name), ('company', 'customer', 'currency', 'custom_ug_order_type'))
    return {row.name: row for row in rows if (row.get('custom_ug_order_type') or 'A') == kind}


def _invoice_orders(invoice, cache, notes):
    sources = set()
    unlinked = False
    for row in invoice.items:
        if row.get('sales_order'):
            sources.add(row.sales_order)
        elif row.get('delivery_note') and row.get('dn_detail'):
            name = row.delivery_note
            if name not in notes:
                note = _read('Delivery Note', name)
                _require_fields(note, (), 'items', ('against_sales_order',))
                notes[name] = {item.name: item.get('against_sales_order') for item in note.items}
            if notes[name].get(row.dn_detail):
                sources.add(notes[name][row.dn_detail])
            else:
                unlinked = True
        else:
            unlinked = True
    # A return may copy only item data; the original native invoice is its source.
    if not sources and invoice.get('return_against'):
        name = invoice.return_against
        if name not in cache:
            cache[name] = None
            original = _read('Sales Invoice', name)
            _require_fields(original, ('return_against',), 'items', ('sales_order', 'delivery_note', 'dn_detail'))
            cache[name] = _invoice_orders(original, cache, notes)
        if cache[name] is None:
            frappe.throw('Les factures d’origine forment une boucle. Vérifier ' + invoice.name + '.')
        sources, unlinked = cache[name]
    return sources, unlinked


def _native_factor(doc, party_currency, company_currencies):
    """Use only the exact native invoice/order conversion, never a live FX rate."""
    if party_currency == doc.currency:
        return 1
    if doc.company not in company_currencies:
        company = _read('Company', doc.company)
        _require_fields(company, ('default_currency',))
        company_currencies[doc.company] = company.default_currency
    if party_currency == company_currencies[doc.company] and flt(doc.get('conversion_rate')) > 0:
        return flt(doc.conversion_rate)
    frappe.throw('La devise du règlement ne peut pas être rapprochée exactement de ' + doc.name + '. Vérifier les devises natives ERPNext.')


def _collect_a(filters, groups):
    # Keep all visible A orders for classification. The order filter is applied
    # after source inspection, so multi-order invoices cannot be misattributed.
    all_filters = frappe._dict(filters)
    all_filters.sales_order = None
    all_filters.currency = None
    orders = _order_rows(all_filters, 'A')
    if not orders:
        return
    if any(not frappe.has_permission(doctype, 'read') for doctype in ('Sales Invoice', 'Payment Entry')):
        frappe.throw('Le suivi A exige la lecture des factures et des règlements ERPNext. Sélectionner le type B ou demander ces droits pour consulter A + B.', frappe.PermissionError)
    invoices, original_sources, notes, company_currencies = {}, {}, {}, {}
    invoice_scope = _scope(filters)
    invoice_scope.pop('currency', None)
    # A payment made before the period end may now be allocated to an invoice
    # issued later. Use that invoice only to classify the existing advance;
    # its debit still belongs exclusively to its own posting period.
    invoice_scope.pop('posting_date', None)
    for name in frappe.get_list('Sales Invoice', filters=invoice_scope, pluck='name', limit_page_length=0):
        doc = _read('Sales Invoice', name)
        _require_fields(doc, ('company', 'customer', 'currency', 'posting_date', 'grand_total', 'rounded_total',
            'is_opening', 'is_pos', 'return_against', 'paid_amount', 'write_off_amount', 'conversion_rate', 'party_account_currency'),
            'items', ('sales_order', 'delivery_note', 'dn_detail'))
        source_orders, unlinked = _invoice_orders(doc, original_sources, notes)
        if not (source_orders & set(orders)):
            continue
        if source_orders - set(orders):
            frappe.throw('La facture ' + doc.name + ' regroupe des commandes hors du périmètre A lisible. Vérifier ses documents d’origine.')
        if any((orders[order].company, orders[order].customer) != (doc.company, doc.customer) for order in source_orders):
            frappe.throw('Les origines de la facture ' + doc.name + ' sont incohérentes avec la société ou le client.')
        invoices[name] = (doc, source_orders, unlinked)
        if getdate(doc.posting_date) > getdate(filters.to_date):
            continue
        if filters.currency and doc.currency != filters.currency:
            continue
        if filters.sales_order and filters.sales_order not in source_orders:
            continue
        if filters.sales_order and (len(source_orders) > 1 or unlinked):
            frappe.throw('La facture ' + doc.name + ' couvre plusieurs commandes A ou des lignes sans commande. Retirer le filtre Commande pour consulter son total exact, sans répartition estimée.')
        order_name = next(iter(source_orders)) if len(source_orders) == 1 and not unlinked else None
        key = (doc.company, doc.customer, doc.currency, 'A')
        total = flt(doc.get('rounded_total') or doc.grand_total)
        opening = doc.get('is_opening') == 'Yes'
        groups[key].append(_event(doc, total, 'Avoir ERPNext TTC' if total < 0 else 'Facture ERPNext TTC', order_name, opening))
        # Native immediate payments and write-offs live on the invoice itself.
        for field, description in (('paid_amount', 'Règlement sur facture ERPNext'), ('write_off_amount', 'Ajustement facture ERPNext')):
            if field == 'paid_amount' and not doc.get('is_pos'):
                continue
            amount = flt(doc.get(field))
            if amount:
                groups[key].append(_event(doc, -amount, description, order_name, opening))

    # Source special receipts identify native unallocated advances without adding
    # their amount a second time. They are metadata only in the A ledger.
    receipt_sources = {}
    if frappe.has_permission(b.PAYMENT, 'read'):
        for name in frappe.get_list(b.PAYMENT, filters=dict(_scope(filters), order_type=['in', ['A', 'Mixte']]),
                pluck='name', limit_page_length=0):
            receipt = _read(b.PAYMENT, name)
            _require_fields(receipt, ('sales_order', 'payment_entry', 'currency', 'order_type'))
            if receipt.get('payment_entry') and receipt.get('sales_order') in orders:
                receipt_sources[receipt.payment_entry] = receipt.sales_order

    payment_scope = {'docstatus': 1, 'party_type': 'Customer', 'posting_date': ['<=', filters.to_date]}
    if filters.company:
        payment_scope['company'] = filters.company
    if filters.customer:
        payment_scope['party'] = filters.customer
    native_order_cache = {}
    for name in frappe.get_list('Payment Entry', filters=payment_scope, pluck='name', limit_page_length=0):
        doc = _read('Payment Entry', name)
        if doc.payment_type not in ('Receive', 'Pay'):
            continue
        _require_fields(doc, ('company', 'party', 'posting_date', 'payment_type', 'paid_amount', 'received_amount',
            'paid_from_account_currency', 'paid_to_account_currency', 'unallocated_amount'),
            'references', ('reference_doctype', 'reference_name', 'allocated_amount'))
        party_currency = doc.paid_from_account_currency if doc.payment_type == 'Receive' else doc.paid_to_account_currency
        sign = -1 if doc.payment_type == 'Receive' else 1
        parts, related = defaultdict(float), defaultdict(set)
        all_source_orders = set()
        unknown_references = False
        ambiguous_currencies = set()
        for reference in doc.references:
            amount = flt(reference.allocated_amount)
            if doc.payment_type == 'Pay':
                amount = abs(amount)
            if abs(amount) <= EPS:
                continue
            order_names, target, unlinked = set(), None, False
            if reference.reference_doctype == 'Sales Invoice' and reference.reference_name in invoices:
                target, order_names, unlinked = invoices[reference.reference_name]
            elif reference.reference_doctype == 'Sales Order' and reference.reference_name in orders:
                order_names = {reference.reference_name}
                if reference.reference_name not in native_order_cache:
                    target = _read('Sales Order', reference.reference_name)
                    _require_fields(target, ('company', 'customer', 'currency', 'conversion_rate'))
                    native_order_cache[reference.reference_name] = target
                target = native_order_cache[reference.reference_name]
            if target is None:
                unknown_references = True
                continue
            all_source_orders.update(order_names)
            if filters.sales_order and filters.sales_order not in order_names:
                continue
            if filters.sales_order and (len(order_names) > 1 or unlinked):
                frappe.throw('Le règlement ' + doc.name + ' concerne une facture de plusieurs commandes A ou des lignes sans commande. Retirer le filtre Commande pour conserver une affectation exacte.')
            if (target.company, target.customer) != (doc.company, doc.party):
                frappe.throw('Les origines du règlement ' + doc.name + ' sont incohérentes avec la société ou le client.')
            if filters.currency and target.currency != filters.currency:
                continue
            factor = _native_factor(target, party_currency, company_currencies)
            parts[target.currency] += amount / factor
            related[target.currency].update(order_names)
            if unlinked:
                ambiguous_currencies.add(target.currency)

        source_order = receipt_sources.get(doc.name)
        if source_order:
            all_source_orders.add(source_order)
        advance = flt(doc.unallocated_amount)
        if advance > EPS and all_source_orders:
            advance_order = source_order or (next(iter(all_source_orders))
                if len(all_source_orders) == 1 and not unknown_references else None)
            if filters.sales_order and not advance_order and filters.sales_order in all_source_orders:
                frappe.throw('Le règlement ' + doc.name + ' comporte une avance commune à plusieurs commandes A. Retirer le filtre Commande pour consulter le solde client exact.')
            if (not unknown_references or source_order) and (not filters.sales_order or advance_order == filters.sales_order):
                # Without a unique source currency, retain the native party
                # currency instead of inventing an exchange rate or allocation.
                currency, factor = party_currency, 1
                if advance_order:
                    if advance_order not in native_order_cache:
                        target = _read('Sales Order', advance_order)
                        _require_fields(target, ('company', 'customer', 'currency', 'conversion_rate'))
                        native_order_cache[advance_order] = target
                    target = native_order_cache[advance_order]
                    currency, factor = target.currency, _native_factor(target, party_currency, company_currencies)
                if not filters.currency or currency == filters.currency:
                    parts[currency] += advance / factor
                    if advance_order:
                        related[currency].add(advance_order)
        for currency, amount in parts.items():
            if abs(amount) <= EPS:
                continue
            # Multiple invoice/payment-term allocations produce one cash event.
            related_order = next(iter(related[currency])) if len(related[currency]) == 1 else None
            if currency in ambiguous_currencies:
                related_order = None
            proxy = frappe._dict(doctype=doc.doctype, name=doc.name, posting_date=doc.posting_date, creation=doc.creation)
            key = (doc.company, doc.party, currency, 'A')
            groups[key].append(_event(proxy, sign * amount,
                'Règlement / affectation ERPNext' if sign < 0 else 'Remboursement ERPNext', related_order))


def _render(filters, groups):
    data = []
    for (company, customer, currency, kind), events in sorted(groups.items()):
        common = dict(company=company, customer=customer, currency=currency, order_type=kind, basis='TTC' if kind == 'A' else 'HT')
        start, end = getdate(filters.from_date), getdate(filters.to_date)
        opening = sum(event['delta'] for event in events if getdate(event['posting_date']) < start or
            (event['is_opening'] and getdate(event['posting_date']) == start))
        balance = b.money(opening, currency)
        data.append(dict(common, posting_date=filters.from_date, description='Solde initial', balance=balance, debit=0, credit=0))
        for event in sorted(events, key=lambda row: (getdate(row['posting_date']), row['creation'], row['reference_name'])):
            if getdate(event['posting_date']) < start or getdate(event['posting_date']) > end or (event['is_opening'] and getdate(event['posting_date']) == start):
                continue
            balance = b.money(balance + event['delta'], currency)
            values = {key: value for key, value in event.items() if key not in ('delta', 'creation', 'is_opening')}
            data.append(dict(common, **values, balance=balance))
        data.append(dict(common, posting_date=filters.to_date, description='Solde final', balance=balance, debit=0, credit=0))
    return data


def _columns():
    columns = [dict(fieldname='company', label='Société', fieldtype='Link', options='Company', width=160),
        dict(fieldname='customer', label='Client', fieldtype='Link', options='Customer', width=170),
        dict(fieldname='currency', label='Devise', fieldtype='Link', options='Currency', width=75),
        dict(fieldname='order_type', label='Type', fieldtype='Data', width=65),
        dict(fieldname='basis', label='Base', fieldtype='Data', width=65),
        dict(fieldname='posting_date', label='Date', fieldtype='Date', width=100),
        dict(fieldname='description', label='Opération', fieldtype='Data', width=190),
        dict(fieldname='reference_doctype', label='Document', fieldtype='Data', hidden=1),
        dict(fieldname='reference_name', label='Référence', fieldtype='Dynamic Link', options='reference_doctype', width=200),
        dict(fieldname='sales_order', label='Commande', fieldtype='Link', options='Sales Order', width=190)]
    columns.extend(dict(fieldname=key, label=label, fieldtype='Currency', options='currency', width=140)
        for key, label in (('debit', 'Débit'), ('credit', 'Crédit'), ('balance', 'Solde progressif')))
    return columns


def execute(filters=None):
    reports.report_access()
    filters = reports.normalise(filters)
    if not filters.from_date or not filters.to_date:
        frappe.throw('Renseigner les dates de début et de fin.')
    kinds = reports.selected_types(filters)
    if filters.sales_order:
        order = _read('Sales Order', filters.sales_order)
        kinds = ((order.get('custom_ug_order_type') or 'A'),)
    groups = defaultdict(list)
    for kind in kinds:
        if kind == 'B':
            _collect_b(filters, groups)
        else:
            _collect_a(filters, groups)
        for order in _order_rows(filters, kind).values():
            groups.setdefault((order.company, order.customer, order.currency, kind), [])
    return _columns(), _render(filters, groups)
