"""Pure completion evidence for B's HT circuit, without changing ERP statuses."""
from collections import defaultdict
from math import isfinite

EPS = .000001


def _number(value):
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if isfinite(result) else None


def _group(values, key):
    result = defaultdict(list)
    for row in values:
        result[row.get(key)].append(row)
    return result


def _active(row):
    return row.get('docstatus') != 2


def _order_done(order, metric, deliveries, payments, allocations):
    if (order.get('custom_ug_order_type') != 'B' or order.get('docstatus') != 1
            or order.get('status') == 'On Hold'):
        return False
    keys = ('remaining_all', 'order_amount', 'delivery_amount', 'delivery_balance',
            'order_balance', 'advances')
    values = {key: _number(metric.get(key)) for key in keys}
    if any(value is None for value in values.values()):
        return False
    if any(abs(values[key]) > EPS for key in ('remaining_all', 'delivery_balance', 'order_balance', 'advances')):
        return False
    # B documents round CFA to whole francs; the source quotation/order may
    # retain fractions. A whole franc still remains a real unpaid amount.
    tolerance = .5 if order.get('currency') in ('XOF', 'XAF') else .005
    if abs(values['order_amount'] - values['delivery_amount']) > tolerance + EPS:
        return False
    if any(row.get('docstatus') == 0 for row in deliveries):
        return False
    delivery_names = {row['name'] for row in deliveries}
    for row in payments:
        if row.get('docstatus') == 0 and (row.get('sales_order') == order['name'] or
                any(line.get('bordereau') in delivery_names for line in allocations[row['name']])):
            return False
    return True


def completed_b_branches(snapshot, metrics):
    """Only hide ancestors when all source quantities have proved completion.

    Missing fields, filtered-out peers and inaccessible/truncated source rows
    keep ancestors visible. Native A documents never acquire B's HT completion.
    """
    orders = {row['name']: row for row in snapshot.get('order', [])}
    quotations = {row['name']: row for row in snapshot.get('quotation', [])}
    projects = {row['name']: row for row in snapshot.get('project', [])}
    deliveries = _group(snapshot.get('delivery', []), 'sales_order')
    allocations = _group(snapshot.get('allocations', []), 'parent')
    done = {name for name, order in orders.items() if _order_done(order,
        metrics.get(name, {}), deliveries[name], snapshot.get('payment', []), allocations)}
    result = dict(order=done, quotation=set(), project=set())
    incomplete = snapshot.get('incomplete_children', set())
    if (not done or snapshot.get('completion_scope_incomplete') or
            set(snapshot.get('incomplete_parents', ())) & {'order', 'quotation', 'project'}):
        return result
    order_peers = snapshot.get('completion_orders', list(orders.values()))
    quote_peers = snapshot.get('completion_quotations', list(quotations.values()))
    order_lines = _group(snapshot.get('order_items', []), 'prevdoc_docname')
    quote_lines = _group(snapshot.get('quotation_items', []), 'parent')
    if 'quotation_items' not in incomplete and snapshot['capabilities'].get('can_read_quotations'):
        for name, quote in quotations.items():
            source = quote_lines[name]
            linked = [row for row in order_lines[name] if row.get('parent') in orders and _active(orders[row['parent']])]
            if (quote.get('docstatus') != 1 or not source or not linked or
                    any(row.get('parent') not in done for row in linked)):
                continue
            chantier = quote.get('custom_chantier')
            if any(_active(row) and row['name'] not in orders and
                    (not row.get('custom_chantier') or row.get('custom_chantier') == chantier)
                    for row in order_peers):
                continue
            covered = _group(linked, 'quotation_item')
            complete = True
            for row in source:
                # Alternatives and unit-price-only lines need an explicit native
                # choice; their absence cannot prove the whole source is done.
                qty = _number(row.get('qty'))
                children = covered[row['name']]
                if qty is None or qty <= 0 or not children:
                    complete = False
                    break
                use_stock = _number(row.get('stock_qty')) is not None and all(
                    _number(child.get('stock_qty')) is not None for child in children)
                field = 'stock_qty' if use_stock else 'qty'
                expected = _number(row.get(field))
                amounts = [_number(child.get(field)) for child in children]
                if expected is None or any(amount is None for amount in amounts) or sum(amounts) + EPS < expected:
                    complete = False
                    break
                ordered = _number(row.get('ordered_qty'))
                if use_stock and ordered is not None and ordered > sum(amounts) + EPS:
                    complete = False
                    break
            if complete:
                result['quotation'].add(name)

    if (incomplete & {'quotation_items', 'project_lines', 'project_extras'} or
            'project_lines' not in snapshot or 'project_extras' not in snapshot or
            not snapshot['capabilities'].get('can_read_projects')):
        return result
    project_lines = _group(snapshot.get('project_lines', []), 'parent')
    project_extras = _group(snapshot.get('project_extras', []), 'parent')
    for name, project in projects.items():
        sources = project_lines[name] + project_extras[name]
        linked = [row for row in quotations.values() if row.get('custom_chantier') == name and
            _active(row) and row.get('status') not in ('Lost', 'Closed', 'Cancelled')]
        if (project.get('docstatus') != 1 or not sources or not linked or
                any(row['name'] not in result['quotation'] for row in linked)):
            continue
        if any(_active(row) and row.get('custom_chantier') == name and row['name'] not in done
                for row in order_peers):
            continue
        if any(_active(row) and row.get('custom_chantier') == name and
                row.get('status') not in ('Lost', 'Closed', 'Cancelled') and
                row['name'] not in result['quotation'] for row in quote_peers):
            continue
        supplied = defaultdict(float)
        repere_ids = defaultdict(set)
        for row in project_lines[name]:
            if row.get('repere'):
                repere_ids[row['repere']].add(row.get('line_id'))
        valid = True
        for quote in linked:
            for row in quote_lines[quote['name']]:
                identity = row.get('custom_chantier_line')
                if not identity and len(repere_ids[row.get('custom_repere')]) == 1:
                    identity = next(iter(repere_ids[row.get('custom_repere')]))
                qty = _number(row.get('qty'))
                if qty is None:
                    valid = False
                    break
                if identity:
                    supplied[identity] += qty
        if valid and all(row.get('line_id') and _number(row.get('qty')) is not None and
                supplied[row['line_id']] + EPS >= _number(row['qty']) for row in sources):
            result['project'].add(name)
    return result
