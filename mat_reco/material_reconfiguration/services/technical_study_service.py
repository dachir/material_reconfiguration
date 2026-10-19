"""Two standard submittable documents, sharing ERPNext Item and sales services."""
import json
import math
import uuid

import frappe
from frappe.utils import flt, cint, nowdate, add_days
from mat_reco.material_reconfiguration.services.chantier_service import fingerprint, chantier_doc, section_matches, get_quotation_usage
from mat_reco.material_reconfiguration.services import chantier_extras

GLASS = ('PRIMAIRE', 'DECOUPE', 'OUVRAGE')
MACRO_FIELDS = ('line_id','repere','designation','section','proposed_item','length_mm','width_mm','thickness_mm','qty','uom')


def source_hash(chantier):
    from .chantier_work_types import is_v2, technical_source_hash
    if is_v2(chantier):return technical_source_hash(chantier)
    rows=[]
    for row in chantier.get('lines',[]):
        values={k:row.get(k) for k in MACRO_FIELDS}
        for field in ('length_mm','width_mm','thickness_mm'):values[field]=flt(values[field])
        values['qty']=cint(values['qty'])
        rows.append(values)
    return fingerprint(dict(company=chantier.company,lines=rows))


def commercial_hash(chantier, study, legacy=None):
    values=dict(source=source_hash(chantier),study=study.technical_hash,customer=chantier.customer,
        currency=chantier.currency,price_list=chantier.selling_price_list,terms=chantier.terms,
        prices=[dict(id=r.line_id,rate=flt(r.rate),confirmed=cint(r.rate_set)) for r in chantier.lines])
    if chantier.get('taxes_and_charges'):values['taxes_and_charges']=chantier.taxes_and_charges
    if chantier.get('commercial_extras'):values['extras']=chantier_extras.signature(chantier,legacy=legacy)
    return fingerprint(values)


def commercial_hash_matches(chantier, study):
    # Prior approvals hashed browser integer prices before database float conversion.
    # Accept only exact equivalent payloads, keeping all other approval data checked.
    return any(chantier.commercial_hash==commercial_hash(chantier,study,legacy=mode)
               for mode in (None,'stored','browser'))


def assign_commercial_reperes(chantier):
    """Assign display identifiers without changing existing commercial references."""
    used = {row.repere for row in chantier.get('lines', []) if row.repere}
    number = 1
    for row in chantier.get('lines', []):
        if row.repere:
            continue
        while f'OUV-{number:03d}' in used:
            number += 1
        row.repere = f'OUV-{number:03d}'
        used.add(row.repere)


def validate_macro(chantier):
    from .chantier_work_types import validate_types, is_direct
    validate_types(chantier)
    assign_commercial_reperes(chantier)
    seen, ids = set(), set()
    if not chantier.currency:
        chantier.currency = frappe.get_cached_value('Company',chantier.company,'default_currency')
    if chantier.get('taxes_and_charges'):
        template=frappe.get_doc('Sales Taxes and Charges Template',chantier.taxes_and_charges)
        template.check_permission('read')
        if template.disabled or template.company!=chantier.company:
            frappe.throw('Choisir un modèle de taxes actif de la société du chantier.')
    for row in chantier.get('lines',[]):
        if not row.line_id:
            row.line_id = uuid.uuid4().hex
        if row.line_id in ids or row.repere in seen or not row.repere or not row.designation:
            frappe.throw('Chaque ouvrage doit avoir un identifiant, un repère unique et une désignation.')
        ids.add(row.line_id);seen.add(row.repere)
        if flt(row.qty)<=0 or flt(row.qty)!=cint(row.qty):
            frappe.throw('Les quantités commerciales doivent être des entiers positifs.')
        if flt(row.rate)<0 or any(flt(row.get(n))<0 for n in ('length_mm','width_mm','thickness_mm')):
            frappe.throw('Les dimensions et prix ne peuvent pas être négatifs.')
        if row.section:
            owner=chantier.name
            if chantier.is_new() and chantier.amended_from:
                owner=chantier.amended_from
            section_matches(row.section,owner)
        if row.proposed_item and not is_direct(row):
            item=frappe.get_doc('Item',row.proposed_item);item.check_permission('read')
            if item.disabled or item.custom_item_types not in ('OUVRAGE','DECOUPE'):
                frappe.throw('Choisir un ouvrage ou une découpe actif comme référence commerciale.')

    chantier_extras.validate_extras(chantier)


def approved_study(chantier, lock=False):
    names=frappe.db.sql('SELECT name FROM `tabChantier Technical Study` WHERE chantier=%s AND docstatus=1 ORDER BY modified DESC'+(' FOR UPDATE' if lock else ''),chantier.name)
    for name, in names:
        doc=frappe.get_doc('Chantier Technical Study',name)
        doc.check_permission('read')
        if doc.source_hash==source_hash(chantier):
            return doc
    frappe.throw('Une étude technique validée correspondant aux besoins actuels est obligatoire.')


def submit_chantier(doc):
    from .chantier_work_types import is_v2, approve_commercial
    if is_v2(doc):return approve_commercial(doc)
    if not doc.lines:
        frappe.throw('Ajouter les ouvrages commerciaux avant validation.')
    frappe.db.get_value('Chantier',doc.name,'name',for_update=True)
    study=approved_study(doc,lock=True)
    if not doc.currency:
        frappe.throw('Renseigner la devise du chantier.')
    doc.technical_study=study.name
    doc.commercial_hash=commercial_hash(doc,study)


def cancel_chantier(doc):
    if frappe.db.exists('Quotation',{'custom_chantier':doc.name,'docstatus':['!=',2]}) or frappe.db.exists('Sales Order',{'custom_chantier':doc.name,'docstatus':['!=',2]}):
        frappe.throw('Traiter les devis et commandes liés avant d’annuler le chantier ; supprimer les brouillons ou annuler les documents validés.')
    from .chantier_work_types import is_v2
    if not is_v2(doc) and frappe.db.exists('Chantier Technical Study',{'chantier':doc.name,'docstatus':['!=',2]}):
        frappe.throw('Supprimer les études en brouillon ou annuler les études validées avant d’annuler le chantier.')


def cancel_study(doc):
    if any(frappe.db.exists(dt,{'custom_technical_study':doc.name,'docstatus':['!=',2]}) for dt in ('Quotation','Sales Order')):
        frappe.throw('Traiter les devis et commandes liés avant d’annuler l’étude technique.')
    # The header points back to its approved study. Permit this one backlink
    # after sales documents are cleared; generation rechecks the study's docstatus.
    doc.ignore_linked_doctypes = ['Chantier']


def _ensure_serial(item):
    if item.disabled or not item.is_stock_item:
        frappe.throw(f'{item.name} doit être un article de stock actif.')
    if item.custom_item_types in GLASS and (not item.has_serial_no or item.has_batch_no):
        frappe.throw(f'{item.name} : le suivi Serial No est obligatoire pour les articles vitrés. Cet ancien article doit être remplacé par un article compatible.')
    if item.custom_item_types=='PRIMAIRE' and (not item.custom_is_reconfigurable or min(flt(item.custom_sheet_length_mm),flt(item.custom_sheet_width_mm),flt(item.custom_thickness_mm))<=0):
        frappe.throw(f'{item.name} : dimensions nominales et épaisseur de plaque requises.')


def seed_item(code, ancestors=()):
    if code in ancestors or len(ancestors)>=20:
        frappe.throw('Composition cyclique ou trop profonde.')
    item=frappe.get_doc('Item',code);item.check_permission('read');_ensure_serial(item)
    node=dict(mode='existing',item_code=item.name,item_name=item.item_name,item_type=item.custom_item_types,
        stock_uom=item.stock_uom,item_group=item.item_group,
        length_mm=flt(item.custom_sheet_length_mm),width_mm=flt(item.custom_sheet_width_mm),thickness_mm=flt(item.custom_thickness_mm),
        qty_factor=1,children=[])
    if item.custom_item_types=='OUVRAGE':
        for part in item.get('custom_composite_items',[]):
            child=seed_item(part.component_item_code,ancestors+(code,));child['qty_factor']=part.qty_factor;node['children'].append(child)
        if not node['children']:
            frappe.throw(f'{code} : composition vide.')
    elif item.custom_item_types=='DECOUPE':
        if not item.custom_parent_item:
            frappe.throw(f'{code} : matière primaire manquante.')
        parent=seed_item(item.custom_parent_item,ancestors+(code,))
        if parent['item_type']!='PRIMAIRE':
            frappe.throw(f'{code} : la source doit être un Item PRIMAIRE.')
        node['children']=[parent]
    return node


@frappe.whitelist()
def get_item_definition(item_code):
    return seed_item(item_code)


def _signature(node):
    """Commercial labels and parent usage ratios do not define the Item itself."""
    return dict(type=node['item_type'],uom=node.get('stock_uom'),
        dimensions=[flt(node.get(k)) for k in ('length_mm','width_mm','thickness_mm')] if node['item_type']=='PRIMAIRE' else [],
        components=[dict(code=c.get('item_code') or c.get('proposed_code'),qty=flt(c.get('qty_factor',1))) for c in node.get('children',[]) if c.get('item_type')!='AIR'])


def validate_node(node, depth=0, ancestors=(), budget=None):
    if budget is None:budget=[0]
    budget[0]+=1
    if not isinstance(node,dict) or budget[0]>1000 or depth>20:
        frappe.throw('Définition technique invalide ou trop volumineuse.')
    if node.get('item_type')=='AIR':
        thickness=flt(node.get('thickness_mm'))
        if depth==0 or node.get('children') or not math.isfinite(thickness) or thickness<=0:
            frappe.throw('La lame d’air doit avoir une épaisseur strictement positive et aucun enfant.')
        return
    code=node.get('item_code') if node.get('mode')=='existing' else node.get('proposed_code')
    if not code or code in ancestors:
        frappe.throw('Code article manquant ou composition cyclique.')
    if node.get('mode')=='existing':
        current=seed_item(code)
        if _signature(current)!=_signature(node):
            frappe.throw(f'{code} : la définition diffère de l’Item existant. Recharger cet Item ou définir un nouvel article.')
        # Validate descendants as well; UI may not modify a reused Item's children.
        # Browser JSON turns whole-valued floats into integers (4.0 -> 4).
        # Structural equality preserves numeric equivalence.
        if [_signature(c) for c in current['children']] != [_signature(c) for c in node.get('children',[]) if c.get('item_type')!='AIR']:
            frappe.throw(f'{code} : les composants d’un Item réutilisé ne peuvent pas être modifiés ici.')
    elif node.get('mode')=='new':
        if node.get('item_type') not in GLASS or not node.get('item_name') or not node.get('stock_uom') or not node.get('item_group') or not node.get('warehouse'):
            frappe.throw(f'{code} : type, désignation, unité, groupe et entrepôt sont obligatoires.')
        group=frappe.get_doc('Item Group',node['item_group']);group.check_permission('read')
        if group.is_group:
            frappe.throw('Choisir un groupe d’articles terminal.')
        frappe.get_doc('UOM',node['stock_uom']).check_permission('read')
    else:
        frappe.throw('Choisir un Item existant ou un nouvel article.')
    kind=node.get('item_type');children=node.get('children',[])
    if kind=='PRIMAIRE' and (children or min(flt(node.get('length_mm')),flt(node.get('width_mm')),flt(node.get('thickness_mm')))<=0):
        frappe.throw(f'{code} : format nominal positif requis et aucun composant autorisé.')
    if kind=='DECOUPE' and (len(children)!=1 or children[0].get('item_type')!='PRIMAIRE'):
        frappe.throw(f'{code} : définir exactement une matière PRIMAIRE.')
    if kind=='OUVRAGE' and (not any(c.get('item_type')!='AIR' for c in children) or any(c.get('item_type') not in ('OUVRAGE','DECOUPE','ACCESSOIRE','AIR') for c in children)):
        frappe.throw(f'{code} : ajouter des ouvrages, découpes ou accessoires comme composants.')
    for child in children:
        factor=flt(child.get('qty_factor',1))
        if factor<=0 or factor!=cint(factor):
            frappe.throw('Les ratios des composants doivent être des entiers positifs.')
        validate_node(child,depth+1,ancestors+(code,),budget)


def composition_thickness(node):
    """Thickness of glass layers and air; a cutting source is not another layer."""
    kind=node.get('item_type')
    if kind in ('PRIMAIRE','AIR'):return flt(node.get('thickness_mm'))
    if kind=='DECOUPE':return composition_thickness(node['children'][0])
    if kind=='OUVRAGE':
        return flt(node.get('air_gap_mm'))+sum(
            composition_thickness(child)*flt(child.get('qty_factor',1))
            for child in node.get('children',[]))
    return 0


def air_layers(node, path=(), ratio=1):
    layers=[]
    if node.get('item_type')=='AIR':
        return [dict(path=list(path),thickness_mm=flt(node.get('thickness_mm')),qty=ratio)]
    if flt(node.get('air_gap_mm')):
        layers.append(dict(path=list(path),thickness_mm=flt(node['air_gap_mm']),qty=ratio))
    for i,child in enumerate(node.get('children',[])):
        layers.extend(air_layers(child,path+(i,),ratio*flt(child.get('qty_factor',1))))
    return layers


def validate_study(doc):
    chantier=frappe.get_doc('Chantier',doc.chantier,for_update=True)
    chantier.check_permission('read')
    from .chantier_work_types import is_v2, prepare_type_rows
    loose=is_v2(chantier)
    if (chantier.docstatus!=0 and not loose) or chantier.docstatus==2 or chantier.status=='Cancelled':
        frappe.throw('L’étude technique doit être préparée et validée avant la validation commerciale finale.')
    if not chantier.lines:
        frappe.throw('Ajouter les besoins commerciaux au chantier avant l’étude.')
    if doc.is_new():
        from .ft_activation import require_activation, has_study
        require_activation(chantier)
        if not loose and has_study(chantier.name):
            frappe.throw('Supprimer la fiche technique existante avant d’en préparer une nouvelle.')
        doc.source_hash=source_hash(chantier)
    if not doc.source_hash:frappe.throw('Empreinte des besoins absente.')
    expected={r.line_id:r for r in (prepare_type_rows(chantier) if loose else chantier.lines)}
    if len(doc.lines)!=len(expected) or {r.line_id for r in doc.lines}!=set(expected):
        frappe.throw('L’étude doit couvrir exactement les lignes du chantier. Recharger les besoins.')
    for row in doc.lines:
        row.repere=expected[row.line_id].repere
        if doc.docstatus==0:
            row.result_item=None;row.snapshot_json=None;row.snapshot_hash=None
    if doc.docstatus==1:
        if doc.source_hash!=source_hash(chantier):
            frappe.throw('Les besoins commerciaux ont changé. Préparer une nouvelle étude correspondant à la version actuelle.')
        for row in doc.lines:
            if loose and abs(flt(row.thickness_mm)-flt(expected[row.line_id].thickness_mm))>.001:
                frappe.throw('L’épaisseur technique doit correspondre au type d’ouvrage du chantier.')
            if (flt(row.thickness_mm)<=0 if loose else min(flt(row.length_mm),flt(row.width_mm),flt(row.thickness_mm))<=0):
                frappe.throw(f'{row.repere} : compléter les trois dimensions.')
            node=frappe.parse_json(row.tree_json or '{}')
            if node.get('item_type') not in ('OUVRAGE','DECOUPE'):
                frappe.throw('L’ouvrage final doit être un OUVRAGE ou une DECOUPE.')
            air_gap=flt(node.get('air_gap_mm'))
            if not math.isfinite(air_gap) or air_gap<0 or air_gap>=flt(row.thickness_mm):
                frappe.throw(f'{row.repere} : la lame d’air doit être positive ou nulle et inférieure à l’épaisseur totale.')
            if air_gap and node.get('item_type')!='OUVRAGE':
                frappe.throw(f'{row.repere} : utiliser un OUVRAGE pour un vitrage avec lame d’air.')
            validate_node(node)
            calculated=composition_thickness(node)
            if not math.isfinite(calculated) or abs(calculated-flt(row.thickness_mm))>0.001:
                frappe.throw(f'{row.repere} : épaisseur totale incompatible : {flt(row.thickness_mm):g} mm saisis, {calculated:g} mm calculés (verres et lame d’air).')
            if expected[row.line_id].uom and expected[row.line_id].uom!=node['stock_uom']:
                frappe.throw('L’unité technique doit correspondre à l’unité de prix commerciale.')


def _resolve(node, company, created):
    code=node.get('item_code') if node['mode']=='existing' else node['proposed_code']
    if node['mode']=='existing':return code
    material_children=[c for c in node.get('children',[]) if c.get('item_type')!='AIR']
    children=[(_resolve(c,company,created),c.get('qty_factor',1)) for c in material_children]
    spec=dict(node,children=[dict(c,item_code=resolved) for c,(resolved,_) in zip(material_children,children)])
    if frappe.db.exists('Item',code):
        if _signature(seed_item(code))!=_signature(spec):
            frappe.throw(f'Le code {code} existe avec une définition différente. Aucun Item existant ne sera écrasé.')
        return code
    item=frappe.new_doc('Item')
    item.update(dict(item_code=code,item_name=node['item_name'],item_group=node['item_group'],stock_uom=node['stock_uom'],
        is_stock_item=1,has_serial_no=1,has_batch_no=0,custom_item_types=node['item_type'],
        custom_requires_dimensions=int(node['item_type']!='PRIMAIRE'),custom_is_reconfigurable=int(node['item_type']=='PRIMAIRE'),
        custom_is_composite=int(node['item_type']=='OUVRAGE')))
    if node['item_type']=='PRIMAIRE':
        item.update(dict(custom_sheet_length_mm=node['length_mm'],custom_sheet_width_mm=node['width_mm'],custom_thickness_mm=node['thickness_mm']))
    if node['item_type']=='DECOUPE':item.custom_parent_item=children[0][0]
    if node['item_type']=='OUVRAGE':
        for child,factor in children:item.append('custom_composite_items',dict(component_item_code=child,qty_factor=factor))
    if node.get('warehouse'):
        warehouse=frappe.get_doc('Warehouse',node['warehouse']);warehouse.check_permission('read')
        if warehouse.company!=company or warehouse.is_group:frappe.throw('Entrepôt incompatible avec la société.')
        item.append('item_defaults',dict(company=company,default_warehouse=warehouse.name))
    item.insert()  # Run existing codification, stock controllers with the operator's rights.
    created.append(item.name)
    return item.name


def submit_study(doc):
    chantier=frappe.get_doc('Chantier',doc.chantier,for_update=True)
    chantier.check_permission('read')
    from .chantier_work_types import is_v2
    loose=is_v2(chantier)
    if (chantier.docstatus!=0 and not loose) or chantier.docstatus==2 or doc.source_hash!=source_hash(chantier):
        frappe.throw('Les besoins ont changé pendant la validation. Actualiser l’étude avant de recommencer.')
    if not loose and frappe.db.get_value('Chantier Technical Study',{'chantier':chantier.name,'docstatus':1,'name':['!=',doc.name]},'name',for_update=True):
        frappe.throw('Une étude technique validée existe déjà. L’annuler avant de valider sa révision.')
    # Serialize generated Item names. External Item inserts remain protected by ERPNext's unique key.
    frappe.db.sql("SELECT name FROM tabDocType WHERE name='Item' FOR UPDATE")
    frappe.db.savepoint('technical_items')
    created=[]
    try:
        for row in doc.lines:
            row.result_item=_resolve(frappe.parse_json(row.tree_json),chantier.company,created)
            from mat_reco.material_reconfiguration.services.workshop_service import _tree
            source=frappe._dict(name=row.line_id,idx=row.idx,item_code=row.result_item,
                custom_client_length_mm=(1 if loose else row.length_mm),custom_client_width_mm=(1 if loose else row.width_mm),custom_client_thickness_mm=row.thickness_mm)
            tree=_tree(frappe._dict(name=chantier.name,company=chantier.company),source,item_code=row.result_item)
            definition=frappe.parse_json(row.tree_json)
            tree['air_layers']=air_layers(definition)
            tree['air_gap_mm']=sum(layer['thickness_mm']*layer['qty'] for layer in tree['air_layers'])
            row.snapshot_json=json.dumps(tree,ensure_ascii=False);row.snapshot_hash=fingerprint(tree)
        doc.technical_hash=fingerprint([dict(id=r.line_id,item=r.result_item,hash=r.snapshot_hash) for r in doc.lines])
    except Exception:
        frappe.db.rollback(save_point='technical_items')
        for code in created:frappe.clear_document_cache('Item',code)
        raise


@frappe.whitelist(methods=['POST'])
def prepare_study(chantier):
    dossier=chantier_doc(chantier)
    from .chantier_work_types import is_v2, prepare_study as prepare_types
    if is_v2(dossier):return prepare_types(chantier)
    if dossier.docstatus!=0 or dossier.status=='Cancelled':frappe.throw('Le chantier commercial doit être un brouillon actif.')
    frappe.db.get_value('Chantier',dossier.name,'name',for_update=True)
    from .ft_activation import require_activation
    require_activation(dossier)
    if not dossier.lines:frappe.throw('Ajouter au moins un ouvrage commercial.')
    current=source_hash(dossier)
    existing=frappe.db.get_value('Chantier Technical Study',{'chantier':chantier,'docstatus':['<',2],'source_hash':current},'name',for_update=True)
    if existing:
        frappe.get_doc('Chantier Technical Study',existing).check_permission('read');return existing
    previous=frappe.get_list('Chantier Technical Study',filters={'chantier':chantier},pluck='name',order_by='modified desc',limit_page_length=1)
    previous_lines={r.line_id:r for r in frappe.get_doc('Chantier Technical Study',previous[0]).lines} if previous else {}
    doc=frappe.new_doc('Chantier Technical Study');doc.chantier=chantier
    for row in dossier.lines:
        prior=previous_lines.get(row.line_id)
        code=row.proposed_item or (prior.result_item if prior else None)
        if code:
            tree=seed_item(code)
        elif prior:
            tree=frappe.parse_json(prior.tree_json)
        else:
            tree=dict(mode='new',proposed_code='',item_name=row.designation,item_type='OUVRAGE',stock_uom=row.uom or '',item_group='',qty_factor=1,children=[])
        if prior and 'air_gap_mm' in frappe.parse_json(prior.tree_json or '{}'):
            tree['air_gap_mm']=flt(frappe.parse_json(prior.tree_json).get('air_gap_mm'))
        doc.append('lines',dict(line_id=row.line_id,repere=row.repere,
            length_mm=row.length_mm or (prior.length_mm if prior else 0),width_mm=row.width_mm or (prior.width_mm if prior else 0),
            thickness_mm=row.thickness_mm or (prior.thickness_mm if prior else 0),tree_json=json.dumps(tree,ensure_ascii=False)))
    doc.insert();return doc.name


@frappe.whitelist()
def get_study(name=None):
    available=frappe.get_list('Chantier Technical Study',fields=['name','chantier','docstatus','modified'],order_by='modified desc',limit_page_length=100)
    if not name:return dict(studies=available)
    doc=frappe.get_doc('Chantier Technical Study',name);doc.check_permission('read');chantier=chantier_doc(doc.chantier)
    return dict(studies=available,study=doc.as_dict(),chantier=chantier.as_dict(),stale=doc.source_hash!=source_hash(chantier),
        sections=frappe.get_list('Chantier Section',filters={'chantier':chantier.name},fields=['name','section_name','parent_chantier_section'],limit_page_length=0),
        permissions=dict(write=doc.has_permission('write'),submit=doc.has_permission('submit'),cancel=doc.has_permission('cancel'),delete=doc.has_permission('delete')))


@frappe.whitelist(methods=['POST'])
def save_study(name, modified, lines, notes=None):
    doc=frappe.get_doc('Chantier Technical Study',name,for_update=True);doc.check_permission('write')
    if doc.docstatus!=0 or str(doc.modified)!=str(modified):frappe.throw('L’étude a changé. Actualiser avant de l’enregistrer.')
    incoming=frappe.parse_json(lines)
    if not isinstance(incoming,list) or len(incoming)>500:frappe.throw('Définition trop volumineuse.')
    doc.set('lines',[{k:r.get(k) for k in ('line_id','length_mm','width_mm','thickness_mm','tree_json')} for r in incoming]);doc.notes=notes;doc.save();return get_study(doc.name)


@frappe.whitelist()
def get_rate(chantier, item_code, uom=None):
    dossier=chantier_doc(chantier);item=frappe.get_doc('Item',item_code);item.check_permission('read')
    if not dossier.selling_price_list:return dict(found=False)
    price_list=frappe.get_doc('Price List',dossier.selling_price_list);price_list.check_permission('read')
    if price_list.currency!=dossier.currency:frappe.throw('La devise de la liste de prix diffère du chantier. Saisir un prix dans la devise du chantier.')
    from erpnext.stock.get_item_details import get_item_price
    args=frappe._dict(price_list=price_list.name,uom=uom or item.stock_uom,transaction_date=nowdate(),customer=dossier.customer)
    prices=get_item_price(args,item.name)
    if not prices:
        args.customer=None;prices=get_item_price(args,item.name)
    return dict(found=bool(prices),rate=prices[0][1] if prices else None,currency=price_list.currency)


def quotation_rows(chantier, study):
    technical={r.line_id:r for r in study.lines}
    return {r.line_id:(r,technical[r.line_id]) for r in chantier.lines}


def validate_quote(doc, chantier):
    from .chantier_work_types import is_v2, validate_commercial_quote
    if is_v2(chantier):return validate_commercial_quote(doc,chantier)
    if chantier.docstatus!=1:frappe.throw('Valider le chantier commercial avant de créer le devis.')
    study=approved_study(chantier)
    if chantier.technical_study!=study.name or not commercial_hash_matches(chantier,study):
        frappe.throw('Les validations technique et commerciale ne correspondent plus.')
    if doc.currency!=chantier.currency:frappe.throw('La devise doit correspondre au chantier approuvé.')
    if chantier.get('taxes_and_charges') and doc.taxes_and_charges!=chantier.taxes_and_charges:
        frappe.throw('Le modèle de taxes doit correspondre au chantier approuvé.')
    definitions=quotation_rows(chantier,study)
    by_repere={r.repere:r.line_id for r in chantier.lines}
    doc.custom_technical_study=study.name
    frappe.db.get_value('Chantier',chantier.name,'name',for_update=True)
    extras=chantier_extras.validate_quote_extras(doc,chantier)
    seen=set()
    for row in doc.items:
        if row.get('custom_chantier_line') in extras:continue
        identity=row.get('custom_chantier_line') or by_repere.get(row.get('custom_repere'))
        if identity not in definitions:frappe.throw('Chaque ligne du devis doit provenir du chantier approuvé.')
        if identity in seen:frappe.throw('Ouvrage dupliqué dans le devis.')
        seen.add(identity)
        macro,tech=definitions[identity]
        if row.item_code!=tech.result_item or row.custom_repere!=macro.repere or row.custom_chantier_section!=macro.section or flt(row.rate)!=flt(macro.rate):
            frappe.throw('Article, repère, section ou prix différent du chantier approuvé.')
        if row.uom!=frappe.get_cached_value('Item',tech.result_item,'stock_uom'):frappe.throw('Unité de prix incompatible.')
        for field,technical in [('custom_client_length_mm','length_mm'),('custom_client_width_mm','width_mm'),('custom_client_thickness_mm','thickness_mm')]:
            if abs(flt(row.get(field))-flt(tech.get(technical)))>.001:frappe.throw('Dimensions différentes de l’étude approuvée.')
        row.custom_chantier_line=identity;row.custom_technical_snapshot=tech.snapshot_json;row.custom_technical_hash=tech.snapshot_hash
        previous=frappe.db.sql('''SELECT i.qty FROM `tabQuotation Item` i JOIN tabQuotation q ON q.name=i.parent
            WHERE q.custom_chantier=%s AND q.docstatus<2 AND q.name!=%s
            AND (i.custom_chantier_line=%s OR (COALESCE(i.custom_chantier_line,'')='' AND i.custom_repere=%s)) FOR UPDATE''',(chantier.name,doc.name or '',identity,macro.repere))
        if sum(flt(r[0]) for r in previous)+flt(row.qty)>macro.qty:frappe.throw('La quantité mise au devis dépasse le besoin du chantier.')


@frappe.whitelist(methods=['POST'])
def generate_quotation(chantier, selections=None, request_key=None, submit=False):
    dossier=chantier_doc(chantier)
    if dossier.docstatus!=1:frappe.throw('Valider le chantier commercial avant de générer le devis.')
    frappe.db.get_value('Chantier',dossier.name,'name',for_update=True)
    from .chantier_work_types import is_v2, types, is_direct
    loose=is_v2(dossier)
    study=None if loose else approved_study(dossier,lock=True)
    if not request_key or len(request_key)>100:frappe.throw('Clé de génération requise.')
    selection=frappe.parse_json(selections) if selections is not None else None
    if selection is not None and (not isinstance(selection,list) or not selection or any(not isinstance(r,dict) or not r.get('line_id') for r in selection)):frappe.throw('Sélection invalide.')
    # Sign the request intent before deriving the residual. A retry must return
    # its original quote even though that quote has now consumed the balance.
    scope=fingerprint(dict(chantier=chantier,selection=None if selection is None else sorted([dict(line_id=r['line_id'],qty=flt(r.get('qty'))) for r in selection],key=lambda r:r['line_id']),submit=cint(submit)))
    key=fingerprint(dict(user=frappe.session.user,key=request_key))
    existing=frappe.db.get_value('Quotation',{'custom_chantier_request_key':key},['name','custom_chantier','docstatus','custom_chantier_request_scope'],as_dict=True,for_update=True)
    if existing:
        if existing.custom_chantier!=chantier or existing.docstatus==2 or existing.custom_chantier_request_scope!=scope:frappe.throw('Cette clé correspond à une autre opération ou à un devis annulé.')
        frappe.get_doc('Quotation',existing.name).check_permission('read');return existing.name
    if selection is None:
        usage=get_quotation_usage(dossier)
        selection=[dict(line_id=r.line_id,qty=max(0,flt(r.qty)-flt(usage.get(r.line_id)))) for r in dossier.lines]
        selection=[r for r in selection if r['qty']>0]
        if not selection:frappe.throw('Tous les ouvrages de ce chantier sont déjà au devis.')
    definitions={r.line_id:(r,None) for r in dossier.lines} if loose else quotation_rows(dossier,study)
    if not isinstance(selection,list) or not selection or len(selection)>500 or len({r.get('line_id') for r in selection})!=len(selection):frappe.throw('Sélection de lignes invalide.')
    quote=frappe.new_doc('Quotation')
    quote.update(dict(quotation_to='Customer',party_name=dossier.customer,company=dossier.company,currency=dossier.currency,selling_price_list=dossier.selling_price_list,custom_chantier=dossier.name,custom_technical_study=None if loose else study.name,custom_chantier_request_key=key,custom_chantier_request_scope=scope,ignore_pricing_rule=1,valid_till=add_days(nowdate(),30),terms=dossier.terms))
    if loose:
        section_order={row.name:i for i,row in enumerate(frappe.get_list('Chantier Section',filters={'chantier':dossier.name},fields=['name'],order_by='lft asc',limit_page_length=0))}
        type_order={row.type_id:i for i,row in enumerate(dossier.work_types)}
        macros={row.line_id:row for row in dossier.lines}
        selection.sort(key=lambda chosen:(section_order.get(macros.get(chosen.get('line_id'),frappe._dict()).get('section'),-1),type_order.get(macros.get(chosen.get('line_id'),frappe._dict()).get('work_type'),0)))
    for chosen in selection:
        if chosen.get('line_id') not in definitions or flt(chosen.get('qty'))<=0 or flt(chosen['qty'])!=cint(chosen['qty']):frappe.throw('Quantité entière positive requise sur une ligne du chantier.')
        macro,tech=definitions[chosen['line_id']]
        if loose:tech=frappe._dict(result_item=macro.sale_item if is_direct(macro) else types(dossier)[macro.work_type].commercial_item,length_mm=macro.length_mm,width_mm=macro.width_mm,thickness_mm=macro.thickness_mm)
        quote.append('items',dict(item_code=tech.result_item,qty=chosen['qty'],uom=frappe.get_cached_value('Item',tech.result_item,'stock_uom'),rate=macro.rate,
            custom_repere=macro.repere,custom_chantier_section=macro.section,custom_chantier_line=macro.line_id,
            custom_client_length_mm=tech.length_mm,custom_client_width_mm=tech.width_mm,custom_client_thickness_mm=tech.thickness_mm))
    chantier_extras.add_quote_rows(quote,dossier)
    if dossier.get('taxes_and_charges'):
        quote.taxes_and_charges=dossier.taxes_and_charges
    quote.run_method('set_missing_values')
    if dossier.get('taxes_and_charges'):
        from erpnext.controllers.accounts_controller import get_taxes_and_charges
        quote.taxes_and_charges=dossier.taxes_and_charges
        quote.set('taxes',get_taxes_and_charges('Sales Taxes and Charges Template',dossier.taxes_and_charges))
    prices={r.line_id:r for r in list(dossier.lines)+list(dossier.get('commercial_extras', []))}
    # Preserve the manager-approved price, including an explicitly free line.
    for row in quote.items:
        macro=prices[row.custom_chantier_line]
        if loose and macro.line_id in {r.line_id for r in dossier.lines}:
            row.item_name=macro.designation;row.description=frappe.utils.escape_html(macro.designation)
        row.rate=macro.rate;row.price_list_rate=macro.rate;row.discount_percentage=0;row.discount_amount=0
        row.is_free_item=int(flt(macro.rate)==0)
    quote.run_method('calculate_taxes_and_totals');quote.insert()
    if cint(submit):quote.submit()
    return quote.name


@frappe.whitelist(methods=['POST'])
def save_commercial(chantier, modified, lines, currency=None, selling_price_list=None, terms=None, commercial_extras=None, header=None, taxes_and_charges=None, work_types=None, upgrade_types=False):
    doc=frappe.get_doc('Chantier',chantier,for_update=True);doc.check_permission('write')
    if doc.docstatus!=0 or str(doc.modified)!=str(modified):frappe.throw('Le chantier a changé. Actualiser avant de l’enregistrer.')
    if cint(upgrade_types) and not doc.get('workflow_version'):
        if any(frappe.db.exists(dt,{key:chantier}) for dt,key in [('Chantier Technical Study','chantier'),('Quotation','custom_chantier'),('Sales Order','custom_chantier')]):
            frappe.throw('Conserver les documents existants : utiliser un nouveau chantier pour le nouveau parcours.')
        doc.workflow_version=2
    incoming=frappe.parse_json(lines)
    if not isinstance(incoming,list) or len(incoming)>500:frappe.throw('Saisir au maximum 500 ouvrages.')
    allowed=MACRO_FIELDS+('rate','rate_set','price_source','work_type','excluded_type_extras','line_kind','sale_item')
    if work_types is not None:
        type_rows=frappe.parse_json(work_types)
        if not isinstance(type_rows,list) or len(type_rows)>200:frappe.throw('Types d’ouvrage invalides.')
        existing={r.type_id:r for r in doc.get('work_types',[])}
        doc.set('work_types',[])
        for row in type_rows:
            prior=existing.get(row.get('type_id'))
            values={k:row.get(k) for k in ('type_id','designation','thickness_mm','proposed_item','common_extras')}
            if prior:values.update(name=prior.name,commercial_item=prior.commercial_item)
            doc.append('work_types',values)
    doc.set('lines',[{k:r.get(k) for k in allowed} for r in incoming])
    if commercial_extras is not None:
        supplements=frappe.parse_json(commercial_extras)
        if not isinstance(supplements,list) or len(supplements)>2000:frappe.throw('Liste de compléments invalide (maximum 2000).')
        doc.set('commercial_extras',[{k:r.get(k) for k in chantier_extras.FIELDS+('inherited_from','inherited_key','inherited_qty_override','inherited_rate_override')} for r in supplements])
    if header is not None:
        values = frappe.parse_json(header)
        if not isinstance(values, dict):
            frappe.throw('En-tête de chantier invalide.')
        for field in ('customer', 'designation', 'responsible', 'expected_start_date', 'expected_end_date'):
            if field in values:
                doc.set(field, values[field])
    if taxes_and_charges is not None:doc.taxes_and_charges=taxes_and_charges
    doc.currency=currency;doc.selling_price_list=selling_price_list;doc.terms=terms;doc.save();return doc.as_dict()


@frappe.whitelist(methods=['POST'])
def confirm_order(quotation, acceptance_reference, delivery_date, request_key, direct_only=False):
    quote=frappe.get_doc('Quotation',quotation);quote.check_permission('read')
    if quote.docstatus!=1 or not quote.custom_chantier:frappe.throw('Un devis de chantier validé est requis.')
    if not acceptance_reference or not acceptance_reference.strip() or not delivery_date or not request_key or len(request_key)>100:frappe.throw('Renseigner l’acceptation client, la date et une clé de confirmation.')
    frappe.db.get_value('Chantier',quote.custom_chantier,'name',for_update=True)
    frappe.db.get_value('Quotation',quote.name,'name',for_update=True)
    intent=dict(quotation=quotation,acceptance=acceptance_reference.strip(),date=str(frappe.utils.getdate(delivery_date)))
    if cint(direct_only):intent['direct_only']=True
    scope=fingerprint(intent)
    key=fingerprint(dict(user=frappe.session.user,key=request_key))
    existing=frappe.db.get_value('Sales Order',{'custom_chantier_order_key':key},['name','custom_chantier','docstatus','custom_chantier_order_scope'],as_dict=True,for_update=True)
    if existing:
        if existing.custom_chantier!=quote.custom_chantier or existing.docstatus!=1 or existing.custom_chantier_order_scope!=scope:frappe.throw('Clé déjà utilisée par une autre opération.')
        frappe.get_doc('Sales Order',existing.name).check_permission('read');return existing.name
    from erpnext.selling.doctype.quotation.quotation import make_sales_order
    order=make_sales_order(quote.name)
    if cint(direct_only):
        from .chantier_work_types import is_direct
        parent=frappe.get_doc('Chantier',quote.custom_chantier)
        direct={r.line_id for r in parent.lines if is_direct(r)}
        direct_quote_names={r.name for r in quote.items if r.custom_chantier_line in direct}
        order.set('items',[r for r in order.items if r.get('custom_chantier_line') in direct or next((q.get('custom_parent_row') in direct_quote_names for q in quote.items if q.name==r.quotation_item),False)])
    if not order.items:frappe.throw('Ce devis a déjà été entièrement transformé en commande.')
    order.custom_customer_acceptance=acceptance_reference.strip();order.custom_chantier_order_key=key;order.custom_chantier_order_scope=scope;order.delivery_date=delivery_date
    for row in order.items:row.delivery_date=delivery_date
    order.insert();order.submit();return order.name


def before_insert_chantier(doc):
    # Amendments retain their original model and historical technical identities.
    doc.workflow_version=frappe.get_cached_value("Chantier",doc.amended_from,"workflow_version") if doc.amended_from else 2
    if doc.amended_from and doc.reference==frappe.get_cached_value('Chantier',doc.amended_from,'reference'):
        from frappe.model.naming import getseries
        prefix=doc.reference+'-R';doc.reference=prefix+getseries(prefix,2)


def clone_sections(doc):
    if not doc.amended_from:return
    originals=frappe.get_all('Chantier Section',filters={'chantier':doc.amended_from},fields=['name','section_name','parent_chantier_section','is_group'],order_by='lft',limit_page_length=0)
    mapping={}
    for old in originals:
        section=frappe.get_doc(dict(doctype='Chantier Section',chantier=doc.name,section_name=old.section_name,is_group=old.is_group,parent_chantier_section=mapping.get(old.parent_chantier_section)))
        section.insert();mapping[old.name]=section.name
    for row in doc.lines:
        if row.section:
            row.section=mapping.get(row.section);frappe.db.set_value('Chantier Line',row.name,'section',row.section,update_modified=False)


@frappe.whitelist(methods=['POST'])
def delete_study(name, modified):
    doc=frappe.get_doc('Chantier Technical Study',name,for_update=True)
    doc.check_permission('delete')
    if str(doc.modified)!=str(modified):
        frappe.throw('L’étude a changé. Actualiser avant de la supprimer.')
    if doc.docstatus==1:
        frappe.throw('Annuler l’étude validée avant de la supprimer.')
    chantier=doc.chantier
    frappe.delete_doc(doc.doctype,doc.name)
    return chantier


@frappe.whitelist(methods=['POST'])
def cancel_dossier(chantier, modified):
    doc=frappe.get_doc('Chantier',chantier,for_update=True)
    doc.check_permission('write' if doc.docstatus==0 else 'cancel')
    if str(doc.modified)!=str(modified):
        frappe.throw('Le chantier a changé. Actualiser avant de l’annuler.')
    cancel_chantier(doc)
    if doc.docstatus==0:
        doc.status='Cancelled'
        doc.save()
    elif doc.docstatus==1:
        doc.cancel()
    return doc.name


@frappe.whitelist()
def designation_suggestions(txt=''):
    # Query parents through get_list so document-level permissions still apply.
    parents=frappe.get_list('Chantier',pluck='name',limit_page_length=0)
    if not parents:return []
    values=[]
    for child in ('Chantier Line','Chantier Work Type'):
        values.extend(frappe.get_all(child,
            filters={'parent':['in',parents],'parenttype':'Chantier','designation':['like','%'+txt+'%']},
            fields=['designation'],group_by='designation',order_by='designation asc',limit_page_length=10,
            pluck='designation'))
    return sorted(set(values),key=str.casefold)[:10]


@frappe.whitelist()
def designation_autocomplete(txt='', query=None):
    return [dict(value=value,label=frappe.utils.escape_html(value)) for value in designation_suggestions(txt)]
