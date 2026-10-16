"""Pure workshop calculations. Inventory is a shared, finite allocation pool.

Plans are previews, never inventory or manufacturing receipts. Only the Frappe
adapter may submit operations, after building a fresh plan under database locks.
"""
from copy import deepcopy
import math


def whole(value):
    value = float(value)
    if not math.isfinite(value) or value < 0 or value != int(value):
        raise ValueError("La quantité doit être un entier positif ou nul.")
    return int(value)


def stock_key(node):
    dims = sorted((round(float(node.get('length_mm', 0)), 3), round(float(node.get('width_mm', 0)), 3)))
    return (node['item_code'], *dims, round(float(node.get('thickness_mm', 0)), 3))


class Pool:
    def __init__(self, records=()):
        self.records = deepcopy(list(records))

    def take(self, node, qty):
        result = []
        for row in self.records:
            if qty <= 0:
                break
            if stock_key(row) != stock_key(node) or row.get('owner') not in (None, '', node['sales_order_item']):
                continue
            amount = min(qty, row['qty'])
            if amount <= 0:
                continue
            row['qty'] -= amount
            qty -= amount
            result.append({**row, 'qty': amount})
        return result, qty

    def available(self, node):
        return sum(r['qty'] for r in self.records if stock_key(r) == stock_key(node)
                   and r.get('owner') in (None, '', node['sales_order_item']))


def plan(node, qty, pool, *, consume_existing=True):
    """Allocate the complete request, retaining missing leaves and postorder tasks."""
    qty = whole(qty)
    available = pool.available(node)
    inputs, missing = pool.take(node, qty) if consume_existing else ([], qty)
    result = {'node_id': node['id'], 'qty': qty, 'stock': inputs, 'available': available,
              'produce_qty': missing, 'tasks': [], 'shortages': [], 'children': []}
    if not missing:
        return result
    if not node.get('children') and not consume_existing and node['item_type'] == 'DECOUPE':
        # A finished loose piece needs a real Repack to acquire a commercial
        # attribution; stock alone never closes a Sales Order line.
        assigned, shortage = pool.take(node, qty)
        result['assignment_inputs'] = assigned
        result['produce_qty'] = qty
        result['tasks'] = [{'node_id': node['id'], 'qty': qty}]
        if shortage:
            result['shortages'] = [{'node_id': node['id'], 'item_code': node['item_code'],
                                    'qty': shortage, 'kind': 'cutting'}]
        return result
    if not node.get('children'):
        result['shortages'] = [{'node_id': node['id'], 'item_code': node['item_code'],
                                'qty': missing, 'kind': 'cutting' if node['item_type'] == 'DECOUPE' else 'stock'}]
        return result
    for child in node['children']:
        branch = plan(child, missing * whole(child['ratio']), pool)
        result['children'].append(branch)
        result['shortages'].extend(branch['shortages'])
        if branch['produce_qty'] and child.get('quality_required'):
            result['shortages'].append({'node_id':child['id'],'item_code':child['item_code'],
                'qty':branch['produce_qty'],'kind':'quality'})
        result['tasks'].extend(branch['tasks'])
    result['tasks'].append({'node_id': node['id'], 'qty': missing})
    return result


def capacity(node, qty, pool, *, consume_existing=True):
    low, high = 0, whole(qty)
    while low < high:
        middle = (low + high + 1) // 2
        attempt = plan(node, middle, deepcopy(pool), consume_existing=consume_existing)
        if attempt['shortages']:
            high = middle - 1
        else:
            low = middle
    return low


def annotate(node, allocation, original_pool, *, final=False):
    node.update(remaining_qty=allocation['qty'], allocatable_qty=sum(r['qty'] for r in allocation['stock']),
                physical_qty=node.get('physical_qty', original_pool.available(node)),
                fabricable_qty=capacity(node, allocation['qty'], original_pool, consume_existing=not final),
                missing_qty=sum(s['qty'] for s in allocation['shortages']),
                requires_mcp=any(s['kind'] == 'cutting' for s in allocation['shortages']))
    if allocation['qty'] == 0 or (not final and node['allocatable_qty'] >= allocation['qty']):
        node['state'], node['state_label'] = 'ok', 'Besoin satisfait'
    elif node['fabricable_qty'] >= allocation['qty']:
        node['state'], node['state_label'] = 'ready', 'Fabrication disponible'
    elif node['fabricable_qty']:
        node['state'], node['state_label'] = 'partial', 'Partiellement réalisable'
    else:
        node['state'], node['state_label'] = 'blocked', 'Découpe nécessaire' if node['requires_mcp'] else 'Composant indisponible'
    by_id = {c['node_id']: c for c in allocation['children']}
    child_pool = deepcopy(original_pool)
    # Parent stock has already satisfied part of its requirement; only expand
    # the residual into children. Reserve siblings in their presentation order.
    if not final:
        child_pool.take(node, allocation['qty'])
    for child in node.get('children', []):
        branch = by_id.get(child['id']) or plan(child, 0, deepcopy(child_pool))
        annotate(child, branch, deepcopy(child_pool))
        plan(child, branch['qty'], child_pool)
    return node
