"""Native ERPNext line discounts and proportional additional discount on net total."""
import math
import frappe
from frappe.utils import flt,cint
from .chantier_pricing import unit_rate,set_sales_fields,matches


def all_rows(doc):return list(doc.lines)+list(doc.get('commercial_extras',[]))


def gross_total(doc):return sum(flt(r.qty)*unit_rate(r) for r in all_rows(doc))


def percentage(doc,row):return flt(row.get('discount_percentage')) if doc.get('discount_mode')!='Montant' else 0


def normalize(doc):
    mode=doc.discount_mode or 'Pourcentage';value=flt(doc.discount_value)
    if mode not in ('Pourcentage','Montant') or not math.isfinite(value) or value<0 or (mode=='Pourcentage' and value>100):
        frappe.throw('Remise invalide : pourcentage entre 0 et 100, ou montant positif ou nul.')
    doc.discount_mode=mode
    for row in all_rows(doc):
        row.discount_percentage=0 if mode=='Montant' else (flt(row.discount_percentage) if cint(row.get('discount_override')) else value)
        if not math.isfinite(flt(row.discount_percentage)) or not 0<=flt(row.discount_percentage)<=100:frappe.throw('La remise de chaque ligne doit être comprise entre 0 et 100 %.')
    if mode=='Montant' and value>gross_total(doc)+.000001:frappe.throw('La remise globale ne peut pas dépasser le montant HT du chantier.')


def signature(doc):
    if not flt(doc.get('discount_value')) and not any(percentage(doc,r) or r.get('discount_override') for r in all_rows(doc)):return None
    return dict(mode=doc.get('discount_mode') or 'Pourcentage',value=flt(doc.discount_value),
        lines=[dict(id=r.line_id,percentage=percentage(doc,r),override=cint(r.get('discount_override'))) for r in all_rows(doc)])


def rate_matches(doc,macro,row):
    pct=percentage(doc,macro);expected=flt(unit_rate(macro)*(1-pct/100),row.precision('rate'))
    return matches(row,macro) and abs(flt(row.rate)-expected)<.000001 and abs(flt(row.discount_percentage)-pct)<.000001 and (not pct or abs(flt(row.price_list_rate)-unit_rate(macro))<.000001)


def apply_quote(quote,doc):
    by_id={r.line_id:r for r in all_rows(doc)}
    for row in quote.items:
        macro=by_id[row.custom_chantier_line];pct=percentage(doc,macro)
        set_sales_fields(row,macro)
        row.price_list_rate=unit_rate(macro);row.discount_percentage=pct;row.discount_amount=unit_rate(macro)*pct/100
        row.rate=flt(unit_rate(macro)*(1-pct/100),row.precision('rate'))
    ratio=flt(doc.discount_value)/gross_total(doc)*100 if doc.get('discount_mode')=='Montant' and gross_total(doc)>0 else 0
    quote.apply_discount_on='Net Total' if ratio else ''
    quote.additional_discount_percentage=ratio;quote.discount_amount=0


def validate_quote(quote,doc):
    expected=flt(doc.discount_value)/gross_total(doc)*100 if doc.get('discount_mode')=='Montant' and gross_total(doc)>0 else 0
    if abs(flt(quote.additional_discount_percentage)-expected)>.000001 or (expected and quote.apply_discount_on!='Net Total'):
        frappe.throw('Reprendre la remise globale du chantier approuvé.')
    if not expected and flt(quote.discount_amount):frappe.throw('Remise globale différente du chantier approuvé.')
