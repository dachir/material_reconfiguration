"""Physical glass stock, sharing classification, geometry and permissions with Stock de Vitres."""
from collections import Counter

import frappe

from mat_reco.material_reconfiguration.services.glass_stock import _inventory, _read_all


def get_columns(detail=False):
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
    if detail:
        columns.insert(4, {'fieldname': 'serial_no', 'label': 'N° série', 'fieldtype': 'Link', 'options': 'Serial No', 'width': 170})
    return columns


def build_rows(stock, items, stock_type="Les deux", detail=False, primary_item=None):
    groups, rows = {}, []
    counts = Counter()
    for source in stock:
        kind = "Plaques" if source["classification"] == "volumes" else "Chutes"
        if stock_type != "Les deux" and kind != stock_type:
            continue
        if primary_item and source["primary_item"] != primary_item:
            continue
        root = source["primary_item"]
        row = {
            "primary_item": root, "item_name": items[root].get("item_name") or root,
            "stock_type": kind, "item_code": source["item_code"],
            "serial_no": source["serial_no"] if detail else "",
            "length_mm": source["length_mm"], "width_mm": source["width_mm"],
            "thickness_mm": source["thickness_mm"],
            "removed_length_mm": source.get("removed_length_mm") or None,
            "removed_width_mm": source.get("removed_width_mm") or None,
            "warehouse": source["warehouse"], "qty": 1, "area_m2": source["area_m2"],
            "note": "Surface inconnue : géométrie invalide" if source.get("geometry_error")
            else "Chute en L" if source.get("removed_length_mm") else "",
        }
        counts[kind] += 1
        counts["unknown"] += source["area_m2"] is None
        counts["area"] += source["area_m2"] or 0
        if detail:
            rows.append(row)
        else:
            key = tuple(row[field] for field in (
                "primary_item", "stock_type", "item_code", "length_mm", "width_mm",
                "thickness_mm", "removed_length_mm", "removed_width_mm", "warehouse", "note"))
            if key in groups:
                groups[key]["qty"] += 1
                if source["area_m2"] is not None:
                    groups[key]["area_m2"] += source["area_m2"]
            else:
                groups[key] = row
    if not detail:
        rows = list(groups.values())
    rows.sort(key=lambda r: (r["item_name"], r["stock_type"], r["warehouse"],
                             r["length_mm"], r["width_mm"], r["serial_no"]))
    if rows:
        rows.append({"item_name": "TOTAL", "qty": counts["Plaques"] + counts["Chutes"],
                     "area_m2": counts["area"],
                     "note": f"{counts['unknown']} surface(s) inconnue(s)" if counts["unknown"] else ""})
    return rows, counts


def execute(filters=None):
    filters = frappe._dict(filters or {})
    stock_type = filters.get("stock_type") or "Les deux"
    presentation = filters.get("detail") or "Synthèse"
    if stock_type not in ("Les deux", "Plaques", "Chutes"):
        frappe.throw("Type de stock invalide.")
    if presentation not in ("Synthèse", "Détail par série"):
        frappe.throw("Présentation invalide.")
    stock, diagnostics, items = _inventory(warehouse=filters.get("warehouse"))
    if filters.get("company"):
        allowed = {w["name"] for w in _read_all("Warehouse", ["name"],
                   {"is_group": 0, "company": filters.company})}
        if filters.get("warehouse") and filters.warehouse not in allowed:
            frappe.throw("Dépôt hors de la société sélectionnée.")
        stock = [row for row in stock if row["warehouse"] in allowed]
    detail = presentation == "Détail par série"
    rows, counts = build_rows(stock, items, stock_type, detail, filters.get("primary_item"))
    message = ("Stock physique actuel ; réservations non déduites. "
               "Surface nette : retrait de l’évidement pour les chutes en L.")
    if diagnostics.get("unresolved_lineage"):
        message += f" {diagnostics['unresolved_lineage']} série(s) exclue(s) : filiation primaire inaccessible ou invalide."
    summary = [
        {"label": "Plaques", "value": counts["Plaques"], "datatype": "Int"},
        {"label": "Chutes", "value": counts["Chutes"], "datatype": "Int"},
        {"label": "Surface connue (m²)", "value": counts["area"], "datatype": "Float", "precision": 4},
    ]
    return get_columns(detail), rows, message, None, summary, True
