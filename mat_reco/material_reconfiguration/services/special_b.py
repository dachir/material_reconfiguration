"""Shared operational documents: native accounting for A, separate balances for B.

Stock remains native ERPNext: no valuation override and no suppressed stock GL.
A company row lock serializes deliveries, allocations, reversals and cutover imports.
"""
import math
from collections import defaultdict
from contextlib import contextmanager

import frappe
from frappe.utils import flt, getdate, get_datetime, cint, nowdate
from . import order_b_stock as stock
from .order_b import can_access

DELIVERY='Bordereau Special'
PAYMENT='Reglement Special'
OPENING='Solde Initial Client B'
EPS=.000001


def sales_order_dashboard(data):
    transactions = data.setdefault("transactions", [])
    existing = {doctype for group in transactions for doctype in group.get("items", [])}
    items = [doctype for doctype in (DELIVERY, PAYMENT) if doctype not in existing]
    if items:
        transactions.append({"label": frappe._("Livraisons et règlements"), "items": items})
    data.setdefault("non_standard_fieldnames", {}).update({DELIVERY: "sales_order", PAYMENT: "sales_order"})
    return data


def permission(doc=None,user=None,ptype=None):
    if not can_access(user):return False
    return None


def query_conditions(user=None):
    # The same callback serves both documents; the table name is supplied through
    # distinct wrappers below to keep SQL conditions explicit and permission-safe.
    return '' if can_access(user) else '1=0'


def delivery_query_conditions(user=None):
    return query_conditions(user)


def payment_query_conditions(user=None):
    return query_conditions(user)


def access():
    if not can_access():frappe.throw('Accès aux modules spéciaux requis.',frappe.PermissionError)


def number(value,positive=False):
    value=flt(value)
    if not math.isfinite(value) or (positive and value<=0):frappe.throw('Saisir un montant ou une quantité finie et positive.')
    return value


def money(value,currency):
    return flt(value,0 if currency in ('XOF','XAF') else cint(frappe.db.get_default('currency_precision') or 2))


def get_order(name,lock=False):
    """Shared A/B entry point; direct B stock APIs keep their original B-only guard."""
    if not any(frappe.has_permission(dt,'read') for dt in (DELIVERY,PAYMENT)):
        frappe.throw('Accès aux livraisons ou règlements spéciaux requis.',frappe.PermissionError)
    order=frappe.get_doc('Sales Order',name)
    order.check_permission('read')
    if lock:
        frappe.db.get_value('Company',order.company,'name',for_update=True)
        order=frappe.get_doc('Sales Order',name,for_update=True)
    if order.docstatus!=1 or order.get('custom_ug_order_type') not in ('A','B'):
        frappe.throw('Une commande A ou B validée est requise.')
    if order.custom_ug_order_type=='B':access()
    return order


def account(doc,lock=True):
    access()
    frappe.get_doc('Company',doc.company).check_permission('read')
    frappe.get_doc('Customer',doc.customer).check_permission('read')
    if lock:frappe.db.get_value('Company',doc.company,'name',for_update=True)
    if lock and doc.doctype in (DELIVERY,PAYMENT,OPENING) and not doc.is_new() and doc.get('_original_modified'):
        current=frappe.db.get_value(doc.doctype,doc.name,'modified',for_update=True)
        if current and get_datetime(current)!=get_datetime(doc._original_modified):
            frappe.throw('Le document a été modifié par une autre session. Actualiser avant de continuer.',frappe.TimestampMismatchError)
    kinds=set()
    source_kind=None
    if doc.get('sales_order'):
        order=get_order(doc.sales_order,lock=lock)
        if order.company!=doc.company or order.customer!=doc.customer or order.currency!=doc.currency:
            frappe.throw('La société, le client et la devise doivent correspondre à la commande.')
        source_kind=order.custom_ug_order_type
    for row in doc.get('allocations') or []:
        if row.bordereau:
            bl=frappe.get_doc(DELIVERY,row.bordereau);bl.check_permission('read')
            kinds.add(bl.get('order_type') or 'B')
    if source_kind:kinds.add(source_kind)
    kind='Mixte' if len(kinds)>1 else next(iter(kinds)) if kinds else doc.get('order_type') or 'B'
    if kind not in ('A','B','Mixte'):frappe.throw('Le type des pièces du règlement est invalide.')
    if doc.doctype==PAYMENT and kind=='Mixte' and not source_kind:
        remainder=flt(doc.amount)-sum(flt(row.amount) for row in doc.allocations)
        if remainder>EPS:frappe.throw('Sélectionner la commande source de l’avance pour affecter le montant non réparti du règlement mixte.')
    if doc.doctype==OPENING and kind!='B':frappe.throw('Les soldes initiaux spéciaux concernent uniquement le circuit B.')
    if doc.doctype!=OPENING:doc.order_type=kind
    if kind in ('B','Mixte') and not frappe.db.exists('Sales Order',dict(company=doc.company,customer=doc.customer,custom_ug_order_type='B')):
        frappe.throw('Ce client ne possède aucune commande B dans cette société.')


def cutover(doc):
    """Opening balances are beginning-of-day snapshots, entered before live activity."""
    if doc.get('order_type')=='A':return
    rows=frappe.db.sql('''SELECT posting_date,sales_order FROM `tabSolde Initial Client B`
        WHERE company=%s AND customer=%s AND currency=%s AND docstatus=1 FOR UPDATE''',
        (doc.company,doc.customer,doc.currency),as_dict=True)
    scopes={doc.get('sales_order')} - {None,''}
    if doc.doctype==PAYMENT:
        scopes.update(frappe.db.get_value(DELIVERY,r.bordereau,'sales_order') for r in doc.allocations
                      if (frappe.db.get_value(DELIVERY,r.bordereau,'order_type') or 'B')=='B')
    for opening in rows:
        if (not opening.sales_order or not scopes or opening.sales_order in scopes) and getdate(doc.posting_date)<getdate(opening.posting_date):
            frappe.throw('La date précède le solde initial B. Ne pas réimporter les mouvements historiques déjà repris dans ce solde.')


def allocated(bordereau,exclude_payment=None,lock=False):
    return flt(frappe.db.sql('''SELECT COALESCE(SUM(a.amount),0) FROM `tabReglement Special Allocation` a
        JOIN `tabReglement Special` p ON p.name=a.parent WHERE p.docstatus=1 AND a.bordereau=%s AND p.name!=%s'''+(' FOR UPDATE' if lock else ''),
        (bordereau,exclude_payment or ''))[0][0])


def delivered(order,exclude=None,lock=False):
    """Commercial quantities including old direct issues, without counting linked issues twice."""
    result=defaultdict(float)
    if order.custom_ug_order_type=='A':
        result.update({row.name:max(0,flt(row.delivered_qty)) for row in order.items})
        return result
    for r in frappe.db.sql('''SELECT i.sales_order_item,SUM(i.qty) qty FROM `tabBordereau Special Item` i
        JOIN `tabBordereau Special` b ON b.name=i.parent
        WHERE b.sales_order=%s AND b.docstatus=1 AND b.name!=%s GROUP BY i.sales_order_item'''+(' FOR UPDATE' if lock else ''),(order.name,exclude or ''),as_dict=True):
        result[r.sales_order_item]+=flt(r.qty)
    for r in frappe.db.sql('''SELECT i.custom_sales_order_item,SUM(i.qty*i.conversion_factor) qty
        FROM `tabStock Entry Detail` i JOIN `tabStock Entry` s ON s.name=i.parent
        WHERE s.custom_ug_b_sales_order=%s AND s.docstatus=1 AND COALESCE(s.custom_ug_special_delivery,'')=''
        GROUP BY i.custom_sales_order_item'''+(' FOR UPDATE' if lock else ''),order.name,as_dict=True):
        row=next((i for i in order.items if i.name==r.custom_sales_order_item),None)
        if row:result[row.name]+=flt(r.qty)/(flt(row.conversion_factor) or 1)
    return result


def delivery_validate(doc):
    if doc.docstatus==2:return
    account(doc)
    order=get_order(doc.sales_order,lock=True)
    if order.status in ('Closed','On Hold'):frappe.throw('Commande clôturée ou suspendue.')
    cutover(doc)
    prior=doc.get_doc_before_save()
    if prior and any(prior.get(f)!=doc.get(f) for f in ('stock_entry','adopt_existing_stock','delivery_note','sales_invoice')):
        frappe.throw('La sortie associée ne peut pas être remplacée.')
    if order.custom_ug_order_type=='A' and (doc.get('adopt_existing_stock') or doc.get('stock_entry')):
        frappe.throw('Une livraison A utilise un Delivery Note, sans sortie directe B.')
    if doc.is_new() and (doc.get('delivery_note') or doc.get('sales_invoice')):
        frappe.throw('Les documents ERPNext sont créés automatiquement à la validation du bordereau.')
    if not doc.items:frappe.throw('Ajouter au moins un article à livrer.')
    if len(doc.items)>500:frappe.throw('Un bordereau accepte au maximum 500 lignes.')
    booked=delivered(order,exclude=doc.name,lock=True)
    existing=None
    if doc.get('adopt_existing_stock'):
        existing=frappe.get_doc('Stock Entry',doc.stock_entry,for_update=True);existing.check_permission('read')
        if existing.docstatus!=1 or existing.custom_ug_b_sales_order!=order.name or existing.stock_entry_type!='Material Issue':
            frappe.throw('Une sortie B validée de cette commande est requise.')
        if getdate(existing.posting_date)!=getdate(doc.posting_date):frappe.throw('La reprise doit conserver la date de la sortie existante.')
        if existing.get('custom_ug_special_delivery') and existing.custom_ug_special_delivery!=doc.name:frappe.throw('Cette sortie possède déjà un bordereau.')
        if frappe.db.exists(DELIVERY,{'stock_entry':existing.name,'docstatus':['<',2],'name':['!=',doc.name or '']}):frappe.throw('Cette sortie possède déjà un bordereau.')
        for line in existing.items:
            source=next((r for r in order.items if r.name==line.custom_sales_order_item),None)
            if source and not existing.get('custom_ug_special_delivery'):booked[source.name]-=flt(line.qty)/(flt(source.conversion_factor) or 1)
    elif doc.get('stock_entry') and doc.docstatus==0:frappe.throw('Utiliser la reprise contrôlée pour rattacher une sortie existante.')
    sources={r.name:r for r in order.items};seen=set();net=0;basis=0
    for row in doc.items:
        source=sources.get(row.sales_order_item)
        if not source or row.sales_order_item in seen:frappe.throw('Ligne inconnue ou dupliquée dans la commande.')
        seen.add(row.sales_order_item)
        row.qty=number(row.qty,positive=True)
        row.item_code=source.item_code;row.item_name=source.item_name;row.uom=source.uom
        row.length_mm=source.get('custom_client_length_mm');row.width_mm=source.get('custom_client_width_mm');row.thickness_mm=source.get('custom_client_thickness_mm')
        row.ordered_qty=source.qty;row.delivered_qty=max(0,booked[source.name]);row.remaining_qty=max(0,flt(source.qty)-row.delivered_qty)
        if row.qty>row.remaining_qty+EPS:frappe.throw('La quantité à livrer dépasse le reste de la commande : '+source.item_code)
        row.rate=flt(source.net_amount)/flt(source.qty) if source.qty else 0
        row.currency=doc.currency
        row.amount=money(row.rate*(row.delivered_qty+row.qty),order.currency)-money(row.rate*row.delivered_qty,order.currency)
        net+=row.amount;basis+=row.rate*row.qty
        row.warehouse=row.warehouse or doc.get('warehouse') or source.warehouse
        if frappe.get_cached_value('Item',row.item_code,'is_stock_item'):
            if not row.warehouse:frappe.throw('Un dépôt est requis pour les articles physiques.')
            wh=frappe.get_doc('Warehouse',row.warehouse);wh.check_permission('read')
            if wh.company!=doc.company or wh.is_group:frappe.throw('Dépôt incompatible avec la société du BL.')
    if existing:
        actual=defaultdict(float)
        for line in existing.items:actual[line.custom_sales_order_item]+=flt(line.qty)
        expected={r.sales_order_item:flt(r.qty)*(flt(sources[r.sales_order_item].conversion_factor) or 1) for r in doc.items if frappe.get_cached_value('Item',r.item_code,'is_stock_item')}
        if set(actual)!=set(expected) or any(abs(actual[k]-expected[k])>EPS for k in actual):frappe.throw('Les lignes reprises doivent correspondre exactement à la sortie existante.')
        for row in doc.items:
            originals=[r for r in existing.items if r.custom_sales_order_item==row.sales_order_item]
            if not originals:continue
            if len({r.s_warehouse for r in originals})!=1 or len({r.batch_no or '' for r in originals})!=1:
                frappe.throw('Reprendre séparément les sorties comportant plusieurs dépôts ou lots pour une même ligne.')
            row.warehouse=originals[0].s_warehouse;row.batch_no=originals[0].batch_no
            row.serial_no='\n'.join(serial for r in originals for serial in stock._serials(r))
    # B deliveries settle the commercial net amount only; order taxes are excluded.
    # Row amounts already distribute currency rounding across partial deliveries.
    doc.net_total=money(net,doc.currency)
    doc.billing_basis=basis
    doc.grand_total=doc.net_total
    if doc.net_total<0:frappe.throw('Un bordereau de livraison ne peut pas avoir un montant négatif.')
    doc.tax_amount=0
    if order.custom_ug_order_type=='A':
        from . import special_a
        special_a.delivery_validate(doc,order)
    doc.status='Validé' if doc.docstatus==1 else 'Brouillon'
    from .production_reservations import fill_delivery
    fill_delivery(doc)


@contextmanager
def stock_context(name):
    before=frappe.flags.get('ug_special_delivery_operation');frappe.flags.ug_special_delivery_operation=name
    try:yield
    finally:frappe.flags.ug_special_delivery_operation=before


def delivery_on_submit(doc):
    # Validation/row locks above and the stock transaction share the request transaction.
    order=get_order(doc.sales_order,lock=True)
    if order.custom_ug_order_type=='A':
        from . import special_a
        return special_a.delivery_on_submit(doc,order)
    sources={r.name:r for r in order.items}
    physical=[r for r in doc.items if frappe.get_cached_value('Item',r.item_code,'is_stock_item')]
    with stock_context(doc.name):
        if doc.adopt_existing_stock:
            entry=frappe.get_doc('Stock Entry',doc.stock_entry)
            entry.db_set('custom_ug_special_delivery',doc.name,update_modified=False)
        elif physical:
            selected=[dict(sales_order_item=r.sales_order_item,warehouse=r.warehouse,
                qty=flt(r.qty)*(flt(sources[r.sales_order_item].conversion_factor) or 1),
                serials=[s.strip() for s in (r.serial_no or '').splitlines() if s.strip()],batch_no=r.batch_no) for r in physical]
            name=stock.create_issue(doc.sales_order,selected,'bordereau:'+doc.name,
                accounting_dimensions=doc.accounting_dimensions_json or '{}',special_delivery=doc.name,posting_date=doc.posting_date)
            doc.db_set('stock_entry',name,update_modified=False)
    doc.db_set('status','Validé',update_modified=False)


def delivery_before_cancel(doc):
    account(doc)
    if allocated(doc.name,lock=True)>EPS:frappe.throw('Retirer les affectations de règlements avant d’annuler ce bordereau.')
    if doc.get('order_type')=='A':
        from . import special_a
        return special_a.delivery_before_cancel(doc)
    if doc.stock_entry:
        entry=frappe.get_doc('Stock Entry',doc.stock_entry)
        if entry.docstatus!=1:frappe.throw('La sortie associée doit être validée avant annulation du bordereau.')
        entry.ignore_linked_doctypes=[DELIVERY]
        with stock_context(doc.name):entry.cancel()
    doc.status='Annulé'


def guard_stock(doc,method=None):
    link=doc.get('custom_ug_special_delivery')
    if not link:return
    # Only the BL controller can create/reverse its linked movement.
    if frappe.flags.get('ug_special_delivery_operation')!=link:
        frappe.throw('Utiliser le Bordereau Spécial pour créer ou annuler sa sortie de stock.')
    bl=frappe.get_doc(DELIVERY,link)
    if bl.sales_order!=doc.custom_ug_b_sales_order:frappe.throw('Sortie de stock liée à une autre commande B.')


def payment_validate(doc):
    if doc.docstatus==2:return
    account(doc);cutover(doc)
    doc.amount=money(number(doc.amount,positive=True),doc.currency)
    if doc.amount<=0:frappe.throw('Montant encaissé supérieur à zéro requis.')
    if not str(doc.reference or '').strip():frappe.throw('Référence du règlement requise.')
    # One bank/cash reference per account prevents repeated imports of the same receipt.
    doc.reference=str(doc.reference).strip()
    duplicate=frappe.db.sql('''SELECT name FROM `tabReglement Special` WHERE company=%s AND customer=%s
        AND currency=%s AND reference=%s AND docstatus<2 AND name!=%s FOR UPDATE''',
        (doc.company,doc.customer,doc.currency,doc.reference,doc.name or ''))
    if duplicate:frappe.throw('Cette référence de règlement existe déjà pour ce client et cette devise.')
    prior=doc.get_doc_before_save()
    if (doc.is_new() and doc.get('payment_entry')) or (prior and prior.get('payment_entry')!=doc.get('payment_entry')):
        frappe.throw('Le Payment Entry associé ne peut pas être remplacé.')
    if len(doc.allocations)>500:frappe.throw('Un règlement accepte au maximum 500 affectations.')
    seen=set();total=0
    for row in doc.allocations:
        if row.bordereau in seen:frappe.throw('Un BL ne peut apparaître qu’une fois dans les affectations.')
        seen.add(row.bordereau)
        bl=frappe.get_doc(DELIVERY,row.bordereau,for_update=True);bl.check_permission('read')
        if bl.docstatus!=1 or (bl.company,bl.customer,bl.currency)!=(doc.company,doc.customer,doc.currency):frappe.throw('Affecter uniquement des bordereaux validés du même client, de la même société et de la même devise.')
        row.amount=money(number(row.amount,positive=True),doc.currency)
        row.currency=doc.currency
        if bl.get('order_type')=='A':
            from .special_a import payment_limit
            available=payment_limit(bl,doc)
        else:available=flt(bl.net_total)-allocated(bl.name,doc.name,lock=True)
        if row.amount<=0 or row.amount>available+EPS:frappe.throw('L’affectation dépasse le solde du BL.')
        total+=row.amount
    if total>doc.amount+EPS:frappe.throw('Les affectations dépassent le montant encaissé.')
    doc.allocated_amount=money(total,doc.currency);doc.unallocated_amount=money(doc.amount-total,doc.currency)
    doc.status='Validé' if doc.docstatus==1 else 'Brouillon'


def payment_before_update_after_submit(doc):
    # Only allocations may change after receipt validation. The receipt header is immutable.
    old=doc.get_doc_before_save()
    for field in ('company','customer','currency','sales_order','posting_date','amount','mode_of_payment','reference','payment_entry'):
        before,after=old.get(field),doc.get(field)
        equal=(getdate(before)==getdate(after)) if field=='posting_date' else (flt(before)==flt(after)) if field=='amount' else (before or '')==(after or '')
        if not equal:frappe.throw('Les données du règlement validé sont immuables. Annuler avant correction.')
    payment_validate(doc)


def payment_before_cancel(doc):
    account(doc)
    if doc.get('payment_entry'):
        from . import special_a
        special_a.payment_before_cancel(doc)
    doc.status='Annulé'


def payment_on_submit(doc):
    if doc.get('order_type') in ('A','Mixte'):
        from . import special_a
        special_a.payment_on_submit(doc)


def payment_after_update_after_submit(doc):
    if doc.get('order_type') in ('A','Mixte') or doc.get('payment_entry'):
        from . import special_a
        special_a.payment_after_update_after_submit(doc)


def opening_validate(doc):
    if doc.docstatus==2:return
    account(doc)
    doc.amount=money(number(doc.amount),doc.currency)
    if not doc.amount:frappe.throw('Un solde initial non nul est requis.')
    doc.migration_reference=str(doc.migration_reference or '').strip()
    if not doc.migration_reference:frappe.throw('Référence unique de reprise requise.')
    scope=dict(company=doc.company,customer=doc.customer,currency=doc.currency,docstatus=1)
    for other in frappe.db.sql('''SELECT name,sales_order FROM `tabSolde Initial Client B`
        WHERE company=%s AND customer=%s AND currency=%s AND docstatus=1 FOR UPDATE''',
        (doc.company,doc.customer,doc.currency),as_dict=True):
        if other.name!=doc.name and (not other.sales_order or not doc.sales_order or other.sales_order==doc.sales_order):
            frappe.throw('Un solde initial recouvre déjà ce compte B. Éviter une double reprise historique.')
    for dt in (DELIVERY,PAYMENT):
        filters=dict(scope,posting_date=['<',doc.posting_date],order_type=['in',['B','Mixte']] if dt==PAYMENT else 'B')
        if doc.sales_order and dt!=PAYMENT:filters['sales_order']=doc.sales_order
        if dt==PAYMENT:
            exists=any(payment_share(frappe.get_doc(PAYMENT,name),doc.sales_order)>EPS
                       for name in frappe.get_all(PAYMENT,filters=filters,pluck='name'))
        else:exists=frappe.db.exists(dt,filters)
        if exists:frappe.throw('Des mouvements B antérieurs existent déjà : ne pas les ajouter à nouveau dans le solde initial.')


def opening_before_cancel(doc):
    account(doc)
    filters=dict(company=doc.company,customer=doc.customer,currency=doc.currency,docstatus=1)
    deliveries=dict(filters,order_type='B')
    if doc.sales_order:deliveries['sales_order']=doc.sales_order
    payments=frappe.get_all(PAYMENT,filters=dict(filters,order_type=['in',['B','Mixte']]),pluck='name')
    if frappe.db.exists(DELIVERY,deliveries) or any(
            payment_share(frappe.get_doc(PAYMENT,name),doc.sales_order)>EPS for name in payments):
        frappe.throw('Annuler les mouvements B du compte avant d’annuler sa reprise d’ouverture.')


@frappe.whitelist()
def make_delivery(sales_order):
    order=get_order(sales_order)
    frappe.has_permission(DELIVERY,'create',throw=True)
    booked=delivered(order)
    from .ug_warehouse import operational_warehouse, is_glass
    stores=operational_warehouse(order.company)
    other_stock=any(not is_glass(r.item_code) and frappe.get_cached_value('Item',r.item_code,'is_stock_item') for r in order.items)
    preferred=stores if any(is_glass(r.item_code) for r in order.items) and not other_stock else None
    doc=frappe.new_doc(DELIVERY)
    doc.update(dict(company=order.company,customer=order.customer,sales_order=order.name,currency=order.currency,
        posting_date=nowdate(),order_type=order.custom_ug_order_type,warehouse=preferred or order.set_warehouse or next((r.warehouse for r in order.items if r.warehouse),None)))
    for row in order.items:
        remaining=max(0,flt(row.qty)-booked[row.name])
        if remaining>EPS:doc.append('items',dict(sales_order_item=row.name,item_code=row.item_code,item_name=row.item_name,
            ordered_qty=row.qty,delivered_qty=booked[row.name],remaining_qty=remaining,qty=remaining,uom=row.uom,warehouse=(stores if is_glass(row.item_code) else None) or row.warehouse or doc.warehouse))
    if not doc.items:frappe.throw('Cette commande est déjà entièrement livrée ou sortie du stock.')
    from .ug_warehouse import apply_defaults
    apply_defaults(doc)
    delivery_validate(doc)
    return doc.as_dict()


@frappe.whitelist()
def get_delivery_data(sales_order):
    return stock.issue_data(get_order(sales_order))


@frappe.whitelist()
def make_payment(sales_order=None,bordereau=None):
    frappe.has_permission(PAYMENT,'create',throw=True)
    if bordereau:
        bl=frappe.get_doc(DELIVERY,bordereau);bl.check_permission('read')
        if bl.docstatus!=1:frappe.throw('Valider le BL avant de l’affecter.')
        doc=frappe.new_doc(PAYMENT);doc.update({k:bl.get(k) for k in ('company','customer','currency','sales_order','order_type')})
        doc.posting_date=nowdate()
        if bl.get('order_type')=='A':
            from .special_a import payment_limit
            balance=payment_limit(bl,doc)
        else:balance=max(0,flt(bl.net_total)-allocated(bl.name))
        doc.amount=balance
        doc.append('allocations',dict(bordereau=bl.name,amount=balance));return doc.as_dict()
    order=get_order(sales_order)
    doc=frappe.new_doc(PAYMENT)
    doc.update(dict(company=order.company,customer=order.customer,currency=order.currency,sales_order=order.name,posting_date=nowdate(),order_type=order.custom_ug_order_type))
    return doc.as_dict()


@frappe.whitelist(methods=['POST'])
def make_from_issue(stock_entry):
    entry=frappe.get_doc('Stock Entry',stock_entry);entry.check_permission('read')
    order=stock.get_order(entry.custom_ug_b_sales_order)
    frappe.has_permission(DELIVERY,'create',throw=True)
    doc=frappe.new_doc(DELIVERY);doc.update(dict(company=order.company,customer=order.customer,sales_order=order.name,currency=order.currency,
        posting_date=entry.posting_date,adopt_existing_stock=1,stock_entry=entry.name))
    sources={r.name:r for r in order.items}
    for row in entry.items:
        source=sources.get(row.custom_sales_order_item)
        if not source:frappe.throw('Ligne de sortie sans correspondance dans la commande B.')
        doc.append('items',dict(sales_order_item=source.name,qty=flt(row.qty)/(flt(source.conversion_factor) or 1),warehouse=row.s_warehouse,
            serial_no='\n'.join(stock._serials(row)),batch_no=row.batch_no))
    doc.insert();return doc.name


def payment_share(payment,sales_order=None,circuit='B'):
    """Attribute the one receipt to its actual A/B pieces, including mixed receipts."""
    kind=payment.get('order_type') or 'B'
    if not sales_order and kind==circuit:return flt(payment.amount)
    share=0
    for row in payment.allocations:
        bl=frappe.db.get_value(DELIVERY,row.bordereau,['sales_order','order_type'],as_dict=True)
        if bl and (bl.order_type or 'B')==circuit and (not sales_order or bl.sales_order==sales_order):
            share+=flt(row.amount)
    remainder=flt(payment.amount)-sum(flt(r.amount) for r in payment.allocations)
    source_kind=frappe.db.get_value('Sales Order',payment.sales_order,'custom_ug_order_type') if payment.sales_order else kind
    if source_kind==circuit and (not sales_order or payment.sales_order==sales_order):share+=remainder
    return share


def accounting_amount(doc):
    return money(payment_share(doc,circuit='A'),doc.currency)


@frappe.whitelist()
def get_order_summary(sales_order):
    order=get_order(sales_order)
    deliveries=frappe.get_list(DELIVERY,filters={'sales_order':order.name},fields=['name','company','customer','currency','posting_date','docstatus','net_total','grand_total','stock_entry','delivery_note','sales_invoice','order_type'],order_by='posting_date,name',limit_page_length=0)
    for bl in deliveries:
        if order.custom_ug_order_type=='B':bl.grand_total=bl.net_total
        bl.received=allocated(bl.name) if bl.docstatus==1 else 0
        if order.custom_ug_order_type=='A' and bl.docstatus==1:
            from .special_a import payment_limit
            bl.balance=payment_limit(bl,None)
            bl.received=flt(bl.grand_total)-bl.balance
        else:bl.balance=flt(bl.net_total)-bl.received if bl.docstatus==1 else 0
    payments=[]
    for record in frappe.get_list(PAYMENT,filters=dict(company=order.company,customer=order.customer,currency=order.currency,docstatus=1,order_type=['in',[order.custom_ug_order_type,'Mixte']]),pluck='name',limit_page_length=0):
        p=frappe.get_doc(PAYMENT,record);share=payment_share(p,order.name,circuit=order.custom_ug_order_type)
        if share:payments.append(dict(name=p.name,posting_date=p.posting_date,amount=share,unallocated_amount=p.unallocated_amount if p.sales_order==order.name else 0))
    opening=sum(flt(r.amount) for r in frappe.get_list(OPENING,filters={'sales_order':order.name,'docstatus':1},fields=['amount'],limit_page_length=0))
    amounts=sum(flt(b.grand_total) for b in deliveries if b.docstatus==1)
    receipts=sum(p['amount'] for p in payments)
    booked=delivered(order)
    rows=[dict(sales_order_item=r.name,item_code=r.item_code,item_name=r.item_name,ordered_qty=r.qty,delivered_qty=booked[r.name],remaining_qty=max(0,flt(r.qty)-booked[r.name]),uom=r.uom) for r in order.items]
    return dict(deliveries=deliveries,payments=payments,items=rows,opening=opening,delivery_amount=amounts,received=receipts,
        balance=money(opening+amounts-receipts,order.currency),currency=order.currency)


def install():
    for dt in ('Bordereau Special Item',DELIVERY,'Reglement Special Allocation',PAYMENT,OPENING):
        frappe.reload_doc('material_reconfiguration','doctype',frappe.scrub(dt))
    stock.install()
    from . import special_a
    special_a.install()
    from mat_reco.printing import install_print_formats
    install_print_formats()
    frappe.reload_doc('material_reconfiguration','report','situation_des_comptes_clients_b')
    frappe.db.add_index(DELIVERY,['sales_order','docstatus'])
    frappe.db.add_index(DELIVERY,['stock_entry','docstatus'])
    frappe.db.add_index('Reglement Special Allocation',['bordereau'])
    frappe.db.add_index(PAYMENT,['company','customer','currency','docstatus'])
    if frappe.db.exists('Workspace','Univers Glass'):
        import json
        workspace=frappe.get_doc('Workspace','Univers Glass')
        label='Situation des comptes clients B'
        if not any(r.label==label for r in workspace.shortcuts):
            workspace.append('shortcuts',dict(label=label,type='Report',link_to=label,color='Orange'))
            content=json.loads(workspace.content or '[]');content.append(dict(id='ug-b-balances',type='shortcut',data=dict(shortcut_name=label,col=4)))
            workspace.content=json.dumps(content,ensure_ascii=False);workspace.save(ignore_permissions=True)
