# Inline Script Report: no imports, writes, get_all or SQL bypassing permissions.
def read_all(doctype, fields, conditions):
    values = []
    more = True
    while more:
        page = frappe.get_list(doctype, fields=fields, filters=conditions,
            order_by='name asc', limit_start=len(values), limit_page_length=1000)
        values.extend(page)
        more = len(page) == 1000
    return values

for dt in ['Item', 'Serial No', 'Warehouse', 'Stock Ledger Entry']:
    frappe.get_list(dt, fields=['name'], limit_page_length=1)
kind_filter = filters.get('stock_type') or 'Les deux'
if kind_filter not in ['Les deux', 'Plaques', 'Chutes']:
    frappe.throw('Type de stock invalide.')
mode = filters.get('detail') or 'Synthèse'
if mode not in ['Synthèse', 'Détail par série']:
    frappe.throw('Présentation invalide.')
warehouses = {}
for wh in read_all('Warehouse', ['name', 'company'], {'is_group': 0}):
    if not filters.get('company') or wh.company == filters.company:
        warehouses[wh.name] = wh.company
if filters.get('warehouse'):
    if filters.warehouse not in warehouses:
        frappe.throw('Dépôt non autorisé ou hors de la société sélectionnée.')
    warehouses = {filters.warehouse: warehouses[filters.warehouse]}
items = {}
for item in read_all('Item', ['name', 'item_name', 'custom_item_types', 'custom_parent_item'], {}):
    items[item.name] = item
serials = []
if warehouses:
    serials = read_all('Serial No', ['name', 'item_code', 'warehouse', 'status',
        'custom_material_status', 'custom_dimension_length_mm', 'custom_dimension_width_mm',
        'custom_dimension_thickness_mm', 'custom_removed_length_mm', 'custom_removed_width_mm'],
        {'status': 'Active', 'warehouse': ['in', list(warehouses)]})
groups = {}
rows = []
plates = 0
cuts = 0
surface = 0
unknown = 0
unresolved = 0
for sn in serials:
    item = items.get(sn.item_code)
    if not item or item.custom_item_types not in ['PRIMAIRE', 'DECOUPE'] or sn.custom_material_status == 'Consumed':
        continue
    classification = 'Chutes' if item.custom_item_types == 'DECOUPE' or sn.custom_material_status == 'Partial' else 'Plaques' if sn.custom_material_status == 'Full' else ''
    if not classification or (kind_filter != 'Les deux' and classification != kind_filter):
        continue
    code = sn.item_code
    root = None
    seen = []
    while code and code in items and code not in seen:
        seen.append(code)
        if items[code].custom_item_types == 'PRIMAIRE':
            root = code
        code = items[code].custom_parent_item
    if code or not root:
        unresolved = unresolved + 1
        continue
    if filters.get('primary_item') and root != filters.primary_item:
        continue
    l = frappe.utils.flt(sn.custom_dimension_length_mm)
    w = frappe.utils.flt(sn.custom_dimension_width_mm)
    t = frappe.utils.flt(sn.custom_dimension_thickness_mm)
    rl = frappe.utils.flt(sn.custom_removed_length_mm)
    rw = frappe.utils.flt(sn.custom_removed_width_mm)
    valid = l > 0 and w > 0 and rl >= 0 and rw >= 0 and ((rl == 0 and rw == 0) or (rl > 0 and rw > 0 and rl < l and rw < w))
    area = (l * w - rl * rw) / 1000000 if valid else None
    note = 'Surface inconnue : géométrie invalide' if not valid else 'Chute en L' if rl else ''
    value = {'primary_item': root, 'item_name': items[root].item_name, 'stock_type': classification,
        'item_code': sn.item_code, 'serial_no': sn.name if mode == 'Détail par série' else '',
        'length_mm': l, 'width_mm': w, 'thickness_mm': t, 'removed_length_mm': rl or None,
        'removed_width_mm': rw or None, 'qty': 1, 'area_m2': area, 'warehouse': sn.warehouse, 'note': note}
    if classification == 'Plaques':
        plates = plates + 1
    else:
        cuts = cuts + 1
    surface = surface + (area or 0)
    unknown = unknown + (0 if valid else 1)
    if mode == 'Détail par série':
        rows.append(value)
    else:
        key = (root, classification, sn.item_code, l, w, t, rl, rw, sn.warehouse, note)
        if key in groups:
            groups[key]['qty'] = groups[key]['qty'] + 1
            if area is not None:
                groups[key]['area_m2'] = groups[key]['area_m2'] + area
        else:
            groups[key] = value
if mode == 'Synthèse':
    rows = list(groups.values())
rows = sorted(rows, key=lambda r: (r['item_name'], r['stock_type'], r['warehouse'], r['length_mm'], r['width_mm'], r['serial_no']))
if rows:
    rows.append({'item_name': 'TOTAL', 'qty': plates + cuts, 'area_m2': surface,
        'note': str(unknown) + ' surface(s) inconnue(s)' if unknown else ''})
columns = [
    {'fieldname': 'primary_item', 'label': 'Article primaire', 'fieldtype': 'Link', 'options': 'Item', 'width': 130},
    {'fieldname': 'item_name', 'label': 'Désignation', 'fieldtype': 'Data', 'width': 230},
    {'fieldname': 'stock_type', 'label': 'Type', 'fieldtype': 'Data', 'width': 85},
    {'fieldname': 'item_code', 'label': 'Article en stock', 'fieldtype': 'Link', 'options': 'Item', 'width': 130},
    {'fieldname': 'length_mm', 'label': 'L (mm)', 'fieldtype': 'Float', 'precision': 0, 'width': 80},
    {'fieldname': 'width_mm', 'label': 'H (mm)', 'fieldtype': 'Float', 'precision': 0, 'width': 80},
    {'fieldname': 'thickness_mm', 'label': 'Ép. (mm)', 'fieldtype': 'Float', 'precision': 2, 'width': 80},
    {'fieldname': 'removed_length_mm', 'label': 'Retrait L (mm)', 'fieldtype': 'Float', 'precision': 0, 'width': 100},
    {'fieldname': 'removed_width_mm', 'label': 'Retrait H (mm)', 'fieldtype': 'Float', 'precision': 0, 'width': 100},
    {'fieldname': 'qty', 'label': 'Qté', 'fieldtype': 'Int', 'width': 65},
    {'fieldname': 'area_m2', 'label': 'Surface (m²)', 'fieldtype': 'Float', 'precision': 4, 'width': 110},
    {'fieldname': 'warehouse', 'label': 'Dépôt', 'fieldtype': 'Link', 'options': 'Warehouse', 'width': 170},
    {'fieldname': 'note', 'label': 'Observation', 'fieldtype': 'Data', 'width': 180}
]
if mode == 'Détail par série':
    columns.insert(4, {'fieldname': 'serial_no', 'label': 'N° série', 'fieldtype': 'Link', 'options': 'Serial No', 'width': 170})
message = 'Stock physique actuel ; réservations non déduites. Surface nette : retrait de l’évidement pour les chutes en L.'
if unresolved:
    message = message + ' ' + str(unresolved) + ' série(s) exclue(s) : filiation primaire inaccessible ou invalide.'
summary = [{'label': 'Plaques', 'value': plates, 'datatype': 'Int'},
    {'label': 'Chutes', 'value': cuts, 'datatype': 'Int'},
    {'label': 'Surface connue (m²)', 'value': surface, 'datatype': 'Float', 'precision': 4}]
data = columns, rows, message, None, summary, True
