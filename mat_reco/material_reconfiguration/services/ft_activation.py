"""Explicit technical handoff; commercial changes invalidate it until a study exists."""
import json
import uuid
from contextlib import contextmanager

import frappe

FIELDS = ('designation','company','customer','responsible','expected_start_date','expected_end_date',
          'description','work_types','currency','selling_price_list','taxes_and_charges','terms','lines','commercial_extras')
SYSTEM = {'name','owner','creation','modified','modified_by','docstatus','parent','parenttype','parentfield','idx','doctype'}


def snapshot(doc):
    def clean(value):
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, list):
            return [clean(v.as_dict() if hasattr(v, 'as_dict') else v) for v in value]
        if isinstance(value, dict):
            return {k: clean(v) for k,v in value.items() if k not in SYSTEM and not k.startswith('_')}
        return value or None
    return json.dumps({k:clean(doc.get(k)) for k in FIELDS}, sort_keys=True, default=str)


def has_study(chantier):
    return bool(frappe.db.exists('Chantier Technical Study', {'chantier':chantier}))


@contextmanager
def activation_change():
    previous = frappe.flags.ug_ft_update
    frappe.flags.ug_ft_update = True
    try:
        yield
    finally:
        frappe.flags.ug_ft_update = previous


def validate_activation(doc, method=None):
    old = doc.get_doc_before_save()
    if not old:
        if doc.get('ft_active') or doc.get('ft_activation_key'):
            frappe.throw('Enregistrer le chantier puis utiliser « Activer FT ».')
        return
    frappe.db.get_value('Chantier',doc.name,'name',for_update=True)
    if not frappe.flags.ug_ft_update and any(doc.get(k)!=old.get(k) for k in ('ft_active','ft_activation_key')):
        frappe.throw('Utiliser le bouton « Activer FT » pour modifier cette activation.')
    if snapshot(doc) != snapshot(old):
        from .chantier_work_types import is_v2, technical_source_hash
        loose=is_v2(doc)
        if not loose and has_study(doc.name):
            frappe.throw('Supprimer la fiche technique avant de modifier le chantier.')
        if not has_study(doc.name) or (loose and technical_source_hash(doc)!=technical_source_hash(old)):
            doc.ft_active = 0
            doc.ft_activation_key = None


def cancel_generated(doc):
    from .task_notifications import close_tasks
    # The activation tasks can reference the dossier, or the study once prepared.
    close_tasks(frappe._dict(doctype=doc.doctype,name=doc.name,docstatus=0),'technical')
    for name in frappe.get_all('Notification Log', filters={
            'document_type':doc.doctype,'document_name':doc.name,
            'subject':['like','Fiche technique à traiter :%']}, pluck='name'):
        frappe.delete_doc('Notification Log', name, ignore_permissions=True)


def after_chantier_update(doc, method=None):
    old = doc.get_doc_before_save()
    if old and old.get('ft_active') and not doc.get('ft_active'):
        cancel_generated(doc)
        from .chantier_work_types import is_v2
        if is_v2(doc):
            for name in frappe.get_all('Chantier Technical Study',filters={'chantier':doc.name},pluck='name'):
                cancel_generated(frappe._dict(doctype='Chantier Technical Study',name=name))


@frappe.whitelist(methods=['POST'])
def set_ft_active(chantier, active, modified):
    from frappe.utils import cint
    from .task_notifications import send_tasks
    doc=frappe.get_doc('Chantier',chantier,for_update=True)
    doc.check_permission('write')
    from .chantier_work_types import is_v2
    loose=is_v2(doc)
    if (doc.docstatus!=0 and not loose) or doc.docstatus==2 or doc.status=='Cancelled' or str(doc.modified)!=str(modified):
        frappe.throw('Le chantier a changé ou n’est plus modifiable. Actualiser.')
    active=cint(active)
    if active not in (0,1):
        frappe.throw('Activation invalide.')
    if not loose and not active and has_study(doc.name):
        frappe.throw('Supprimer la fiche technique avant de désactiver FT.')
    if bool(doc.get('ft_active')) == bool(active):
        return doc.as_dict()
    if active and loose and not any(r.get('line_kind')!='Vente directe' for r in doc.lines):
        frappe.throw('Aucun ouvrage ou découpe à préparer : les ventes directes ne nécessitent pas de fiche technique.')
    if active and not doc.lines:
        frappe.throw('Ajouter au moins un ouvrage avant d’activer FT.')
    with activation_change():
        doc.ft_active=active
        doc.ft_activation_key=uuid.uuid4().hex if active else None
        doc.save()
    if active:
        study=frappe.db.get_value('Chantier Technical Study',{'chantier':chantier,'docstatus':0 if loose else ['<',2]},'name')
        target=frappe.get_doc('Chantier Technical Study',study) if study else doc
        send_tasks(target,'technical','ft-activation:'+doc.ft_activation_key)
    return doc.as_dict()


def require_activation(doc):
    if not doc.get('ft_active'):
        frappe.throw('Activer FT sur le chantier avant de préparer la fiche technique.')


def study_created(doc, method=None):
    from frappe.utils import escape_html
    old_link='/app/chantiers/'+doc.chantier
    new_link='/app/technical-study/'+doc.name
    for name in frappe.get_all('ToDo',filters={'reference_type':'Chantier','reference_name':doc.chantier,
            'status':'Open','description':['like','[Univers Glass — Fiche technique]%']},pluck='name'):
        todo=frappe.get_doc('ToDo',name)
        todo.reference_type=doc.doctype;todo.reference_name=doc.name
        todo.description=todo.description.replace(escape_html(old_link),escape_html(new_link))
        todo.save(ignore_permissions=True)
    for name in frappe.get_all('Notification Log',filters={'document_type':'Chantier','document_name':doc.chantier,
            'subject':['like','Fiche technique à traiter :%']},pluck='name'):
        notification=frappe.get_doc('Notification Log',name)
        notification.document_type=doc.doctype;notification.document_name=doc.name
        notification.email_content=(notification.email_content or '').replace(escape_html(old_link),escape_html(new_link))
        if notification.meta.has_field('link'):notification.link=new_link
        notification.save(ignore_permissions=True)


def study_deleted(doc, method=None):
    cancel_generated(doc)
    if not has_study(doc.chantier):
        dossier=frappe.get_doc('Chantier',doc.chantier,for_update=True)
        cancel_generated(dossier)
        frappe.db.set_value('Chantier',doc.chantier,{'ft_active':0,'ft_activation_key':None})


def guard_section(doc, deleting=False):
    old=doc.get_doc_before_save() if not deleting else None
    if not deleting and old and all(old.get(k)==doc.get(k) for k in ('section_name','parent_chantier_section','is_group')):
        return
    parent=frappe.get_doc('Chantier',doc.chantier,for_update=True)
    from .chantier_work_types import is_v2
    if not is_v2(parent) and has_study(parent.name):
        frappe.throw('Supprimer la fiche technique avant de modifier les sections du chantier.')
    if parent.get('ft_active') and not has_study(parent.name):
        with activation_change():
            parent.ft_active=0;parent.ft_activation_key=None;parent.save(ignore_permissions=True)


def guard_section_delete(doc, method=None):
    guard_section(doc, deleting=True)


def study_before_delete(doc, method=None):
    cancel_generated(doc)
