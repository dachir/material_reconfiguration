"""Chantier dossier, commercial-line provenance and production consolidation."""
import hashlib
import json

import frappe
from frappe.utils import flt, getdate


DIMENSIONS = [('custom_client_length_mm', 'length_mm'), ('custom_client_width_mm', 'width_mm'), ('custom_client_thickness_mm', 'thickness_mm')]


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def chantier_doc(name, permission='read'):
    doc = frappe.get_doc('Chantier', name)
    doc.check_permission(permission)
    return doc


def validate_chantier(doc):
    if doc.expected_start_date and doc.expected_end_date and getdate(doc.expected_end_date) < getdate(doc.expected_start_date):
        frappe.throw('La fin prévue doit être postérieure au début prévu.')
    old = doc.get_doc_before_save()
    if old and (old.company != doc.company or old.customer != doc.customer):
        if any(frappe.db.exists(dt, {'custom_chantier':doc.name}) for dt in ('Quotation','Sales Order')):
            frappe.throw('Le client et la société ne peuvent plus changer après création des documents commerciaux.')


def validate_section(doc):
    parent_dossier = chantier_doc(doc.chantier)
    if parent_dossier.docstatus != 0:
        frappe.throw('Les sections d’un chantier validé ou annulé ne peuvent pas être modifiées.')
    old = doc.get_doc_before_save()
    if old and old.chantier != doc.chantier:
        frappe.throw('Une section existante ne peut pas changer de chantier.')
    if not doc.is_group and frappe.db.exists('Chantier Section', {'parent_chantier_section':doc.name}):
        frappe.throw('Une section avec des enfants doit rester un groupe.')
    if doc.parent_chantier_section:
        parent = frappe.get_doc('Chantier Section', doc.parent_chantier_section)
        parent.check_permission('read')
        if parent.chantier != doc.chantier or not parent.is_group:
            frappe.throw('La section parente doit être un groupe du même chantier.')


def section_matches(name, chantier):
    if not name:
        return
    section = frappe.get_doc('Chantier Section', name)
    section.check_permission('read')
    if section.chantier != chantier:
        frappe.throw('La section appartient à un autre chantier.')


def map_chantier(doc, method, source_doc):
    if source_doc.doctype != 'Quotation':
        return
    value = source_doc.get('custom_chantier')
    if doc.get('custom_chantier') and doc.custom_chantier != value:
        frappe.throw('Impossible de regrouper des devis de chantiers différents ou sans chantier.')
    if value:
        # An existing legacy target with rows from unlinked quotations cannot acquire a dossier silently.
        for row in doc.get('items', []):
            if row.get('prevdoc_docname') and row.prevdoc_docname != source_doc.name:
                other = frappe.get_cached_value('Quotation', row.prevdoc_docname, 'custom_chantier')
                if other != value:
                    frappe.throw('Les devis regroupés doivent appartenir au même chantier.')
        doc.custom_chantier = value


def _validate_geometry(row):
    if min([flt(row.get(f)) for f, _ in DIMENSIONS] + [flt(row.qty)]) <= 0 or flt(row.qty) != int(flt(row.qty)):
        frappe.throw(f'Ligne {row.idx} : dimensions positives et quantité entière requises.')
    item = frappe.get_cached_doc('Item', row.item_code)
    item.check_permission('read')
    if row.uom != item.stock_uom or flt(row.get('conversion_factor') or 1) != 1:
        frappe.throw(f'Ligne {row.idx} : utiliser l’unité de stock de l’article.')


def _check_source(row, source):
    if source.item_code != row.item_code or source.uom != row.uom:
        frappe.throw('Article ou unité différent du devis accepté.')
    for field, _ in DIMENSIONS:
        if abs(flt(row.get(field)) - flt(source.get(field))) > .001:
            frappe.throw('Dimensions différentes du devis accepté : une révision commerciale est nécessaire.')
    if row.get('custom_repere') != source.get('custom_repere') or row.get('custom_chantier_section') != source.get('custom_chantier_section'):
        frappe.throw('Repère ou section différent du devis accepté.')
    if not source.get('custom_technical_snapshot'):
        frappe.throw('La ligne du devis ne possède pas de composition technique validée.')
    tree = json.loads(source.custom_technical_snapshot)
    if fingerprint(tree) != source.get('custom_technical_hash'):
        frappe.throw('Empreinte de la composition du devis invalide.')
    return tree


def validate_commercial(doc, method=None):
    if not doc.get('custom_chantier'):
        if any(row.get('custom_chantier_section') or row.get('custom_technical_snapshot') for row in doc.get('items', [])):
            frappe.throw('Un chantier est requis pour les lignes de chantier.')
        # Preserve existing non-chantier workflows and their Item composition behavior.
        return
    chantier = chantier_doc(doc.custom_chantier)
    if chantier.status in ('Cancelled', 'On Hold') and doc.docstatus != 2:
        frappe.throw('Ce chantier est suspendu ou annulé.')
    customer = doc.get('customer') if doc.doctype == 'Sales Order' else (doc.party_name if doc.quotation_to == 'Customer' else None)
    if chantier.company != doc.company or chantier.customer != customer:
        frappe.throw('La société et le client doivent correspondre au chantier.')
    if doc.doctype == 'Quotation':
        from mat_reco.material_reconfiguration.services.technical_study_service import validate_quote
        validate_quote(doc, chantier)
    elif not doc.get('custom_customer_acceptance'):
        frappe.throw('Enregistrer la référence de l’acceptation client avant de confirmer la commande de chantier.')
    if doc.doctype=='Sales Order':
        from .chantier_extras import map_order_extras
        map_order_extras(doc)
    seen, quotations = set(), {}
    for row in doc.get('items', []):
        section_matches(row.get('custom_chantier_section'), chantier.name)
        origin = None
        if doc.doctype == 'Sales Order':
            if not row.prevdoc_docname or not row.quotation_item:
                frappe.throw(f'Ligne {row.idx} : un devis validé est obligatoire.')
            if row.prevdoc_docname not in quotations:
                source = frappe.get_doc('Quotation', row.prevdoc_docname)
                source.check_permission('read')
                quotations[row.prevdoc_docname] = source
            source = quotations[row.prevdoc_docname]
            origin = next((r for r in source.items if r.name == row.quotation_item), None)
            if source.docstatus != 1 or source.get('custom_chantier') != chantier.name or not origin:
                frappe.throw('Le devis d’origine doit être validé et appartenir au même chantier.')
        kind = (json.loads(origin.custom_technical_snapshot).get('item_type') if origin and origin.get('custom_technical_snapshot') else frappe.get_cached_value('Item', row.item_code, 'custom_item_types'))
        if kind not in ('OUVRAGE', 'DECOUPE'):
            # Commercial services and accessories do not create physical production branches.
            row.custom_technical_snapshot = None
            row.custom_technical_hash = None
            continue
        _validate_geometry(row)
        if not row.get('custom_repere'):
            frappe.throw(f'Ligne {row.idx} : le repère ouvrage est obligatoire.')
        if row.custom_repere in seen:
            frappe.throw('Chaque repère doit identifier une seule ligne de vitrage dans le document.')
        seen.add(row.custom_repere)
        if doc.doctype == 'Quotation':
            # The submitted technical study is authoritative; validate_quote filled the frozen definition.
            pass
        else:
            _check_source(row, origin)
            # Only the submitted source is authoritative, never values sent by the browser.
            row.custom_technical_snapshot = origin.custom_technical_snapshot
            row.custom_technical_hash = origin.custom_technical_hash
    if doc.doctype == 'Sales Order':
        frappe.db.get_value('Chantier', chantier.name, 'name', for_update=True)
        for row in doc.get('items', []):
            if not row.get('custom_technical_snapshot'):
                continue
            # Serialize confirmations against the same quote row, including concurrent operators.
            previous = frappe.db.sql('''SELECT i.qty FROM `tabSales Order Item` i
                JOIN `tabSales Order` s ON s.name=i.parent
                WHERE s.docstatus=1 AND s.name!=%s AND i.quotation_item=%s FOR UPDATE''', (doc.name or '', row.quotation_item))
            source_row = next(r for r in quotations[row.prevdoc_docname].items if r.name == row.quotation_item)
            if sum(flt(r[0]) for r in previous) + flt(row.qty) > flt(source_row.qty):
                frappe.throw('La quantité commandée dépasse la quantité acceptée au devis.')


def protect_produced_order(doc, method=None):
    """Cancellation changes row identities on amendment; never orphan production."""
    if not doc.get('custom_chantier'):
        return
    rows = [r.name for r in doc.items]
    produced = frappe.db.sql('''SELECT d.name FROM `tabStock Entry Detail` d
        JOIN `tabStock Entry` s ON s.name=d.parent
        WHERE s.docstatus=1 AND d.custom_sales_order_item IN %(rows)s
        LIMIT 1''', {'rows':rows}) if rows else []
    if not produced and rows:
        from mat_reco.material_reconfiguration.services.workshop_service import _receipts
        accepted, pending, history, _ = _receipts([doc])
        produced = any(accepted[r] or pending[r] for r in rows) or any(history.values())
    if produced:
        frappe.throw('Cette commande a une fabrication validée. Son annulation nécessite le traitement préalable des opérations liées ; la traçabilité doit être conservée.')


def frozen_tree(order, row):
    if not row.get('custom_technical_snapshot'):
        if order.get('custom_chantier'):
            frappe.throw('Composition technique validée manquante sur la ligne de commande.')
        return None
    tree = json.loads(row.custom_technical_snapshot)
    if fingerprint(tree) != row.get('custom_technical_hash'):
        frappe.throw('Empreinte technique invalide.')
    if tree.get('item_code') != row.item_code or any(abs(flt(tree.get(n)) - flt(row.get(f))) > .001 for f,n in DIMENSIONS):
        frappe.throw('La définition technique ne correspond pas à la ligne de commande.')
    if order.get('custom_chantier'):
        chantier_doc(order.custom_chantier)
    from mat_reco.material_reconfiguration.services.repack_from_sales_order_service import _get_default_target_warehouse
    def bind(node, path=()):
        item = frappe.get_cached_doc('Item', node['item_code'])
        item.check_permission('read')
        node['id'] = row.name + ':' + ('.'.join(map(str,path)) or 'root')
        node.update(sales_order=order.name, sales_order_item=row.name, chantier=order.get('custom_chantier'),
            section=row.get('custom_chantier_section'), repere=row.get('custom_repere'), company=order.company,
            warehouse=_get_default_target_warehouse(node['item_code'], order.company), has_serial_no=bool(item.has_serial_no),
            has_batch_no=bool(item.has_batch_no), quality_required=bool(item.get('custom_control_quality')))
        for idx, child in enumerate(node['children']):
            bind(child, path + (idx,))
    bind(tree)
    return tree


@frappe.whitelist()
def create_quotation(chantier):
    dossier = chantier_doc(chantier)
    from mat_reco.material_reconfiguration.services.technical_study_service import approved_study
    if dossier.docstatus != 1:
        frappe.throw('Valider l’étude technique puis le chantier commercial avant de générer un devis.')
    approved_study(dossier)
    frappe.throw('Utiliser la génération de devis depuis les ouvrages approuvés du chantier.')


@frappe.whitelist(methods=['POST'])
def create_mpp(sales_order, sales_order_item):
    order = frappe.get_doc('Sales Order', sales_order)
    order.check_permission('read')
    if order.docstatus != 1 or order.status in ('Closed', 'On Hold', 'Cancelled'):
        frappe.throw('Une commande confirmée et active est requise.')
    row = next((r for r in order.items if r.name == sales_order_item), None)
    if not row or not row.get('custom_technical_snapshot'):
        frappe.throw('Sélectionner une ligne de chantier avec sa composition validée.')
    frappe.db.get_value('Sales Order', order.name, 'name', for_update=True)
    existing = frappe.db.get_value('Material Production Plan', {'sales_order': order.name, 'so_item_row': row.name, 'docstatus': ['!=',2]}, 'name', for_update=True)
    if existing:
        frappe.get_doc('Material Production Plan', existing).check_permission('read')
        return existing
    doc = frappe.get_doc(dict(doctype='Material Production Plan', sales_order=order.name, so_item_row=row.name))
    doc.insert()
    return doc.name


def populate_mpp(doc):
    order = frappe.get_doc('Sales Order', doc.sales_order)
    order.check_permission('read')
    row = next((r for r in order.items if r.name == doc.so_item_row), None)
    if order.docstatus != 1 or order.status in ('Cancelled','Closed','On Hold') or not row:
        frappe.throw('Le MPP doit désigner une ligne de commande confirmée et active.')
    frappe.db.get_value('Sales Order', order.name, 'name', for_update=True)
    if frappe.db.get_value('Material Production Plan', {'sales_order':order.name, 'so_item_row':row.name, 'docstatus':['!=',2], 'name':['!=',doc.name]}, 'name', for_update=True):
        frappe.throw('Un MPP actif existe déjà pour cette ligne.')
    from mat_reco.material_reconfiguration.services.workshop_service import _tree
    tree = _tree(order, row)
    doc.company, doc.chantier = order.company, order.get('custom_chantier')
    doc.quotation_item = row.get('quotation_item')
    doc.snapshot_hash = row.get('custom_technical_hash') or fingerprint(tree)
    doc.fg_item_code, doc.fg_total_qty = row.item_code, row.qty
    doc.fg_length_mm, doc.fg_width_mm, doc.fg_thickness_mm = tree['length_mm'], tree['width_mm'], tree['thickness_mm']
    doc.statut = 'Tree Generated'
    doc.set('nodes', [])
    def append(node, qty, parent=None, depth=0):
        doc.append('nodes', dict(node_id=node['id'], parent_node=parent, indent_level=depth,
            item_code=node['item_code'], item_name=node['label'], node_label=node['label'],
            node_type='Final Product' if depth==0 else ('Composite' if node['children'] else 'Leaf Material'),
            is_composite=bool(node['children']), required_qty=qty, length_mm=node['length_mm'], width_mm=node['width_mm'], thickness_mm=node['thickness_mm'], warehouse=node['warehouse']))
        for child in node['children']:
            append(child, qty*child['ratio'], node['id'], depth+1)
    append(tree, row.qty)


def section_scope(section, chantier=None):
    if not section:
        return None
    doc = frappe.get_doc('Chantier Section', section)
    doc.check_permission('read')
    if chantier and doc.chantier != chantier:
        frappe.throw('La section sélectionnée appartient à un autre chantier.')
    return set(frappe.get_list('Chantier Section', filters={'chantier':doc.chantier, 'lft':['>=',doc.lft], 'rgt':['<=',doc.rgt]}, pluck='name', limit_page_length=0))


@frappe.whitelist()
def get_dossier(chantier=None):
    dossiers = frappe.get_list('Chantier', fields=['name', 'designation', 'customer', 'status'], order_by='modified desc', limit_page_length=0)
    permissions = dict(section_template=frappe.has_permission('Chantier Section Template','create'),chantier=frappe.has_permission('Chantier','create'), section=frappe.has_permission('Chantier Section','create'), quotation=frappe.has_permission('Quotation','create'), mpp=frappe.has_permission('Material Production Plan','create'))
    if not chantier:
        return dict(permissions=permissions,chantiers=dossiers, sections=[], quotations=[], lines=[], summary={})
    dossier = chantier_doc(chantier)
    studies = frappe.get_list('Chantier Technical Study',filters={'chantier':chantier,'docstatus':['<',2]},fields=['name','docstatus','source_hash','technical_hash'],order_by='modified desc',limit_page_length=0) if frappe.has_permission('Chantier Technical Study','read') else []
    permissions.update(technical=frappe.has_permission('Chantier Technical Study','create'),submit=bool(dossier.has_permission('submit')),write=bool(dossier.has_permission('write')))
    from mat_reco.material_reconfiguration.services.technical_study_service import source_hash
    current_hash = source_hash(dossier)
    relevant = next((r for r in studies if r.source_hash == current_hash), studies[0] if studies else None)
    technical = frappe.get_doc('Chantier Technical Study',relevant.name).as_dict() if relevant else None
    quote_usage = {}
    for r in frappe.db.sql('''SELECT i.custom_chantier_line, i.custom_repere, SUM(i.qty) qty FROM `tabQuotation Item` i
        JOIN tabQuotation q ON q.name=i.parent WHERE q.custom_chantier=%s AND q.docstatus<2
        GROUP BY i.custom_chantier_line,i.custom_repere''',chantier,as_dict=True):
        identity=r.custom_chantier_line or next((l.line_id for l in dossier.lines if l.repere==r.custom_repere),None)
        if identity:quote_usage[identity]=quote_usage.get(identity,0)+r.qty
    sections = frappe.get_list('Chantier Section', filters={'chantier':chantier}, fields=['name','section_name','parent_chantier_section','lft'], order_by='lft', limit_page_length=0)
    quotations = frappe.get_list('Quotation', filters={'custom_chantier':chantier}, fields=['name','docstatus','status','grand_total','currency','amended_from'], order_by='modified desc', limit_page_length=0)
    orders = [frappe.get_doc('Sales Order', n) for n in frappe.get_list('Sales Order', filters={'custom_chantier':chantier,'docstatus':1}, pluck='name', limit_page_length=0)]
    from mat_reco.material_reconfiguration.services.workshop_service import _receipts, _load
    # Financial roles may read dossiers and quotes without access to stock operations.
    production_visible = frappe.has_permission('Stock Entry','read')
    if not production_visible:
        return dict(technical=technical,technical_stale=bool(relevant and relevant.source_hash!=current_hash),quote_usage=quote_usage,studies=studies,permissions=permissions,chantiers=dossiers,chantier=dossier.as_dict(),sections=sections,quotations=quotations,lines=[],summary={},production_visible=False)
    accepted, pending, _, _ = _receipts(orders)
    roots, errors, _ = _load(dossier.company)
    live = {b['sales_order_item']:b for root in roots for b in root['children']}
    extra = {}
    refabs = frappe.db.get_all('Workshop Refabrication', filters={'docstatus':1,'sales_order':['in',[o.name for o in orders]]}, fields=['sales_order_item','qty']) if orders else []
    for r in refabs:
        extra[r.sales_order_item] = extra.get(r.sales_order_item,0)+r.qty
    plans = frappe.get_list('Material Production Plan', filters={'sales_order':['in',[o.name for o in orders]],'docstatus':['!=',2]}, fields=['name','so_item_row'], limit_page_length=0) if orders and frappe.has_permission('Material Production Plan','read') else []
    plan_map = {p.so_item_row:p.name for p in plans}
    lines = []
    for order in orders:
        for row in order.items:
            if not row.get('custom_technical_snapshot'):
                continue
            area = flt(row.get('custom_client_length_mm'))*flt(row.get('custom_client_width_mm'))/1e6
            rework = extra.get(row.name,0)
            good = min(row.qty,max(0,accepted[row.name]-rework))
            state = live.get(row.name,{})
            lines.append(dict(sales_order=order.name,sales_order_item=row.name,repere=row.custom_repere,
                section=row.custom_chantier_section,item_code=row.item_code,mpp=plan_map.get(row.name),
                qty=row.qty,produced=accepted[row.name],refabrication=rework,remaining=max(0,row.qty+rework-accepted[row.name]),
                pending_quality=pending[row.name],area=area*row.qty,conform_area=area*good,
                fabricable=state.get('fabricable_qty',0),state=state.get('state','completed'),status=order.status))
    summary = summarize(lines)
    # Sections roll up every descendant exactly once, including rows directly on the section.
    by_section = {}
    for section in sections:
        descendants = section_scope(section.name,chantier)
        by_section[section.name] = summarize([r for r in lines if r['section'] in descendants])
    return dict(technical=technical,technical_stale=bool(relevant and relevant.source_hash!=current_hash),quote_usage=quote_usage,studies=studies,permissions=permissions,chantiers=dossiers,chantier=dossier.as_dict(),sections=sections,quotations=quotations,lines=lines,
        summary=summary,by_section=by_section,production_visible=True,errors=[e for e in errors if e['sales_order'] in {o.name for o in orders}])


def summarize(lines):
    result = dict(ouvrages=len(lines),ordered_qty=sum(r['qty'] for r in lines),produced_qty=sum(r['produced'] for r in lines),
        remaining_qty=sum(r['remaining'] for r in lines),area=sum(r['area'] for r in lines),conform_area=sum(r['conform_area'] for r in lines),
        blocked=sum(r['remaining']>0 and r['state']=='blocked' for r in lines),pending_quality=sum(r['pending_quality'] for r in lines))
    result['progress'] = 100*result['conform_area']/result['area'] if result['area'] else 0
    return result
