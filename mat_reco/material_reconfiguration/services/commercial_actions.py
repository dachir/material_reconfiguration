"""Permission-checked modal operations over existing commercial documents.

The modal is only an editor. Native controllers, workflows and special-delivery
services remain responsible for validation, stock and accounting. A technical
Commercial Operation record makes retries durable in the same transaction.
"""
import json
import math
import uuid

import frappe
from frappe.utils import add_days, flt, get_datetime, nowdate

from .chantier_service import fingerprint

SOURCES = {'Chantier', 'Quotation', 'Sales Order', 'Bordereau Special', 'Reglement Special'}
SPECIAL = {'Bordereau Special', 'Reglement Special'}
EPS = .000001
MAX_ROWS = 500
JOURNAL = 'Commercial Operation'
HEADERS = {
    'Quotation': {'transaction_date', 'valid_till', 'terms'},
    'Sales Order': {'transaction_date', 'delivery_date', 'po_no', 'po_date', 'terms',
        'acceptance_reference', 'order_type'},
    'Chantier': set(),
}
ALIASES = {'acceptance_reference': 'custom_customer_acceptance', 'order_type': 'custom_ug_order_type'}


def _access():
    if not (frappe.has_permission('Bordereau Special', 'read') or frappe.has_permission('Reglement Special', 'read')):
        frappe.throw('Accès en lecture aux bordereaux spéciaux ou règlements spéciaux requis.', frappe.PermissionError)


def _json(value, expected):
    try:
        value = frappe.parse_json(value) if isinstance(value, str) else value
    except (ValueError, TypeError):
        frappe.throw('Données de la fenêtre invalides.')
    if value is None:
        value = expected()
    if not isinstance(value, expected):
        frappe.throw('Données de la fenêtre invalides.')
    return value


def _positive(value, label='Quantité'):
    if isinstance(value, bool):
        frappe.throw(label + ' positive requise.')
    try:
        number = float(value)
    except (ValueError, TypeError, OverflowError):
        frappe.throw(label + ' positive requise.')
    if not math.isfinite(number) or number <= 0:
        frappe.throw(label + ' positive requise.')
    return number


def _source(doctype, name, lock=False, allow_cancelled=False):
    if not isinstance(doctype, str) or doctype not in SOURCES or not name or not isinstance(name, str):
        frappe.throw('Document source non pris en charge.')
    doc = frappe.get_doc(doctype, name, for_update=lock)
    doc.check_permission('read')
    if doc.docstatus == 2 and not allow_cancelled:
        frappe.throw('Ce document est annulé.')
    return doc


def _target(source, action, check_state=True):
    if not isinstance(action, str) or action not in ('quotation', 'order', 'delivery', 'payment', 'edit', 'validate', 'allocate'):
        frappe.throw('Action commerciale inconnue.')
    if action == 'allocate' and source.doctype == 'Reglement Special' and (not check_state or source.docstatus == 1):
        return source.doctype
    if action in ('edit', 'validate') and (not check_state or source.docstatus == 0):
        if action == 'edit' and source.doctype == 'Chantier':
            frappe.throw('Modifier les ouvrages depuis la page Chantier.')
        return source.doctype
    allowed = {('Chantier', 'quotation'): 'Quotation', ('Quotation', 'order'): 'Sales Order',
        ('Sales Order', 'delivery'): 'Bordereau Special', ('Sales Order', 'payment'): 'Reglement Special',
        ('Bordereau Special', 'payment'): 'Reglement Special'}
    if (check_state and source.docstatus != 1) or (source.doctype, action) not in allowed:
        frappe.throw('Cette opération ne correspond pas à l’état du document.')
    return allowed[source.doctype, action]


def _workflow(doctype):
    from frappe.model.workflow import get_workflow_name
    return get_workflow_name(doctype)


def submission(doc):
    """Expose only native, explicit, currently permitted progression actions."""
    from frappe.model.workflow import get_transitions, get_workflow, has_approval_access
    workflow_name = _workflow(doc.doctype)
    is_new = doc.is_new()
    values = dict(can_save=bool(frappe.has_permission(doc.doctype, 'create') if is_new else doc.has_permission('write')),
        can_submit=bool(not workflow_name and doc.docstatus == 0 and doc.meta.is_submittable and
            doc.has_permission('submit')), workflow_name=workflow_name or '', workflow_actions=[])
    if workflow_name and not is_new:
        workflow = get_workflow(doc.doctype)
        states = {row.state: int(row.doc_status or 0) for row in workflow.states}
        for transition in get_transitions(doc, workflow):
            status = states.get(transition.next_state)
            if status not in (0, 1) or not has_approval_access(frappe.session.user, doc, transition):
                continue
            if status == 1 and doc.docstatus == 0 and not doc.has_permission('submit'):
                continue
            values['workflow_actions'].append(dict(action=transition.action, label=transition.action,
                next_state=transition.next_state, docstatus=status))
    return values


def _field(name, label, fieldtype='Data', **kwargs):
    return dict(fieldname=name, label=label, fieldtype=fieldtype, **kwargs)


def _fields(doctype):
    fields = []
    if doctype in ('Quotation', 'Sales Order'):
        fields.append(_field('transaction_date', 'Date', 'Date', reqd=1))
    if doctype == 'Quotation':
        fields.append(_field('valid_till', 'Valable jusqu’au', 'Date'))
    if doctype == 'Sales Order':
        fields += [_field('delivery_date', 'Date de livraison', 'Date', reqd=1),
            _field('acceptance_reference', 'Référence de l’acceptation client'),
            _field('order_type', 'Type de commande', 'Select', options='A\nB', reqd=1),
            _field('po_no', 'Commande du client'), _field('po_date', 'Date de commande du client', 'Date')]
    if doctype in ('Quotation', 'Sales Order'):
        fields.append(_field('terms', 'Conditions', 'Text Editor'))
    meta = frappe.get_meta(doctype)
    readable = set(meta.get_permitted_fieldnames(permission_type='read'))
    writable = set(meta.get_permitted_fieldnames(permission_type='write'))
    return [field for field in fields if ALIASES.get(field['fieldname'], field['fieldname']) in readable & writable]


def _values(doc, fields):
    result = {field['fieldname']: doc.get(ALIASES.get(field['fieldname'], field['fieldname'])) for field in fields}
    if 'transaction_date' in result:
        result['transaction_date'] = result['transaction_date'] or nowdate()
    if 'delivery_date' in result:
        result['delivery_date'] = result['delivery_date'] or nowdate()
    if 'order_type' in result:
        result['order_type'] = result['order_type'] or 'A'
    return result


def _headers(doc, values):
    allowed = HEADERS.get(doc.doctype, set())
    if set(values) - allowed:
        frappe.throw('Des champs non modifiables ont été transmis.')
    permitted = set(doc.meta.get_permitted_fieldnames(permission_type='write'))
    for field, value in values.items():
        actual = ALIASES.get(field, field)
        if actual not in permitted:
            frappe.throw('Modification du champ non autorisée : ' + field, frappe.PermissionError)
        if field == 'order_type' and value not in ('A', 'B'):
            frappe.throw('Choisir une commande A ou B.')
        if isinstance(value, (dict, list)):
            frappe.throw('Valeur de champ invalide.')
        doc.set(actual, value)
    if doc.doctype == 'Sales Order':
        for row in doc.get('items', []):
            row.delivery_date = doc.delivery_date


def _row(row, identity=None, used=0, parent_id=None):
    qty = flt(row.get('qty'))
    remaining = max(0, qty - flt(used))
    return dict(id=identity or row.name, label=row.get('repere') or row.get('item_name') or row.get('designation') or row.get('item_code') or identity or row.name,
        item_code=row.get('item_code') or row.get('sale_item') or row.get('proposed_item'),
        description=row.get('description') or row.get('designation') or row.get('item_name') or '',
        qty=remaining, ordered_qty=qty, processed_qty=flt(used), remaining_qty=remaining,
        uom=row.get('uom'), rate=flt(row.get('rate')), amount=remaining * flt(row.get('rate')),
        parent_id=parent_id, selected=remaining > EPS and not parent_id, readonly=bool(parent_id))


def _read_rows(source, tablefield):
    table = source.meta.get_field(tablefield)
    if not table or (table.permlevel or 0) not in source.meta.get_permlevel_access('read'):
        frappe.throw('Lecture des lignes du document requise.', frappe.PermissionError)
    meta = frappe.get_meta(table.options)
    allowed = set(meta.get_permitted_fieldnames(parenttype=source.doctype, permission_type='read')) | {'name'}
    critical = {'qty', 'rate'} | ({'line_id'} if source.doctype == 'Chantier' else set())
    if source.doctype == 'Chantier':
        critical.update(field for field in ('price_per_sqm', 'discount_percentage', 'length_mm', 'width_mm') if meta.has_field(field))
    critical.update(field for field in ('custom_parent_row', 'parent_line_id') if meta.has_field(field))
    if critical - allowed:
        frappe.throw('Lecture des quantités, prix et liens des lignes requise.', frappe.PermissionError)
    return [frappe._dict({field: row.get(field) for field in allowed}) for row in source.get(tablefield, [])]


def _order_usage(quote_name, exclude=None):
    # Residual control includes drafts and hidden orders. It returns quantities,
    # never their identities or commercial amounts, and is guarded by the source.
    rows = frappe.db.sql('''SELECT i.quotation_item, SUM(i.qty) qty FROM `tabSales Order Item` i
        JOIN `tabSales Order` p ON p.name=i.parent
        WHERE i.prevdoc_docname=%s AND p.docstatus<2 AND p.name!=%s
        GROUP BY i.quotation_item''', (quote_name, exclude or ''), as_dict=True)
    return {row.quotation_item: flt(row.qty) for row in rows}


def _quote_rows(source):
    from .chantier_service import get_quotation_usage
    from .chantier_pricing import unit_rate
    from .chantier_discounts import percentage
    usage = get_quotation_usage(source)
    lines = _read_rows(source, 'lines')
    rows = [_row(row, row.line_id, usage.get(row.line_id, 0)) for row in lines]
    for row, macro in zip(rows, lines):
        row['rate'] = unit_rate(macro) * (1 - percentage(source, macro) / 100)
        row['amount'] = row['rate'] * row['qty']
        row['uom'] = macro.get('uom') or 'PC'
        row['must_be_whole_number'] = True
    parents = {row.line_id: row for row in lines}
    extras = _read_rows(source, 'commercial_extras') if source.get('commercial_extras') else []
    for extra in extras:
        parent = parents.get(extra.parent_line_id)
        if parent and flt(parent.qty) > 0:
            used = flt(extra.qty) * flt(usage.get(parent.line_id)) / flt(parent.qty)
            row = _row(extra, extra.line_id, used, extra.parent_line_id)
            row['rate'] = unit_rate(extra) * (1 - percentage(source, extra) / 100)
            row['amount'] = row['rate'] * row['qty']
            rows.append(row)
    return rows


def _commercial_rows(source, action):
    if action == 'quotation':
        return _quote_rows(source)
    usage = _order_usage(source.name) if action == 'order' else {}
    rows = [_row(row, used=usage.get(row.name, 0), parent_id=row.get('custom_parent_row'))
        for row in _read_rows(source, 'items')]
    if action == 'edit':
        _draft_limits(source, rows)
    return rows


def _draft_limits(source, rows):
    """A draft may grow up to the current residual of its original source."""
    children = {row.name: row for row in source.get('items', [])}
    if source.doctype == 'Quotation' and source.get('custom_chantier'):
        from .chantier_service import get_quotation_usage
        parent = frappe.get_doc('Chantier', source.custom_chantier)
        parent.check_permission('read')
        usage = get_quotation_usage(parent)
        lines = _read_rows(parent, 'lines')
        extras = _read_rows(parent, 'commercial_extras') if parent.get('commercial_extras') else []
        original = {row.line_id: row for row in lines + extras}
        for row in rows:
            child = children[row['id']]
            origin = original.get(child.get('custom_chantier_line'))
            if not origin:
                frappe.throw('Ligne d’origine du chantier introuvable.')
            row['remaining_qty'] = max(0, flt(origin.qty) - usage.get(origin.line_id, 0) + flt(child.qty))
    elif source.doctype == 'Sales Order':
        for name in sorted({row.prevdoc_docname for row in children.values() if row.get('prevdoc_docname')}):
            quote = frappe.get_doc('Quotation', name)
            quote.check_permission('read')
            original = {row.name: row for row in _read_rows(quote, 'items')}
            usage = _order_usage(name, exclude=source.name)
            for row in rows:
                child = children[row['id']]
                if child.prevdoc_docname != name:
                    continue
                origin = original.get(child.quotation_item)
                if not origin:
                    frappe.throw('Ligne du devis d’origine introuvable.')
                row['remaining_qty'] = max(0, flt(origin.qty) - usage.get(origin.name, 0))


def _selection(rows, selections):
    """Select stable parent IDs, deriving service/accessory quantities server-side."""
    indexed = {row['id']: row for row in rows}
    if not selections or len(selections) > MAX_ROWS or len(indexed) != len(rows):
        frappe.throw('Sélectionner des lignes distinctes.')
    chosen = {}
    for incoming in selections:
        if not isinstance(incoming, dict) or set(incoming) - {'id', 'qty'}:
            frappe.throw('Sélection de ligne invalide.')
        identity = incoming.get('id')
        if not isinstance(identity, str) or not identity or len(identity) > 140:
            frappe.throw('Identifiant de ligne invalide.')
        row = indexed.get(identity)
        if not row or identity in chosen:
            frappe.throw('Ligne inconnue ou sélectionnée deux fois.')
        quantity = _positive(incoming.get('qty'))
        if row.get('must_be_whole_number') and not quantity.is_integer():
            frappe.throw('Une quantité entière est requise pour cet ouvrage.')
        if quantity > flt(row['remaining_qty']) + EPS:
            frappe.throw('La quantité sélectionnée dépasse le reste disponible.')
        chosen[identity] = quantity
    for identity, quantity in list(chosen.items()):
        row = indexed[identity]
        if row.get('parent_id'):
            parent = indexed.get(row['parent_id'])
            if not parent or parent['id'] not in chosen:
                frappe.throw('Un service ou accessoire doit accompagner son ouvrage.')
            expected = flt(row['ordered_qty']) * chosen[parent['id']] / flt(parent['ordered_qty'])
            if abs(quantity - expected) > EPS:
                frappe.throw('La quantité du complément doit suivre celle de son ouvrage.')
    for row in rows:
        parent_id = row.get('parent_id')
        if parent_id not in chosen:
            continue
        parent = indexed[parent_id]
        if flt(parent['ordered_qty']) <= 0:
            frappe.throw('Quantité de référence du parent invalide.')
        expected = flt(row['ordered_qty']) * chosen[parent_id] / flt(parent['ordered_qty'])
        if expected > flt(row['remaining_qty']) + EPS or expected <= 0:
            frappe.throw('Le complément ne dispose plus de la quantité nécessaire.')
        chosen[row['id']] = expected
    return chosen


def _build_order(source, selections, values):
    from erpnext.selling.doctype.quotation.quotation import make_sales_order
    rows = _commercial_rows(source, 'order')
    chosen = _selection(rows, selections)
    doc = frappe.new_doc('Sales Order')
    calculate = doc.calculate_taxes_and_totals

    def calculate_partial():
        # The native mapper calculates before returning. A full fixed discount
        # can exceed a small selection unless scoped before that first call.
        for row in doc.get('items', []):
            if row.get('quotation_item') in chosen:
                row.qty = chosen[row.quotation_item]
                row.stock_qty = row.qty * (flt(row.conversion_factor) or 1)
        _scale_order_charges(source, doc, chosen)
        calculate()

    doc.calculate_taxes_and_totals = calculate_partial
    try:
        make_sales_order(source.name, target_doc=doc, args={'filtered_children': list(chosen)})
    finally:
        del doc.calculate_taxes_and_totals
    mapped = {row.quotation_item: row for row in doc.get('items', [])}
    if set(mapped) != set(chosen):
        frappe.throw('Certaines lignes ne sont plus commandables. Actualiser la fenêtre.')
    for name, quantity in chosen.items():
        row = mapped[name]
        row.qty = quantity
        row.stock_qty = quantity * (flt(row.conversion_factor) or 1)
    _headers(doc, values)
    _scale_order_charges(source, doc, chosen)
    doc.run_method('calculate_taxes_and_totals')
    return doc


def _scale_order_charges(quote, order, chosen):
    """Allocate actual charges once, including earlier standard/draft orders."""
    fixed = [row for row in quote.get('taxes', []) if row.charge_type == 'Actual']
    discount = bool(flt(quote.get('discount_amount')) and not flt(quote.get('additional_discount_percentage')))
    if not fixed and not discount:
        return
    basis = sum(flt(row.amount) for row in quote.items)
    if basis <= 0:
        frappe.throw('Les frais fixes nécessitent une base commerciale positive.')
    previous = frappe.db.sql('''SELECT DISTINCT p.name FROM `tabSales Order` p
        JOIN `tabSales Order Item` i ON i.parent=p.name
        WHERE i.prevdoc_docname=%s AND p.docstatus<2 AND p.name!=%s''',
        (quote.name, order.name or ''), pluck=True)
    applied_discount = 0
    applied = {row.idx: 0 for row in fixed}
    for name in previous:
        prior = frappe.get_doc('Sales Order', name)
        taxes = [row for row in prior.get('taxes', []) if row.charge_type == 'Actual' and flt(row.tax_amount)]
        if {row.prevdoc_docname for row in prior.items} != {quote.name}:
            if flt(prior.discount_amount) or taxes:
                frappe.throw('Une commande précédente regroupe plusieurs devis avec des remises ou frais fixes non attribuables. Vérifier cette commande avant de poursuivre.')
            continue
        applied_discount += flt(prior.discount_amount)
        for tax in taxes:
            candidates = [row for row in fixed if (row.account_head, row.description) == (tax.account_head, tax.description)]
            match = next((row for row in candidates if row.idx == tax.idx), None)
            if match is None and len(candidates) == 1:
                match = candidates[0]
            if match is None and candidates:
                frappe.throw('Les frais fixes d’une commande précédente sont ambigus.')
            if match:
                applied[match.idx] += flt(tax.tax_amount)
    usage = _order_usage(quote.name, exclude=order.name)
    cumulative = sum(flt(row.amount) * min(flt(row.qty), usage.get(row.name, 0) + chosen.get(row.name, 0)) / flt(row.qty)
        for row in quote.items if flt(row.qty) > 0)

    def portion(value, consumed, precision):
        sign = -1 if flt(value) < 0 else 1
        total, consumed = sign * flt(value), sign * flt(consumed)
        target = flt(total * min(1, cumulative / basis), precision)
        return sign * flt(min(max(0, target - consumed), max(0, total - consumed)), precision)

    if discount:
        order.discount_amount = portion(quote.discount_amount, applied_discount, order.precision('discount_amount'))
    for source, target in zip(quote.get('taxes', []), order.get('taxes', [])):
        if source.charge_type == 'Actual':
            target.tax_amount = portion(source.tax_amount, applied[source.idx], target.precision('tax_amount'))


def _edit(source, selections, values):
    source.check_permission('write')
    if source.docstatus != 0:
        frappe.throw('Seul un brouillon peut être modifié.')
    if selections:
        table = source.meta.get_field('items')
        if not table or (table.permlevel or 0) not in source.meta.get_permlevel_access('write'):
            frappe.throw('Modification de la table des articles non autorisée.', frappe.PermissionError)
        childmeta = frappe.get_meta(table.options)
        if 'qty' not in childmeta.get_permitted_fieldnames(parenttype=source.doctype, permission_type='write'):
            frappe.throw('Modification des quantités non autorisée.', frappe.PermissionError)
        rows = _commercial_rows(source, 'edit')
        chosen = _selection(rows, selections)
        for row in source.get('items', []):
            if row.name in chosen:
                row.qty = chosen[row.name]
        source.set('items', [row for row in source.get('items', []) if row.name in chosen])
        if source.doctype == 'Sales Order':
            sources = {row.prevdoc_docname for row in source.get('items', []) if row.prevdoc_docname}
            for name in sorted(sources):
                quote = frappe.get_doc('Quotation', name, for_update=True)
                quote.check_permission('read')
                usage = _order_usage(name, exclude=source.name)
                original = {row.name: row for row in _read_rows(quote, 'items')}
                for row in source.items:
                    if row.prevdoc_docname == name and (row.quotation_item not in original or
                            flt(row.qty) + usage.get(row.quotation_item, 0) > flt(original[row.quotation_item].qty) + EPS):
                        frappe.throw('La quantité commandée dépasse le reste disponible sur le devis.')
                fixed = bool(flt(quote.get('discount_amount')) and not flt(quote.get('additional_discount_percentage'))) or any(
                    row.charge_type == 'Actual' for row in quote.get('taxes', []))
                if fixed and len(sources) != 1:
                    frappe.throw('Modifier les quantités d’une commande regroupant plusieurs devis avec frais fixes depuis le formulaire standard.')
                _scale_order_charges(quote, source, {row.quotation_item: flt(row.qty) for row in source.items if row.prevdoc_docname == name})
    _headers(source, values)
    return source


def _prepare(source, action):
    target = _target(source, action)
    if target in SPECIAL:
        from .commercial_special_actions import prepare_special
        return prepare_special(source, action)
    editing = action in ('edit', 'validate', 'allocate')
    if editing:
        source.check_permission('write' if action == 'edit' else 'read')
        doc = source
    else:
        frappe.has_permission(target, 'create', throw=True)
        doc = frappe.new_doc(target)
    fields = [] if action == 'validate' else _fields(target)
    values = _values(doc, fields)
    rows = [] if action == 'validate' else _commercial_rows(source, action)
    if action == 'quotation':
        defaults = dict(transaction_date=nowdate(), valid_till=add_days(nowdate(), 30), terms=source.get('terms'))
        values.update({field: value for field, value in defaults.items() if field in values})
    if action == 'order':
        defaults = dict(transaction_date=nowdate(), delivery_date=source.get('delivery_date') or nowdate(),
            order_type='A', terms=source.get('terms'))
        values.update({field: value for field, value in defaults.items() if field in values})
        for field in fields:
            if field['fieldname'] == 'acceptance_reference':
                field['reqd'] = int(bool(source.get('custom_chantier')))
    return dict(target_doctype=target, fields=fields, values=values, rows=rows)


@frappe.whitelist()
def get_actions(source_doctype, source_name):
    _access()
    source = _source(source_doctype, source_name, allow_cancelled=True)
    result = []
    if source.docstatus == 0:
        permissions = submission(source)
        if source.doctype != 'Chantier' and permissions['can_save']:
            result.append(dict(action='edit', label='Modifier le brouillon'))
        if permissions['can_submit'] or permissions['workflow_actions']:
            result.append(dict(action='validate', label='Valider' if permissions['can_submit'] else 'Faire évoluer'))
    elif source.docstatus == 1:
        if source.doctype == 'Reglement Special' and source.has_permission('write'):
            result.append(dict(action='allocate', label='Affecter le règlement'))
        for action, target, label in [('quotation', 'Quotation', 'Créer un devis'),
                ('order', 'Sales Order', 'Créer une commande'), ('delivery', 'Bordereau Special', 'Livrer'),
                ('payment', 'Reglement Special', 'Enregistrer un règlement')]:
            allowed = (source.doctype, action) in {('Chantier', 'quotation'), ('Quotation', 'order'),
                ('Sales Order', 'delivery'), ('Sales Order', 'payment'), ('Bordereau Special', 'payment')}
            if allowed and frappe.has_permission(target, 'create'):
                result.append(dict(action=action, label=label))
    return result


@frappe.whitelist(methods=['POST'])
def prepare_action(source_doctype, source_name, action):
    _access()
    source = _source(source_doctype, source_name)
    prepared = _prepare(source, action)
    target = prepared['target_doctype']
    doc = source if action in ('edit', 'validate', 'allocate') else frappe.new_doc(target)
    prepared.update(action=action, title={'quotation':'Créer un devis', 'order':'Créer une commande',
        'delivery':'Préparer une livraison', 'payment':'Enregistrer un règlement', 'edit':'Modifier le brouillon',
        'validate':'Faire évoluer le document', 'allocate':'Affecter le règlement'}.get(action, action),
        source=dict(doctype=source.doctype, name=source.name, modified=str(source.modified)),
        submission=submission(doc))
    if action == 'allocate':
        prepared['submission'].update(can_submit=False, workflow_actions=[])
    permitted = set(source.meta.get_permitted_fieldnames(permission_type='read'))
    prepared.update({key: source.get(key) for key in ('company', 'currency') if key in permitted})
    customer_field = 'party_name' if source.doctype == 'Quotation' else 'customer'
    if customer_field in permitted:
        prepared['customer'] = source.get(customer_field)
    prepared['amount_label'] = 'Total lignes HT'
    return prepared


def _apply_intent(doc, intent, workflow_action):
    if intent not in ('save', 'submit', 'workflow'):
        frappe.throw('Action de validation invalide.')
    permissions = submission(doc)
    if intent == 'workflow':
        if not workflow_action or not any(row['action'] == workflow_action for row in permissions['workflow_actions']):
            frappe.throw('Transition non autorisée. Enregistrer puis actualiser les actions disponibles.', frappe.PermissionError)
    elif intent == 'submit':
        if permissions['workflow_name']:
            frappe.throw('Utiliser une transition du workflow ; la validation directe est désactivée.')
        doc.check_permission('submit')
        if not permissions['can_submit']:
            frappe.throw('Ce document ne peut pas être validé.', frappe.PermissionError)
    elif not permissions['can_save']:
        frappe.throw('Enregistrement non autorisé.', frappe.PermissionError)
    if doc.is_new():
        doc.check_permission('create')
        doc.insert()
    elif intent in ('save', 'submit'):
        doc.check_permission('write')
        doc.save()
    if intent == 'submit':
        doc.submit()
    elif intent == 'workflow':
        from frappe.model.workflow import apply_workflow
        doc = apply_workflow(doc.as_dict(), workflow_action) or doc
        doc.reload()
    return doc


def _result(doc, replay=False):
    doc.check_permission('read')
    return dict(document=dict(doctype=doc.doctype, name=doc.name, docstatus=int(doc.docstatus), modified=str(doc.modified)),
        message='Opération déjà réalisée.' if replay else 'Document validé.' if doc.docstatus == 1 else 'Brouillon enregistré.',
        replay=replay, submission=submission(doc))


@frappe.whitelist(methods=['POST'])
def execute_action(source_doctype, source_name, action, selections=None, values=None,
        source_modified=None, request_key=None, intent='save', workflow_action=None):
    _access()
    selections, values = _json(selections, list), _json(values, dict)
    if len(selections) > MAX_ROWS or not request_key or not isinstance(request_key, str) or len(request_key) > 100:
        frappe.throw('Clé de requête et sélection valides requises.')
    # Reject NaN/Infinity in the signed request, including optional special fields.
    try:
        json.dumps([selections, values], allow_nan=False)
    except (ValueError, TypeError):
        frappe.throw('Valeur numérique invalide.')
    source = _source(source_doctype, source_name)
    target = _target(source, action, check_state=False)
    key = fingerprint(dict(user=frappe.session.user, request_key=request_key))
    scope = fingerprint(dict(source_doctype=source_doctype, source_name=source_name, action=action,
        selections=sorted(selections, key=lambda row: str(row.get('id', ''))) if all(isinstance(row, dict) for row in selections) else selections,
        values=values, intent=intent, workflow_action=workflow_action))
    savepoint = 'commercial_' + uuid.uuid4().hex
    frappe.db.savepoint(savepoint)
    from .special_a import operation
    try:
        with operation(source.doctype, source.name):
            company = source.get('company')
            if company:
                frappe.db.get_value('Company', company, 'name', for_update=True)
            source = _source(source_doctype, source_name, lock=True)
            if source.get('company') != company:
                frappe.throw('La société du document a changé. Actualiser la fenêtre.', frappe.TimestampMismatchError)
            existing = frappe.db.get_value(JOURNAL, {'request_key': key}, ['scope', 'target_doctype', 'target_name'], as_dict=True, for_update=True)
            if existing:
                if existing.scope != scope:
                    frappe.throw('Cette clé correspond à une autre opération.')
                doc = frappe.get_doc(existing.target_doctype, existing.target_name)
                doc.check_permission('read')
                if doc.docstatus == 2:
                    frappe.throw('Le document créé par cette opération a été annulé.')
                return _result(doc, replay=True)
            try:
                current = bool(source_modified) and get_datetime(source.modified) == get_datetime(source_modified)
            except (ValueError, TypeError, OverflowError):
                current = False
            if not current:
                frappe.throw('Le document a changé. Actualiser la fenêtre avant de continuer.', frappe.TimestampMismatchError)
            _target(source, action)
            if action == 'allocate' and intent != 'save':
                frappe.throw('L’affectation conserve le règlement validé : utiliser Enregistrer.')
            if action not in ('edit', 'validate', 'allocate'):
                frappe.has_permission(target, 'create', throw=True)
            if target in SPECIAL:
                from .commercial_special_actions import build_special
                doc = build_special(source, action, selections, values)
            elif action == 'quotation':
                from .technical_study_service import generate_quotation
                chosen = _selection(_quote_rows(source), selections)
                parents = {row.line_id for row in source.lines}
                selected = [dict(line_id=name, qty=quantity) for name, quantity in chosen.items() if name in parents]
                name = generate_quotation(source.name, selections=selected, request_key=request_key, submit=False)
                doc = frappe.get_doc('Quotation', name)
                _headers(doc, values)
            elif action == 'order':
                doc = _build_order(source, selections, values)
            elif action == 'edit':
                doc = _edit(source, selections, values)
            else:
                if selections or values:
                    frappe.throw('Valider le document existant sans modifier ses données.')
                doc = source
            if intent == 'workflow' and (action == 'edit' or target in SPECIAL and action == 'validate'):
                doc.check_permission('write')
                doc.save()
            doc = _apply_intent(doc, intent, workflow_action)
            # Return the persisted native state (including controller updates),
            # and fail if a third-party hook unexpectedly rolled it back.
            doc.reload()
            result = _result(doc)
            # Technical journal only. All business documents above retain native
            # create/write/submit permissions and their normal controllers.
            prior_flag = frappe.flags.get('in_commercial_operation')
            frappe.flags.in_commercial_operation = True
            try:
                frappe.get_doc(dict(doctype=JOURNAL, request_key=key, user=frappe.session.user,
                    source_doctype=source.doctype, source_name=source.name, action=action, intent=intent,
                    scope=scope, target_doctype=doc.doctype, target_name=doc.name,
                    result_json=json.dumps(result, default=str))).insert(ignore_permissions=True)
            finally:
                frappe.flags.in_commercial_operation = prior_flag
            return result
    except Exception:
        frappe.db.rollback(save_point=savepoint)
        raise
