"""Workshop read model and transactional orchestration of existing ERP services."""
from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
import hashlib
import json
import math

import frappe
from frappe.utils import flt, now_datetime

from mat_reco.material_reconfiguration.services.workshop_planner import Pool, plan, capacity, annotate, stock_key, whole
from mat_reco.material_reconfiguration.services.order_explosion_service import get_ouvrage_components
from mat_reco.material_reconfiguration.services.repack_from_sales_order_service import (
    _get_default_target_warehouse, _append_input_row, _set_stock_uom_fields,
)
from mat_reco.material_reconfiguration.services.serial_creation_service import ensure_repack_output_serials_and_bundles_for_stock_entry


def _json(value, fallback=None):
    if not value:
        return fallback if fallback is not None else {}
    return json.loads(value) if isinstance(value, str) else value


def _permission(doctype, action='read'):
    if not frappe.has_permission(doctype, action):
        frappe.throw(f'Droit {action} requis sur {doctype}.', frappe.PermissionError)


def _qty(value):
    try:
        return whole(value)
    except (ValueError, TypeError, OverflowError):
        frappe.throw('Quantité entière requise pour les ouvrages et découpes.')


def _walk(node):
    yield node
    for child in node.get('children', []):
        yield from _walk(child)


def _item_thickness(item_code):
    seen=set()
    while item_code and item_code not in seen:
        seen.add(item_code)
        item=frappe.get_cached_doc('Item',item_code)
        if flt(item.get('custom_thickness_mm')):return flt(item.custom_thickness_mm)
        item_code=item.get('custom_parent_item')
    return 0


def _tree(order, row, item_code=None, path=(), ancestors=(), allow_invalid=False):
    if item_code is None and (row.get('custom_technical_snapshot') or order.get('custom_chantier')):
        from mat_reco.material_reconfiguration.services.chantier_service import frozen_tree
        return frozen_tree(order, row)
    item_code = item_code or row.item_code
    if item_code in ancestors or len(ancestors) > 20:
        frappe.throw(f'Nomenclature cyclique ou trop profonde : {item_code}.')
    item = frappe.get_cached_doc('Item', item_code)
    item.check_permission('read')
    token = '.'.join(map(str, path)) or 'root'
    node = dict(id=f'{row.name}:{token}', sales_order=order.name, sales_order_item=row.name,
                item_code=item_code, label=item.item_name or item_code,
                item_type=item.get('custom_item_types') or 'ACCESSOIRE', ratio=1,
                length_mm=flt(row.get('custom_client_length_mm')),
                width_mm=flt(row.get('custom_client_width_mm')),
                thickness_mm=flt(item.get('custom_thickness_mm') or row.get('custom_client_thickness_mm')) if path else flt(row.get('custom_client_thickness_mm')),
                children=[], is_final=not path, warehouse=_get_default_target_warehouse(item_code, order.company),
                has_serial_no=bool(item.has_serial_no), has_batch_no=bool(item.has_batch_no),
                stock_uom=item.stock_uom, primary_item=None, section=row.get('custom_chantier_section'), repere=row.get('custom_repere'), chantier=order.get('custom_chantier'))
    if node['item_type'] == 'OUVRAGE':
        components = get_ouvrage_components(item)
        if not components:
            frappe.throw(f'Ouvrage {item_code} sans composants.')
        for index, component in enumerate(components):
            child = _tree(order, row, component['item_code'], path + (index,), ancestors + (item_code,),allow_invalid=allow_invalid)
            child['ratio'] = _qty(component['qty_factor'])
            if not child['ratio']:
                frappe.throw(f'Ratio nul dans la nomenclature de {item_code}.')
            node['children'].append(child)
    elif node['item_type'] == 'DECOUPE':
        parent, seen = item_code, set()
        while parent and parent not in seen:
            seen.add(parent)
            raw = frappe.get_cached_doc('Item', parent)
            if raw.get('custom_item_types') == 'PRIMAIRE':
                node['primary_item'] = parent
                if path:
                    node['thickness_mm'] = flt(item.get('custom_thickness_mm') or raw.get('custom_thickness_mm') or node['thickness_mm'])
                technical=flt(raw.get('custom_thickness_mm'))
                if technical and node['thickness_mm'] and abs(technical-node['thickness_mm'])>0.001:
                    message=f'Épaisseur incompatible sur {order.name}, ligne {row.idx} : {node["thickness_mm"]} mm demandés pour une matière de {technical} mm.'
                    if not allow_invalid:frappe.throw(message)
                    node['invalid_message']=message
                break
            parent = raw.get('custom_parent_item')
        if min(node['length_mm'], node['width_mm'], node['thickness_mm']) <= 0:
            if not allow_invalid:
                frappe.throw(f'Dimensions manquantes sur {order.name}, ligne {row.idx}.')
            node['invalid_message']=f'Dimensions manquantes sur {order.name}, ligne {row.idx}.'
    # Accessories have no glass dimensions and use their own stock UOM.
    if node['item_type'] not in ('OUVRAGE', 'DECOUPE'):
        node.update(length_mm=0, width_mm=0, thickness_mm=0)
    invalid=[n.get('invalid_message') for n in node['children'] if n.get('invalid_message')]
    if invalid:node['invalid_message']=' '.join(dict.fromkeys(invalid))
    return node


def _quality_qty(detail, se, lock=False):
    """Submitted output quantity; mat_reco does not require quality inspection."""
    return flt(detail.get('transfer_qty') or detail.qty)


def _pending_qty(detail, se, accepted, lock=False):
    return 0


def _serials(detail):
    result = [s.strip() for s in (detail.get('serial_no') or '').splitlines() if s.strip()]
    if detail.get('serial_and_batch_bundle'):
        result += frappe.get_all('Serial and Batch Entry', filters={'parent': detail.serial_and_batch_bundle,
             'serial_no': ['is', 'set']}, pluck='serial_no')
    result += _json(detail.get('custom_mcp_serial_nos_json'), [])
    return list(dict.fromkeys(result))


def _mcp_output_mapping(se):
    """Allocation metadata from actual output serials, not a stock balance."""
    from mat_reco.material_reconfiguration.services.repack_draft_service import build_effective_nodes
    mcp=frappe.get_doc('Material Cutting Plan',se.custom_material_cutting_plan)
    expected={}
    # Original and effective identities both matter for previously submitted
    # outputs later changed by an explicit MCP incident.
    for field in ('result_json','effective_result_json'):
        tree=_json(mcp.get(field))
        tree=tree.get('tree') or tree
        for sheet in tree.get('nodes',[]):
            for child in sheet.get('children',[]):
                if child.get('sales_order_item'):
                    expected[child.get('id') or child.get('piece_uid')]=child
    for sheet in build_effective_nodes(mcp):
        for child in sheet.get('children',[]):
            if child.get('sales_order_item'):
                expected[child.get('id') or child.get('piece_uid')]=child
    result={}
    for detail in se.items:
        if not detail.t_warehouse or detail.s_warehouse:continue
        for serial in _serials(detail):
            piece=expected.get(serial)
            line=piece.get('sales_order_item') if piece else None
            if not line:
                parts=serial.split('::')
                if len(parts)>=4 and frappe.db.exists('Sales Order Item',parts[1]):line=parts[1]
            if line:
                result[serial]=dict(sales_order_item=line,item_code=detail.item_code)
    return result


def freeze_mcp_allocations(doc):
    # Saved on the submitted Stock Entry, so subsequent changes to the MCP
    # geometry cannot erase production already attributed to an order.
    if doc.get('custom_material_cutting_plan') and doc.meta.has_field('custom_workshop_allocations_json'):
        doc.custom_workshop_allocations_json=json.dumps(_mcp_output_mapping(doc),ensure_ascii=False)


def backfill_workshop_allocations():
    """Migrate allocation metadata only; never change ledger or production qty."""
    from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
    create_custom_fields({'Stock Entry':[dict(fieldname='custom_workshop_allocations_json',
        label='Workshop Output Allocations',fieldtype='Long Text',insert_after='custom_material_cutting_plan',
        hidden=1,read_only=1,no_copy=1,module='Material Reconfiguration')]},update=True)
    for name in frappe.get_all('Stock Entry',filters={'docstatus':1,'stock_entry_type':'Repack',
            'custom_material_cutting_plan':['is','set'],'custom_workshop_allocations_json':['is','not set']},pluck='name'):
        doc=frappe.get_doc('Stock Entry',name)
        freeze_mcp_allocations(doc)
        frappe.db.set_value('Stock Entry',name,'custom_workshop_allocations_json',
                            doc.custom_workshop_allocations_json,update_modified=False)


def _output_matches_line(detail,row):
    expected=sorted((flt(row.get('custom_client_length_mm')),flt(row.get('custom_client_width_mm'))))
    actual=sorted((flt(detail.get('custom_dimension_length_mm')),flt(detail.get('custom_dimension_width_mm'))))
    if min(expected)>0 and min(actual)>0 and any(abs(a-b)>0.001 for a,b in zip(expected,actual)):
        return False
    expected_t=flt(row.get('custom_client_thickness_mm'))
    actual_t=flt(detail.get('custom_dimension_thickness_mm'))
    return not (expected_t and actual_t and abs(expected_t-actual_t)>0.001)


def _receipts(orders, lock=False):
    """Use submitted output rows, never stock balances, to prove production."""
    accepted, pending = defaultdict(float), defaultdict(float)
    node_history = defaultdict(float)
    owner = {}
    item_rows = {r.name: r for so in orders for r in so.items}
    if not item_rows:
        return accepted, pending, node_history, owner
    entries = frappe.db.sql('''SELECT DISTINCT se.name FROM `tabStock Entry` se
        JOIN `tabStock Entry Detail` d ON d.parent=se.name
        WHERE se.docstatus=1 AND se.stock_entry_type='Repack'
          AND (d.custom_sales_order_item IN %(rows)s OR COALESCE(se.custom_material_cutting_plan,'')!='')''' + (' FOR UPDATE' if lock else ''),
        {'rows': list(item_rows)}, pluck=True)
    for name in entries:
        se = frappe.get_doc('Stock Entry', name, for_update=lock)
        mapping = _json(se.get('custom_workshop_allocations_json'))
        if not mapping and se.get('custom_material_cutting_plan'):
            mapping = _mcp_output_mapping(se)
        for detail in se.items:
            if not detail.t_warehouse or detail.s_warehouse:
                continue
            qty = flt(detail.get('transfer_qty') or detail.qty)
            good = _quality_qty(detail, se, lock=lock)
            line = detail.get('custom_sales_order_item')
            if line in item_rows and detail.item_code == item_rows[line].item_code:
                # Intermediate cockpit outputs have the same attribution but a
                # distinct item; only the final item closes a commercial line.
                if not _output_matches_line(detail,item_rows[line]):
                    good=0
                accepted[line] += good
                pending[line] += _pending_qty(detail,se,good,lock=lock)
            if line in item_rows:
                batches=[detail.get('batch_no')] if detail.get('batch_no') else []
                if detail.get('serial_and_batch_bundle'):
                    batches += frappe.get_all('Serial and Batch Entry',filters={'parent':detail.serial_and_batch_bundle,
                        'batch_no':['is','set']},pluck='batch_no')
                for batch in batches:
                    owner['batch:'+batch]=line
            serial_names = _serials(detail)
            for sn in serial_names:
                piece = mapping.get(sn)
                piece_line = piece.get('sales_order_item') if piece else line
                if piece_line in item_rows:
                    owner[sn] = piece_line
                    if piece and item_rows[piece_line].item_code == detail.item_code and line != piece_line:
                        # Aggregated MCP output rows do not carry a single SO line.
                        # Do not attribute partial output quantities to arbitrary serials.
                        if good == qty and _output_matches_line(detail,item_rows[piece_line]):
                            accepted[piece_line] += 1
                        else:
                            pending[piece_line] += 1
    operations = frappe.get_all('Workshop Operation', filters={'sales_order': ['in', [o.name for o in orders]]},
                                fields=['result_json'])
    for op in operations:
        for output in _json(op.result_json).get('outputs', []):
            entry=frappe.get_doc('Stock Entry',output['stock_entry'],for_update=lock)
            if entry.docstatus==1:
                node_history[output['node_id']] += sum(_quality_qty(d,entry,lock=lock)
                    for d in entry.items if d.t_warehouse and not d.s_warehouse
                    and d.item_code==output['item_code']
                    and d.get('custom_sales_order_item')==output['node_id'].split(':')[0])
    return accepted, pending, node_history, owner


def _inventory(nodes, company, ownership, *, lock=False):
    _permission('Warehouse')
    _permission('Serial No')
    warehouses = frappe.get_list('Warehouse', filters={'company': company, 'is_group': 0}, pluck='name', limit_page_length=0)
    items = sorted({n['item_code'] for n in nodes})
    if not warehouses or not items:
        return Pool(), Pool()
    if lock:
        frappe.db.sql('SELECT name FROM `tabItem` WHERE name IN %s ORDER BY name FOR UPDATE', (items,))
        frappe.db.sql('SELECT name FROM `tabBin` WHERE item_code IN %s AND warehouse IN %s ORDER BY name FOR UPDATE', (items, warehouses))
        frappe.db.sql('SELECT name FROM `tabSerial No` WHERE item_code IN %s AND warehouse IN %s ORDER BY name FOR UPDATE', (items, warehouses))
        frappe.db.sql('SELECT name FROM `tabStock Reservation Entry` WHERE item_code IN %s AND warehouse IN %s ORDER BY name FOR UPDATE', (items, warehouses))
    # A quantity reservation without serials conservatively withholds that
    # quantity from the shared pool; named reservations withhold those serials.
    reserved = defaultdict(float)
    reserved_serials = set()
    for reservation in frappe.db.get_values('Stock Reservation Entry', filters={'docstatus': 1, 'item_code': ['in', items],
            'warehouse': ['in', warehouses], 'status': ['not in', ['Cancelled', 'Delivered']]},
            fieldname=['name', 'item_code', 'warehouse', 'reserved_qty', 'delivered_qty', 'reservation_based_on'], as_dict=True, for_update=lock):
        amount = max(0, flt(reservation.reserved_qty) - flt(reservation.delivered_qty))
        if not amount:
            continue
        serials = frappe.db.get_values('Serial and Batch Entry', filters={'parent': reservation.name}, fieldname=['serial_no'],as_dict=True,for_update=lock)
        names = {r.serial_no for r in serials if r.serial_no}
        reserved_serials.update(names)
        if not names:
            reserved[reservation.item_code, reservation.warehouse] += amount
    records = []
    # Already assigned serials from active MCP plans are excluded from the raw
    # material selector separately; here they are exact finished components.
    for code in items:
        item = frappe.get_cached_doc('Item', code)
        if item.has_serial_no:
            rows = frappe.db.get_values('Serial No', filters={'item_code': code, 'warehouse': ['in', warehouses],
                'status': 'Active'}, fieldname=['name','warehouse','custom_material_status',
                'custom_dimension_length_mm','custom_dimension_width_mm','custom_dimension_thickness_mm'], order_by='creation asc, name asc',as_dict=True,for_update=lock)
            for row in rows:
                if row.custom_material_status not in ('Full', 'Partial', None, ''):
                    continue
                # Exact components must not be L-shaped leftovers.
                sn = frappe.get_doc('Serial No', row.name,for_update=lock)
                if not sn.has_permission('read'):
                    continue
                if flt(sn.get('custom_removed_length_mm')) or flt(sn.get('custom_removed_width_mm')):
                    continue
                records.append(dict(item_code=code, warehouse=row.warehouse, serial_no=row.name, qty=1,
                    length_mm=flt(row.custom_dimension_length_mm), width_mm=flt(row.custom_dimension_width_mm),
                    thickness_mm=flt(row.custom_dimension_thickness_mm) or _item_thickness(code), owner=ownership.get(row.name),
                    reserved=row.name in reserved_serials,batch_no=sn.get('batch_no')))
        elif item.has_batch_no:
            from erpnext.stock.doctype.batch.batch import get_batch_qty
            meta=frappe.get_meta('Batch')
            dimensions=('custom_dimension_length_mm','custom_dimension_width_mm','custom_dimension_thickness_mm')
            if item.get('custom_item_types') in ('OUVRAGE','DECOUPE') and not all(meta.has_field(f) for f in dimensions):
                continue
            for warehouse in warehouses:
                for batch in get_batch_qty(item_code=code,warehouse=warehouse,ignore_reserved_stock=True):
                    doc=frappe.get_doc('Batch',batch.batch_no,for_update=lock)
                    doc.check_permission('read')
                    if doc.disabled:continue
                    records.append(dict(item_code=code,warehouse=warehouse,qty=math.floor(max(0,flt(batch.qty))),
                        batch_no=batch.batch_no,length_mm=flt(doc.get(dimensions[0])),width_mm=flt(doc.get(dimensions[1])),
                        thickness_mm=flt(doc.get(dimensions[2])),owner=ownership.get('batch:'+batch.batch_no),reserved=False))
        else:
            for row in frappe.db.get_values('Bin', filters={'item_code': code,'warehouse': ['in', warehouses]}, fieldname=['warehouse','actual_qty'],as_dict=True,for_update=lock):
                # Dimensioned glass without serials cannot be matched safely.
                if item.get('custom_item_types') in ('OUVRAGE','DECOUPE'):
                    continue
                remaining=max(0,flt(row.actual_qty))
                records.append(dict(item_code=code,warehouse=row.warehouse,qty=math.floor(remaining),
                    length_mm=0,width_mm=0,thickness_mm=0,owner=None,reserved=False))
    physical = Pool(records)
    free = []
    for row in records:
        if row['reserved']:
            continue
        row={**row,'qty':row.get('free_qty',row['qty'])}
        key = row['item_code'], row['warehouse']
        withheld = min(row['qty'], reserved[key])
        reserved[key] -= withheld
        row = {**row, 'qty': row['qty'] - withheld}
        if row['qty']:
            free.append(row)
    return Pool(free), physical


def _load(company=None, *, lock=False):
    from .chantier_work_types import logical_section
    _permission('Sales Order')
    _permission('Stock Entry')
    orders = [frappe.get_doc('Sales Order', r.name, for_update=lock) for r in frappe.get_list('Sales Order',
        filters={'docstatus': 1, **({'company':company} if company else {})}, fields=['name'],
        order_by='delivery_date asc, transaction_date asc, name asc', limit_page_length=0)]
    accepted, pending, history, ownership = _receipts(orders,lock=lock)
    extra = defaultdict(float)
    for r in frappe.db.get_values('Workshop Refabrication', filters={'docstatus':1},fieldname=['sales_order_item','qty'],as_dict=True,for_update=lock):
        extra[r.sales_order_item] += r.qty
    roots, errors = [], []
    for order in orders:
        root = dict(id=order.name,label=order.name,item_type='ORDER',sales_order=order.name,
                    company=order.company,customer=order.customer,status=order.status,chantier=order.get('custom_chantier'),delivery_date=str(order.delivery_date or ''),
                    transaction_date=str(order.transaction_date),children=[],required_qty=0,produced_qty=0,remaining_qty=0)
        for row in order.items:
            kind = _json(row.get('custom_technical_snapshot')).get('item_type') if row.get('custom_technical_snapshot') else frappe.get_cached_value('Item',row.item_code,'custom_item_types')
            if kind not in ('OUVRAGE','DECOUPE'):
                continue
            total = flt(row.qty) + extra[row.name]
            remaining = max(0,total-accepted[row.name])
            root['required_qty'] += total
            root['produced_qty'] += accepted[row.name]
            root['remaining_qty'] += remaining
            if not remaining:
                continue
            node=None
            try:
                node = _tree(order,row,allow_invalid=True)
                if node.get('invalid_message'):
                    raise frappe.ValidationError(node['invalid_message'])
                node.update(required_qty=_qty(total),produced_qty=accepted[row.name],
                            remaining_qty=_qty(remaining),pending_quality_qty=pending[row.name],
                            manufacture_qty=_qty(max(0,remaining-pending[row.name])))
                for child in _walk(node):
                    child.setdefault('produced_qty',history[child['id']])
                    child['company'] = order.company
                    child['stock_note'] = ('Les articles vitrés doivent être suivis par série avec leurs dimensions.'
                        if child['item_type'] in ('DECOUPE','OUVRAGE') and not child['has_serial_no'] else '')
                root['children'].append(node)
            except frappe.ValidationError as exc:
                frappe.clear_messages()
                errors.append({'sales_order':order.name,'sales_order_item':row.name,'message':str(exc)})
                root['children'].append(dict(id=row.name+':root',label=row.item_name or row.item_code,
                    item_code=row.item_code,item_type=frappe.get_cached_value('Item',row.item_code,'custom_item_types'),
                    sales_order=order.name,sales_order_item=row.name,company=order.company,children=[],is_final=True,
                    required_qty=total,produced_qty=accepted[row.name],remaining_qty=remaining,manufacture_qty=remaining,
                    section=logical_section(order,row),
                    pending_quality_qty=pending[row.name],fabricable_qty=0,physical_qty=0,allocatable_qty=0,
                    missing_qty=0,requires_mcp=False,state='blocked',state_label='Données à corriger',
                    invalid_message=str(exc),stock_note=str(exc),primary_items=list({n['primary_item'] for n in _walk(node) if n.get('primary_item')}) if node else [],length_mm=flt(row.get('custom_client_length_mm')),
                    width_mm=flt(row.get('custom_client_width_mm')),thickness_mm=flt(row.get('custom_client_thickness_mm'))))
        if root['children']:
            roots.append(root)
    pools = {}
    for comp in dict.fromkeys(r['company'] for r in roots):
        nodes = [n for r in roots if r['company']==comp for branch in r['children'] for n in _walk(branch)]
        pools[comp] = _inventory(nodes,comp,ownership,lock=lock)
    for root in roots:
        pool, physical = pools[root['company']]
        for branch in root['children']:
            if branch.get('invalid_message'):continue
            for node in _walk(branch):
                node['physical_qty'] = sum(
                    r['qty'] for r in physical.records if stock_key(r)==stock_key(node))
            before = deepcopy(pool)
            allocation = plan(branch,branch['manufacture_qty'],pool,consume_existing=False)
            original_remaining = branch['remaining_qty']
            annotate(branch,allocation,before,final=True)
            branch['remaining_qty'] = original_remaining
        root['manufacture_qty'] = sum(n['manufacture_qty'] for n in root['children'])
        root['fabricable_qty'] = sum(n['fabricable_qty'] for n in root['children'])
        root['requires_mcp'] = any(n['requires_mcp'] for n in root['children'])
        root['state'] = ('ready' if root['fabricable_qty']>=root['manufacture_qty'] else 'partial') if root['fabricable_qty'] else 'blocked'
        root['state_label'] = ('Fabrication disponible' if root['state']=='ready' else 'Partiellement réalisable') if root['fabricable_qty'] else 'Besoin restant'
    return roots,errors,pools


def _dimension_choices(company=None):
    from mat_reco.material_reconfiguration.utils.accounting_dimensions import get_active_accounting_dimension_fields
    from mat_reco.material_reconfiguration.utils.accounting_dimensions import get_company_dimension_config
    meta=frappe.get_meta('Stock Entry')
    companies=[company] if company else frappe.get_list('Company',pluck='name',limit_page_length=0)
    required={field for comp in companies for field,config in get_company_dimension_config(comp).items()
              if config.get('mandatory_for_bs') or config.get('mandatory_for_pl')}
    result=[]
    for field in get_active_accounting_dimension_fields():
        df=meta.get_field(field)
        if field in required and df and df.fieldtype=='Link' and frappe.has_permission(df.options,'read'):
            result.append(dict(fieldname=field,label=df.label,options=frappe.get_list(df.options,pluck='name',limit_page_length=0)))
    return result


def _validated_dimensions(value):
    values=_json(value)
    choices={d['fieldname']:set(d['options']) for d in _dimension_choices()}
    if not isinstance(values,dict) or any(k not in choices or v not in choices[k] for k,v in values.items() if v):
        frappe.throw('Dimension comptable non autorisée.')
    return {k:v for k,v in values.items() if v}


@frappe.whitelist()
def get_dashboard(filters=None,expanded_orders=None):
    filters = _json(filters)
    roots,errors,_ = _load(filters.get('company'))
    primary = filters.get('primary_item')
    # Apply filters after global allocation so narrowing a view never promises
    # resources already allocated to an earlier, hidden order.
    def matches(root):
        if primary and not any(n.get('primary_item')==primary or primary in n.get('primary_items',[]) for b in root['children'] for n in _walk(b)):
            return False
        if filters.get('from_date') and root['transaction_date'] < filters['from_date']:
            return False
        if filters.get('to_date') and root['transaction_date'] > filters['to_date']:
            return False
        query = (filters.get('search') or '').casefold()
        return not query or query in json.dumps(root,ensure_ascii=False).casefold()
    from mat_reco.material_reconfiguration.services.chantier_service import section_scope, chantier_doc
    if filters.get('chantier'):
        chantier_doc(filters['chantier'])
    scope = section_scope(filters.get('section'), filters.get('chantier'))
    filtered = []
    for root in roots:
        if not matches(root) or (filters.get('chantier') and root.get('chantier') != filters['chantier']) or (filters.get('sales_order') and root['id'] != filters['sales_order']):
            continue
        children = [b for b in root['children'] if (scope is None or b.get('section') in scope) and (not filters.get('state') or b.get('state') == filters['state'])]
        if not children:
            continue
        if len(children) != len(root['children']):
            root['partial_view'] = True
            root['children'] = children
            for key in ('required_qty','produced_qty','remaining_qty','fabricable_qty','manufacture_qty'):
                root[key] = sum(b.get(key,0) for b in children)
        filtered.append(root)
    roots = filtered
    nodes = [n for r in roots for b in r['children'] for n in _walk(b)]
    counters=dict(orders=len(roots),works=sum(n.get('is_final',False) for n in nodes),
        remaining=sum(r['remaining_qty'] for r in roots),fabricable=sum(r['fabricable_qty'] for r in roots),
        missing_cuts=sum(max(0,n.get('remaining_qty',0)-n.get('allocatable_qty',0)) for n in nodes if n['item_type']=='DECOUPE'),
        blocked=sum(r['state']=='blocked' for r in roots))
    for n in nodes:
        if not n.get('children') and not n.get('invalid_message'):
            n['children']=[dict(id=n['id']+':stock',label='Stock compatible',item_code=n['item_code'],
                item_type='STOCK',sales_order=n['sales_order'],sales_order_item=n['sales_order_item'],
                required_qty=n['remaining_qty'],remaining_qty=n['remaining_qty'],produced_qty=0,
                physical_qty=n['physical_qty'],allocatable_qty=n['allocatable_qty'],fabricable_qty=0,
                state='ok' if n['allocatable_qty']>=n['remaining_qty'] else 'blocked',
                state_label=f"{n['allocatable_qty']} allouables / {n['physical_qty']} physiques",children=[],
                stock_note=n.get('stock_note',''),length_mm=n['length_mm'],width_mm=n['width_mm'],thickness_mm=n['thickness_mm'])]
    from .workshop_graph import get_workshop_mcps
    mcps = get_workshop_mcps(roots)
    if expanded_orders is not None:
        expanded=set(_json(expanded_orders,[]))
        for root in roots:
            root['has_children']=bool(root['children'])
            if root['id'] not in expanded:
                root['children']=[]
    return dict(roots=roots,mcps=mcps,errors=errors,as_of=str(now_datetime()),dimension_fields=_dimension_choices(filters.get('company')),
        primary_items=frappe.get_list('Item',filters={'custom_item_types':'PRIMAIRE','disabled':0},fields=['name','item_name'],limit_page_length=0),
        companies=frappe.get_list('Company',pluck='name',limit_page_length=0),
        chantiers=frappe.get_list('Chantier',fields=['name','designation'],limit_page_length=0) if frappe.has_permission('Chantier','read') else [],
        sections=frappe.get_list('Chantier Section',filters={'chantier':filters['chantier']} if filters.get('chantier') else {},fields=['name','section_name','chantier'],limit_page_length=0) if frappe.has_permission('Chantier Section','read') else [],
        counters=counters)


@frappe.whitelist()
def get_branch(sales_order):
    so=frappe.get_doc('Sales Order',sales_order)
    so.check_permission('read')
    data=get_dashboard({'company':so.company},expanded_orders=[sales_order])
    return next((root for root in data['roots'] if root['id']==sales_order),None)


def _select(roots, order_name, node_id):
    root = next((r for r in roots if r['id']==order_name),None)
    if not root:
        frappe.throw('Commande achevée ou inaccessible. Actualisez le cockpit.')
    if node_id == root['id']:
        return root,root
    node = next((n for b in root['children'] for n in _walk(b) if n['id']==node_id),None)
    if not node:
        frappe.throw('Sélectionnez un ouvrage ou un composant de la commande.')
    return root,node


def _open_mcp_coverage(company, exclude=None):
    """Count actual pending placements, never the requested (possibly missing) cuts."""
    from mat_reco.material_reconfiguration.services.repack_draft_service import build_effective_nodes
    from mat_reco.material_reconfiguration.services.mcp_compensation_service import submitted_receipts
    coverage = defaultdict(int)
    filters = {'company': company, 'docstatus': ['<', 2],
               'status': ['not in', ['Cancelled', 'Executed']]}
    if exclude:
        filters['name'] = ['!=', exclude]
    for row in frappe.get_all('Material Cutting Plan', filters=filters, fields=['name']):
        doc = frappe.get_doc('Material Cutting Plan', row.name)
        scope = _json(doc.get('workshop_request_json'))
        produced, _ = submitted_receipts(doc)
        # Older cockpit plans encoded the occurrence only in their hashed UID.
        legacy = {}
        for need in scope.get('needs', []):
            order = need.get('sales_order', scope.get('sales_order'))
            for unit in range(_qty(need['qty'])):
                identity = f"{scope['operation']}:{order}:{need['node_id']}:{unit}"
                legacy['WC-' + hashlib.sha256(identity.encode()).hexdigest()[:28]] = (order, need['node_id'])
        seen = set()
        for sheet in build_effective_nodes(doc):
            for piece in sheet.get('children', []):
                uid = piece.get('piece_uid') or piece.get('id')
                if piece.get('node_type') != 'finished_good' or not uid or uid in seen:
                    continue
                if (piece.get('id') or uid) in produced:
                    continue  # Physical stock is already allocated by _inventory.
                seen.add(uid)
                key = legacy.get(uid)
                if piece.get('workshop_node_id'):
                    key = (piece.get('sales_order'), piece['workshop_node_id'])
                if not key and not str(uid).startswith('WC-'):
                    parts = str(uid).split('::')
                    if len(parts) >= 5 and parts[4].startswith('root'):
                        occurrence = parts[4].removeprefix('root.')
                        key = (piece.get('sales_order'), f"{piece.get('sales_order_item')}:{occurrence}")
                if key:
                    coverage[key] += 1
    return coverage


def _uncovered_request(root, request):
    coverage = _open_mcp_coverage(root['company'])
    shortages = []
    covered = 0
    for shortage in request['shortages']:
        row = dict(shortage)
        if row['kind'] == 'cutting':
            amount = min(row['qty'], coverage[(root['id'], row['node_id'])])
            row['qty'] -= amount
            covered += amount
        if row['qty']:
            shortages.append(row)
    request['shortages'] = shortages
    request['covered_cutting_qty'] = covered
    return request


def _fresh_request(sales_order,node_id,qty,lock=False,dimensions=None):
    so = frappe.get_doc('Sales Order',sales_order,for_update=lock)
    so.check_permission('read')
    if so.docstatus != 1 or so.status in ('Closed','On Hold','Cancelled'):
        frappe.throw('Cette commande ne permet pas de fabrication actuellement.')
    roots,errors,_ = _load(so.company,lock=lock)
    root,node = _select(roots,sales_order,node_id)
    root['accounting_dimensions'] = _validated_dimensions(dimensions)
    if node.get('invalid_message'):
        frappe.throw(node['invalid_message'])
    if node['id']==root['id'] and any(n.get('invalid_message') for n in root['children']):
        frappe.throw('Corrigez les lignes signalées ou sélectionnez un ouvrage valide de cette commande.')
    qty = _qty(qty)
    if qty <= 0 or qty > node.get('manufacture_qty',node['remaining_qty']):
        frappe.throw('La quantité dépasse le besoin de fabrication restant.')
    # Rebuild global priority up to the selected branch, then allocate this
    # request at its own node. Ancestors consume no stock twice.
    all_nodes = [n for r in roots for b in r['children'] for n in _walk(b)]
    _,_,_,ownership = _receipts([frappe.get_doc('Sales Order',r['id'],for_update=lock) for r in roots],lock=lock)
    pool,_ = _inventory(all_nodes,so.company,ownership,lock=lock)
    for r in roots:
        if r['id']==node_id:
            if qty!=r['manufacture_qty']:
                frappe.throw('Pour une commande entière, confirmez le besoin actuel ou sélectionnez un ouvrage pour une quantité partielle.')
            request=dict(node_id=node_id,qty=qty,stock=[],available=0,produce_qty=0,tasks=[],shortages=[],children=[],
                         accounting_dimensions=root['accounting_dimensions'])
            for branch in r['children']:
                if not branch['manufacture_qty']:continue
                child=plan(branch,branch['manufacture_qty'],pool,consume_existing=False)
                request['children'].append(child)
                request['tasks'].extend(child['tasks'])
                request['shortages'].extend(child['shortages'])
            return root,node,_uncovered_request(root,request)
        for b in r['children']:
            if any(n['id']==node_id for n in _walk(b)):
                request = plan(node,qty,pool,consume_existing=not node['is_final'])
                request['accounting_dimensions'] = root['accounting_dimensions']
                return root,node,_uncovered_request(root,request)
            if not b.get('invalid_message'):
                plan(b,b['manufacture_qty'],pool,consume_existing=False)
    frappe.throw('Branche introuvable.')


def _preview(root,node,request):
    by_id = {n['id']:n for b in root['children'] for n in _walk(b)}
    def movements(branch):
        result=[]
        for stock in branch['stock'] + branch.get('assignment_inputs', []):
            result.append(dict(item_code=by_id[branch['node_id']]['item_code'],qty=stock['qty'],
                warehouse=stock['warehouse'],serial_no=stock.get('serial_no'),batch_no=stock.get('batch_no'),direction='Consommation'))
        for child in branch['children']:
            result.extend(movements(child))
            if child['produce_qty'] and not child['shortages']:
                n=by_id[child['node_id']]
                result.append(dict(item_code=n['item_code'],qty=child['produce_qty'],warehouse=n['warehouse'],
                    serial_no='Créé par l’assemblage précédent',direction='Consommation'))
        return result
    cutting = any(s['kind']=='cutting' for s in request['shortages'])
    blocked = [s for s in request['shortages'] if s['kind']!='cutting']
    return dict(sales_order=root['id'],node_id=node['id'],qty=request['qty'],
        action='mcp' if cutting else 'blocked' if blocked or request.get('covered_cutting_qty') else 'repack',
        movements=movements(request),shortages=request['shortages'],
        tasks=[dict(**t,item_code=by_id[t['node_id']]['item_code'],label=by_id[t['node_id']]['label'],warehouse=by_id[t['node_id']]['warehouse']) for t in request['tasks']],
        message='Préparer les découpes dans le MCP, puis revenir pour assembler.' if cutting else
                'Découpes déjà planifiées dans un autre MCP : terminez ces découpes avant l’assemblage.' if request.get('covered_cutting_qty') else
                'Composant indisponible : fabrication impossible.' if blocked else 'Assemblages des sous-ouvrages vers le parent.')


@frappe.whitelist()
def preview_action(sales_order,node_id,qty,dimensions=None):
    root,node,request = _fresh_request(sales_order,node_id,qty,dimensions=dimensions)
    result = _preview(root,node,request)
    # A signed, user-bound preview prevents an altered quantity or a silent
    # switch from the confirmed repack action to a new cutting plan.
    from frappe.utils.password import get_encryption_key
    import hmac
    payload=json.dumps(dict(user=frappe.session.user,order=sales_order,node=node_id,qty=_qty(qty),
                            plan=request),sort_keys=True,default=str)
    result['version']=hmac.new(get_encryption_key().encode(),payload.encode(),hashlib.sha256).hexdigest()
    return result


def _version(root,node,request):
    from frappe.utils.password import get_encryption_key
    import hmac
    payload=json.dumps(dict(user=frappe.session.user,order=root['id'],node=node['id'],qty=request['qty'],
                            plan=request),sort_keys=True,default=str)
    return hmac.new(get_encryption_key().encode(),payload.encode(),hashlib.sha256).hexdigest()


def _repack(root,node,qty,inputs,operation,sequence):
    target=node['warehouse']
    if not target:
        frappe.throw(f"Entrepôt par défaut manquant pour {node['item_code']}.")
    frappe.get_doc('Warehouse',target).check_permission('read')
    if frappe.db.get_value('Warehouse',target,'company') != root['company']:
        frappe.throw('L’entrepôt cible appartient à une autre société.')
    se=frappe.new_doc('Stock Entry')
    se.stock_entry_type='Repack'
    se.company=root['company']
    se.custom_sales_order=root['id']
    se.set_basic_rate_manually=1
    se.remarks=f'Cockpit atelier • {operation.name} • {node["id"]}'
    for child,stocks in inputs:
        groups=defaultdict(list)
        for stock in stocks:
            groups[(stock['warehouse'],stock.get('batch_no'))].append(stock)
        for (warehouse,batch),rows in groups.items():
            req=dict(item_code=child['item_code'],item_name=child['label'],warehouse=warehouse,
                qty=sum(r['qty'] for r in rows),length_mm=child['length_mm'],width_mm=child['width_mm'],
                thickness_mm=child['thickness_mm'],serials=[r['serial_no'] for r in rows if r.get('serial_no')])
            detail=_append_input_row(se,req,node['sales_order_item'])
            if req['serials'] or batch:
                detail.use_serial_batch_fields=1
            if batch:
                detail.batch_no=batch
    detail=se.append('items',dict(item_code=node['item_code'],t_warehouse=target,
        custom_sales_order_item=node['sales_order_item']))
    _set_stock_uom_fields(detail,node['item_code'],qty)
    for field,value in [('custom_dimension_length_mm',node['length_mm']),('custom_dimension_width_mm',node['width_mm']),
                         ('custom_dimension_thickness_mm',node['thickness_mm'])]:
        if hasattr(detail,field):setattr(detail,field,value)
    if node['has_batch_no']:
        batch=frappe.get_doc(dict(doctype='Batch',item=node['item_code'],
            batch_id='WREP-'+hashlib.sha256(f'{operation.name}:{sequence}'.encode()).hexdigest()[:18]))
        for field,value in [('custom_dimension_length_mm',node['length_mm']),('custom_dimension_width_mm',node['width_mm']),
                            ('custom_dimension_thickness_mm',node['thickness_mm'])]:
            if batch.meta.has_field(field):batch.set(field,value)
        batch.insert()
        detail.batch_no=batch.name
        detail.use_serial_batch_fields=1
    if node['has_serial_no']:
        prefix=hashlib.sha256(f'{operation.name}:{sequence}'.encode()).hexdigest()[:18]
        detail.serial_no='\n'.join(f'WREP-{prefix}-{i+1}' for i in range(qty))
    from mat_reco.material_reconfiguration.utils.accounting_dimensions import resolve_and_apply_stock_entry_dimensions
    for field,value in root.get('accounting_dimensions',{}).items():
        se.set(field,value)
    resolve_and_apply_stock_entry_dimensions(se,source_doc=se,
        fallback_docs=[frappe.get_doc('Sales Order',root['id'])],validate_mandatory=True)
    se.insert()  # All ERPNext, accounting dimensions and existing SO cost hooks.
    ensure_repack_output_serials_and_bundles_for_stock_entry(se)
    se.save()
    for serial in _serials(detail):
        frappe.db.set_value('Serial No',serial,'custom_dimension_thickness_mm',node['thickness_mm'])
    se.submit()
    serials=_serials(detail)
    stocks=[dict(item_code=node['item_code'],warehouse=target,qty=1,serial_no=s,
        length_mm=node['length_mm'],width_mm=node['width_mm'],thickness_mm=node['thickness_mm'],
        owner=node['sales_order_item'],batch_no=detail.get('batch_no')) for s in serials]
    if not node['has_serial_no']:
        stocks=[dict(item_code=node['item_code'],warehouse=target,qty=qty,length_mm=0,width_mm=0,thickness_mm=0,
                     owner=node['sales_order_item'],batch_no=detail.get('batch_no'))]
    return se,stocks


def _assemble(root,node,request,operation):
    by_id={n['id']:n for b in root['children'] for n in _walk(b)}
    outputs=[]
    def execute(branch):
        n=by_id[branch['node_id']]
        stocks=list(branch['stock'])
        if not branch['produce_qty']:
            return stocks
        inputs=[]
        for child in branch['children']:
            inputs.append((by_id[child['node_id']],execute(child)))
        if branch.get('assignment_inputs'):
            inputs = [(n, branch['assignment_inputs'])]
        if not inputs:
            frappe.throw('Découpe manquante : aucun MCP ne peut être exécuté pendant un assemblage.')
        try:
            se,produced=_repack(root,n,branch['produce_qty'],inputs,operation,len(outputs))
        except (frappe.ValidationError,frappe.PermissionError) as exc:
            frappe.throw(f"Échec de l’assemblage {n['label']} ({branch['produce_qty']} unité(s)). L’action complète est annulée. Détail : {exc}")
        outputs.append(dict(stock_entry=se.name,node_id=n['id'],qty=branch['produce_qty'],item_code=n['item_code']))
        return stocks+produced
    if node.get('item_type')=='ORDER':
        for branch in request['children']:
            execute(branch)
    else:
        execute(request)
    return dict(action='repack',stock_entries=[r['stock_entry'] for r in outputs],outputs=outputs,
                message='Assemblages validés.' if outputs else 'Composants déjà disponibles. Aucun mouvement nécessaire.')


def _raw_bins(source,company):
    from mat_reco.material_reconfiguration.services.stock_candidate_service import get_available_cutting_bins
    variants=frappe.get_all('Item',filters={'custom_parent_item':source,'custom_item_types':'PRIMAIRE','disabled':0},pluck='name')
    bins=get_available_cutting_bins(source,variant_item_codes=variants)
    eligible=[]
    thickness=flt(frappe.get_cached_value('Item',source,'custom_thickness_mm'))
    for row in bins:
        row['thickness_mm']=flt(row.get('thickness_mm')) or _item_thickness(row['item_code'])
        if thickness and abs(flt(row.get('thickness_mm'))-thickness)>0.001:
            continue
        current=frappe.get_doc('Serial No',row['serial_no'],for_update=True)
        if not current.has_permission('read'):
            continue
        if current.warehouse!=row['warehouse'] or current.status!='Active' or current.get('custom_material_status') not in ('Full','Partial'):
            continue
        if not row['warehouse'] or frappe.db.get_value('Warehouse',row['warehouse'],'company')!=company:
            continue
        frappe.get_doc('Warehouse',row['warehouse']).check_permission('read')
        # Existing active MCP sources and ERP reservations must not be reused.
        busy=frappe.db.sql('''SELECT c.name FROM `tabMCP Stock Candidate` c JOIN `tabMaterial Cutting Plan` m ON m.name=c.parent
            WHERE c.serial_no=%s AND c.is_active_input=1 AND m.docstatus<2
              AND COALESCE(m.status,'') NOT IN ('Cancelled','Executed') LIMIT 1 FOR UPDATE''',(row['serial_no'],))
        reserved=frappe.db.sql('''SELECT s.name FROM `tabSerial and Batch Entry` s
            JOIN `tabStock Reservation Entry` r ON r.name=s.parent
            WHERE s.serial_no=%s AND r.docstatus=1 AND r.reserved_qty>r.delivered_qty LIMIT 1 FOR UPDATE''',(row['serial_no'],))
        quantity_reserved=frappe.db.sql('''SELECT name FROM `tabStock Reservation Entry` WHERE item_code=%s
            AND warehouse=%s AND docstatus=1 AND reserved_qty>delivered_qty LIMIT 1 FOR UPDATE''',(row['item_code'],row['warehouse']))
        if not busy and not reserved and not quantity_reserved:
            eligible.append(row)
    return eligible


def _scope_signature(spec):
    import hmac
    from frappe.utils.password import get_encryption_key
    payload=json.dumps({k:v for k,v in spec.items() if k!='signature'},sort_keys=True,ensure_ascii=False)
    return hmac.new(get_encryption_key().encode(),payload.encode(),hashlib.sha256).hexdigest()


def orders_for_source_item(source_item, company=None, exclude_plan=None):
    """Use residual workshop demand for both the MCP button and cockpit handoff."""
    if not source_item:
        return []
    roots, _, _ = _load(company)
    coverage = {}
    result = []
    for root in roots:
        if (company and root['company'] != company) or root.get('status') in ('Closed', 'On Hold', 'Cancelled'):
            continue
        comp = root['company']
        if comp not in coverage:
            coverage[comp] = _open_mcp_coverage(comp, exclude=exclude_plan)
        if any(leaf['item_type']=='DECOUPE' and leaf.get('primary_item')==source_item
               and not leaf.get('invalid_message')
               and leaf.get('missing_qty',0)>coverage[comp][(root['id'],leaf['id'])]
               for branch in root['children'] for leaf in _walk(branch)):
            result.append(dict(name=root['id'], customer=root.get('customer'),
                               transaction_date=root.get('transaction_date')))
    return result


def _prepare_mcp(root,node,request,operation):
    _permission('Material Cutting Plan','create')
    by_id={n['id']:n for b in root['children'] for n in _walk(b)}
    groups=defaultdict(list)
    for shortage in request['shortages']:
        if shortage['kind']!='cutting':continue
        leaf=by_id[shortage['node_id']]
        source=leaf['primary_item']
        if not source:
            frappe.throw(f"Item PRIMAIRE introuvable pour {leaf['item_code']}.")
        groups[source].append({'sales_order':root['id'],'node_id':leaf['id'],'qty':shortage['qty']})
    names=[]
    for source,needs in sorted(groups.items()):
        thicknesses={by_id[n['node_id']]['thickness_mm'] for n in needs}
        if len(thicknesses)!=1:
            frappe.throw('Des épaisseurs différentes sont rattachées à la même matière. Corrigez les caractéristiques des articles.')
        thickness=next(iter(thicknesses))
        bins=[b for b in _raw_bins(source,root['company']) if abs(b['thickness_mm']-thickness)<=0.001]
        if not bins:
            frappe.throw(f'Aucune plaque libre compatible pour {source}. Vérifiez les stocks, réservations et MCP ouverts.')
        # Keep the normal MCP warehouse semantics. Choose a single warehouse,
        # leaving the operator to adjust its sources through the usual screen.
        warehouse=bins[0]['warehouse']
        bins=[b for b in bins if b['warehouse']==warehouse]
        for serial in sorted(b['serial_no'] for b in bins):
            frappe.db.sql('SELECT name FROM `tabSerial No` WHERE name=%s FOR UPDATE',serial)
        mcp=frappe.new_doc('Material Cutting Plan')
        # Run the same source-item selection as the MCP form before its first
        # save. Empty signed scope makes every selected order expand in full.
        orders = orders_for_source_item(source, company=root['company'])
        selected_orders = list(dict.fromkeys([root['id']] + [row['name'] for row in orders]))
        scope=dict(sales_order=root['id'],orders=[],node_id=node['id'],qty=request['qty'],needs=[],operation=operation.name)
        scope['signature']=_scope_signature(scope)
        mcp.update(dict(company=root['company'],source_item=source,source_warehouse=warehouse,
            posting_date=now_datetime(),mcp_mode='Planification',status='Draft',max_depth=20,
            packing_algorithm='maxrects',packing_heuristic='best_area_fit',allow_rotation=1,
            workshop_request_json=json.dumps(scope,ensure_ascii=False)))
        for order in selected_orders:
            mcp.append('selected_sales_orders',{'sales_order':order})
        for code in sorted({b['item_code'] for b in bins if b['item_code']!=source}):
            mcp.append('item_variant_detail',{'variant_item_code':code})
        for b in bins:
            mcp.append('mcp_stock_candidate',dict(serial_no=b['serial_no'],item_code=b['item_code'],warehouse=b['warehouse'],
                length_mm=b['length_mm'],width_mm=b['width_mm'],thickness_mm=b['thickness_mm'],
                material_status=b.get('material_status'),is_qualified=1,is_active_input=0))
        mcp.insert()
        names.append(mcp.name)
    return dict(action='mcp',mcps=names,outputs=[],message='Simulation MCP préparée. Poursuivez dans son interface habituelle.')


def workshop_cutting_demands(doc):
    """Residual scope for cockpit-created MCPs; ordinary MCPs are untouched.

    Operators can still group additional compatible Sales Orders using the
    usual MCP interface. The backend derives their residual cutting needs and
    signs the extended scope; the browser never supplies authoritative qty.
    """
    spec=_json(doc.get('workshop_request_json'))
    if not spec:return None
    import hmac
    if not hmac.compare_digest(spec.get('signature',''),_scope_signature(spec)):
        frappe.throw('Le périmètre du MCP cockpit a été modifié. Recréez la simulation depuis le cockpit.')
    # Serialize scope changes and cockpit creation with the same company lock.
    frappe.db.sql('SELECT name FROM `tabCompany` WHERE name=%s FOR UPDATE', doc.company)
    selected={r.sales_order for r in doc.selected_sales_orders if r.sales_order}
    previous=set(spec.get('orders',[spec['sales_order']]))
    planning = doc.get('mcp_mode') != 'Retour Terrain'
    # Terrain pieces already exist: inventory changes must not erase their scope.
    if planning or selected != previous:
        roots,_,_ = _load(doc.company, lock=True)
        residual = {(root['id'], leaf['id']): leaf['missing_qty']
                    for root in roots for branch in root['children'] for leaf in _walk(branch)
                    if leaf['item_type']=='DECOUPE' and not leaf.get('invalid_message')
                    and leaf.get('primary_item')==doc.source_item}
        coverage = _open_mcp_coverage(doc.company, exclude=doc.name)
        spec['needs']=[n for n in spec['needs'] if n.get('sales_order',spec['sales_order']) in selected]
        for name in sorted(selected-previous):
            for (order, node_id), qty in residual.items():
                if order==name and qty:
                    spec['needs'].append(dict(sales_order=name,node_id=node_id,qty=qty))
        # Each MCP may claim only cuts not actually placed in the other plans.
        # A missing cut in another MCP remains available for a second MCP.
        claimed = defaultdict(int)
        for need in spec['needs']:
            if not planning and need.get('sales_order',spec['sales_order']) in previous:
                continue
            key = (need.get('sales_order',spec['sales_order']), need['node_id'])
            available = max(0, residual.get(key,0)-coverage[key]-claimed[key])
            need['qty'] = min(_qty(need['qty']), available)
            claimed[key] += need['qty']
    spec['orders']=sorted(selected)
    spec['signature']=_scope_signature(spec)
    doc.workshop_request_json=json.dumps(spec,ensure_ascii=False)
    from mat_reco.material_reconfiguration.services.order_explosion_service import build_unit_cutting_demands
    contexts={}
    for name in selected:
        so=frappe.get_doc('Sales Order',name);so.check_permission('read')
        if so.company!=doc.company or so.docstatus!=1:
            frappe.throw('Les commandes du MCP doivent être validées et de la même société.')
        trees=[]
        from .chantier_work_types import is_v2, freeze_order
        loose=is_v2(frappe.get_doc('Chantier',so.custom_chantier)) if so.get('custom_chantier') else False
        for row in so.items:
            if frappe.get_cached_value('Item',row.item_code,'custom_item_types') not in ('OUVRAGE','DECOUPE'):continue
            try:
                tree=_tree(so,row,allow_invalid=True)
            except frappe.ValidationError:
                frappe.clear_messages();continue
            if loose and any(n.get('primary_item')==doc.source_item for n in _walk(tree)) and any(
                    need.get('sales_order',spec['sales_order'])==name and flt(need.get('qty'))>0
                    and need['node_id'].startswith(row.name+':') for need in spec['needs']):
                freeze_order(so,node_id=row.name+':root')
            trees.append(tree)
        contexts[name]=(so,trees,{n['id']:n for branch in trees for n in _walk(branch)})
    demands=[]
    for need in spec['needs']:
        name=need.get('sales_order',spec['sales_order'])
        if name not in contexts:continue
        so,trees,by_id=contexts[name]
        leaf=by_id.get(need['node_id']);qty=_qty(need['qty'])
        if not qty:continue
        if not leaf or leaf.get('invalid_message') or leaf['item_type']!='DECOUPE' or leaf['primary_item']!=doc.source_item:
            frappe.throw('Besoin de découpe incompatible avec le MCP.')
        row=next(r for r in so.items if r.name==leaf['sales_order_item'])
        root=next(branch for branch in trees if branch['sales_order_item']==row.name)
        def demand_limit(n,ratio=1):
            if n['id']==leaf['id']:return ratio
            for child in n['children']:
                found=demand_limit(child,ratio*child['ratio'])
                if found:return found
            return 0
        refabs=frappe.db.sql('SELECT COALESCE(SUM(qty),0) FROM `tabWorkshop Refabrication` WHERE docstatus=1 AND sales_order_item=%s',row.name)[0][0]
        if qty<=0 or qty>_qty(flt(row.qty)+flt(refabs))*demand_limit(root):
            frappe.throw('Quantité MCP supérieure au besoin commercial.')
        context=dict(sales_order=so.name,sales_order_item=row.name,root_item_code=row.item_code,root_item_name=row.item_name,
            base_length_mm=leaf['length_mm'],base_width_mm=leaf['width_mm'],base_thickness_mm=leaf['thickness_mm'])
        pieces=build_unit_cutting_demands(frappe.get_cached_doc('Item',leaf['item_code']),qty,context,
                                        [leaf['item_code']],[leaf['label']],0)
        for unit,piece in enumerate(pieces):
            identity=f"{spec['operation']}:{name}:{leaf['id']}:{unit}"
            piece['piece_uid']='WC-'+hashlib.sha256(identity.encode()).hexdigest()[:28]
            piece['workshop_node_id']=leaf['id']
        demands.extend(pieces)
    return demands


@frappe.whitelist(methods=['POST'])
def execute_action(sales_order,node_id,qty,request_key,version,dimensions=None):
    _permission('Workshop Operation','read')
    if not request_key or len(request_key)>100:
        frappe.throw('Clé d’opération requise (100 caractères maximum).')
    so=frappe.get_doc('Sales Order',sales_order);so.check_permission('read')
    # One company lock orders all cockpit allocations; stock and reservation
    # rows are also locked before commit to protect against other stock flows.
    frappe.db.sql('SELECT name FROM `tabCompany` WHERE name=%s FOR UPDATE',so.company)
    key=hashlib.sha256(f'{frappe.session.user}:{request_key}'.encode()).hexdigest()
    existing=frappe.db.get_value('Workshop Operation',{'request_key':key},['name','sales_order','node_id','requested_qty','result_json'],as_dict=True,for_update=True)
    if existing:
        if (existing.sales_order,existing.node_id,existing.requested_qty)!=(sales_order,node_id,_qty(qty)):
            frappe.throw('Cette clé a déjà servi pour une autre opération.')
        return _json(existing.result_json)
    if so.get('custom_chantier'):
        from .chantier_work_types import freeze_order
        freeze_order(so,node_id=node_id)
    root,node,request=_fresh_request(sales_order,node_id,qty,lock=True,dimensions=dimensions)
    import hmac
    if not hmac.compare_digest(version,_version(root,node,request)):
        frappe.throw('Les besoins ou stocks ont changé. Actualisez puis confirmez une nouvelle simulation.')
    preview=_preview(root,node,request)
    if preview['action']=='blocked':frappe.throw(preview['message'])
    if preview['action']=='repack':
        _permission('Stock Entry','create')
        _permission('Stock Entry','submit')
    op=frappe.new_doc('Workshop Operation')
    op.update(dict(company=so.company,request_key=key,sales_order=sales_order,node_id=node_id,requested_qty=_qty(qty)))
    previous_flag=frappe.flags.in_workshop_operation
    frappe.flags.in_workshop_operation=True
    try:
        op.insert(ignore_permissions=True)
    finally:
        frappe.flags.in_workshop_operation=previous_flag
    # No commit or swallowed exceptions: Frappe rolls the entire POST back
    # when any Repack/MCP step fails, including serial creation and the log.
    result=_prepare_mcp(root,node,request,op) if preview['action']=='mcp' else _assemble(root,node,request,op)
    result['operation']=op.name
    op.result_json=json.dumps(result,ensure_ascii=False)
    frappe.flags.in_workshop_operation=True
    try:
        op.save(ignore_permissions=True)
    finally:
        frappe.flags.in_workshop_operation=previous_flag
    frappe.publish_realtime('workshop_updated',{'sales_order':sales_order},after_commit=True)
    return result


def notify_stock_change(doc,method=None):
    frappe.publish_realtime('workshop_updated',{'doctype':doc.doctype,'name':doc.name},after_commit=True)


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def search_order_lines(doctype,txt,searchfield,start,page_len,filters):
    filters=_json(filters)
    if not filters.get('sales_order'):return []
    order=frappe.get_doc('Sales Order',filters['sales_order'])
    order.check_permission('read')
    rows=[[r.name,f"{r.idx} · {r.item_code} · {r.item_name} · {r.qty:g}"] for r in order.items
          if frappe.get_cached_value('Item',r.item_code,'custom_item_types') in ('OUVRAGE','DECOUPE')]
    rows=[row for row in rows if (txt or '').casefold() in ' '.join(row).casefold()]
    return rows[int(start):int(start)+int(page_len)]
