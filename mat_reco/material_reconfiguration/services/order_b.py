"""Access and downstream document boundaries for circuit B."""
import frappe

ROLE='UG COMMANDES B'


def can_access(user=None):
    user=user or frappe.session.user
    return user=='Administrator' or ROLE in frappe.get_roles(user)


def query_conditions(user=None):
    if can_access(user):return ''
    return "COALESCE(`tabSales Order`.custom_ug_order_type, 'A') != 'B'"


def has_permission(doc,user=None,ptype=None):
    if doc.get('custom_ug_order_type')=='B' and not can_access(user):return False
    return None


def study_query_conditions(user=None):
    if can_access(user):return ''
    return "NOT EXISTS (SELECT 1 FROM `tabSales Order` so WHERE so.name=`tabChantier Technical Study`.sales_order AND so.custom_ug_order_type='B')"


def study_has_permission(doc,user=None,ptype=None):
    if doc.get('sales_order') and frappe.db.get_value('Sales Order',doc.sales_order,'custom_ug_order_type')=='B' and not can_access(user):return False
    return None


def validate_order(doc,method=None):
    if doc.get('custom_ug_order_type')=='B' and not can_access():
        frappe.throw('Le rôle UG COMMANDES B est requis pour traiter une commande B.',frappe.PermissionError)


def validate_downstream(doc,method=None):
    """Enforce at save and submit, including API/import and mixed-order documents."""
    orders={r.get('sales_order') or r.get('against_sales_order') for r in doc.get('items',[])}-{None,''}
    if doc.doctype=='Sales Invoice':
        deliveries={r.get('delivery_note') for r in doc.items}-{None,''}
        if deliveries:
            orders.update(frappe.get_all('Delivery Note Item',filters={'parent':['in',list(deliveries)]},pluck='against_sales_order'))
    if orders and frappe.db.exists('Sales Order',{'name':['in',list(orders)],'custom_ug_order_type':'B'}):
        frappe.throw('Circuit B : utiliser la sortie directe et le bon de la commande. Livraison et facture ERPNext interdites.')


def install():
    if not frappe.db.exists('Role',ROLE):frappe.get_doc(dict(doctype='Role',role_name=ROLE,desk_access=1)).insert(ignore_permissions=True)
    frappe.reload_doc('material_reconfiguration','report','suivi_commandes_b')
    if frappe.db.exists('Workspace','Univers Glass'):
        workspace=frappe.get_doc('Workspace','Univers Glass')
        if not any(row.label=='Suivi commandes B' for row in workspace.shortcuts):
            import json
            workspace.append('shortcuts',dict(label='Suivi commandes B',type='Report',link_to='Suivi commandes B',color='Orange'))
            content=json.loads(workspace.content or '[]')
            content.append(dict(id='ug-orders-b',type='shortcut',data=dict(shortcut_name='Suivi commandes B',col=4)))
            workspace.content=json.dumps(content,ensure_ascii=False)
            workspace.save(ignore_permissions=True)


def validate_customer_entries(doc,method=None):
    if doc.docstatus==2:return
    references=doc.get('references',[]) if doc.doctype=='Payment Entry' else doc.get('accounts',[])
    orders={r.get('reference_name') for r in references
        if (r.get('reference_doctype') or r.get('reference_type'))=='Sales Order'}-{None,''}
    if orders and frappe.db.exists('Sales Order',{'name':['in',list(orders)],'custom_ug_order_type':'B'}):
        frappe.throw('Circuit B : les écritures clients et avances sur cette commande doivent être traitées dans Sage 100.')
