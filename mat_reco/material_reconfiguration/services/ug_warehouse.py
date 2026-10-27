"""Single operational warehouse for Univers Glass; never relocate physical stock."""
import frappe

COMPANY = 'Univers Glass'
WAREHOUSE = 'Stores - UG'
GLASS_TYPES = ('PRIMAIRE', 'DECOUPE', 'OUVRAGE')


def is_glass(item_code):
    return bool(item_code) and frappe.get_cached_value('Item', item_code, 'custom_item_types') in GLASS_TYPES


def operational_warehouse(company):
    if company != COMPANY:
        return None
    warehouse = frappe.db.get_value('Warehouse', {
        'name': WAREHOUSE, 'company': company, 'is_group': 0, 'disabled': 0,
    }, 'name')
    return warehouse


def apply_defaults(doc, method=None):
    if doc.docstatus != 0:
        return
    if doc.doctype == 'Item':
        if doc.get('custom_item_types') not in GLASS_TYPES:
            return
        for row in doc.get('item_defaults', []):
            warehouse = operational_warehouse(row.company)
            if warehouse and not row.default_warehouse:
                row.default_warehouse = warehouse
        return
    if doc.get('company') != COMPANY:
        return
    if doc.doctype in ('Quotation', 'Sales Order', 'Bordereau Special'):
        if doc.doctype == 'Bordereau Special' and doc.get('adopt_existing_stock'):
            return
        rows = doc.get('items', [])
        glass_rows = [row for row in rows if is_glass(row.item_code)]
        if not glass_rows:
            return
        warehouse = operational_warehouse(doc.company)
        other_stock = any(not is_glass(row.item_code) and frappe.get_cached_value('Item', row.item_code, 'is_stock_item') for row in rows)
        header = 'warehouse' if doc.doctype == 'Bordereau Special' else 'set_warehouse'
        if not other_stock and not doc.get(header):
            doc.set(header, warehouse)
        for row in glass_rows:
            if not row.warehouse:
                row.warehouse = warehouse
    elif doc.doctype == 'Material Cutting Plan':
        warehouse = operational_warehouse(doc.company)
        if not doc.source_warehouse:
            doc.source_warehouse = warehouse
        if doc.meta.has_field('target_warehouse') and not doc.get('target_warehouse'):
            doc.target_warehouse = warehouse


def install_defaults():
    if not frappe.db.exists('Company', COMPANY):
        return
    warehouse = operational_warehouse(COMPANY)
    if not warehouse:
        return
    for name in frappe.get_all('Item Default', filters={
        'company': COMPANY, 'parenttype': 'Item',
    }, pluck='name'):
        parent = frappe.db.get_value('Item Default', name, 'parent')
        if is_glass(parent):
            frappe.db.set_value('Item Default', name, 'default_warehouse', warehouse, update_modified=False)
    frappe.clear_cache(doctype='Item')
