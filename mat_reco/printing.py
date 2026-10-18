"""A4 reports for saved mat_reco documents, shared by Desk and Vue entry points."""
import json
import math
from html import escape
from pathlib import Path

import frappe

TITLES = {
    'Chantier': 'Dossier chantier',
    'Chantier Section': 'Section de chantier',
    'Chantier Section Template': 'Modèle de sections',
    'Chantier Technical Study': 'Fiche technique',
    'Material Cutting Plan': 'Plan de découpe',
    'Material Production Plan': 'Plan de production',
    'Material Receipt Plan': 'Bon de réception matière',
    'Material Issue Plan': 'Bon de sortie matière',
    'Material Reconfiguration': 'Reconfiguration matière',
    'Workshop Operation': 'Fiche de fabrication',
    'Workshop Refabrication': 'Fiche de refabrication',
    'Quotation': 'Devis', 'Sales Order': 'Commande client',
    'Stock Entry': 'Mouvement de stock', 'Quality Inspection': 'Contrôle qualité',
    'Serial No': 'Fiche de traçabilité du verre',
}
LAYOUT_FIELDS = {'Section Break', 'Column Break', 'Tab Break', 'HTML', 'Button', 'Password', 'Fold'}
INTERNAL = {'lft', 'rgt', 'old_parent', 'request_key', 'source_hash', 'technical_hash',
            'commercial_hash', 'snapshot_hash', 'snapshot_json', 'workshop_request_json'}
LABELS = {'children': 'Composants', 'nodes': 'Éléments', 'item_code': 'Article',
          'proposed_code': 'Code proposé', 'item_name': 'Désignation', 'item_type': 'Type',
          'qty_factor': 'Quantité par parent', 'warehouse': 'Entrepôt', 'stock_uom': 'Unité',
          'length_mm': 'Longueur (mm)', 'width_mm': 'Hauteur (mm)', 'thickness_mm': 'Épaisseur (mm)',
          'mode': 'Mode', 'node_type': 'Type',
          'sales_order': 'Commande', 'serial_no': 'N° de série', 'x': 'X (mm)', 'y': 'Y (mm)'}


def e(value):
    return escape(str(value if value is not None else ''), quote=True)


def populated(value):
    return value is not None and value != '' and value != [] and value != {}


def structured(value):
    if isinstance(value, str):
        for _ in range(2):
            try:
                value = json.loads(value)
            except (ValueError, TypeError):
                break
    return value


def detail(value):
    """Render nested definitions without injecting user HTML or losing children."""
    if isinstance(value, dict):
        return '<dl>' + ''.join(
            f'<dt>{e(LABELS.get(k, k))}</dt><dd>{detail(v)}</dd>'
            for k, v in value.items() if populated(v) and not k.startswith('__')
        ) + '</dl>'
    if isinstance(value, list):
        return '<ol>' + ''.join(f'<li>{detail(v)}</li>' for v in value) + '</ol>'
    if isinstance(value, bool):
        return 'Oui' if value else 'Non'
    return e(value).replace('\n', '<br>')


def printable_fields(meta, doc):
    # Match the current user's field-level access; hidden technical payloads are
    # rendered only by the explicit cutting-plan handler below.
    return [f for f in meta.fields if (not f.get("permlevel") or doc.has_permlevel_access_to(f.fieldname, f))
            and f.fieldtype not in LAYOUT_FIELDS and f.fieldname not in INTERNAL
            and not f.get('print_hide') and not f.get('hidden')]


def value_html(row, field):
    value = row.get(field.fieldname)
    if field.fieldname.endswith('_json'):
        return detail(structured(value))
    if field.fieldtype == 'Check':
        return 'Oui' if value else 'Non'
    if field.fieldtype == 'Text Editor':
        # ERP descriptions often contain formatted HTML. Convert to plain text
        # before escaping rather than allow untrusted tags in the print document.
        from frappe.utils import strip_html
        return e(strip_html(value or '')).replace('\n', '<br>')
    if field.fieldtype in {'Currency', 'Float', 'Int', 'Percent', 'Date', 'Datetime', 'Time'}:
        return e(row.get_formatted(field.fieldname))
    return e(value).replace('\n', '<br>')


def fields_html(doc, fields):
    return '<dl class="facts">' + ''.join(
        f'<dt>{e(frappe._(f.label or f.fieldname))}</dt><dd>{value_html(doc, f)}</dd>'
        for f in fields if populated(doc.get(f.fieldname))
    ) + '</dl>'


def table_html(doc, field):
    rows = doc.get(field.fieldname) or []
    if not rows:
        return ''
    out = [f'<h2>{e(frappe._(field.label))}</h2>']
    # Record blocks retain dimensions, serials, allocation and commercial details
    # even on tables with dozens of columns; no horizontal clipping on A4.
    for index, row in enumerate(rows, 1):
        fields = printable_fields(frappe.get_meta(row.doctype), row)
        scalar = [f for f in fields if f.fieldtype not in {'Table', 'Table MultiSelect'}]
        out.append(f'<h3>{index}. {e(row.get("repere") or row.get("item_code") or row.get("node_label") or field.label)}</h3>')
        out.append(fields_html(row, scalar))
        for child in fields:
            if child.fieldtype in {'Table', 'Table MultiSelect'}:
                out.append(table_html(row, child))
    return ''.join(out)


def number(value):
    try:
        value = float(value or 0)
        return value if math.isfinite(value) else 0
    except (TypeError, ValueError):
        return 0


def physical_regions(node):
    """Same absolute coordinates and Single notch geometry as the Vue canvas."""
    if isinstance(node.get('visual_regions'), list):
        return [region for child in node['visual_regions'] for region in physical_regions(child)]
    x, y = number(node.get('x')), number(node.get('y'))
    destroyed = node.get('node_type') == 'destroyed'
    w = number(node.get('length_mm') if destroyed else node.get('effective_length_mm', node.get('length_mm')))
    h = number(node.get('width_mm') if destroyed else node.get('effective_width_mm', node.get('width_mm')))
    left, top = number(node.get('removed_length_mm')), number(node.get('removed_width_mm'))
    rectangles = [(x + left, y, w - left, top), (x, y + top, w, h - top)] if left > 0 and top > 0 else [(x, y, w, h)]
    return [r for r in rectangles if r[2] > 0 and r[3] > 0]


def cutting_html(doc):
    raw = doc.get('effective_result_json') or doc.get('result_json')
    tree = structured(raw)
    if not isinstance(tree, dict):
        return '<p>Plan de découpe non disponible.</p>'
    tree = tree.get('tree') or tree
    out = ['<h2>Découpe effective enregistrée</h2>' if doc.get('effective_result_json') else '<h2>Découpe planifiée</h2>']
    for sheet in tree.get('nodes', []):
        if sheet.get('node_type') != 'input_serial':
            continue
        width = number(sheet.get('length_mm') or sheet.get('length'))
        height = number(sheet.get('width_mm') or sheet.get('width'))
        out.append(f'<h3>Plaque {e(sheet.get("serial_no") or sheet.get("node_id"))} · {width:g} × {height:g} mm</h3>')
        if width > 0 and height > 0:
            out.append(f'<svg xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Plan de découpe" viewBox="0 0 {width:g} {height:g}" preserveAspectRatio="xMidYMid meet"><rect width="{width:g}" height="{height:g}" fill="white" stroke="black" stroke-width="2"/>')
            stack = list(sheet.get('children') or [])
            while stack:
                piece = stack.pop(0)
                stack[0:0] = piece.get('children') or []
                if piece.get('__preexisting_cutout') or piece.get('node_type') == 'preexisting_cutout':
                    continue
                regions = physical_regions(piece)
                fill = {'waste': '#ccc', 'leftover': '#eef5fa', 'destroyed': '#555'}.get(piece.get('node_type'), '#fff')
                for x, y, w, h in regions:
                    out.append(f'<rect x="{x:g}" y="{y:g}" width="{w:g}" height="{h:g}" fill="{fill}" stroke="black" stroke-width="2"/>')
                if regions:
                    x, y, w, h = max(regions, key=lambda r: r[2] * r[3])
                    label = piece.get('label') or piece.get('piece_item_code') or piece.get('node_type') or ''
                    out.append(f'<text x="{x + w / 2:g}" y="{y + h / 2:g}" text-anchor="middle" font-size="{min(width,height)/60:g}">{e(label)}</text>')
            out.append('</svg>')
        # The textual inventory is authoritative for small or nested pieces.
        out.append('<table><thead><tr><th>Repère / article</th><th>Type</th><th>Dimensions (mm)</th><th>X / Y (mm)</th><th>Commande / détails</th></tr></thead><tbody>')
        stack = [(child, 0) for child in sheet.get('children') or []]
        while stack:
            piece, depth = stack.pop(0)
            stack[0:0] = [(child, depth + 1) for child in piece.get('children') or []]
            label = piece.get('label') or piece.get('node_id') or piece.get('id') or ''
            item = piece.get('piece_item_code') or piece.get('item_code') or ''
            kind = piece.get('node_type') or ''
            kind = {'finished_good': 'Pièce', 'leftover': 'Chute', 'waste': 'Déchet',
                    'destroyed': 'Détruit', 'preexisting_cutout': 'Encoche existante'}.get(kind, kind)
            w = piece.get('effective_length_mm', piece.get('length_mm', ''))
            h = piece.get('effective_width_mm', piece.get('width_mm', ''))
            notes = [e(piece.get('sales_order') or '')]
            if piece.get('removed_length_mm') and piece.get('removed_width_mm'):
                notes.append(f'Encoche : {e(piece["removed_length_mm"])} × {e(piece["removed_width_mm"])} mm')
            for key in ('serial_no', 'plan_ref_id', 'rotation_degrees', 'incident_reference', 'remarks'):
                if populated(piece.get(key)):
                    notes.append(e(key) + ' : ' + e(piece[key]))
            out.append(f'<tr><td>{e("› " * depth + str(label))}<br>{e(item)}</td><td>{e(kind)}</td><td>{e(w)} × {e(h)}</td><td>{e(piece.get("x", 0))} / {e(piece.get("y", 0))}</td><td>{"<br>".join(notes)}</td></tr>')
        out.append('</tbody></table>')
    return ''.join(out)


def render_mat_reco_a4(doc):
    """Jinja entry point; native printview also enforces document print rights."""
    if doc.doctype not in TITLES:
        frappe.throw('Type de document non pris en charge.')
    doc.check_permission('read')
    doc.check_permission('print')
    fields = printable_fields(frappe.get_meta(doc.doctype), doc)
    skip = {'result_json', 'effective_result_json', 'mcp_sheets', 'effective_mcp_sheets'} if doc.doctype == 'Material Cutting Plan' else set()
    fields = [f for f in fields if f.fieldname not in skip]
    status = {0: 'Brouillon', 1: 'Validé', 2: 'Annulé'}.get(doc.docstatus, '')
    out = [f'<meta name="pdfkit-page-size" content="A4"><article class="mat-reco-a4"><h1>{e(TITLES[doc.doctype])}</h1>',
           f'<p class="identity">{e(doc.name)} · {status}</p>',
           f'<p>Dernière modification : {e(doc.get("modified"))}</p>']
    out.append(fields_html(doc, [f for f in fields if f.fieldtype not in {'Table', 'Table MultiSelect'}]))
    for field in fields:
        if field.fieldtype in {'Table', 'Table MultiSelect'}:
            out.append(table_html(doc, field))
    if doc.doctype == 'Material Cutting Plan':
        out.append(cutting_html(doc))
    if doc.doctype == 'Workshop Operation' and doc.get('result_json') and not any(f.fieldname == 'result_json' for f in fields):
        field = doc.meta.get_field('result_json')
        if field and not field.get('print_hide') and (not field.get('permlevel') or doc.has_permlevel_access_to(field.fieldname, field)):
            out.append('<h2>Résultat de fabrication</h2>' + detail(structured(doc.get('result_json'))))
    out.append('<footer>Document enregistré · Dimensions indiquées en mm ; schémas sans échelle.</footer></article>')
    return ''.join(out)


def install_print_formats():
    """Idempotent install; existing formats and site defaults are preserved."""
    css = Path(__file__).with_name('templates').joinpath('mat_reco_a4.css').read_text()
    for doctype in TITLES:
        if not frappe.db.exists('DocType', doctype):
            continue
        name = f'Mat Reco A4 - {doctype}'
        values = dict(doc_type=doctype, module='Material Reconfiguration',
                      custom_format=1, print_format_type='Jinja', disabled=0,
                      html='{{ render_mat_reco_a4(doc) | safe }}', css=css,
                      default_print_language='fr')
        if frappe.db.exists('Print Format', name):
            fmt = frappe.get_doc('Print Format', name)
            fmt.update(values)
            fmt.save(ignore_permissions=True)
        else:
            frappe.get_doc(dict(doctype='Print Format', name=name, **values)).insert(ignore_permissions=True)
