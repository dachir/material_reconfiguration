"""Independent native annual naming series for sales order classes A and B."""
import re

import frappe

SERIES={'A':'SAL-ORD-.YYYY.-.#####','B':'SAL-ORD-B-.YYYY.-.#####'}


def kind(value):
    value=value or 'A'
    if value not in SERIES:frappe.throw('Choisir un type de commande A ou B.')
    return value


def before_naming(doc,method=None):
    selected=kind(doc.get('custom_ug_order_type'))
    if doc.get('amended_from'):
        original=frappe.db.get_value('Sales Order',doc.amended_from,'custom_ug_order_type') or 'A'
        if selected!=original:frappe.throw('Un amendement doit conserver le type de la commande d’origine.')
    doc.custom_ug_order_type=selected
    doc.naming_series=SERIES[selected]


def validate(doc,method=None):
    selected=kind(doc.get('custom_ug_order_type'));old=doc.get_doc_before_save()
    if old and selected!=kind(old.get('custom_ug_order_type')):
        frappe.throw('Le type A/B ne peut plus être modifié après création de la commande.')
    if doc.is_new() and not doc.get('amended_from') and not re.fullmatch(r'SAL-ORD-' + ('B-' if selected=='B' else '') + r'\d{4}-\d{5,}',doc.name or ''):
        frappe.throw('Le numéro de commande doit correspondre à sa série A/B.')
    doc.custom_ug_order_type=selected


def install():
    from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
    from frappe.custom.doctype.property_setter.property_setter import make_property_setter
    create_custom_fields({'Sales Order':[dict(fieldname='custom_ug_order_type',label='Type de commande',fieldtype='Select',
        options='A\nB',default='A',reqd=1,insert_after='naming_series',in_list_view=1,in_standard_filter=1,module='Material Reconfiguration')]},update=True)
    meta=frappe.get_meta('Sales Order',cached=False)
    options=[s for s in (meta.get_field('naming_series').options or '').splitlines() if s and s!='SAL-ORD-A-.YYYY.-.#####']
    for series in SERIES.values():
        if series not in options:options.append(series)
    previous_default=meta.get_field('naming_series').default
    transitional=options + ([previous_default] if previous_default and previous_default not in options else [])
    make_property_setter('Sales Order','naming_series','options','\n'.join(transitional),'Text')
    make_property_setter('Sales Order','naming_series','default',SERIES['A'],'Data')
    make_property_setter('Sales Order','naming_series','options','\n'.join(options),'Text')
