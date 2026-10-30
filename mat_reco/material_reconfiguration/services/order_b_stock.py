"""Circuit B stock exits use native Material Issue and its normal valuation."""
import hashlib
import json
import math
from collections import defaultdict

import frappe
from frappe.utils import flt

from .order_b import can_access
from .workshop_service import _receipts, _serials, _output_matches_line


def get_order(name, write=False, lock=False):
    if not can_access():frappe.throw('Le rôle UG COMMANDES B est requis.',frappe.PermissionError)
    order=frappe.get_doc('Sales Order',name)
    order.check_permission('write' if write else 'read')
    if write or lock:
        frappe.db.get_value('Company',order.company,'name',for_update=True)
        order=frappe.get_doc('Sales Order',name,for_update=True)
    if order.custom_ug_order_type!='B' or order.docstatus!=1:
        frappe.throw('Une commande B validée est requise.')
    return order


def issued_quantities(order, exclude=None, include_drafts=False, lock=False):
    rows=frappe.db.sql('''SELECT d.custom_sales_order_item, SUM(d.qty*d.conversion_factor) qty
        FROM `tabStock Entry` s JOIN `tabStock Entry Detail` d ON d.parent=s.name
        WHERE s.custom_ug_b_sales_order=%s AND s.docstatus '''+('<2' if include_drafts else '=1')+'''
        AND s.name!=%s GROUP BY d.custom_sales_order_item'''+(' FOR UPDATE' if lock else ''),(order.name,exclude or ''),as_dict=True)
    return {r.custom_sales_order_item:flt(r.qty) for r in rows}


def physical_rows(order):
    return [r for r in order.items if frappe.get_cached_value('Item',r.item_code,'is_stock_item')]


def is_complete(order):
    issued=issued_quantities(order)
    return all(issued.get(r.name,0)+.000001>=flt(r.stock_qty or r.qty*r.conversion_factor) for r in physical_rows(order))


def _unreserved(row,warehouse,serials,quantity):
    reservations=frappe.db.sql('''SELECT name,reserved_qty,delivered_qty,reservation_based_on FROM `tabStock Reservation Entry`
        WHERE docstatus=1 AND item_code=%s AND warehouse=%s
        AND reserved_qty>delivered_qty FOR UPDATE''',(row.item_code,warehouse),as_dict=True)
    reserved_names=set()
    for reservation in reservations:
        reserved_names.update(frappe.get_all('Serial and Batch Entry',filters={'parent':reservation.name},pluck='serial_no'))
    if reserved_names.intersection(serials):frappe.throw('Une série choisie est réservée. Libérer sa réservation avant la sortie directe.')
    actual=flt(frappe.db.get_value('Bin',{'item_code':row.item_code,'warehouse':warehouse},'actual_qty',for_update=True))
    if quantity>actual-sum(max(0,flt(r.reserved_qty)-flt(r.delivered_qty)) for r in reservations)+.000001:
        frappe.throw('Stock disponible insuffisant après déduction des réservations.')


def validate_issue(doc,method=None):
    previous=doc.get_doc_before_save()
    if previous and any(previous.get(f)!=doc.get(f) for f in ('custom_ug_b_sales_order','custom_ug_b_request_key','custom_ug_b_request_scope','custom_ug_special_delivery')):
        frappe.throw('La référence de sortie B ne peut pas être modifiée.')
    if not doc.get('custom_ug_b_sales_order'):return
    from .special_b import guard_stock
    guard_stock(doc)
    order=get_order(doc.custom_ug_b_sales_order,lock=True)
    if doc.company!=order.company or doc.stock_entry_type!='Material Issue':frappe.throw('La sortie B doit être un Material Issue de la société de la commande.')
    if order.status in ('Closed','On Hold'):frappe.throw('Cette commande B est clôturée ou suspendue.')
    if order.get('custom_ug_b_export_file'):frappe.throw('La commande est déjà exportée. Traiter son export avant de modifier les sorties.')
    if not order.custom_technical_study or frappe.db.get_value('Chantier Technical Study',order.custom_technical_study,'docstatus')!=1:
        frappe.throw('Valider la fiche technique avant la sortie B.')
    expected={r.name:r for r in physical_rows(order)}
    booked=issued_quantities(order,exclude=doc.name,include_drafts=True,lock=True)
    _,_,_,owners=_receipts([order],lock=True)
    quantities=defaultdict(float);by_stock=defaultdict(float);selected=set()
    for detail in doc.items:
        row=expected.get(detail.get('custom_sales_order_item'))
        if not row or row.item_code!=detail.item_code or detail.t_warehouse or not detail.s_warehouse:
            frappe.throw('Chaque ligne de sortie doit reprendre un article physique de cette commande B.')
        quantity=flt(detail.qty)*flt(detail.conversion_factor)
        if not math.isfinite(quantity) or quantity<=0:frappe.throw('Quantité de sortie positive requise.')
        if detail.uom!=frappe.get_cached_value('Item',row.item_code,'stock_uom') or abs(flt(detail.conversion_factor)-1)>.000001:
            frappe.throw('Utiliser l’unité de stock et un coefficient de conversion égal à 1 pour les sorties B.')
        warehouse=frappe.get_doc('Warehouse',detail.s_warehouse);warehouse.check_permission('read')
        if warehouse.company!=order.company or warehouse.is_group:frappe.throw('Entrepôt incompatible avec la commande B.')
        quantities[row.name]+=quantity;by_stock[(row.item_code,warehouse.name)]+=quantity
        serials=_serials(detail)
        if len(serials)!=len(set(serials)) or selected.intersection(serials):frappe.throw('Une série ne peut être sortie qu’une seule fois.')
        selected.update(serials)
        manufacturing=frappe.get_cached_value('Item',row.item_code,'custom_item_types') in ('OUVRAGE','DECOUPE')
        if manufacturing and not serials:frappe.throw('Sélectionner les séries produites pour les découpes et ouvrages B.')
        if serials and len(serials)!=quantity:frappe.throw('Le nombre de séries doit correspondre à la quantité de sortie.')
        for serial in serials:
            sn=frappe.get_doc('Serial No',serial,for_update=True);sn.check_permission('read')
            if sn.item_code!=row.item_code or sn.warehouse!=warehouse.name or sn.status!='Active':frappe.throw('Série indisponible ou incompatible avec la sortie.')
            if manufacturing:
                if owners.get(serial)!=row.name:frappe.throw('Cette série n’a pas été produite pour cette ligne de commande.')
                if not _output_matches_line(sn,row):frappe.throw('Dimensions de la série différentes de la commande.')
        _unreserved(row,warehouse.name,serials,by_stock[(row.item_code,warehouse.name)])
    for identity,quantity in quantities.items():
        row=expected[identity]
        if booked.get(identity,0)+quantity>flt(row.stock_qty or row.qty*row.conversion_factor)+.000001:
            frappe.throw('Quantité de sortie supérieure au solde de la commande B.')


def before_cancel(doc,method=None):
    from .special_b import guard_stock
    guard_stock(doc)
    if doc.get('custom_ug_b_sales_order'):
        order=get_order(doc.custom_ug_b_sales_order,lock=True)
        if order.get('custom_ug_b_export_file'):frappe.throw('Traiter l’export Sage avant d’annuler cette sortie B.')


@frappe.whitelist()
def get_issue_data(sales_order):
    order=get_order(sales_order)
    return issue_data(order)


def issue_data(order):
    """Shared stock selection, after the caller has checked the source order access."""
    quantities=(issued_quantities(order,include_drafts=True) if order.custom_ug_order_type=='B'
                else {r.name:flt(r.delivered_qty)*(flt(r.conversion_factor) or 1) for r in order.items})
    _,_,_,owners=_receipts([order])
    warehouses=frappe.get_list('Warehouse',filters={'company':order.company,'is_group':0,'disabled':0},pluck='name',limit_page_length=0)
    result=[]
    for row in physical_rows(order):
        remaining=max(0,flt(row.stock_qty or row.qty*row.conversion_factor)-quantities.get(row.name,0))
        if not remaining:continue
        item=frappe.get_cached_doc('Item',row.item_code)
        serials=frappe.get_list('Serial No',filters={'item_code':row.item_code,'warehouse':['in',warehouses],'status':'Active'},
            fields=['name','warehouse','custom_dimension_length_mm','custom_dimension_width_mm','custom_dimension_thickness_mm'],limit_page_length=0) if item.has_serial_no and warehouses else []
        manufacturing=item.custom_item_types in ('OUVRAGE','DECOUPE')
        if manufacturing:serials=[s for s in serials if owners.get(s.name)==row.name and _output_matches_line(s,row)]
        result.append(dict(sales_order_item=row.name,item_code=row.item_code,item_name=row.item_name,remaining_qty=remaining,
            stock_uom=item.stock_uom,has_serial_no=item.has_serial_no,has_batch_no=item.has_batch_no,serials=serials))
    from mat_reco.material_reconfiguration.utils.accounting_dimensions import get_active_accounting_dimension_fields,get_company_dimension_config
    config=get_company_dimension_config(order.company);dimensions=[]
    for fieldname in get_active_accounting_dimension_fields():
        field=frappe.get_meta('Stock Entry').get_field(fieldname)
        if not field:continue
        rules=config.get(fieldname) or {}
        dimensions.append(dict(fieldname=fieldname,label=field.label,fieldtype=field.fieldtype,options=field.options,
            default=order.get(fieldname) or rules.get('default_dimension'),reqd=int(bool(rules.get('mandatory_for_bs') or rules.get('mandatory_for_pl')))))
    return dict(rows=result,warehouses=warehouses,dimensions=dimensions)


@frappe.whitelist(methods=['POST'])
def create_issue(sales_order,rows,request_key,accounting_dimensions=None,special_delivery=None,posting_date=None):
    frappe.has_permission('Stock Entry','create',throw=True);frappe.has_permission('Stock Entry','submit',throw=True)
    order=get_order(sales_order,lock=True)
    if not request_key or len(request_key)>100:frappe.throw('Clé de sortie requise (100 caractères maximum).')
    incoming=frappe.parse_json(rows)
    if not isinstance(incoming,list) or not incoming or len(incoming)>500:frappe.throw('Sélection de sortie invalide.')
    from mat_reco.material_reconfiguration.utils.accounting_dimensions import get_active_accounting_dimension_fields
    dimensions=frappe.parse_json(accounting_dimensions or '{}')
    if not isinstance(dimensions,dict) or set(dimensions)-set(get_active_accounting_dimension_fields()):frappe.throw('Dimensions comptables invalides.')
    for fieldname,value in dimensions.items():
        field=frappe.get_meta('Stock Entry').get_field(fieldname)
        if value and field and field.fieldtype=='Link':frappe.get_doc(field.options,value).check_permission('read')
    scope_data=dict(order=order.name,rows=incoming,dimensions=dimensions)
    if special_delivery:scope_data.update(special_delivery=special_delivery,posting_date=str(posting_date))
    scope=hashlib.sha256(json.dumps(scope_data,sort_keys=True,default=str).encode()).hexdigest()
    key=hashlib.sha256(f'{frappe.session.user}:{request_key}'.encode()).hexdigest()
    existing=frappe.db.get_value('Stock Entry',{'custom_ug_b_request_key':key},['name','docstatus','custom_ug_b_request_scope'],as_dict=True)
    if existing:
        if existing.docstatus!=1 or existing.custom_ug_b_request_scope!=scope:frappe.throw('Cette clé a déjà servi pour une autre sortie.')
        frappe.get_doc('Stock Entry',existing.name).check_permission('read');return existing.name
    order_rows={r.name:r for r in physical_rows(order)}
    entry=frappe.get_doc(dict(doctype='Stock Entry',stock_entry_type='Material Issue',company=order.company,
        custom_ug_b_sales_order=order.name,custom_ug_b_request_key=key,custom_ug_b_request_scope=scope,
        remarks='Sortie directe circuit B — '+order.name))
    if special_delivery:entry.custom_ug_special_delivery=special_delivery
    if posting_date:entry.posting_date=posting_date
    for fieldname,value in dimensions.items():entry.set(fieldname,value)
    for selected in incoming:
        if not isinstance(selected,dict) or selected.get('sales_order_item') not in order_rows:frappe.throw('Ligne de commande inconnue.')
        row=order_rows[selected['sales_order_item']]
        serials=selected.get('serials') or []
        if not isinstance(serials,list) or len(serials)!=len(set(serials)):frappe.throw('Liste de séries invalide ou dupliquée.')
        item=frappe.get_cached_doc('Item',row.item_code)
        entry.append('items',dict(item_code=row.item_code,s_warehouse=selected.get('warehouse'),qty=selected.get('qty'),
            uom=item.stock_uom,stock_uom=item.stock_uom,conversion_factor=1,serial_no='\n'.join(serials),batch_no=selected.get('batch_no'),
            use_serial_batch_fields=1,allow_zero_valuation_rate=1,custom_sales_order_item=row.name,
            custom_dimension_length_mm=row.get('custom_client_length_mm'),custom_dimension_width_mm=row.get('custom_client_width_mm'),
            custom_dimension_thickness_mm=row.get('custom_client_thickness_mm')))
    from mat_reco.material_reconfiguration.utils.accounting_dimensions import resolve_and_apply_stock_entry_dimensions
    resolve_and_apply_stock_entry_dimensions(entry,source_doc=entry,fallback_docs=[order],validate_mandatory=True)
    from .production_reservations import release_for_issue
    release_for_issue(order, incoming)
    entry.insert();entry.submit()
    return entry.name


def install():
    from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
    fields=[dict(fieldname='custom_ug_b_sales_order',label='Commande B',fieldtype='Link',options='Sales Order',read_only=1,no_copy=1,search_index=1),
        dict(fieldname='custom_ug_special_delivery',label='Bordereau Spécial',fieldtype='Link',options='Bordereau Special',read_only=1,no_copy=1,search_index=1),
        dict(fieldname='custom_ug_b_request_key',label='Clé sortie B',fieldtype='Data',read_only=1,hidden=1,no_copy=1,unique=1),
        dict(fieldname='custom_ug_b_request_scope',label='Empreinte sortie B',fieldtype='Data',read_only=1,hidden=1,no_copy=1)]
    for field in fields:field['module']='Material Reconfiguration'
    create_custom_fields({'Stock Entry':fields},update=True)


def refresh_tasks(sales_order,event_key):
    from .task_notifications import send_tasks,close_tasks
    order=frappe.get_doc('Sales Order',sales_order)
    if order.docstatus!=1 or order.custom_ug_order_type!='B':return
    sheet=frappe.db.get_value('Chantier Technical Study',order.custom_technical_study,'docstatus') if order.custom_technical_study else None
    if sheet!=1:return
    if is_complete(order):
        close_tasks(order,'b_issue')
        if not order.get('custom_ug_b_sage_reference'):send_tasks(order,'b_export','ready:'+event_key)
    else:
        close_tasks(frappe._dict(doctype='Sales Order',name=order.name,docstatus=2),'b_export')
        accepted,_,_,_=_receipts([order])
        if any(accepted.values()) or any(frappe.get_cached_value('Item',r.item_code,'custom_item_types') not in ('OUVRAGE','DECOUPE') for r in physical_rows(order)):
            send_tasks(order,'b_issue','ready:'+event_key)


def stock_updated(doc,method=None):
    if doc.docstatus==2 and doc.get('custom_ug_special_delivery'):
        from .special_b import guard_stock
        guard_stock(doc)
        # Native Stock Entry.on_cancel replaces this list. Extend it afterwards.
        doc.ignore_linked_doctypes=list(doc.get('ignore_linked_doctypes') or [])+['Bordereau Special']
    orders={doc.get('custom_ug_b_sales_order')}-{None,''}
    row_ids={r.get('custom_sales_order_item') for r in doc.items}-{None,''}
    allocations=frappe.parse_json(doc.get('custom_workshop_allocations_json') or '{}')
    row_ids.update(value.get('sales_order_item') for value in allocations.values() if isinstance(value,dict))
    row_ids.discard(None)
    if row_ids:orders.update(frappe.get_all('Sales Order Item',filters={'name':['in',list(row_ids)]},pluck='parent'))
    for name in sorted(orders):refresh_tasks(name,doc.name+':'+str(doc.docstatus))
