"""Execute the cutting plan's Repack in the plan submission transaction."""
import json

import frappe

from mat_reco.material_reconfiguration.services import repack_draft_service
from mat_reco.material_reconfiguration.utils.accounting_dimensions import (
    get_active_accounting_dimension_fields,
    resolve_and_apply_stock_entry_dimensions,
)


def execute_on_submit(doc):
    frappe.db.get_value('Material Cutting Plan', doc.name, 'name', for_update=True)
    linked = frappe.get_all('Stock Entry', filters={
        'custom_material_cutting_plan': doc.name, 'stock_entry_type': 'Repack',
        'docstatus': ['<', 2],
    }, fields=['name', 'docstatus'], order_by='creation asc')
    submitted = [row.name for row in linked if row.docstatus == 1]
    drafts = [row.name for row in linked if row.docstatus == 0]
    if submitted and _execution_complete(doc):
        _record_execution(doc, submitted)
        return submitted[-1]
    if len(drafts) > 1:
        frappe.throw('Plusieurs Repack brouillons sont liés à ce plan. Conserver un seul brouillon avant de valider le plan.')
    if drafts:
        entry = frappe.get_doc('Stock Entry', drafts[0])
        entry.check_permission('write')
    else:
        entry = frappe.get_doc(repack_draft_service.make_repack_draft(doc.name))
    entry.check_permission('submit')
    _apply_input_inventory_dimensions(entry)
    sources = []
    for name in dict.fromkeys(row.sales_order for row in (doc.get('selected_sales_orders') or []) if row.sales_order):
        order = frappe.get_doc('Sales Order', name)
        order.check_permission('read')
        sources.append(order)
    for field in get_active_accounting_dimension_fields():
        if entry.get(field) or doc.get(field):
            continue
        values = {order.get(field) for order in sources if order.get(field)}
        if len(values) > 1:
            frappe.throw('Les commandes du plan ont des dimensions comptables différentes ({0}). Préparer des plans distincts.'.format(field))
    resolve_and_apply_stock_entry_dimensions(entry, source_doc=doc, fallback_docs=sources, validate_mandatory=True)
    if not drafts:
        entry.add_waiste_to_stock = doc.get('add_waiste_to_stock') or 0
        entry.insert()
    # Any stock or permission failure rolls back the enclosing plan submission.
    entry.submit()
    if not _execution_complete(doc):
        frappe.throw('Le Repack lié ne couvre pas toutes les entrées et sorties du plan. Compléter le brouillon avant de valider le plan.')
    _record_execution(doc, submitted + [entry.name])
    return entry.name


def _record_execution(doc, entries):
    doc.db_set('created_stock_entries_json', json.dumps(entries))
    doc.db_set('status', 'Executed')


def _execution_complete(doc):
    nodes = repack_draft_service.build_effective_nodes(doc)
    expected, inputs = repack_draft_service._collect_expected_serials(nodes, doc.get('add_waiste_to_stock'))
    generated, consumed = repack_draft_service._collect_generated_outputs_and_inputs_from_serials(doc.name)
    return bool(inputs) and inputs.issubset(consumed) and expected.issubset(generated)


def _apply_input_inventory_dimensions(entry):
    from erpnext.stock.doctype.inventory_dimension.inventory_dimension import get_inventory_dimensions
    from frappe.utils import get_datetime

    dimensions = get_inventory_dimensions()
    if not dimensions:
        return
    for row in entry.get('items') or []:
        if not row.get('s_warehouse'):
            continue
        serials = repack_draft_service._extract_serials_from_row(row)
        if not serials:
            continue
        ledger = frappe.get_doc(dict(doctype='Stock Ledger Entry', item_code=row.item_code,
            posting_datetime=get_datetime('{0} {1}'.format(entry.posting_date, entry.posting_time or '23:59:59'))))
        values = ledger.get_last_inward_dimensions(serials, dimensions)
        if set(values) != serials:
            frappe.throw('Dimensions de stock introuvables pour une matière du Repack.')
        for dimension in dimensions:
            choices = {value.get(dimension.fieldname) for value in values.values()}
            if len(choices) > 1:
                frappe.throw('Les matières regroupées ont des dimensions de stock différentes ({0}). Séparer leurs lignes dans le Repack.'.format(dimension.fieldname))
            row.set(dimension.source_fieldname, choices.pop())
