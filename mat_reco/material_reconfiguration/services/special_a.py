"""The special forms as an operational facade over native circuit A documents.

A delivery creates one Delivery Note and its Sales Invoice. A receipt creates one
Payment Entry; later allocations reconcile that same entry, never another receipt.
Everything runs in the caller's transaction and retains native permissions.
"""
from contextlib import contextmanager

import frappe
from frappe.utils import flt, nowtime

DELIVERY = 'Bordereau Special'
PAYMENT = 'Reglement Special'
DELIVERY_LINK = 'custom_ug_special_delivery'
PAYMENT_LINK = 'custom_ug_special_payment'
EPS = .000001


@contextmanager
def operation(doctype, name):
    previous = frappe.flags.get('ug_special_a_operation')
    frappe.flags.ug_special_a_operation = (doctype, name)
    state = dict(active=True, attempted=False)

    def prevent_partial_commit():
        if state['active']:
            state['attempted'] = True
            # before_commit callbacks are consumed before they run. Register
            # again so a third-party hook cannot catch this error and retry.
            frappe.db.before_commit.add(prevent_partial_commit)
            frappe.throw('Un module tente une validation partielle. La livraison ou le règlement doit rester dans une seule transaction.')

    frappe.db.before_commit.add(prevent_partial_commit)
    try:
        yield
        if state['attempted']:
            frappe.throw('La validation partielle a été empêchée. Corriger le module concerné avant de réessayer.')
    finally:
        state['active'] = False
        frappe.flags.ug_special_a_operation = previous


def _permissions(doctype, *actions):
    for action in actions:
        frappe.has_permission(doctype, action, throw=True)


def _get_order(name):
    order = frappe.get_doc('Sales Order', name, for_update=True)
    order.check_permission('read')
    if (order.get('custom_ug_order_type') or 'A') != 'A' or order.docstatus != 1:
        frappe.throw('Une commande A validée est requise.')
    return order


def _dimensions(doc, target):
    from mat_reco.material_reconfiguration.utils.accounting_dimensions import get_active_accounting_dimension_fields
    values = frappe.parse_json(doc.get('accounting_dimensions_json') or '{}')
    allowed = set(get_active_accounting_dimension_fields())
    if not isinstance(values, dict) or set(values) - allowed:
        frappe.throw('Dimensions comptables invalides.')
    for fieldname, value in values.items():
        field = target.meta.get_field(fieldname)
        if not field:
            continue
        if value and field.fieldtype == 'Link':
            frappe.get_doc(field.options, value).check_permission('read')
        target.set(fieldname, value)
        for row in target.get('items', []):
            if row.meta.has_field(fieldname):
                row.set(fieldname, value)


def _previous_fixed_charges(order):
    """Read amounts actually used by earlier native deliveries, including returns."""
    fixed_taxes = [row for row in order.taxes if row.charge_type == 'Actual']
    fixed_discount = bool(order.discount_amount and not order.additional_discount_percentage)
    result = dict(discount=0, taxes={row.idx: 0 for row in fixed_taxes})
    if not fixed_discount and not fixed_taxes:
        return result
    names = frappe.db.sql('''SELECT DISTINCT d.parent FROM `tabDelivery Note Item` d
        JOIN `tabDelivery Note` p ON p.name=d.parent
        WHERE d.against_sales_order=%s AND p.docstatus=1''', order.name, pluck=True)
    for name in names:
        delivery = frappe.get_doc('Delivery Note', name)
        actual_taxes = [row for row in delivery.taxes if row.charge_type == 'Actual' and flt(row.tax_amount)]
        if {row.against_sales_order for row in delivery.items} != {order.name}:
            if flt(delivery.discount_amount) or actual_taxes:
                frappe.throw('Le bon de livraison ' + name + ' regroupe plusieurs commandes avec des remises ou frais fixes. '
                    'Leur montant ne peut pas être attribué automatiquement à cette commande. Vérifier ce bon avant de créer un bordereau spécial.')
            continue
        if fixed_discount:
            result['discount'] += flt(delivery.discount_amount)
        for row in actual_taxes:
            candidates = [tax for tax in fixed_taxes if (tax.account_head, tax.description) == (row.account_head, row.description)]
            match = next((tax for tax in candidates if tax.idx == row.idx), None)
            if match is None and len(candidates) == 1:
                match = candidates[0]
            if match is None and len(candidates) > 1:
                frappe.throw('Les frais fixes du bon de livraison ' + name + ' ne peuvent pas être rattachés sans ambiguïté aux taxes de la commande.')
            if match is not None:
                result['taxes'][match.idx] += flt(row.tax_amount)
    return result


def _scaled_fixed_charges(order, note):
    """Distribute fixed charges and fixed document discounts over partial BLs.

    Percentage taxes/discounts are left to ERPNext. Subtract the fixed amounts
    actually used by prior native deliveries, rather than assuming proportional
    charges there. This also supports a first delivery from the standard form.
    """
    sources = {row.name: row for row in order.items}
    selected = {row.so_detail: flt(row.qty) for row in note.items}
    basis = sum(flt(row.amount) for row in order.items)
    if abs(basis) <= EPS:
        return
    before = sum(flt(row.amount) * min(max(flt(row.delivered_qty), 0), flt(row.qty)) / flt(row.qty)
                 for row in order.items if row.qty)
    increment = sum(flt(sources[name].amount) * qty / flt(sources[name].qty)
                    for name, qty in selected.items() if sources[name].qty)
    previous = _previous_fixed_charges(order)

    def portion(value, applied, precision):
        sign = -1 if flt(value) < 0 else 1
        value, applied = sign * flt(value), sign * flt(applied)
        cumulative = flt(value * min(basis, before + increment) / basis, precision)
        return sign * flt(min(max(0, cumulative - applied), max(0, value - applied)), precision)

    if order.discount_amount and not order.additional_discount_percentage:
        note.discount_amount = portion(order.discount_amount, previous['discount'], note.precision('discount_amount'))
    for source, target in zip(order.taxes, note.taxes):
        if source.charge_type == 'Actual':
            target.tax_amount = portion(source.tax_amount, previous['taxes'][source.idx], target.precision('tax_amount'))


def _make_note(doc, order):
    from erpnext.selling.doctype.sales_order.sales_order import make_delivery_note
    selected = {row.sales_order_item: row for row in doc.items}
    note = frappe.new_doc('Delivery Note')
    calculate = note.calculate_taxes_and_totals

    def calculate_partial():
        # Native mapping calculates before returning the draft. A full fixed
        # discount can exceed a small partial BL unless scoped before that call.
        _scaled_fixed_charges(order, note)
        calculate()

    note.calculate_taxes_and_totals = calculate_partial
    try:
        make_delivery_note(order.name, target_doc=note,
            kwargs=dict(filtered_children=list(selected), ignore_pricing_rule=1))
    finally:
        del note.calculate_taxes_and_totals
    mapped = {row.so_detail: row for row in note.items}
    if set(mapped) != set(selected):
        frappe.throw('Des lignes ne sont plus livrables. Recharger les articles du bordereau.')
    note.posting_date = doc.posting_date
    note.posting_time = nowtime()
    note.set_posting_time = 1
    note.set_warehouse = doc.get('warehouse')
    note.set(DELIVERY_LINK, doc.name if not doc.is_new() else None)
    note.ignore_pricing_rule = 1
    for name, source in selected.items():
        row = mapped[name]
        row.qty = source.qty
        row.warehouse = source.warehouse
        row.serial_no = source.get('serial_no') or ''
        row.batch_no = source.get('batch_no')
        row.serial_and_batch_bundle = None
        row.use_serial_batch_fields = 1
    _dimensions(doc, note)
    _scaled_fixed_charges(order, note)
    note.calculate_taxes_and_totals()
    # The mapper builds packed quantities before our partial quantities are set.
    from erpnext.stock.doctype.packed_item.packed_item import make_packing_list
    make_packing_list(note)
    return note


def delivery_validate(doc, order):
    if doc.get('stock_entry') or doc.get('adopt_existing_stock'):
        frappe.throw('Une commande A utilise un bon de livraison ERPNext, pas une sortie directe B.')
    if doc.docstatus == 0 and (doc.get('delivery_note') or doc.get('sales_invoice')):
        frappe.throw('Les documents ERPNext associés sont créés à la validation du bordereau.')
    note = _make_note(doc, order)
    mapped = {row.so_detail: row for row in note.items}
    for row in doc.items:
        native = mapped[row.sales_order_item]
        row.amount = native.net_amount
        row.rate = flt(native.net_amount) / flt(row.qty) if row.qty else 0
    doc.net_total = note.net_total
    doc.tax_amount = note.total_taxes_and_charges
    doc.grand_total = note.rounded_total or note.grand_total
    doc.billing_basis = note.net_total


def _manufactured_serials(doc, order, require=False):
    from .workshop_service import _receipts, _output_matches_line, _has_validated_study
    from .production_reservations import active_reservations
    sources = {row.name: row for row in order.items}
    rows = [row for row in doc.items if frappe.get_cached_value('Item', row.item_code, 'custom_item_types')
            in ('OUVRAGE', 'DECOUPE')]
    if not rows:
        return
    _, _, _, owners = _receipts([order], lock=require)
    used = set()
    for row in doc.items:
        if row not in rows:
            used.update(name.strip() for name in (row.serial_no or '').splitlines() if name.strip())
    for row in rows:
        source = sources[row.sales_order_item]
        if require and not _has_validated_study(order, source, lock=True):
            frappe.throw('Valider la fiche technique avant de livrer cette découpe ou cet ouvrage.')
        item = frappe.get_cached_doc('Item', row.item_code)
        if not item.has_serial_no:
            if require:
                frappe.throw('Les découpes et ouvrages livrés doivent être sérialisés : ' + row.item_code)
            continue
        needed = flt(row.qty) * (flt(source.conversion_factor) or 1)
        selected = [name.strip() for name in (row.serial_no or '').splitlines() if name.strip()]
        automatic = not selected or row.serial_no == row.get('auto_serial_no')
        if automatic and needed.is_integer() and needed > 0:
            candidates = frappe.get_list('Serial No', filters=dict(item_code=row.item_code, warehouse=row.warehouse,
                status='Active'), fields=['name', 'item_code', 'warehouse', 'custom_dimension_length_mm',
                'custom_dimension_width_mm', 'custom_dimension_thickness_mm'], order_by='name', limit_page_length=0)
            eligible = []
            for serial in candidates:
                if serial.name in used or owners.get(serial.name) != row.sales_order_item or not _output_matches_line(serial, source):
                    continue
                reservations = active_reservations({serial.name})
                if any(r.voucher_type != 'Sales Order' or r.voucher_no != order.name or
                       r.voucher_detail_no != row.sales_order_item for r in reservations):
                    continue
                eligible.append(serial.name)
            selected = eligible[:int(needed)] if len(eligible) >= needed else []
            row.serial_no = row.auto_serial_no = '\n'.join(selected)
        if require and (not needed.is_integer() or len(selected) != needed):
            frappe.throw('Sélectionner les séries produites de la ligne à livrer : ' + row.item_code)
        for name in selected:
            serial = frappe.get_doc('Serial No', name, for_update=require)
            serial.check_permission('read')
            if name in used or serial.item_code != row.item_code or serial.warehouse != row.warehouse or serial.status != 'Active':
                frappe.throw('Une série choisie est dupliquée ou indisponible : ' + name)
            if owners.get(name) != row.sales_order_item or not _output_matches_line(serial, source):
                frappe.throw('La série produite ne correspond pas à cette ligne de commande : ' + name)
            if any(r.voucher_type != 'Sales Order' or r.voucher_no != order.name or
                   r.voucher_detail_no != row.sales_order_item for r in active_reservations({name})):
                frappe.throw('La série choisie est réservée pour une autre ligne de commande : ' + name)
            used.add(name)


def fill_delivery(doc, order):
    _manufactured_serials(doc, order)


def _existing_native(doc, doctype, field):
    linked = doc.get(field)
    names = frappe.get_all(doctype, filters={DELIVERY_LINK if doc.doctype == DELIVERY else PAYMENT_LINK: doc.name,
        'docstatus': ['<', 2]}, pluck='name')
    if linked or names:
        frappe.throw('Un document ERPNext est déjà associé. Actualiser et vérifier les connexions avant de recommencer.')


def delivery_on_submit(doc, order):
    from erpnext.stock.doctype.delivery_note.delivery_note import make_sales_invoice
    _permissions('Delivery Note', 'create', 'submit')
    _permissions('Sales Invoice', 'create', 'submit')
    _existing_native(doc, 'Delivery Note', 'delivery_note')
    _existing_native(doc, 'Sales Invoice', 'sales_invoice')
    _manufactured_serials(doc, order, require=True)
    with operation(DELIVERY, doc.name):
        note = _make_note(doc, order)
        note.set(DELIVERY_LINK, doc.name)
        note.insert()
        note.submit()
        invoice = make_sales_invoice(note.name)
        invoice.update_stock = 0
        invoice.posting_date = doc.posting_date
        invoice.posting_time = note.posting_time
        invoice.set_posting_time = 1
        invoice.set(DELIVERY_LINK, doc.name)
        _dimensions(doc, invoice)
        # Some sites require the statutory item classification on invoices even
        # when neither Sales Order Item nor Delivery Note Item has that field.
        classification = 'custom_edef_type_article'
        if frappe.get_meta('Sales Invoice Item').has_field(classification) and frappe.get_meta('Item').has_field(classification):
            for row in invoice.items:
                if not row.get(classification):
                    row.set(classification, frappe.get_cached_value('Item', row.item_code, classification))
        invoice.insert()
        invoice.submit()
        doc.db_set(dict(delivery_note=note.name, sales_invoice=invoice.name, net_total=invoice.net_total,
            tax_amount=invoice.total_taxes_and_charges, grand_total=invoice.rounded_total or invoice.grand_total),
            update_modified=False)


def _linked(doc, doctype, field, linkfield):
    name = doc.get(field)
    if not name:
        frappe.throw('Le document ERPNext associé est manquant : ' + doctype)
    native = frappe.get_doc(doctype, name, for_update=True)
    native.check_permission('read')
    if native.docstatus != 1 or native.get(linkfield) != doc.name or native.company != doc.company:
        frappe.throw('Le document ERPNext associé est incohérent : ' + name)
    return native


def delivery_before_cancel(doc):
    invoice = _linked(doc, 'Sales Invoice', 'sales_invoice', DELIVERY_LINK)
    note = _linked(doc, 'Delivery Note', 'delivery_note', DELIVERY_LINK)
    invoice.check_permission('cancel')
    note.check_permission('cancel')
    if frappe.db.exists('Payment Entry Reference', dict(reference_doctype='Sales Invoice', reference_name=invoice.name,
            docstatus=1, allocated_amount=['>', 0])):
        frappe.throw('Annuler ou désaffecter les règlements de la facture avant d’annuler ce bordereau.')
    with operation(DELIVERY, doc.name):
        invoice.cancel()
        note.reload()  # Invoice cancellation updates the delivery's billed amounts.
        note.cancel()
    doc.status = 'Annulé'


def _invoice(bl):
    invoice = _linked(bl, 'Sales Invoice', 'sales_invoice', DELIVERY_LINK)
    if (invoice.customer, invoice.company, invoice.currency) != (bl.customer, bl.company, bl.currency):
        frappe.throw('La facture ne correspond pas au compte du bordereau.')
    return invoice


def _party_factor(invoice):
    currency = invoice.party_account_currency or frappe.get_cached_value('Account', invoice.debit_to, 'account_currency')
    if currency == invoice.currency:
        return 1
    company_currency = frappe.get_cached_value('Company', invoice.company, 'default_currency')
    if currency == company_currency and flt(invoice.conversion_rate) > 0:
        return flt(invoice.conversion_rate)
    frappe.throw('La devise du compte client ne permet pas ce rapprochement automatique.')


def payment_limit(bl, payment):
    invoice = _invoice(bl)
    already = 0
    if payment and payment.get('payment_entry'):
        native = _linked(payment, 'Payment Entry', 'payment_entry', PAYMENT_LINK)
        already = sum(flt(row.allocated_amount) for row in native.references if
            row.reference_doctype == 'Sales Invoice' and row.reference_name == invoice.name)
    return max(0, (flt(invoice.outstanding_amount) + already) / _party_factor(invoice))


def _allocated_invoices(doc):
    result = []
    for row in doc.allocations:
        bl = frappe.get_doc(DELIVERY, row.bordereau, for_update=True)
        bl.check_permission('read')
        if bl.docstatus != 1 or (bl.company, bl.customer, bl.currency) != (doc.company, doc.customer, doc.currency):
            frappe.throw('Affecter uniquement des bordereaux validés du même compte client.')
        if (bl.get('order_type') or 'B') == 'B':
            continue  # The B part of a shared receipt never enters customer GL.
        if bl.get('order_type') != 'A':
            frappe.throw('Le circuit du bordereau affecté est incohérent.')
        invoice = _invoice(bl)
        result.append((invoice, flt(row.amount) * _party_factor(invoice)))
    if len({invoice.debit_to for invoice, _ in result}) > 1:
        frappe.throw('Les factures doivent utiliser le même compte client pour un règlement commun.')
    return result


def _invoice_factor(invoices):
    factor = _party_factor(invoices[0][0])
    if any(abs(_party_factor(invoice) - factor) > 1e-12 for invoice, _ in invoices):
        frappe.throw('Ces factures utilisent des taux différents vers le compte client. Enregistrer des règlements séparés par taux.')
    return factor


def _bank_account(doc):
    mode = frappe.get_doc('Mode of Payment', doc.mode_of_payment)
    mode.check_permission('read')
    if not mode.enabled:
        frappe.throw('Le mode de règlement est désactivé.')
    account = next((row.default_account for row in mode.accounts if row.company == doc.company), None)
    if not account:
        frappe.throw('Configurer le compte de banque ou caisse du mode de règlement pour cette société.')
    record = frappe.get_doc('Account', account)
    record.check_permission('read')
    if record.company != doc.company or record.is_group or record.disabled or record.account_type not in ('Bank', 'Cash'):
        frappe.throw('Le compte du mode de règlement doit être une banque ou caisse active de cette société.')
    return account


def _make_payment(doc):
    from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry
    from .special_b import accounting_amount
    amount_a = accounting_amount(doc)
    invoices = _allocated_invoices(doc)
    if invoices:
        seed, factor = invoices[0][0], _invoice_factor(invoices)
    else:
        if not doc.get('sales_order'):
            frappe.throw('Choisir une commande A pour enregistrer une avance.')
        seed = _get_order(doc.sales_order)
        if flt(seed.per_billed) >= 100:
            # The order helper rightly rejects an advance against a fully billed
            # order. A native invoice can seed an unallocated customer receipt.
            invoices_for_order = frappe.db.sql('''SELECT DISTINCT s.name FROM `tabSales Invoice` s
                JOIN `tabSales Invoice Item` i ON i.parent=s.name
                WHERE i.sales_order=%s AND s.docstatus=1 AND s.is_return=0
                ORDER BY s.name DESC LIMIT 1''', seed.name, pluck=True)
            if not invoices_for_order:
                frappe.throw('Aucune facture validée ne permet de préparer ce règlement de commande facturée.')
            seed = frappe.get_doc('Sales Invoice', invoices_for_order[0])
            seed.check_permission('read')
            factor = _party_factor(seed)
        else:
            from erpnext.accounts.party import get_party_account
            party_account = get_party_account('Customer', doc.customer, doc.company)
            currency = frappe.get_cached_value('Account', party_account, 'account_currency')
            factor = 1 if currency == doc.currency else flt(seed.conversion_rate)
            if currency not in (doc.currency, frappe.get_cached_value('Company', doc.company, 'default_currency')) or not factor:
                frappe.throw('La devise du compte client ne permet pas cette avance automatique.')
    bank_account = _bank_account(doc)
    payment = get_payment_entry(seed.doctype, seed.name, party_amount=amount_a * factor,
        bank_account=bank_account, payment_type='Receive', reference_date=doc.posting_date,
        created_from_payment_request=True)
    payment.set('references', [])
    payment.set('deductions', [])
    payment.posting_date = doc.posting_date
    payment.reference_no = doc.reference
    payment.reference_date = doc.posting_date
    payment.mode_of_payment = doc.mode_of_payment
    # A mode copied from the invoice/order may override the helper's bank_account
    # argument. The operational receipt's chosen mode is authoritative.
    payment.paid_to = bank_account
    payment.paid_to_account_currency = frappe.get_cached_value('Account', bank_account, 'account_currency')
    payment.paid_to_account_type = frappe.get_cached_value('Account', bank_account, 'account_type')
    payment.paid_to_account_balance = None
    payment.paid_amount = amount_a * factor
    payment.set(PAYMENT_LINK, doc.name)
    # Leave any excess as a native unallocated customer advance, without a second
    # receipt or a duplicate reference to an order already represented by invoices.
    for invoice, amount in invoices:
        payment.append('references', dict(reference_doctype='Sales Invoice', reference_name=invoice.name,
            allocated_amount=amount))
    payment.set_missing_values()
    payment.set_missing_ref_details(force=True)
    payment.set_exchange_rate()
    payment.received_amount = flt(payment.paid_amount * payment.source_exchange_rate /
        payment.target_exchange_rate, payment.precision('received_amount'))
    payment.set_amounts()
    return payment


def payment_on_submit(doc):
    from .special_b import accounting_amount
    if accounting_amount(doc) <= EPS:
        return
    _permissions('Payment Entry', 'create', 'submit')
    _existing_native(doc, 'Payment Entry', 'payment_entry')
    with operation(PAYMENT, doc.name):
        payment = _make_payment(doc)
        payment.insert()
        payment.submit()
        doc.db_set('payment_entry', payment.name, update_modified=False)


def payment_before_cancel(doc):
    if not doc.get('payment_entry'):
        return
    payment = _linked(doc, 'Payment Entry', 'payment_entry', PAYMENT_LINK)
    payment.check_permission('cancel')
    with operation(PAYMENT, doc.name):
        payment.cancel()


def payment_after_update_after_submit(doc):
    """Use the native unreconciliation/reconciliation tools on the same receipt."""
    previous = doc.get_doc_before_save()
    if previous and [(r.bordereau, flt(r.amount)) for r in previous.allocations] == [
            (r.bordereau, flt(r.amount)) for r in doc.allocations]:
        return
    from .special_b import accounting_amount
    old_amount = accounting_amount(previous) if previous else 0
    new_amount = accounting_amount(doc)
    if not doc.get('payment_entry'):
        if new_amount > EPS:
            payment_on_submit(doc)
        return
    if abs(new_amount - old_amount) > EPS:
        # Reclassifying part of a receipt between A and B changes its accounting
        # amount. Reverse the old native entry and create one replacement for A.
        # Both operations remain in the same transaction, with one active PE.
        with operation(PAYMENT, doc.name):
            payment_before_cancel(doc)
            doc.db_set('payment_entry', None, update_modified=False)
            if new_amount > EPS:
                payment_on_submit(doc)
        return
    payment = _linked(doc, 'Payment Entry', 'payment_entry', PAYMENT_LINK)
    payment.check_permission('write')
    _permissions('Payment Reconciliation', 'write')
    _permissions('Unreconcile Payment', 'create', 'submit')
    invoices = _allocated_invoices(doc)
    if invoices and abs(flt(new_amount * _invoice_factor(invoices), payment.precision('paid_amount')) -
                        flt(payment.paid_amount)) > EPS:
        frappe.throw('Le taux du nouveau lettrage diffère de celui du règlement. Annuler le règlement avant de le corriger.')
    # An external reconciliation would make this form's allocations misleading.
    # Generated PEs are guarded against direct edits; also verify persisted data.
    allowed = {frappe.db.get_value(DELIVERY, row.bordereau, 'sales_invoice') for row in previous.allocations}
    active_refs = [row for row in payment.references if flt(row.allocated_amount) > EPS]
    if any(row.reference_doctype != 'Sales Invoice' or row.reference_name not in allowed for row in active_refs):
        frappe.throw('Le règlement ERPNext a été rapproché hors de ce formulaire. Vérifier ses références.')
    with operation(PAYMENT, doc.name):
        if active_refs:
            undo = frappe.new_doc('Unreconcile Payment')
            undo.company = doc.company
            undo.voucher_type = 'Payment Entry'
            undo.voucher_no = payment.name
            undo.add_references()
            if not undo.allocations:
                frappe.throw('Le lettrage existant est introuvable. Vérifier le règlement ERPNext.')
            undo.insert()
            undo.submit()
            payment.reload()
        if not invoices:
            return
        reconciliation = frappe.new_doc('Payment Reconciliation')
        reconciliation.company = doc.company
        reconciliation.party_type = 'Customer'
        reconciliation.party = doc.customer
        reconciliation.receivable_payable_account = invoices[0][0].debit_to
        reconciliation.default_advance_account = payment.paid_from if payment.book_advance_payments_in_separate_party_account else None
        reconciliation.payment_name = payment.name
        reconciliation.payment_limit = reconciliation.invoice_limit = 0
        reconciliation.get_unreconciled_entries()
        sources = [row for row in reconciliation.payments if row.reference_type == 'Payment Entry' and row.reference_name == payment.name]
        for source in sources:
            source.unreconciled_amount = source.amount
        pending_invoices = {row.invoice_number: row for row in reconciliation.invoices
                            if row.invoice_type == 'Sales Invoice'}
        for invoice, amount in invoices:
            target = pending_invoices.get(invoice.name)
            if not target:
                frappe.throw('La facture ne présente plus de montant à rapprocher : ' + invoice.name)
            target.exchange_rate = invoice.conversion_rate
            left = amount
            for source in sources:
                if left <= EPS:
                    break
                available = max(0, flt(source.amount))
                take = min(available, left)
                if take <= EPS:
                    continue
                row = reconciliation.get_allocated_entry(source, target, take)
                row.exchange_rate = invoice.conversion_rate
                row.difference_amount = reconciliation.get_difference_amount(source, target, take)
                row.difference_account = frappe.get_cached_value('Company', doc.company, 'exchange_gain_loss_account')
                row.gain_loss_posting_date = doc.posting_date
                reconciliation.append('allocation', row)
                source.amount -= take
                left -= take
            if left > EPS:
                frappe.throw('Le montant disponible du règlement ERPNext est insuffisant pour cette affectation.')
        reconciliation.validate_allocation()
        reconciliation.reconcile_allocations()


def guard_native(doc, method=None):
    field, parenttype = (PAYMENT_LINK, PAYMENT) if doc.doctype == 'Payment Entry' else (DELIVERY_LINK, DELIVERY)
    link = doc.get(field)
    stored = frappe.db.get_value(doc.doctype, doc.name, field) if not doc.is_new() else None
    if not link and not stored:
        return
    if stored and stored != link:
        frappe.throw('Le lien avec le document spécial ne peut pas être modifié.')
    if frappe.flags.get('ug_special_a_operation') != (parenttype, link):
        frappe.throw('Utiliser le document spécial associé pour modifier ou annuler ce document ERPNext.')
    parent = frappe.get_doc(parenttype, link)
    allowed_circuit = parent.get('order_type') in ('A', 'Mixte')
    if parenttype == PAYMENT and method in ('before_cancel', 'on_cancel'):
        # Allocation changes may have reclassified the saved receipt as B just
        # before its obsolete A accounting entry is reversed.
        allowed_circuit = True
    if not allowed_circuit or parent.company != doc.company:
        frappe.throw('Le document spécial associé doit appartenir au circuit A et à la même société.')
    if doc.doctype == 'Payment Entry':
        if doc.party_type != 'Customer' or doc.party != parent.customer or doc.payment_type != 'Receive':
            frappe.throw('Le règlement ERPNext doit encaisser le client du règlement spécial.')
    else:
        if doc.customer != parent.customer:
            frappe.throw('Le client du document spécial ne correspond pas.')
        if doc.doctype == 'Sales Invoice' and doc.update_stock:
            frappe.throw('La sortie de stock est déjà réalisée par le bon de livraison associé.')
    # Native on_cancel implementations replace this list. Extend it from an
    # on_cancel hook, after the controller, rather than bypassing all link checks.
    if method == 'on_cancel':
        ignored = list(doc.get('ignore_linked_doctypes') or getattr(doc, 'ignore_linked_doctypes', []) or [])
        if parenttype not in ignored:
            ignored.append(parenttype)
        doc.ignore_linked_doctypes = ignored


def install():
    from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
    create_custom_fields({doctype: [dict(fieldname=DELIVERY_LINK, label='Bordereau Spécial', fieldtype='Link',
        options=DELIVERY, read_only=1, no_copy=1, insert_after='customer', allow_on_submit=0)]
        for doctype in ('Delivery Note', 'Sales Invoice')}, update=True)
    create_custom_fields({'Payment Entry': [dict(fieldname=PAYMENT_LINK, label='Règlement Spécial', fieldtype='Link',
        options=PAYMENT, read_only=1, no_copy=1, insert_after='party', allow_on_submit=0)]}, update=True)
    for doctype, field in (('Delivery Note', DELIVERY_LINK), ('Sales Invoice', DELIVERY_LINK), ('Payment Entry', PAYMENT_LINK)):
        frappe.db.add_index(doctype, [field, 'docstatus'])
