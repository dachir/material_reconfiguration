"""Commercial supplements, distinct from the physical Item composition."""
import uuid
import frappe
from frappe.utils import flt, cint

FIELDS = ('line_id', 'parent_line_id', 'item_code', 'manual_qty', 'qty', 'rate', 'rate_set', 'price_source')


def quantity(item, parent, dimensions=None):
    basis = 'MANUEL' if item.custom_item_types == 'ACCESSOIRE' else (item.custom_service_calc_basis or 'MANUEL')
    dimensions = dimensions or parent
    length, width = flt(dimensions.length_mm), flt(dimensions.width_mm)
    count = flt(parent.qty)
    values = {'SURFACE': length * width / 1_000_000 * count,
              'PERIMETRE': 2 * (length + width) / 1000 * count,
              'PIECE': count, 'FIXE': flt(item.custom_service_fixed_qty) or 1, 'MANUEL': 0}
    if basis not in values:
        frappe.throw('Base de calcul du service inconnue.')
    return basis, values[basis]


def validate_extras(doc):
    from .technical_study_service import source_hash
    parents = {r.line_id: r for r in doc.lines}
    dimensions = {}
    if doc.get('commercial_extras') and not doc.is_new() and frappe.has_permission('Chantier Technical Study', 'read'):
        for row in frappe.get_list('Chantier Technical Study', filters={'chantier': doc.name, 'docstatus': ['<', 2], 'source_hash': source_hash(doc)}, fields=['name'], order_by='docstatus desc, modified desc', limit_page_length=1):
            study = frappe.get_doc('Chantier Technical Study', row.name)
            dimensions = {r.line_id: r for r in study.lines}
    seen = set(parents)
    for extra in doc.get('commercial_extras', []):
        extra.line_id = extra.line_id or uuid.uuid4().hex
        if extra.line_id in seen or extra.parent_line_id not in parents:
            frappe.throw('Chaque complément doit avoir un identifiant unique et un ouvrage parent du chantier.')
        seen.add(extra.line_id)
        item = frappe.get_doc('Item', extra.item_code);item.check_permission('read')
        if item.disabled or item.custom_item_types not in ('SERVICE', 'ACCESSOIRE') or not item.is_sales_item:
            frappe.throw('Choisir un service ou accessoire actif et vendable.')
        basis, calculated = quantity(item, parents[extra.parent_line_id], dimensions.get(extra.parent_line_id))
        extra.item_name, extra.item_type, extra.uom = item.item_name, item.custom_item_types, item.stock_uom
        extra.calculation_basis, extra.calculated_qty = basis, calculated
        if basis == 'MANUEL': extra.manual_qty = 1
        extra.qty = flt(extra.qty) if cint(extra.manual_qty) else calculated
        if extra.qty <= 0 or flt(extra.rate) < 0:
            parent=parents[extra.parent_line_id]
            reason='saisir un prix positif ou nul' if flt(extra.rate)<0 else ('compléter les dimensions de l’ouvrage ou son étude technique à jour' if basis in ('SURFACE','PERIMETRE') and not cint(extra.manual_qty) else 'saisir une quantité positive')
            frappe.throw(f'{parent.repere} — {item.item_name} : {reason}.')


def signature(doc, legacy=None):
    rows=[]
    for row in doc.get('commercial_extras', []):
        values={k:row.get(k) for k in FIELDS+('item_type','uom','calculation_basis')}
        if legacy=='browser':
            rate=flt(values['rate'])
            values['rate']=int(rate) if rate.is_integer() else rate
        elif not legacy:
            for field in ('qty','rate'):values[field]=flt(values[field])
            for field in ('manual_qty','rate_set'):values[field]=cint(values[field])
        rows.append(values)
    return rows


@frappe.whitelist()
def preview(chantier, parent_line_id, item_code):
    from .chantier_service import chantier_doc
    from .technical_study_service import get_rate
    doc = chantier_doc(chantier)
    parent = next((r for r in doc.lines if r.line_id == parent_line_id), None)
    if not parent: frappe.throw('Ouvrage parent introuvable.')
    extra = doc.append('commercial_extras', dict(parent_line_id=parent_line_id, item_code=item_code, qty=1, manual_qty=1))
    validate_extras(doc)
    basis, calculated = extra.calculation_basis, extra.calculated_qty
    return dict(item_name=extra.item_name, item_type=extra.item_type, uom=extra.uom,
                calculation_basis=basis, calculated_qty=calculated, manual_qty=int(basis=='MANUEL'),
                qty=calculated if basis!='MANUEL' else 1, **get_rate(chantier,item_code))


def add_quote_rows(quote, dossier):
    parents = {r.custom_chantier_line: r for r in quote.items}
    macros = {r.line_id: r for r in dossier.lines}
    for extra in dossier.get('commercial_extras', []):
        parent = parents.get(extra.parent_line_id)
        if not parent: continue
        macro = macros[extra.parent_line_id]
        quote.append('items', dict(item_code=extra.item_code, qty=flt(extra.qty)*flt(parent.qty)/flt(macro.qty),
            uom=extra.uom, rate=extra.rate, custom_chantier_line=extra.line_id,
            custom_repere=macro.repere, custom_chantier_section=macro.section,
            custom_is_service_row=int(extra.item_type=='SERVICE'), custom_is_accessory_row=int(extra.item_type=='ACCESSOIRE'),
            custom_item_types=extra.item_type))
    # Allocate final child names once before wiring commercial parent references.
    quote.set_new_name()
    for extra in dossier.get('commercial_extras', []):
        child = next((r for r in quote.items if r.custom_chantier_line==extra.line_id), None)
        if child: child.custom_parent_row = parents[extra.parent_line_id].name


def validate_quote_extras(quote, dossier):
    extras = {r.line_id: r for r in dossier.get('commercial_extras', [])}
    parents = {r.custom_chantier_line: r for r in quote.items if r.custom_chantier_line not in extras}
    macros = {r.line_id: r for r in dossier.lines}
    seen = set()
    for row in quote.items:
        extra = extras.get(row.custom_chantier_line)
        if not extra: continue
        parent = parents.get(extra.parent_line_id)
        if not parent or extra.line_id in seen: frappe.throw('Complément dupliqué ou sans ouvrage parent dans le devis.')
        seen.add(extra.line_id)
        expected = flt(extra.qty)*flt(parent.qty)/flt(macros[extra.parent_line_id].qty)
        if (row.item_code!=extra.item_code or row.uom!=extra.uom or abs(flt(row.rate)-flt(extra.rate))>.000001
            or abs(flt(row.qty)-expected)>.000001 or row.custom_parent_row!=parent.name
            or cint(row.custom_is_service_row)!=int(extra.item_type=='SERVICE')
            or cint(row.custom_is_accessory_row)!=int(extra.item_type=='ACCESSOIRE')
            or row.custom_repere!=parent.custom_repere or row.custom_chantier_section!=parent.custom_chantier_section):
            frappe.throw('Le complément du devis diffère du chantier approuvé.')
        row.custom_technical_snapshot=None;row.custom_technical_hash=None
    expected_ids = {e.line_id for e in extras.values() if e.parent_line_id in parents}
    if seen!=expected_ids: frappe.throw('Reprendre tous les services et accessoires des ouvrages sélectionnés.')
    return extras


def map_order_extras(order):
    """Rebind quotation child names to Sales Order child names and enforce accepted prices."""
    sources = {}
    keys = [(r.prevdoc_docname, r.quotation_item) for r in order.items if r.prevdoc_docname and r.quotation_item]
    if len(keys)!=len(set(keys)):frappe.throw('Une ligne du devis ne peut pas être reprise deux fois dans la même commande.')
    mapped = {(r.prevdoc_docname, r.quotation_item): r for r in order.items}
    for row in order.items:
        if not row.prevdoc_docname or not row.quotation_item: continue
        if row.prevdoc_docname not in sources:
            source = frappe.get_doc('Quotation', row.prevdoc_docname);source.check_permission('read')
            if source.docstatus!=1 or source.custom_chantier!=order.custom_chantier:
                frappe.throw('Devis de chantier validé requis.')
            sources[source.name] = source
        origin = next((r for r in sources[row.prevdoc_docname].items if r.name==row.quotation_item), None)
        if not origin or not (origin.custom_is_service_row or origin.custom_is_accessory_row): continue
        parent = mapped.get((row.prevdoc_docname, origin.custom_parent_row))
        source_parent = next((r for r in sources[row.prevdoc_docname].items if r.name==origin.custom_parent_row), None)
        if not parent or not source_parent: frappe.throw('Le complément doit accompagner son ouvrage dans la commande.')
        if (row.item_code!=origin.item_code or row.uom!=origin.uom or abs(flt(row.rate)-flt(origin.rate))>.000001
            or abs(flt(row.qty)-flt(origin.qty)*flt(parent.qty)/flt(source_parent.qty))>.000001):
            frappe.throw('Service ou accessoire différent du devis accepté.')
        row.custom_parent_row=parent.name
        row.custom_is_service_row=origin.custom_is_service_row
        row.custom_is_accessory_row=origin.custom_is_accessory_row
        row.custom_item_types=origin.custom_item_types
        row.custom_chantier_line=origin.custom_chantier_line
        row.custom_repere=origin.custom_repere;row.custom_chantier_section=origin.custom_chantier_section
    for source in sources.values():
        for origin in source.items:
            if origin.custom_parent_row and (source.name,origin.custom_parent_row) in mapped and (source.name,origin.name) not in mapped:
                frappe.throw('Reprendre les services et accessoires de chaque ouvrage commandé.')


@frappe.whitelist()
def catalogue():
    """Permission-filtered commercial catalogue; quantities remain server-calculated."""
    rows = frappe.get_list('Item', filters={'custom_item_types': ['in', ['SERVICE', 'ACCESSOIRE']],
        'disabled': 0, 'is_sales_item': 1}, fields=['name', 'item_name', 'custom_item_types',
        'custom_service_calc_basis', 'stock_uom'], order_by='item_name asc', limit_page_length=0)
    for row in rows:
        row['basis'] = 'MANUEL' if row.custom_item_types=='ACCESSOIRE' else (row.custom_service_calc_basis or 'MANUEL')
    return rows


@frappe.whitelist(methods=['POST'])
def preview_batch(chantier, modified, parent_line_ids, assignments):
    """Validate the whole selection before returning any draft assignments, without writing."""
    from .chantier_service import chantier_doc
    from .technical_study_service import get_rate
    doc = chantier_doc(chantier);doc.check_permission('write')
    if doc.docstatus!=0 or str(doc.modified)!=str(modified):
        frappe.throw('Le chantier a changé. Actualiser avant de l’affecter.')
    parents, choices = frappe.parse_json(parent_line_ids), frappe.parse_json(assignments)
    if (not isinstance(parents, list) or not parents or len(parents)>500
        or any(not isinstance(p,str) for p in parents) or len(set(parents))!=len(parents)
        or not isinstance(choices,list) or not choices or any(not isinstance(c,dict) or not isinstance(c.get('item_code'),str) for c in choices)
        or len(choices)>500 or len({c['item_code'] for c in choices})!=len(choices)):
        frappe.throw('Sélection d’ouvrages et de compléments invalide.')
    known = {r.line_id for r in doc.lines}
    if not set(parents).issubset(known):frappe.throw('Un ouvrage sélectionné ne fait pas partie de ce chantier.')
    existing = {(r.parent_line_id,r.item_code) for r in doc.get('commercial_extras',[])}
    missing = [(parent,c) for parent in parents for c in choices if (parent,c['item_code']) not in existing]
    if len(missing)+len(doc.get('commercial_extras',[]))>2000:frappe.throw('Maximum 2000 compléments par chantier.')
    # Validate Items even when their assignments already exist; never accept arbitrary kinds.
    prices = {}
    for choice in choices:
        item = frappe.get_doc('Item',choice['item_code']);item.check_permission('read')
        if item.disabled or not item.is_sales_item or item.custom_item_types not in ('SERVICE','ACCESSOIRE'):
            frappe.throw('Choisir des services et accessoires actifs et vendables.')
        prices[item.name] = get_rate(chantier,item.name)
    added=[]
    for parent,choice in missing:
        price=prices[choice['item_code']]
        custom_rate=choice.get('rate') not in (None,'')
        if custom_rate and flt(choice['rate'])<0:
            frappe.throw('Le prix commun doit être positif ou nul.')
        added.append(doc.append('commercial_extras',dict(parent_line_id=parent,item_code=choice['item_code'],
            manual_qty=cint(choice.get('manual_qty')),qty=flt(choice.get('qty')),
            rate=flt(choice['rate']) if custom_rate else (price['rate'] if price['found'] else 0),
            rate_set=int(bool(cint(choice.get('rate_set')))) if custom_rate else int(bool(price['found'])),price_source='Manual' if custom_rate else ('Price List' if price['found'] else ''))))
    validate_extras(doc)
    return dict(rows=[r.as_dict() for r in added],skipped=len(parents)*len(choices)-len(added))
