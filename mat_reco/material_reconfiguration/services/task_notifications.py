"""Role-based Desk notifications paired with personal, document-linked tasks."""
import hashlib
import json

import frappe
from frappe.utils import escape_html

SETTINGS = 'Mat Reco Settings'
STAGES = {
    'chantier': ('chantier_notification_role', 'Validation chantier', 'chantier'),
    'technical': ('technical_notification_role', 'Fiche technique', 'technical-study'),
    'workshop': ('workshop_notification_role', 'Atelier', 'workshop-cockpit'),
}


def recipients(stage, doc):
    role = frappe.db.get_single_value(SETTINGS, STAGES[stage][0])
    if not role:
        return []
    users = frappe.db.sql('''SELECT DISTINCT u.name FROM `tabUser` u
        JOIN `tabHas Role` r ON r.parent=u.name AND r.parenttype='User'
        WHERE r.role=%s AND u.enabled=1 AND u.user_type='System User'
        AND u.name!=%s''', (role, 'Guest'), pluck=True)
    return [u for u in users if frappe.has_permission(doc=doc, user=u,
        ptype='submit' if stage == 'chantier' else 'read')]


def send_tasks(doc, stage, event_key):
    # Serialize task creation per source document, including concurrent requests.
    frappe.db.get_value(doc.doctype, doc.name, 'name', for_update=True)
    label, route = STAGES[stage][1:]
    link = '/app/' + route + ('/' + doc.name if stage in ('technical', 'chantier') else '')
    prefix = f'[Univers Glass — {label}]'
    description = f'{prefix} {escape_html(doc.name)} — <a href="{escape_html(link)}">Ouvrir {label.lower()}</a>'
    if stage == 'workshop':
        order_link = '/app/sales-order/' + doc.name
        description += f' — <a href="{escape_html(order_link)}">Voir la commande</a>'
        if doc.docstatus == 0:
            description += ' — Commande en brouillon : planification atelier après validation.'
            link = order_link
    users = recipients(stage, doc)
    for user in users:
        log_name = hashlib.sha256(f'ug:{stage}:{doc.name}:{event_key}:{user}'.encode()).hexdigest()[:32]
        if frappe.db.exists('Notification Log', log_name):
            continue
        todo = frappe.db.get_value('ToDo', {
            'reference_type': doc.doctype, 'reference_name': doc.name,
            'allocated_to': user, 'status': 'Open', 'description': ['like', prefix + '%'],
        }, 'name')
        if not todo:
            todo = frappe.get_doc(dict(doctype='ToDo', allocated_to=user,
                assigned_by=frappe.session.user, reference_type=doc.doctype,
                reference_name=doc.name, description=description, status='Open', priority='Medium')).insert(ignore_permissions=True).name
        notification = frappe.get_doc(dict(doctype='Notification Log', type='Alert',
            subject=f'{label} à traiter : {doc.name}', email_content=description,
            for_user=user, from_user=frappe.session.user,
            document_type=doc.doctype, document_name=doc.name))
        if notification.meta.has_field('source_doctype') and notification.meta.has_field('source_name'):
            notification.source_doctype = 'ToDo'
            notification.source_name = todo
        if notification.meta.has_field('link'):
            notification.link = link
        notification.insert(ignore_permissions=True, set_name=log_name)
    return users


@frappe.whitelist(methods=['POST'])
def handoff_study(chantier, request_key, study=None):
    if not request_key or len(request_key) > 100:
        frappe.throw('Clé de transmission requise (100 caractères maximum).')
    dossier = frappe.get_doc('Chantier', chantier)
    dossier.check_permission('read')
    if not study:
        from .technical_study_service import prepare_study
        study = prepare_study(chantier)
    doc = frappe.get_doc('Chantier Technical Study', study)
    doc.check_permission('read')
    if doc.chantier != chantier:
        frappe.throw('La fiche technique appartient à un autre chantier.')
    if doc.docstatus == 0:
        users = send_tasks(doc, 'technical', request_key)
        if not users:
            frappe.msgprint('Aucun destinataire actif autorisé : vérifier le rôle des fiches techniques dans Mat Reco Settings.', alert=True)
    return doc.name


def order_created(doc, method=None):
    if any(frappe.get_cached_value('Item', r.item_code, 'custom_item_types') in ('PRIMAIRE', 'DECOUPE', 'OUVRAGE') for r in doc.get('items', [])):
        send_tasks(doc, 'workshop', 'order-created')


def close_tasks(doc, stage):
    prefix = f'[Univers Glass — {STAGES[stage][1]}]'
    for name in frappe.get_all('ToDo', filters={'reference_type': doc.doctype,
            'reference_name': doc.name, 'status': 'Open', 'description': ['like', prefix + '%']}, pluck='name'):
        todo = frappe.get_doc('ToDo', name)
        todo.status = 'Closed' if doc.docstatus == 1 else 'Cancelled'
        todo.save(ignore_permissions=True)


def study_finished(doc, method=None):
    close_tasks(doc, 'technical')
    dossier = frappe.get_doc('Chantier', doc.chantier)
    if doc.docstatus == 1 and dossier.docstatus == 0 and dossier.status not in ('Cancelled', 'On Hold'):
        send_tasks(dossier, 'chantier', 'study-validated:' + doc.name)
    elif doc.docstatus == 2:
        close_tasks(dossier, 'chantier')


def chantier_finished(doc, method=None):
    close_tasks(doc, 'chantier')


def order_cancelled(doc, method=None):
    close_tasks(doc, 'workshop')


def install_workspace_tasks():
    if not frappe.db.exists('Workspace', 'Univers Glass'):
        return
    doc = frappe.get_doc('Workspace', 'Univers Glass')
    existing_roles = {r.role for r in doc.roles}
    for field, _, _ in STAGES.values():
        role = frappe.db.get_single_value(SETTINGS, field)
        if role and role not in existing_roles:
            doc.append('roles', dict(role=role))
            existing_roles.add(role)
    label = 'Mes tâches Univers Glass'
    filters = '[["ToDo","allocated_to","=",frappe.session.user],["ToDo","status","=","Open"],["ToDo","reference_type","in",["Chantier","Chantier Technical Study","Sales Order"]],["ToDo","description","like","[Univers Glass — %"]]'
    row = next((r for r in doc.quick_lists if r.label == label), None)
    if row:
        row.quick_list_filter = filters
    else:
        doc.append('quick_lists', dict(document_type='ToDo', label=label, quick_list_filter=filters))
    content = json.loads(doc.content or '[]')
    if not any(r.get('data', {}).get('quick_list_name') == label for r in content):
        content.append(dict(id='ug-personal-tasks', type='quick_list', data=dict(quick_list_name=label, col=12)))
    doc.content = json.dumps(content, ensure_ascii=False)
    doc.save(ignore_permissions=True)


def install_task_notifications():
    """Install recipient roles with document consultation rights only."""
    from frappe.permissions import setup_custom_perms
    role_fields = [(STAGES['chantier'][0], 'UG CHANTIER'),
                   (STAGES['technical'][0], 'UG FICHE TECHNIQUE'),
                   (STAGES['workshop'][0], 'UG ATELIER')]
    for field, role in role_fields:
        if not frappe.db.exists('Role', role):
            frappe.get_doc(dict(doctype='Role', role_name=role, desk_access=1)).insert(ignore_permissions=True)
        if not frappe.db.get_single_value(SETTINGS, field):
            frappe.db.set_single_value(SETTINGS, field, role)
    grants = {
        'UG CHANTIER': ['Chantier','Chantier Section','Chantier Technical Study','Company','Customer','Item','Item Group','UOM','Sales Taxes and Charges Template'],
        'UG FICHE TECHNIQUE': ['Chantier','Chantier Section','Chantier Technical Study','Item','Company','Item Group','UOM','Warehouse'],
        'UG ATELIER': ['Sales Order','Chantier','Chantier Section','Chantier Technical Study','Item','Company','Item Group','UOM','Warehouse','Serial No','Stock Entry','Stock Entry Type','Stock Reservation Entry','Material Cutting Plan','Workshop Operation','Workshop Refabrication'],
    }
    for role, doctypes in grants.items():
        for dt in doctypes:
            if frappe.db.exists('DocType',dt) and not frappe.db.exists('Custom DocPerm',{'parent':dt,'role':role,'permlevel':0,'if_owner':0}):
                # Preserve existing permission rows, including legacy metadata;
                # the new grant is limited to consultation at permission level 0.
                setup_custom_perms(dt)
                frappe.get_doc(dict(doctype='Custom DocPerm',parent=dt,role=role,
                    permlevel=0,if_owner=0,read=1)).insert(ignore_permissions=True)
                frappe.clear_cache(doctype=dt)
    install_workspace_tasks()
