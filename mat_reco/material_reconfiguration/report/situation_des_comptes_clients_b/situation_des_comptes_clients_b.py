"""B-only operational customer ledger. Never query Sales Invoice/Payment Entry/GL."""
from collections import defaultdict
import frappe
from frappe.utils import flt,getdate
from mat_reco.material_reconfiguration.services import special_b as b


def execute(filters=None):
    b.access();f=frappe._dict(filters or {})
    if not f.from_date or not f.to_date:frappe.throw('Renseigner les dates de début et de fin.')
    if getdate(f.from_date)>getdate(f.to_date):frappe.throw('La date de début doit précéder la date de fin.')
    if f.sales_order:b.stock.get_order(f.sales_order)
    base={'docstatus':1,'posting_date':['<=',f.to_date]}
    for field in ('company','customer','currency'):
        if f.get(field):base[field]=f[field]
    groups=defaultdict(list)
    for dt,sign in ((b.OPENING,1),(b.DELIVERY,1),(b.PAYMENT,-1)):
        for name in frappe.get_list(dt,filters=base,pluck='name',limit_page_length=0):
            doc=frappe.get_doc(dt,name)
            if dt==b.PAYMENT:amount=b.payment_share(doc,f.sales_order)
            elif f.sales_order and doc.sales_order!=f.sales_order:continue
            else:amount=flt(doc.amount if dt==b.OPENING else doc.net_total)
            if not amount and dt!=b.DELIVERY:continue
            key=(doc.company,doc.customer,doc.currency)
            groups[key].append(dict(posting_date=doc.posting_date,reference_doctype=dt,reference_name=doc.name,
                sales_order=doc.sales_order,description='Reprise du solde initial' if dt==b.OPENING else 'BL validé' if dt==b.DELIVERY else 'Règlement reçu',
                debit=max(0,sign*amount),credit=max(0,-sign*amount),delta=sign*amount,creation=doc.creation))
    # Accounts with no movement in the selected period are still shown, including zero balances.
    orders={'custom_ug_order_type':'B','docstatus':1}
    for field in ('company','customer','currency'):
        if f.get(field):orders[field]=f[field]
    if f.sales_order:orders['name']=f.sales_order
    for order in frappe.get_list('Sales Order',filters=orders,fields=['company','customer','currency'],limit_page_length=0):
        groups.setdefault((order.company,order.customer,order.currency),[])
    data=[]
    for (company,customer,currency),events in sorted(groups.items()):
        common=dict(company=company,customer=customer,currency=currency)
        opening=sum(e['delta'] for e in events if getdate(e['posting_date'])<getdate(f.from_date))
        # A beginning-of-day imported opening on from_date belongs to the initial balance.
        opening+=sum(e['delta'] for e in events if e['reference_doctype']==b.OPENING and getdate(e['posting_date'])==getdate(f.from_date))
        balance=b.money(opening,currency)
        data.append(dict(common,posting_date=f.from_date,description='Solde initial',balance=balance,debit=0,credit=0))
        for event in sorted(events,key=lambda e:(getdate(e['posting_date']),e['creation'],e['reference_name'])):
            if getdate(event['posting_date'])<getdate(f.from_date) or (event['reference_doctype']==b.OPENING and getdate(event['posting_date'])==getdate(f.from_date)):continue
            balance=b.money(balance+event['delta'],currency)
            data.append(dict(common,**{k:v for k,v in event.items() if k not in ('delta','creation')},balance=balance))
        data.append(dict(common,posting_date=f.to_date,description='Solde final',balance=balance,debit=0,credit=0))
    columns=[dict(fieldname='company',label='Société',fieldtype='Link',options='Company',width=160),
        dict(fieldname='customer',label='Client',fieldtype='Link',options='Customer',width=170),
        dict(fieldname='currency',label='Devise',fieldtype='Link',options='Currency',width=75),
        dict(fieldname='posting_date',label='Date',fieldtype='Date',width=100),
        dict(fieldname='description',label='Opération',fieldtype='Data',width=170),
        dict(fieldname='reference_doctype',label='Document',fieldtype='Data',hidden=1),
        dict(fieldname='reference_name',label='Référence',fieldtype='Dynamic Link',options='reference_doctype',width=200),
        dict(fieldname='sales_order',label='Commande B',fieldtype='Link',options='Sales Order',width=190)]
    columns.extend(dict(fieldname=k,label=label,fieldtype='Currency',options='currency',width=140) for k,label in [('debit','BL HT / Débit'),('credit','Règlements / Crédit'),('balance','Solde progressif HT')])
    return columns,data
