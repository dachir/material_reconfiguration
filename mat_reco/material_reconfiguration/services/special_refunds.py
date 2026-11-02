"""Refund only the unused cash of one receipt; never reverse a real receipt.

All balance decisions share special_b's company lock. The standard document
transaction rolls back the refund, native Pay entry and source totals together.
"""
import frappe
from frappe.utils import flt, getdate


def is_refund(doc):
    return doc.get('payment_kind') == 'Remboursement'


def refunded(source, exclude=None):
    rows = frappe.db.sql('''SELECT amount FROM `tabReglement Special`
        WHERE refund_of=%s AND payment_kind='Remboursement' AND docstatus=1 AND name!=%s
        FOR UPDATE''', (source, exclude or ''), pluck=True)
    return sum(flt(amount) for amount in rows)


def available(source, exclude=None):
    from .special_b import money
    return money(flt(source.amount) - sum(flt(row.amount) for row in source.allocations)
        - refunded(source.name, exclude), source.currency)


def origin(doc):
    if not doc.get('refund_of') or doc.refund_of == doc.name:
        frappe.throw('Choisir le règlement encaissé à rembourser.')
    source = frappe.get_doc('Reglement Special', doc.refund_of, for_update=True)
    source.check_permission('read')
    from .commercial_special_actions import _fields, _table
    _fields('Reglement Special', ['company', 'customer', 'currency', 'sales_order', 'amount', 'posting_date', 'payment_kind', 'payment_entry'])
    _table('Reglement Special', 'allocations', ['bordereau', 'amount'])
    if source.docstatus != 1 or is_refund(source):
        frappe.throw('Rembourser uniquement une avance encaissée et validée.')
    return source


def validate(doc):
    from . import special_b as b
    b.access()
    # Same lock order as receipts and allocation changes.
    frappe.get_doc('Company', doc.company).check_permission('read')
    frappe.db.get_value('Company', doc.company, 'name', for_update=True)
    source = origin(doc)
    if doc.docstatus == 2:
        return
    for field in ('company', 'customer', 'currency', 'sales_order'):
        if (doc.get(field) or '') != (source.get(field) or ''):
            frappe.throw('Le remboursement doit reprendre le compte et la commande de son avance.')
    if getdate(doc.posting_date) < getdate(source.posting_date):
        frappe.throw('Le remboursement ne peut pas précéder l’encaissement.')
    if doc.allocations:
        frappe.throw('Un remboursement ne peut pas être affecté à un bordereau.')
    doc.amount = b.money(b.number(doc.amount, positive=True), doc.currency)
    if doc.amount <= 0 or doc.amount > available(source, doc.name) + b.EPS:
        frappe.throw('Le remboursement dépasse le montant encore disponible de l’avance.')
    doc.reference = str(doc.get('reference') or '').strip()
    if not doc.reference:
        frappe.throw('Référence du remboursement requise.')
    duplicate = frappe.db.sql('''SELECT name FROM `tabReglement Special`
        WHERE company=%s AND customer=%s AND currency=%s AND reference=%s AND docstatus<2 AND name!=%s
        FOR UPDATE''', (doc.company, doc.customer, doc.currency, doc.reference, doc.name or ''))
    if duplicate:
        frappe.throw('Cette référence de règlement existe déjà pour ce client et cette devise.')
    old = doc.get_doc_before_save()
    if (doc.is_new() and doc.get('payment_entry')) or (old and old.get('payment_entry') != doc.get('payment_entry')):
        frappe.throw('Le paiement ERPNext associé ne peut pas être remplacé.')
    if doc.get('sales_order'):
        order = frappe.get_doc('Sales Order', doc.sales_order)
        order.check_permission('read')  # Also permits refunds after cancellation.
        doc.order_type = order.get('custom_ug_order_type') or 'A'
    else:
        doc.order_type = source.get('order_type') or 'B'
    if doc.order_type not in ('A', 'B'):
        frappe.throw('Choisir la commande source de l’avance mixte avant remboursement.')
    b.cutover(doc)
    doc.allocated_amount = doc.unallocated_amount = doc.refunded_amount = 0
    doc.status = 'Validé' if doc.docstatus == 1 else 'Brouillon'


def sync_source(doc):
    from .special_b import money
    source = origin(doc)
    total = refunded(source.name)
    source.db_set(dict(refunded_amount=money(total, source.currency),
        unallocated_amount=available(source)), update_modified=True)


def on_submit(doc):
    if doc.order_type == 'A':
        make_native_refund(doc)
    sync_source(doc)


def make_native_refund(doc):
    from . import special_a as a
    a._permissions('Payment Entry', 'create', 'submit')
    a._existing_native(doc, 'Payment Entry', 'payment_entry')
    source = origin(doc)
    if not source.get('payment_entry'):
        frappe.throw('L’avance A ne possède pas d’encaissement ERPNext validé.')
    received = a._linked(source, 'Payment Entry', 'payment_entry', a.PAYMENT_LINK)
    received.check_permission('read')
    if received.docstatus != 1 or received.payment_type != 'Receive':
        frappe.throw('L’encaissement ERPNext d’origine doit être validé.')
    from .special_b import accounting_amount
    original_amount = accounting_amount(source)
    if original_amount <= 0:
        frappe.throw('Aucune avance comptable A disponible.')
    factor = flt(received.paid_amount) / original_amount
    bank = a._bank_account(doc)
    payment = frappe.new_doc('Payment Entry')
    payment.update(dict(payment_type='Pay', party_type='Customer', party=doc.customer,
        company=doc.company, posting_date=doc.posting_date, mode_of_payment=doc.mode_of_payment,
        reference_no=doc.reference, reference_date=doc.posting_date,
        paid_from=bank, paid_to=received.paid_from,
        paid_from_account_currency=frappe.get_cached_value('Account', bank, 'account_currency'),
        paid_to_account_currency=received.paid_from_account_currency,
        received_amount=doc.amount * factor))
    payment.set(a.PAYMENT_LINK, doc.name)
    from mat_reco.material_reconfiguration.utils.accounting_dimensions import get_active_accounting_dimension_fields
    for field in get_active_accounting_dimension_fields():
        if payment.meta.has_field(field):
            payment.set(field, received.get(field))
    payment.cost_center = received.get('cost_center')
    # Standard reverse payments are created unallocated, then reconciled with
    # the original receipt through ERPNext's Payment Reconciliation tool.
    payment.setup_party_account_field()
    payment.set_missing_values()
    payment.set_missing_ref_details(force=True)
    payment.set_exchange_rate()
    payment.paid_amount = flt(payment.received_amount * payment.target_exchange_rate /
        payment.source_exchange_rate, payment.precision('paid_amount'))
    payment.set_amounts()
    with a.operation('Reglement Special', doc.name):
        payment.insert()
        payment.submit()
        doc.db_set('payment_entry', payment.name, update_modified=False)
    a._permissions('Payment Reconciliation', 'write')
    reconciliation = frappe.new_doc('Payment Reconciliation')
    reconciliation.company = doc.company
    reconciliation.party_type = 'Customer'
    reconciliation.party = doc.customer
    reconciliation.receivable_payable_account = received.paid_from
    reconciliation.default_advance_account = received.paid_from if received.book_advance_payments_in_separate_party_account else None
    reconciliation.payment_limit = reconciliation.invoice_limit = 0
    reconciliation.get_unreconciled_entries()
    invoices = [row.as_dict() for row in reconciliation.invoices if row.invoice_type == 'Payment Entry' and row.invoice_number == payment.name]
    payments = [row.as_dict() for row in reconciliation.payments if row.reference_type == 'Payment Entry' and row.reference_name == received.name]
    if len(invoices) != 1 or not payments:
        frappe.throw('L’avance ERPNext ne présente plus de montant à rembourser.')
    reconciliation.allocate_entries(frappe._dict(invoices=invoices, payments=payments))
    if abs(sum(flt(row.allocated_amount) for row in reconciliation.allocation) - doc.amount * factor) > .000001:
        frappe.throw('Le montant disponible de l’avance ERPNext est insuffisant.')
    with a.operation('Reglement Special', source.name):
        reconciliation.reconcile()


def build(source, action, selections, values):
    """Unsaved document, submitted only by the cockpit's idempotent facade."""
    from .commercial_special_actions import _fields, _date, _number, _text
    source.check_permission('read')
    editing = action in ('edit', 'validate') and is_refund(source)
    if editing:
        source.check_permission('write' if action == 'edit' else 'read')
        if source.docstatus != 0:
            frappe.throw('Un remboursement validé est immuable.')
        doc = frappe.get_doc(source.as_dict())
    else:
        if action != 'refund' or source.docstatus != 1 or is_refund(source):
            frappe.throw('Rembourser uniquement un encaissement validé.')
        frappe.has_permission('Reglement Special', 'create', throw=True)
        doc = frappe.new_doc('Reglement Special')
        doc.update({key: source.get(key) for key in ('company', 'customer', 'currency', 'sales_order')})
        doc.update(dict(payment_kind='Remboursement', refund_of=source.name))
    allowed = {'posting_date', 'amount', 'mode_of_payment', 'reference'}
    if not isinstance(values, dict) or set(values) - allowed or selections:
        frappe.throw('Les champs ou affectations du remboursement ne sont pas autorisés.')
    _fields('Reglement Special', allowed, 'write')
    for field, value in values.items():
        doc.set(field, _number(value, positive=True) if field == 'amount' else _date(value) if field == 'posting_date' else _text(value))
    return doc


def prepare(source, action):
    from frappe.utils import nowdate
    from .commercial_special_actions import _fields
    if not is_refund(source) and (source.docstatus != 1 or action != 'refund'):
        frappe.throw('Choisir un encaissement validé.')
    source.check_permission('read')
    _fields('Reglement Special', ['amount', 'unallocated_amount', 'refunded_amount', 'payment_kind', 'refund_of'])
    editing = is_refund(source)
    original = origin(source) if editing else source
    if not editing:
        frappe.has_permission('Reglement Special', 'create', throw=True)
    balance = available(original, source.name if editing else None)
    fields = [dict(fieldname='posting_date', label='Date du remboursement', fieldtype='Date', reqd=1),
        dict(fieldname='amount', label='Montant à rembourser', fieldtype='Currency', reqd=1),
        dict(fieldname='mode_of_payment', label='Mode de remboursement', fieldtype='Link', options='Mode of Payment', reqd=1),
        dict(fieldname='reference', label='Référence du remboursement', fieldtype='Data', reqd=1)]
    values = {field['fieldname']: source.get(field['fieldname']) for field in fields} if editing else dict(
        posting_date=nowdate(), amount=balance, mode_of_payment=source.mode_of_payment, reference='')
    return dict(target_doctype='Reglement Special', fields=[] if action == 'validate' else fields,
        values={} if action == 'validate' else values, rows=[], payment_kind='Remboursement',
        description='Remboursement de '+original.name+' · Disponible : '+str(balance)+' '+original.currency,
        refund_of=original.name, company=original.company, customer=original.customer, currency=original.currency)
