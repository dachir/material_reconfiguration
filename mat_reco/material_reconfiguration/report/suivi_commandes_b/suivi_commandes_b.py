"""Order B production board; no accounting or stock write occurs here."""
import frappe
from frappe.utils import flt
from mat_reco.material_reconfiguration.services.order_b import can_access


def execute(filters=None):
    if not can_access():frappe.throw('Le rôle UG COMMANDES B est requis.',frappe.PermissionError)
    filters=frappe._dict(filters or {})
    conditions={'custom_ug_order_type':'B'}
    if filters.company:conditions['company']=filters.company
    if filters.customer:conditions['customer']=filters.customer
    if filters.from_date and filters.to_date:conditions['transaction_date']=['between',[filters.from_date,filters.to_date]]
    elif filters.from_date:conditions['transaction_date']=['>=',filters.from_date]
    elif filters.to_date:conditions['transaction_date']=['<=',filters.to_date]
    rows=frappe.get_list('Sales Order',filters=conditions,fields=['name','transaction_date','company','customer','customer_name',
        'docstatus','custom_chantier','custom_technical_study','grand_total','currency','custom_ug_b_export_file','custom_ug_b_sage_reference'],order_by='transaction_date desc, creation desc',limit_page_length=0)
    orders=[frappe.get_doc('Sales Order',r.name) for r in rows]
    from mat_reco.material_reconfiguration.services.workshop_service import _receipts
    accepted,_,_,_=_receipts(orders) if orders else ({},{},{},{})
    from mat_reco.material_reconfiguration.services.order_b_stock import issued_quantities,physical_rows
    result=[]
    for row,order in zip(rows,orders):
        study=frappe.db.get_value('Chantier Technical Study',row.custom_technical_study,['docstatus','name'],as_dict=True) if row.custom_technical_study else None
        manufactured=[r for r in order.items if frappe.get_cached_value('Item',r.item_code,'custom_item_types') in ('OUVRAGE','DECOUPE')]
        row.required_qty=sum(flt(r.qty) for r in manufactured)
        row.produced_qty=sum(min(flt(r.qty),flt(accepted.get(r.name))) for r in manufactured)
        row.remaining_qty=max(0,row.required_qty-row.produced_qty)
        physical=physical_rows(order);issued=issued_quantities(order)
        row.issued_qty=sum(issued.values())
        row.to_issue_qty=sum(max(0,flt(r.stock_qty or r.qty*r.conversion_factor)-issued.get(r.name,0)) for r in physical)
        if row.docstatus==1:
            from mat_reco.material_reconfiguration.services.special_b import get_order_summary
            followup=get_order_summary(row.name)
            row.bl_count=sum(b.docstatus==1 for b in followup['deliveries'])
            row.bl_amount=followup['delivery_amount'];row.received=followup['received'];row.order_balance=followup['balance']
            row.bl_balance=sum(flt(b.balance) for b in followup['deliveries'] if b.docstatus==1)
        row.stage=('Annulée' if row.docstatus==2 else 'Brouillon' if row.docstatus==0 else
            'Fiche technique à préparer' if not study or study.docstatus!=1 else
            'Import Sage confirmé' if row.custom_ug_b_sage_reference else 'Exportée vers Sage' if row.custom_ug_b_export_file else
            'À exporter vers Sage' if not row.to_issue_qty else 'Sortie partielle' if row.issued_qty else
            'À sortir' if not manufactured else
            'À sortir' if row.remaining_qty==0 else 'Production partielle' if row.produced_qty else 'À produire')
        if not filters.stage or row.stage==filters.stage:result.append(row)
    columns=[dict(fieldname='name',label='Commande B',fieldtype='Link',options='Sales Order',width=190),
        dict(fieldname='transaction_date',label='Date',fieldtype='Date',width=100),
        dict(fieldname='customer',label='Client',fieldtype='Link',options='Customer',width=180),
        dict(fieldname='custom_chantier',label='Chantier',fieldtype='Link',options='Chantier',width=170),
        dict(fieldname='custom_technical_study',label='Fiche technique',fieldtype='Link',options='Chantier Technical Study',width=140),
        dict(fieldname='stage',label='Étape',fieldtype='Data',width=190)]
    columns.extend(dict(fieldname=field,label=label,fieldtype='Float',width=110) for field,label in
        [('required_qty','À produire'),('produced_qty','Produites'),('remaining_qty','Restantes'),('issued_qty','Sorties'),('to_issue_qty','À sortir')])
    columns.extend([dict(fieldname='grand_total',label='Montant commande',fieldtype='Currency',options='currency',width=140),
        dict(fieldname='custom_ug_b_sage_reference',label='Référence Sage',fieldtype='Data',width=150),
        dict(fieldname='currency',label='Devise',fieldtype='Link',options='Currency',hidden=1)])
    columns.append(dict(fieldname='bl_count',label='BL validés',fieldtype='Int',width=100))
    columns.extend(dict(fieldname=k,label=label,fieldtype='Currency',options='currency',width=140) for k,label in
        [('bl_amount','Montants BL'),('received','Règlements B'),('bl_balance','Solde des BL'),('order_balance','Solde commande B')])
    return columns,result
