"""Delivery and customer balances for circuit B, separate from the customer GL.

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
        transactions.append({"label": frappe._("Circuit B"), "items": items})
    data.setdefault("non_standard_fieldnames", {}).update({DELIVERY: "sales_order", PAYMENT: "sales_order"})
    return data


def permission(doc=None,user=None,ptype=None):
    if not can_access(user):return False
    return None


def query_conditions(user=None):
    return '' if can_access(user) else '1=0'


def access():
    if not can_access():frappe.throw('Le rôle UG COMMANDES B est requis.',frappe.PermissionError)


def number(value,positive=False):
    value=flt(value)
    if not math.isfinite(value) or (positive and value<=0):frappe.throw('Saisir un montant ou une quantité finie et positive.')
    return value


def money(value,currency):
    return flt(value,0 if currency in ('XOF','XAF') else cint(frappe.db.get_default('currency_precision') or 2))


def account(doc,lock=True):
    access()
    frappe.get_doc('Company',doc.company).check_permission('read')
    frappe.get_doc('Customer',doc.customer).check_permission('read')
    if lock:frappe.db.get_value('Company',doc.company,'name',for_update=True)
    if lock and doc.doctype in (DELIVERY,PAYMENT,OPENING) and not doc.is_new() and doc.get('_original_modified'):
        current=frappe.db.get_value(doc.doctype,doc.name,'modified',for_update=True)
        if current and get_datetime(current)!=get_datetime(doc._original_modified):
            frappe.throw('Le document a été modifié par une autre session. Actualiser avant de continuer.',frappe.TimestampMismatchError)
    if doc.get('sales_order'):
        order=stock.get_order(doc.sales_order,lock=lock)
        if order.company!=doc.company or order.customer!=doc.customer or order.currency!=doc.currency:
            frappe.throw('La société, le client et la devise doivent correspondre à la commande B.')
    if not frappe.db.exists('Sales Order',dict(company=doc.company,customer=doc.customer,custom_ug_order_type='B')):
        frappe.throw('Ce client ne possède aucune commande B dans cette société.')


def cutover(doc):
    """Opening balances are beginning-of-day snapshots, entered before live activity."""
    rows=frappe.db.sql('''SELECT posting_date,sales_order FROM `tabSolde Initial Client B`
        WHERE company=%s AND customer=%s AND currency=%s AND docstatus=1 FOR UPDATE''',
        (doc.company,doc.customer,doc.currency),as_dict=True)
    for opening in rows:
        if (not opening.sales_order or not doc.get('sales_order') or opening.sales_order==doc.get('sales_order')) and getdate(doc.posting_date)<getdate(opening.posting_date):
            frappe.throw('La date précède le solde initial B. Ne pas réimporter les mouvements historiques déjà repris dans ce solde.')


def allocated(bordereau,exclude_payment=None,lock=False):
    return flt(frappe.db.sql('''SELECT COALESCE(SUM(a.amount),0) FROM `tabReglement Special Allocation` a
        JOIN `tabReglement Special` p ON p.name=a.parent WHERE p.docstatus=1 AND a.bordereau=%s AND p.name!=%s'''+(' FOR UPDATE' if lock else ''),
        (bordereau,exclude_payment or ''))[0][0])


def delivered(order,exclude=None,lock=False):
    """Commercial quantities including old direct issues, without counting linked issues twice."""
    result=defaultdict(float)
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
    order=stock.get_order(doc.sales_order,lock=True)
    if order.status in ('Closed','On Hold'):frappe.throw('Commande B clôturée ou suspendue.')
    cutover(doc)
    prior=doc.get_doc_before_save()
    if prior and any(prior.get(f)!=doc.get(f) for f in ('stock_entry','adopt_existing_stock')):
        frappe.throw('La sortie associée ne peut pas être remplacée.')
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
        if not source or row.sales_order_item in seen:frappe.throw('Ligne inconnue ou dupliquée dans la commande B.')
        seen.add(row.sales_order_item)
        row.qty=number(row.qty,positive=True)
        row.item_code=source.item_code;row.item_name=source.item_name;row.uom=source.uom
        row.length_mm=source.get('custom_client_length_mm');row.width_mm=source.get('custom_client_width_mm');row.thickness_mm=source.get('custom_client_thickness_mm')
        row.ordered_qty=source.qty;row.delivered_qty=max(0,booked[source.name]);row.remaining_qty=max(0,flt(source.qty)-row.delivered_qty)
        if row.qty>row.remaining_qty+EPS:frappe.throw('La quantité à livrer dépasse le reste de la commande B : '+source.item_code)
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
    previous=frappe.db.sql('''SELECT COALESCE(SUM(billing_basis),0),COALESCE(SUM(grand_total),0)
        FROM `tabBordereau Special` WHERE sales_order=%s AND docstatus=1 AND name!=%s FOR UPDATE''',(order.name,doc.name or ''))[0]
    doc.net_total=money(net,doc.currency)
    doc.billing_basis=basis
    if not flt(order.net_total) and flt(order.grand_total):frappe.throw('Commande sans base HT : répartition des montants impossible.')
    ratio=flt(order.grand_total)/flt(order.net_total) if order.net_total else 0
    doc.grand_total=money((flt(previous[0])+basis)*ratio,doc.currency)-flt(previous[1])
    if doc.net_total<0 or doc.grand_total<0:frappe.throw('Un bordereau de livraison B ne peut pas avoir un montant négatif.')
    doc.tax_amount=money(doc.grand_total-doc.net_total,doc.currency)
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
    order=stock.get_order(doc.sales_order,lock=True);sources={r.name:r for r in order.items}
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
    if len(doc.allocations)>500:frappe.throw('Un règlement accepte au maximum 500 affectations.')
    seen=set();total=0
    for row in doc.allocations:
        if row.bordereau in seen:frappe.throw('Un BL ne peut apparaître qu’une fois dans les affectations.')
        seen.add(row.bordereau)
        bl=frappe.get_doc(DELIVERY,row.bordereau,for_update=True);bl.check_permission('read')
        if bl.docstatus!=1 or (bl.company,bl.customer,bl.currency)!=(doc.company,doc.customer,doc.currency):frappe.throw('Affecter uniquement des BL B validés du même compte client.')
        if doc.sales_order and bl.sales_order!=doc.sales_order:frappe.throw('Le BL ne correspond pas à la commande du règlement.')
        row.amount=money(number(row.amount,positive=True),doc.currency)
        row.currency=doc.currency
        if row.amount<=0 or row.amount+allocated(bl.name,doc.name,lock=True)>flt(bl.grand_total)+EPS:frappe.throw('L’affectation dépasse le solde du BL.')
        total+=row.amount
    if total>doc.amount+EPS:frappe.throw('Les affectations dépassent le montant encaissé.')
    doc.allocated_amount=money(total,doc.currency);doc.unallocated_amount=money(doc.amount-total,doc.currency)
    doc.status='Validé' if doc.docstatus==1 else 'Brouillon'


def payment_before_update_after_submit(doc):
    # Only allocations may change after receipt validation. The receipt header is immutable.
    old=doc.get_doc_before_save()
    for field in ('company','customer','currency','sales_order','posting_date','amount','mode_of_payment','reference'):
        before,after=old.get(field),doc.get(field)
        equal=(getdate(before)==getdate(after)) if field=='posting_date' else (flt(before)==flt(after)) if field=='amount' else (before or '')==(after or '')
        if not equal:frappe.throw('Les données du règlement validé sont immuables. Annuler avant correction.')
    payment_validate(doc)


def payment_before_cancel(doc):
    account(doc);doc.status='Annulé'


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
        filters=dict(scope,posting_date=['<',doc.posting_date])
        if doc.sales_order and dt!=PAYMENT:filters['sales_order']=doc.sales_order
        if frappe.db.exists(dt,filters):frappe.throw('Des mouvements B antérieurs existent déjà : ne pas les ajouter à nouveau dans le solde initial.')


def opening_before_cancel(doc):
    account(doc)
    filters=dict(company=doc.company,customer=doc.customer,currency=doc.currency,docstatus=1)
    if doc.sales_order:filters['sales_order']=doc.sales_order
    if any(frappe.db.exists(dt,filters) for dt in (DELIVERY,PAYMENT)):
        frappe.throw('Annuler les mouvements B du compte avant d’annuler sa reprise d’ouverture.')


@frappe.whitelist()
def make_delivery(sales_order):
    order=stock.get_order(sales_order)
    frappe.has_permission(DELIVERY,'create',throw=True)
    booked=delivered(order)
    from .ug_warehouse import operational_warehouse, is_glass
    stores=operational_warehouse(order.company)
    other_stock=any(not is_glass(r.item_code) and frappe.get_cached_value('Item',r.item_code,'is_stock_item') for r in order.items)
    preferred=stores if any(is_glass(r.item_code) for r in order.items) and not other_stock else None
    doc=frappe.new_doc(DELIVERY)
    doc.update(dict(company=order.company,customer=order.customer,sales_order=order.name,currency=order.currency,
        posting_date=nowdate(),warehouse=preferred or order.set_warehouse or next((r.warehouse for r in order.items if r.warehouse),None)))
    for row in order.items:
        remaining=max(0,flt(row.qty)-booked[row.name])
        if remaining>EPS:doc.append('items',dict(sales_order_item=row.name,item_code=row.item_code,item_name=row.item_name,
            ordered_qty=row.qty,delivered_qty=booked[row.name],remaining_qty=remaining,qty=remaining,uom=row.uom,warehouse=(stores if is_glass(row.item_code) else None) or row.warehouse or doc.warehouse))
    if not doc.items:frappe.throw('Cette commande B est déjà entièrement livrée ou sortie du stock.')
    from .ug_warehouse import apply_defaults
    apply_defaults(doc)
    delivery_validate(doc)
    return doc.as_dict()


@frappe.whitelist()
def make_payment(sales_order=None,bordereau=None):
    frappe.has_permission(PAYMENT,'create',throw=True)
    if bordereau:
        bl=frappe.get_doc(DELIVERY,bordereau);bl.check_permission('read')
        if bl.docstatus!=1:frappe.throw('Valider le BL avant de l’affecter.')
        doc=frappe.new_doc(PAYMENT);doc.update({k:bl.get(k) for k in ('company','customer','currency','sales_order')})
        balance=max(0,flt(bl.grand_total)-allocated(bl.name));doc.amount=balance
        doc.append('allocations',dict(bordereau=bl.name,amount=balance));return doc.as_dict()
    order=stock.get_order(sales_order)
    doc=frappe.new_doc(PAYMENT)
    doc.update(dict(company=order.company,customer=order.customer,currency=order.currency,sales_order=order.name,posting_date=nowdate()))
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


def payment_share(payment,sales_order=None):
    if not sales_order or payment.sales_order==sales_order:return flt(payment.amount)
    return sum(flt(a.amount) for a in payment.allocations
        if frappe.db.get_value(DELIVERY,a.bordereau,'sales_order')==sales_order)


@frappe.whitelist()
def get_order_summary(sales_order):
    order=stock.get_order(sales_order)
    deliveries=frappe.get_list(DELIVERY,filters={'sales_order':order.name},fields=['name','posting_date','docstatus','grand_total','stock_entry'],order_by='posting_date,name',limit_page_length=0)
    for bl in deliveries:
        bl.received=allocated(bl.name) if bl.docstatus==1 else 0
        bl.balance=flt(bl.grand_total)-bl.received if bl.docstatus==1 else 0
    payments=[]
    for record in frappe.get_list(PAYMENT,filters=dict(company=order.company,customer=order.customer,currency=order.currency,docstatus=1),pluck='name',limit_page_length=0):
        p=frappe.get_doc(PAYMENT,record);share=payment_share(p,order.name)
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
