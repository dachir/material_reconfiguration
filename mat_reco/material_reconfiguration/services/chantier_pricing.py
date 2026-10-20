"""Surface pricing with physical ERP quantities kept in pieces for serial tracking."""
import frappe
from frappe.utils import flt,cint


def surface(row):return flt(row.length_mm)*flt(row.width_mm)/1_000_000


def unit_rate(row):return flt(row.rate)*(surface(row) if cint(row.get('price_per_sqm')) else 1)


def set_sales_fields(target,row):
    enabled=cint(row.get('price_per_sqm'))
    target.custom_ug_price_per_sqm=enabled
    target.custom_ug_pricing_rate=flt(row.rate)
    target.custom_ug_pricing_surface=surface(row) if enabled else 0


def matches(target,row):
    enabled=cint(row.get('price_per_sqm'))
    return (cint(target.get('custom_ug_price_per_sqm'))==enabled and (not enabled or (
        abs(flt(target.get('custom_ug_pricing_rate'))-flt(row.rate))<.000001 and
        abs(flt(target.get('custom_ug_pricing_surface'))-surface(row))<.000001)))


def install_fields():
    from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
    create_custom_fields({dt:[dict(fieldname='custom_ug_price_per_sqm',label='Prix au m²',fieldtype='Check',read_only=1,module='Material Reconfiguration'),
        dict(fieldname='custom_ug_pricing_rate',label='Prix de tarification',fieldtype='Currency',options='currency',read_only=1,module='Material Reconfiguration'),
        dict(fieldname='custom_ug_pricing_surface',label='Surface par pièce (m²)',fieldtype='Float',precision='6',read_only=1,module='Material Reconfiguration')]
        for dt in ('Quotation Item','Sales Order Item','Delivery Note Item','Sales Invoice Item')},update=True)
