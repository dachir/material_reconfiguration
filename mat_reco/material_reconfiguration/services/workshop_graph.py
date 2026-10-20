"""Read-only MCP links to the cockpit's compatible-stock occurrences."""
import json

import frappe


def _json(value):
    return json.loads(value) if isinstance(value, str) and value else value or {}


def linked_stocks(doc, leaves):
    scope = _json(doc.get('workshop_request_json'))
    needs = scope.get('needs') or []
    if needs:
        identities = {(n.get('sales_order', scope.get('sales_order')), n.get('node_id'))
                      for n in needs if n.get('qty', 0) > 0}
        return sorted({n['id'] + ':stock' for n in leaves
                       if (n['sales_order'], n['id']) in identities})
    tree = _json(doc.get('effective_result_json') or doc.get('result_json'))
    tree = tree.get('tree') or tree
    pieces = [piece for sheet in tree.get('nodes', []) for piece in sheet.get('children', [])
              if piece.get('node_type') == 'finished_good']
    if pieces:
        links = set()
        for piece in pieces:
            for node in leaves:
                if piece.get('sales_order') != node['sales_order']:
                    continue
                if piece.get('workshop_node_id'):
                    match = piece['workshop_node_id'] == node['id']
                else:
                    match = (piece.get('sales_order_item') == node['sales_order_item']
                             and (not piece.get('item_code') or piece['item_code'] == node['item_code']))
                if match:
                    links.add(node['id'] + ':stock')
        return sorted(links)
    # A newly created, unsimulated plan already has its selected orders and raw
    # glass family. It can target all their compatible cutting occurrences.
    orders = {r.get('sales_order') for r in doc.get('selected_sales_orders', [])}
    return sorted({n['id'] + ':stock' for n in leaves if n['sales_order'] in orders
                   and n.get('primary_item') and n['primary_item'] == doc.get('source_item')})


def get_workshop_mcps(roots):
    if not roots or not frappe.has_permission('Material Cutting Plan', 'read'):
        return []
    def walk(node):
        yield node
        for child in node.get('children', []):
            yield from walk(child)
    leaves = [n for root in roots for branch in root.get('children', []) for n in walk(branch)
              if n.get('item_type') == 'DECOUPE' and not n.get('invalid_message')]
    if not leaves:
        return []
    paths = {}
    def collect_paths(node, ancestors):
        path = ancestors + [node['id']]
        if node.get('item_type') == 'DECOUPE':
            stock_id = node['id'] + ':stock'
            paths[stock_id] = path + [stock_id]
        for child in node.get('children', []):
            collect_paths(child, path)
    for root in roots:
        collect_paths(root, [])
    plans = frappe.get_list('Material Cutting Plan',
        filters={'company': ['in', sorted({r['company'] for r in roots})]},
        fields=['name', 'creation', 'status', 'docstatus'],
        order_by='creation asc, name asc', limit_page_length=0)
    result = []
    for plan in plans:
        doc = frappe.get_doc('Material Cutting Plan', plan.name)
        links = linked_stocks(doc, leaves)
        if links:
            result.append(dict(id='mcp:' + plan.name, name=plan.name, label=plan.name,
                creation=str(plan.creation), status=plan.status, docstatus=plan.docstatus,
                stock_ids=links, stock_paths={key: paths[key] for key in links}))
    return result
