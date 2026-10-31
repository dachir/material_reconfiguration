"""Technical handoff scoped to a submitted sales order, for both commercial circuits."""
import copy
import json

import frappe
from frappe.utils import flt


def requires_study(order):
    """Whole plates, accessories and services are sold without a technical sheet."""
    return any(frappe.get_cached_value('Item', row.item_code, 'custom_item_types')
        in ('OUVRAGE', 'DECOUPE') for row in order.items)


def context(study, check_permission=True):
    """Return the order's commercial scope without modifying its source chantier."""
    from .chantier_work_types import is_v2, technical_source_hash
    from .technical_study_service import seed_item, composition_thickness
    from .chantier_service import fingerprint
    order=frappe.get_doc('Sales Order',study.sales_order)
    if check_permission:order.check_permission('read')
    if order.docstatus!=1:frappe.throw('Une commande validée est requise pour préparer ou valider sa fiche technique.')
    if order.custom_chantier:
        original=frappe.get_doc('Chantier',order.custom_chantier)
        if not is_v2(original):frappe.throw('Cette commande utilise le parcours technique historique.')
        dossier=copy.deepcopy(original)
        macros={r.line_id:r for r in original.lines}
        selected=[]
        for row in order.items:
            macro=macros.get(row.get('custom_chantier_line'))
            if not macro:continue
            values=macro.as_dict();values['qty']=row.qty
            values.update(length_mm=row.custom_client_length_mm,width_mm=row.custom_client_width_mm)
            selected.append(values)
        dossier.set('lines',selected)
        used={r.work_type for r in dossier.lines if r.work_type}
        dossier.set('work_types',[r.as_dict() for r in original.work_types if r.type_id in used])
    else:
        dossier=frappe.get_doc(dict(doctype='Chantier',name=order.name,company=order.company,customer=order.customer,
            designation=order.name,workflow_version=2,lines=[],work_types=[]))
        known=set()
        for row in order.items:
            item=frappe.get_cached_doc('Item',row.item_code)
            manufacturing=item.get('custom_item_types') in ('OUVRAGE','DECOUPE')
            thickness=flt(row.get('custom_client_thickness_mm'))
            if manufacturing and not thickness:thickness=composition_thickness(seed_item(item.name))
            identity=f'{item.name}:{thickness:g}'
            if manufacturing and identity not in known:
                dossier.append('work_types',dict(type_id=identity,designation=item.item_name,thickness_mm=thickness,proposed_item=item.name))
                known.add(identity)
            dossier.append('lines',dict(line_id=row.name,repere=str(row.idx),designation=row.item_name,qty=row.qty,
                work_type=identity if manufacturing else None,line_kind=None if manufacturing else 'Vente directe',
                sale_item=None if manufacturing else item.name,uom=row.uom,length_mm=row.get('custom_client_length_mm'),
                width_mm=row.get('custom_client_width_mm'),thickness_mm=thickness))
    signature=fingerprint(dict(sales_order=order.name,technical=technical_source_hash(dossier)))
    return order,dossier,signature


def prepare(order):
    """Called inside Sales Order.on_submit; a retry reuses the same active sheet."""
    from .chantier_work_types import is_v2, prepare_type_rows
    from .technical_study_service import seed_item
    from .task_notifications import send_tasks
    if order.docstatus!=1 or not requires_study(order):return
    if order.custom_chantier and not is_v2(frappe.get_doc('Chantier',order.custom_chantier)):
        # Submitted legacy orders already carry their approved technical definition.
        if any(frappe.get_cached_value('Item',r.item_code,'custom_item_types') in ('OUVRAGE','DECOUPE') for r in order.items):
            send_tasks(order,'workshop','order-created')
        return
    frappe.db.get_value('Sales Order',order.name,'name',for_update=True)
    existing=frappe.db.get_value('Chantier Technical Study',{'sales_order':order.name,'docstatus':['<',2]},'name')
    if existing:
        study=frappe.get_doc('Chantier Technical Study',existing)
    else:
        study=frappe.get_doc(dict(doctype='Chantier Technical Study',sales_order=order.name,
            chantier=order.custom_chantier,loose_link=1))
        _,dossier,signature=context(study,check_permission=False)
        rows=prepare_type_rows(dossier)
        if not rows:return
        study.source_hash=signature
        for row in rows:
            tree=seed_item(row.proposed_item) if row.proposed_item else dict(mode='new',proposed_code='',item_name=row.designation,
                item_type='OUVRAGE',stock_uom=row.uom,item_group='',qty_factor=1,children=[])
            study.append('lines',dict(line_id=row.line_id,repere=row.repere,thickness_mm=row.thickness_mm,tree_json=json.dumps(tree,ensure_ascii=False)))
        study.insert(ignore_permissions=True)
    order.custom_technical_study=study.name
    frappe.db.set_value('Sales Order',order.name,'custom_technical_study',study.name,update_modified=False)
    if study.docstatus==0:send_tasks(study,'technical','order-validated:'+order.name)
    return study.name


def source(study):
    return context(study,check_permission=False)[1] if study.get('sales_order') else frappe.get_doc('Chantier',study.chantier,for_update=True)


def source_hash(study,dossier):
    if study.get('sales_order'):return context(study,check_permission=False)[2]
    from .technical_study_service import source_hash as original_hash
    return original_hash(dossier)


def install():
    frappe.reload_doc('material_reconfiguration','doctype','chantier_technical_study')


@frappe.whitelist(methods=['POST'])
def prepare_for_order(sales_order):
    order=frappe.get_doc('Sales Order',sales_order)
    order.check_permission('read')
    frappe.has_permission('Chantier Technical Study','create',throw=True)
    if order.docstatus!=1:frappe.throw('Valider la commande avant de préparer sa fiche technique.')
    return prepare(order)
