"""Permission-scoped A/B order follow-up using the commercial read model.

A follows native Delivery Notes, Sales Invoices and Payment Entries. B keeps
the special HT account. A special document and the native document it creates
are never added twice. This report does not save or lock business documents.
"""
from collections import defaultdict

import frappe
from frappe.utils import flt

from mat_reco.material_reconfiguration.services import commercial_cockpit as commercial


def _native_deliveries(snapshot, order_name):
    """Count native BLs once, and avoid inventing a share of a multi-order BL."""
    caps = snapshot['capabilities']
    incomplete = snapshot.get('incomplete_children', set())
    if not caps.get('can_read_native_deliveries') or 'native_delivery_items' in incomplete:
        return None, None
    lines = commercial._group(snapshot.get('native_delivery_items', []))
    linked = {row.get('delivery_note') for row in snapshot.get('delivery', [])
              if row.get('sales_order') == order_name and row.get('docstatus') == 1}
    linked.discard(None)
    linked.discard('')
    visible = {row['name']: row for row in snapshot.get('native_delivery', [])}
    # A special BL is only an origin link; its native Delivery Note is the
    # delivery fact. An unreadable linked DN must not look like a zero amount.
    count_unknown = bool(linked - set(visible))
    unknown = count_unknown
    amounts, count = [], 0
    for row in visible.values():
        if row.get('docstatus') != 1:
            continue
        sources = {line.get('against_sales_order') for line in lines[row['name']]}
        if order_name not in sources and row['name'] not in linked:
            continue
        count += 1
        if sources != {order_name}:
            unknown = True
        amount = commercial._amount(row, 'native_delivery')
        if amount is None:
            unknown = True
        else:
            amounts.append(amount)
    return (None if count_unknown else count), (None if unknown else sum(amounts))


def financial_metrics(snapshot):
    """Reuse the cockpit's native accounting and mixed-receipt allocation rules."""
    rows = {kind: {row['name']: row for row in snapshot.get(kind, [])} for kind in commercial.DT}
    allocations = commercial._group(snapshot.get('allocations', []))
    references = commercial._group(snapshot.get('payment_references', []))
    invoice_items = commercial._group(snapshot.get('invoice_items', []))
    by_order_deliveries = commercial._group(rows['delivery'].values(), 'sales_order')
    companies = {row['name']: row.get('default_currency') for row in snapshot.get('companies', [])}
    parts = {name: commercial._receipt_parts(row, allocations[name], rows['delivery'], rows['order'])
             for name, row in rows['payment'].items()}
    outstanding, by_order_invoices, ambiguous = {}, defaultdict(list), set()
    incomplete = snapshot.get('incomplete_children', set())
    for name, invoice in rows['invoice'].items():
        outstanding[name] = commercial._party_value(invoice.get('outstanding_amount'),
            invoice.get('party_account_currency'), invoice, companies)
        sources = {row.get('sales_order') for row in invoice_items[name]}
        visible = sources.intersection(rows['order'])
        if len(sources) != 1 or 'invoice_items' in incomplete:
            ambiguous.update(visible)
        for source in visible:
            by_order_invoices[source].append(invoice)
    result = {}
    for name, order in rows['order'].items():
        active = [row for row in by_order_deliveries[name] if row.get('docstatus') == 1]
        invoices = [row for row in by_order_invoices[name] if row.get('docstatus') == 1]
        values = commercial._order_finances(name, order, active, invoices, rows, allocations,
            references, parts, outstanding, companies, snapshot['capabilities'], incomplete, ambiguous)
        if commercial._kind(order) == 'A':
            values['bl_count'], values['delivery_amount'] = _native_deliveries(snapshot, name)
            # A refund against a Sales Order is not a new positive advance.
            # The shared cockpit model does not sign those allocations, so
            # keep the account total unknown rather than inventing a credit.
            for payment in rows['native_payment'].values():
                if payment.get('docstatus') != 1:
                    continue
                source_receipt = rows['payment'].get(payment.get('custom_ug_special_payment'), {})
                linked = source_receipt.get('sales_order') == name or any(
                    ref.get('reference_doctype') == 'Sales Order' and ref.get('reference_name') == name or
                    ref.get('reference_doctype') == 'Sales Invoice' and any(
                        line.get('sales_order') == name for line in invoice_items[ref.get('reference_name')])
                    for ref in references[payment['name']])
                if not linked:
                    continue
                native_credit_unknown = not source_receipt and (payment.get('unallocated_amount') is None or
                    abs(flt(payment.get('unallocated_amount'))) > commercial.EPS)
                # A native PE's unallocated credit belongs to the customer, not
                # necessarily to its one currently referenced order. Unlike a
                # special receipt, it has no explicit advance source order.
                # Do not label its referenced share as the entire receipt.
                if payment.get('payment_type') != 'Receive' or native_credit_unknown:
                    values['advances'] = values['order_balance'] = None
        else:
            values['bl_count'] = len(active) if snapshot['capabilities'].get('can_read_deliveries') else None
        # Include advances without counting a mixed special receipt or its
        # native Payment Entry a second time.
        paid, advances = values['received'], values['advances']
        values['received'] = None if paid is None or advances is None else paid + advances
        result[name] = values
    return result


def _stage(row, manufactured, study, kind):
    if row.docstatus == 2:
        return 'Annulée'
    if row.docstatus == 0:
        return 'Brouillon'
    if manufactured and (not study or study.get('docstatus') != 1):
        return 'Fiche technique à préparer'
    if kind == 'B':
        if row.get('custom_ug_b_sage_reference'):
            return 'Import Sage confirmé'
        if row.get('custom_ug_b_export_file'):
            return 'Exportée vers Sage'
        if row.get('remaining_all') is not None and not row.remaining_all:
            return 'À exporter vers Sage'
        if row.issued_qty or row.get('has_delivery'):
            return 'Sortie partielle'
    else:
        if row.get('remaining_all') is not None and not row.remaining_all:
            return 'Livrée'
        if row.issued_qty or row.get('has_delivery'):
            return 'Livraison partielle'
    if not manufactured or row.remaining_qty == 0:
        return 'À sortir' if kind == 'B' else 'À livrer'
    return 'Production partielle' if row.produced_qty else 'À produire'


def _columns():
    columns = [dict(fieldname='name', label='Commande', fieldtype='Link', options='Sales Order', width=190),
        dict(fieldname='order_type', label='Type', fieldtype='Data', width=65),
        dict(fieldname='transaction_date', label='Date', fieldtype='Date', width=100),
        dict(fieldname='customer', label='Client', fieldtype='Link', options='Customer', width=180),
        dict(fieldname='company', label='Société', fieldtype='Link', options='Company', width=160),
        dict(fieldname='custom_chantier', label='Chantier', fieldtype='Link', options='Chantier', width=170),
        dict(fieldname='custom_technical_study', label='Fiche technique', fieldtype='Link', options='Chantier Technical Study', width=140),
        dict(fieldname='stage', label='Étape', fieldtype='Data', width=190)]
    columns.extend(dict(fieldname=field, label=label, fieldtype='Float', width=110) for field, label in
        [('required_qty', 'À produire'), ('produced_qty', 'Produites'), ('remaining_qty', 'Restantes'),
         ('issued_qty', 'Livrées / sorties'), ('to_issue_qty', 'À livrer / sortir')])
    columns.extend([dict(fieldname='basis', label='Base montants', fieldtype='Data', width=100),
        dict(fieldname='order_amount', label='Montant commande', fieldtype='Currency', options='currency', width=140),
        dict(fieldname='bl_count', label='BL validés', fieldtype='Int', width=100)])
    columns.extend(dict(fieldname=field, label=label, fieldtype='Currency', options='currency', width=145)
        for field, label in [('bl_amount', 'Montants BL'), ('received', 'Règlements reçus'),
            ('bl_balance', 'Solde des BL / factures'), ('advances', 'Avances'),
            ('order_balance', 'Solde commande')])
    columns.extend([dict(fieldname='custom_ug_b_sage_reference', label='Référence Sage', fieldtype='Data', width=150),
        dict(fieldname='currency', label='Devise', fieldtype='Link', options='Currency', width=80)])
    return columns


def execute(filters=None):
    from mat_reco.material_reconfiguration.services.commercial_reports import normalise, report_access, selected_types
    report_access()
    filters = normalise(filters)
    kinds = selected_types(filters)
    # Loading both kinds preserves the attribution of a single mixed receipt.
    # Record-level permissions remain enforced by every read-model parent list.
    values = commercial._normalise(dict(filters, circuit='all', state='all', followup='all'))
    values['sales_order'] = filters.get('sales_order')
    caps = commercial._capabilities()
    snapshot = commercial._snapshot(values, caps)
    if snapshot.get('truncated'):
        frappe.throw('La consultation dépasse la limite de 500 documents par type. Affiner la société, le client, la commande ou la période.')
    metrics = financial_metrics(snapshot)
    visible = [row for row in snapshot.get('order', []) if commercial._kind(row) in kinds]
    orders = []
    for row in visible:
        order = frappe.get_doc('Sales Order', row['name'])
        order.check_permission('read')
        orders.append(order)
    from mat_reco.material_reconfiguration.services.workshop_service import _receipts
    accepted, _, _, _ = _receipts(orders) if orders else ({}, {}, {}, {})
    from mat_reco.material_reconfiguration.services.order_b_stock import issued_quantities, physical_rows
    studies = {row['name']: row for row in snapshot.get('study', [])}
    items = commercial._group(snapshot.get('order_items', []))
    deliveries = commercial._group(snapshot.get('delivery', []), 'sales_order')
    delivery_items = commercial._group(snapshot.get('delivery_items', []))
    permitted_quantity = 'order_items' not in snapshot.get('incomplete_children', set())
    result = []
    for raw, order in zip(visible, orders):
        row = frappe._dict(raw)
        kind = row.order_type = commercial._kind(raw)
        row.basis = 'HT' if kind == 'B' else 'TTC'
        all_quantities = commercial._quantities(raw, items[row.name],
            [delivery for delivery in deliveries[row.name] if delivery.get('docstatus') == 1],
            delivery_items, caps, snapshot.get('incomplete_children', set()))
        row.remaining_all = all_quantities['remaining_all']
        row.has_delivery = any(group['delivered'] > 0 for group in all_quantities['quantities_by_uom'])
        quantities_visible = permitted_quantity and bool(items[row.name])
        manufactured = [line for line in order.items if frappe.get_cached_value('Item', line.item_code,
            'custom_item_types') in ('OUVRAGE', 'DECOUPE')] if quantities_visible else []
        row.required_qty = sum(flt(line.qty) for line in manufactured) if quantities_visible else None
        row.produced_qty = sum(min(flt(line.qty), flt(accepted.get(line.name))) for line in manufactured) if quantities_visible else None
        row.remaining_qty = max(0, row.required_qty - row.produced_qty) if quantities_visible else None
        physical = physical_rows(order) if quantities_visible else []
        if kind == 'B':
            issued = issued_quantities(order) if quantities_visible else {}
        else:
            issued = {line.name: flt(line.delivered_qty) * (flt(line.conversion_factor) or 1)
                      for line in physical}
        row.issued_qty = sum(issued.values()) if quantities_visible else None
        row.to_issue_qty = sum(max(0, flt(line.stock_qty or line.qty * (flt(line.conversion_factor) or 1)) - issued.get(line.name, 0))
                               for line in physical) if quantities_visible else None
        # Sage fields remain B-specific and respect field-level read access.
        if kind == 'B':
            allowed = commercial._read_fields('Sales Order', ['custom_ug_b_export_file', 'custom_ug_b_sage_reference'])
            for field in allowed:
                row[field] = order.get(field)
        study = studies.get(row.get('custom_technical_study'))
        if row.get('custom_technical_study') not in studies:
            row.custom_technical_study = None
        financial = metrics[row.name]
        row.update(dict(order_amount=financial['order_amount'], bl_count=financial['bl_count'],
            bl_amount=financial['delivery_amount'], received=financial['received'],
            bl_balance=financial['delivery_balance'], order_balance=financial['order_balance'],
            advances=financial['advances']))
        row.stage = _stage(row, manufactured, study, kind)
        if not filters.get('stage') or row.stage == filters.stage:
            result.append(row)
    result.sort(key=lambda row: (str(row.get('transaction_date') or ''), row.name), reverse=True)
    return _columns(), result
