"""Commercial types independent of sections and of their technical definitions."""
import copy
import hashlib
import json
import math
import uuid

import frappe
from frappe.utils import flt, cint


def is_v2(doc):
    return cint(doc.get('workflow_version')) >= 2


def is_direct(row):
    return row.get('line_kind')=='Vente directe'


def types(doc):
    return {row.type_id: row for row in doc.get('work_types', [])}


def validate_types(doc):
    old=doc.get_doc_before_save()
    if old and is_v2(old) and not is_v2(doc):
        frappe.throw('Le modèle des types d’ouvrage ne peut pas être désactivé.')
    if old and not is_v2(old) and is_v2(doc) and any(frappe.db.exists(dt,{field:doc.name}) for dt,field in [('Chantier Technical Study','chantier'),('Quotation','custom_chantier'),('Sales Order','custom_chantier')]):
        frappe.throw('Conserver le modèle des chantiers ayant déjà des documents liés.')
    if not is_v2(doc):
        return
    seen=set()
    for row in doc.get('work_types', []):
        row.type_id=row.type_id or uuid.uuid4().hex
        if row.type_id in seen or not (row.designation or '').strip() or not math.isfinite(flt(row.thickness_mm)) or flt(row.thickness_mm)<=0:
            frappe.throw('Chaque type d’ouvrage doit avoir une désignation et une épaisseur positive.')
        seen.add(row.type_id)
        definitions=frappe.parse_json(row.common_extras or '[]')
        if not isinstance(definitions,list) or len(definitions)>100:
            frappe.throw('Liste de compléments communs invalide.')
        keys=set()
        for extra in definitions:
            if not isinstance(extra,dict):frappe.throw('Complément commun invalide.')
            extra['key']=extra.get('key') or uuid.uuid4().hex
            if extra['key'] in keys:frappe.throw('Complément commun dupliqué.')
            keys.add(extra['key'])
            item=frappe.get_doc('Item',extra.get('item_code'));item.check_permission('read')
            if item.disabled or not item.is_sales_item or item.custom_item_types not in ('SERVICE','ACCESSOIRE'):
                frappe.throw('Choisir un service ou accessoire actif et vendable.')
            if any(not math.isfinite(flt(extra.get(k,default))) for k,default in [('rate',0),('factor',1),('qty',1)]) or flt(extra.get('rate'))<0 or flt(extra.get('factor',1))<=0 or flt(extra.get('qty',1))<=0:
                frappe.throw('Prix positif ou nul et coefficient positif requis.')
            extra['factor']=flt(extra.get('factor',1))
        row.common_extras=json.dumps(definitions,ensure_ascii=False)
    known=types(doc)
    for row in doc.get('lines', []):
        if is_direct(row):
            item=frappe.get_doc('Item',row.sale_item);item.check_permission('read')
            if item.disabled or not item.is_sales_item or item.custom_item_types not in ('PRIMAIRE','ACCESSOIRE','SERVICE'):
                frappe.throw('Vente directe : choisir une plaque, un accessoire ou un service actif et vendable.')
            row.work_type=None;row.designation=row.designation or item.item_name;row.uom=item.stock_uom
            row.length_mm=row.width_mm=row.thickness_mm=0
            continue
        if row.work_type not in known:
            frappe.throw('Choisir un type d’ouvrage pour chaque ouvrage.')
        selected=known[row.work_type]
        row.thickness_mm=selected.thickness_mm
        if not (row.designation or '').strip():row.designation=selected.designation
        row.uom=row.uom or ('PC' if frappe.db.exists('UOM','PC') else 'Nos')
    sync_inherited(doc)


def sync_inherited(doc):
    from .chantier_extras import quantity
    known=types(doc)
    saved={r.line_id:r for r in doc.get('commercial_extras',[]) if r.get('inherited_from')}
    extras=[r.as_dict() for r in doc.get('commercial_extras',[]) if not r.get('inherited_from')]
    for row in doc.get('lines',[]):
        if is_direct(row):continue
        if not row.line_id:row.line_id=uuid.uuid4().hex
        # Type complements are mandatory on every associated work line.
        row.excluded_type_extras=None
        type_row=known[row.work_type]
        for definition in frappe.parse_json(type_row.common_extras or '[]'):
            identity=uuid.uuid5(uuid.NAMESPACE_URL,f"ug:{row.line_id}:{type_row.type_id}:{definition['key']}").hex
            item=frappe.get_doc('Item',definition['item_code'])
            basis,amount=quantity(item,row)
            amount=(flt(definition.get('qty',1))*flt(row.qty) if basis=='MANUEL' else amount)*definition['factor']
            if amount<=0:frappe.throw(f'{row.repere or row.designation} : compléter les dimensions pour les services communs.')
            extra=dict(line_id=identity,parent_line_id=row.line_id,item_code=item.name,qty=amount,
                manual_qty=1,rate=flt(definition.get('rate')),rate_set=1,
                inherited_from=type_row.type_id,inherited_key=definition['key'])
            previous=saved.get(identity) or next((e for e in saved.values() if e.parent_line_id==row.line_id and e.inherited_from==type_row.type_id and e.inherited_key==definition['key']),None)
            if previous:
                if previous.name and not previous.is_new():extra['name']=previous.name
                for flag,field in [('inherited_qty_override','qty'),('inherited_rate_override','rate')]:
                    if cint(previous.get(flag)):
                        extra[flag]=1;extra[field]=previous.get(field)
            extras.append(extra)
    doc.set('commercial_extras',extras)


def ensure_commercial_item(doc, type_row):
    """Stable serialized sales SKU; its manufacturing tree comes from an explicit FT allocation."""
    code='UG-COM-'+hashlib.sha256((doc.name+':'+type_row.type_id).encode()).hexdigest()[:16].upper()
    if frappe.db.exists('Item',code):
        return code
    group='Ouvrages commerciaux UG'
    if not frappe.db.exists('Item Group',group):
        root=frappe.db.get_value('Item Group',{'is_group':1,'parent_item_group':['in',['',None]]},'name') or 'All Item Groups'
        frappe.get_doc(dict(doctype='Item Group',item_group_name=group,parent_item_group=root)).insert(ignore_permissions=True)
    unit=next(r.uom for r in doc.lines if r.work_type==type_row.type_id)
    item=frappe.get_doc(dict(doctype='Item',item_code=code,item_name=type_row.designation,
        description=type_row.designation,item_group=group,stock_uom=unit,is_stock_item=1,has_serial_no=1,
        has_batch_no=0,is_sales_item=1,custom_item_types='OUVRAGE',custom_is_composite=1,
        custom_requires_dimensions=1))
    warehouses=frappe.get_list('Warehouse',filters={'company':doc.company,'is_group':0,'disabled':0},pluck='name',limit_page_length=1)
    if warehouses:item.append('item_defaults',dict(company=doc.company,default_warehouse=warehouses[0]))
    item.insert(ignore_permissions=True)
    return item.name


def commercial_hash(doc):
    from .chantier_service import fingerprint
    from .ft_activation import snapshot
    return fingerprint(dict(commercial=snapshot(doc),types=[dict(id=t.type_id,name=t.designation,thickness=flt(t.thickness_mm),extras=t.common_extras) for t in doc.work_types]))


def approve_commercial(doc):
    if not doc.lines:frappe.throw('Ajouter les ouvrages avant validation commerciale.')
    for row in doc.lines:
        if not is_direct(row) and min(flt(row.length_mm),flt(row.width_mm),flt(row.thickness_mm))<=0:
            frappe.throw(f'{row.repere} : compléter longueur, hauteur et épaisseur.')
    for type_row in doc.work_types:
        if len({r.uom for r in doc.lines if r.work_type==type_row.type_id})>1:
            frappe.throw('Utiliser la même unité pour les ouvrages d’un même type.')
        if any(r.work_type==type_row.type_id for r in doc.lines):
            type_row.commercial_item=ensure_commercial_item(doc,type_row)
    doc.commercial_hash=commercial_hash(doc)


def prepare_type_rows(doc):
    return [frappe._dict(line_id=t.type_id,repere=t.designation,designation=t.designation,
        thickness_mm=t.thickness_mm,length_mm=0,width_mm=0,proposed_item=t.proposed_item,uom='PC')
        for t in doc.work_types if any(r.work_type==t.type_id for r in doc.lines)]


def technical_source_hash(doc):
    from .chantier_service import fingerprint
    return fingerprint(dict(company=doc.company,types=[dict(id=r.line_id,designation=r.designation,thickness=flt(r.thickness_mm),operations=[{k:e.get(k) for k in ('item_code','factor','qty')} for e in frappe.parse_json(types(doc)[r.line_id].common_extras or '[]')]) for r in prepare_type_rows(doc)]))


def validate_commercial_quote(quote, doc):
    from .chantier_service import fingerprint
    from .chantier_extras import validate_quote_extras
    if doc.docstatus!=1 or doc.commercial_hash!=commercial_hash(doc):
        frappe.throw('Valider la version commerciale du chantier avant de générer le devis.')
    if quote.currency!=doc.currency or (doc.taxes_and_charges and quote.taxes_and_charges!=doc.taxes_and_charges):
        frappe.throw('Reprendre la devise et le modèle de taxes du chantier approuvé.')
    known=types(doc);macros={r.line_id:r for r in doc.lines}
    extras=validate_quote_extras(quote,doc);seen=set()
    quote.custom_technical_study=None
    for row in quote.items:
        if row.custom_chantier_line in extras:continue
        macro=macros.get(row.custom_chantier_line)
        if not macro or macro.line_id in seen:frappe.throw('Ouvrage commercial inconnu ou dupliqué.')
        seen.add(macro.line_id)
        expected=known.get(macro.work_type)
        row.custom_ug_work_type=expected.type_id if expected else None
        row.custom_ug_work_type_name=expected.designation if expected else None
        expected_item=macro.sale_item if is_direct(macro) else expected.commercial_item
        if row.item_code!=expected_item or row.uom!=macro.uom or flt(row.rate)!=flt(macro.rate) or row.custom_repere!=macro.repere or row.custom_chantier_section!=macro.section:
            frappe.throw('Le devis diffère du chantier commercial approuvé.')
        for field,source in [('custom_client_length_mm','length_mm'),('custom_client_width_mm','width_mm'),('custom_client_thickness_mm','thickness_mm')]:
            if abs(flt(row.get(field))-flt(macro.get(source)))>.001:frappe.throw('Dimensions commerciales différentes du chantier.')
        row.custom_technical_snapshot=None;row.custom_technical_hash=None
        previous=frappe.db.sql('''SELECT i.qty FROM `tabQuotation Item` i JOIN `tabQuotation` q ON q.name=i.parent
            WHERE q.custom_chantier=%s AND q.docstatus<2 AND q.name!=%s AND i.custom_chantier_line=%s FOR UPDATE''',(doc.name,quote.name or '',macro.line_id))
        if sum(flt(x[0]) for x in previous)+flt(row.qty)>macro.qty:frappe.throw('Quantité du devis supérieure au besoin commercial.')


def technical_tree(order, row, study_name=None):
    if not frappe.has_permission('Chantier Technical Study','read'):
        frappe.throw('Lecture de la fiche technique requise avant fabrication.')
    from .chantier_service import chantier_doc
    doc=chantier_doc(order.custom_chantier)
    macro=next((r for r in doc.lines if r.line_id==row.get('custom_chantier_line')),None)
    if not macro:frappe.throw('Ouvrage commercial du chantier introuvable.')
    if is_direct(macro):frappe.throw('Cette vente directe ne nécessite pas de fabrication.')
    candidates=frappe.get_list('Chantier Technical Study',filters={'chantier':doc.name,'docstatus':1,
        **({'name':study_name} if study_name else {})},pluck='name',order_by='modified desc',limit_page_length=0)
    for name in candidates:
        study=frappe.get_doc('Chantier Technical Study',name)
        if study.source_hash!=technical_source_hash(doc):continue
        definition=next((r for r in study.lines if r.line_id==macro.work_type),None)
        if not definition or not definition.snapshot_json:continue
        tree=copy.deepcopy(frappe.parse_json(definition.snapshot_json))
        tree['technical_item_code']=tree['item_code'];tree['item_code']=row.item_code
        tree['technical_study']=name;tree['work_type']=macro.work_type
        def dimensions(node):
            if node['item_type'] in ('OUVRAGE','DECOUPE'):
                node['length_mm']=flt(row.custom_client_length_mm);node['width_mm']=flt(row.custom_client_width_mm)
            for child in node.get('children',[]):dimensions(child)
        dimensions(tree)
        tree['thickness_mm']=flt(row.custom_client_thickness_mm)
        return tree
    frappe.throw('Fiche technique validée correspondant au type d’ouvrage requise avant fabrication.')


def freeze_order(order, study_name=None, node_id=None):
    from .chantier_service import fingerprint
    doc=frappe.get_doc('Chantier',order.custom_chantier)
    if not is_v2(doc):return
    for row in order.items:
        if node_id and node_id!=order.name and not node_id.startswith(row.name+':'):continue
        if row.get('custom_is_service_row') or row.get('custom_is_accessory_row') or not row.get('custom_chantier_line') or row.get('custom_technical_snapshot') or any(m.line_id==row.get('custom_chantier_line') and is_direct(m) for m in doc.lines):continue
        tree=technical_tree(order,row,study_name)
        frappe.db.set_value('Sales Order Item',row.name,dict(custom_technical_snapshot=json.dumps(tree,ensure_ascii=False),custom_technical_hash=fingerprint(tree)),update_modified=False)
        row.custom_technical_snapshot=json.dumps(tree,ensure_ascii=False);row.custom_technical_hash=fingerprint(tree)


def migrate_draft_types():
    """Upgrade only drafts without technical/commercial children; submitted histories stay untouched."""
    for name in frappe.get_all('Chantier',filters={'docstatus':0,'workflow_version':['<',2]},pluck='name'):
        if any(frappe.db.exists(dt,{field:name}) for dt,field in [('Chantier Technical Study','chantier'),('Quotation','custom_chantier'),('Sales Order','custom_chantier')]):continue
        doc=frappe.get_doc('Chantier',name)
        groups={}
        for row in doc.lines:
            key=(row.designation,flt(row.thickness_mm) or 1)
            if key not in groups:
                type_id=uuid.uuid4().hex;groups[key]=type_id
                doc.append('work_types',dict(type_id=type_id,designation=key[0],thickness_mm=key[1],proposed_item=row.proposed_item))
            row.work_type=groups[key]
        doc.workflow_version=2
        # No guessed thickness: drafts with missing thickness wait for an explicit user choice.
        if any(flt(r.thickness_mm)<=0 for r in doc.lines):continue
        doc.save(ignore_permissions=True)


def prepare_study(chantier):
    from .chantier_service import chantier_doc
    from .technical_study_service import seed_item
    from .ft_activation import require_activation
    doc=frappe.get_doc('Chantier',chantier,for_update=True);doc.check_permission('read')
    if doc.docstatus==2 or doc.status=='Cancelled':frappe.throw('Chantier annulé.')
    require_activation(doc)
    expected=prepare_type_rows(doc)
    if not expected:frappe.throw('Ajouter un type et ses ouvrages avant de préparer la fiche.')
    current=technical_source_hash(doc)
    previous=frappe.get_list('Chantier Technical Study',filters={'chantier':chantier,'docstatus':['<',2]},fields=['name','docstatus','source_hash'],order_by='modified desc',limit_page_length=0)
    matching=next((r for r in previous if r.source_hash==current),None)
    if matching:return matching.name
    draft=next((r for r in previous if r.docstatus==0),None)
    prior=frappe.get_doc('Chantier Technical Study',draft.name if draft else previous[0].name) if previous else None
    prior_lines={r.line_id:r for r in prior.lines} if prior else {}
    study=frappe.get_doc('Chantier Technical Study',draft.name) if draft else frappe.new_doc('Chantier Technical Study')
    study.chantier=chantier;study.loose_link=1;study.source_hash=current;study.set('lines',[])
    for row in expected:
        old=prior_lines.get(row.line_id)
        tree=json.loads(old.tree_json) if old else seed_item(row.proposed_item) if row.proposed_item else dict(mode='new',proposed_code='',item_name=row.designation,item_type='OUVRAGE',stock_uom='PC',item_group='',qty_factor=1,children=[])
        study.append('lines',dict(line_id=row.line_id,repere=row.repere,thickness_mm=row.thickness_mm,tree_json=json.dumps(tree,ensure_ascii=False)))
    study.save() if draft else study.insert()
    return study.name


def install_fields():
    from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
    create_custom_fields({dt:[dict(fieldname='custom_ug_work_type',label='Type d’ouvrage',fieldtype='Data',read_only=1,module='Material Reconfiguration'),
        dict(fieldname='custom_ug_work_type_name',label='Désignation du type d’ouvrage',fieldtype='Data',read_only=1,module='Material Reconfiguration')]
        for dt in ('Quotation Item','Sales Order Item')}, update=True)


def logical_section(order, row):
    if not order.get('custom_chantier'):return row.get('custom_chantier_section')
    doc=frappe.get_doc('Chantier',order.custom_chantier)
    if not is_v2(doc):return row.get('custom_chantier_section')
    return next((r.section for r in doc.lines if r.line_id==row.get('custom_chantier_line')),None)


def require_order_technical(order, doc):
    """Gate new orders and draft submissions; retain existing submitted histories."""
    old=order.get_doc_before_save()
    if not order.is_new() and not (order.docstatus==1 and old and old.docstatus==0):return
    macros={r.line_id:r for r in doc.lines}
    frappe.db.get_value('Chantier',doc.name,'name',for_update=True)
    current=technical_source_hash(doc)
    approved=frappe.get_all('Chantier Technical Study',filters={'chantier':doc.name,'docstatus':1,'source_hash':current},pluck='name')
    definitions=set()
    for name in approved:
        definitions.update(r.line_id for r in frappe.get_doc('Chantier Technical Study',name).lines if r.snapshot_json)
    missing=[]
    for row in order.items:
        macro=macros.get(row.get('custom_chantier_line'))
        if not macro or is_direct(macro):continue
        if macro.work_type not in definitions:missing.append(types(doc)[macro.work_type].designation)
    if missing:frappe.throw('Fiche technique validée requise avant commande pour : '+', '.join(dict.fromkeys(missing)))
