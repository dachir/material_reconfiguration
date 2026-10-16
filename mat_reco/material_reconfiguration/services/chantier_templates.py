"""Reusable snapshots of chantier section trees, without commercial lines."""
import frappe
from mat_reco.material_reconfiguration.services.chantier_service import chantier_doc
from mat_reco.material_reconfiguration.doctype.chantier_section_template.chantier_section_template import validate_rows


def snapshot(chantier):
    chantier_doc(chantier)
    frappe.has_permission('Chantier Section', 'read', throw=True)
    sections = frappe.get_list('Chantier Section', filters={'chantier': chantier},
        fields=['name', 'section_name', 'parent_chantier_section', 'is_group'],
        order_by='lft', limit_page_length=0)
    positions = {row.name: i for i, row in enumerate(sections, 1)}
    rows = []
    for row in sections:
        if row.parent_chantier_section and row.parent_chantier_section not in positions:
            frappe.throw('Impossible de copier une arborescence dont certaines sections sont inaccessibles.')
        rows.append(frappe._dict(section_name=row.section_name, is_group=row.is_group,
            parent_row=positions.get(row.parent_chantier_section, 0)))
    validate_rows(rows)
    return rows


@frappe.whitelist()
def save_template(chantier, template_name):
    doc = frappe.get_doc(dict(doctype='Chantier Section Template',
        template_name=template_name, sections=snapshot(chantier)))
    doc.insert()
    return doc.name


@frappe.whitelist()
def apply_sections(chantier, source_chantier=None, template=None):
    if bool(source_chantier) == bool(template):
        frappe.throw('Choisir un chantier source ou un modèle.')
    target = chantier_doc(chantier, 'write')
    frappe.db.get_value('Chantier', chantier, 'name', for_update=True)
    target.reload()
    if target.docstatus != 0:
        frappe.throw('Les sections peuvent être ajoutées uniquement à un chantier brouillon.')
    frappe.has_permission('Chantier Section', 'create', throw=True)
    if source_chantier == chantier:
        frappe.throw('Choisir un chantier source différent du chantier courant.')
    if template:
        doc = frappe.get_doc('Chantier Section Template', template)
        doc.check_permission('read')
        rows = doc.sections
        validate_rows(rows)
    else:
        rows = snapshot(source_chantier)
    return insert_sections(chantier, rows)


def insert_sections(chantier, rows):
    target = chantier_doc(chantier, 'write')
    frappe.db.get_value('Chantier', chantier, 'name', for_update=True)
    target.reload()
    if target.docstatus != 0:
        frappe.throw('Les sections peuvent être ajoutées uniquement à un chantier brouillon.')
    frappe.has_permission('Chantier Section', 'create', throw=True)
    validate_rows(rows)
    created = []
    for row in rows:
        section = frappe.get_doc(dict(doctype='Chantier Section', chantier=chantier,
            section_name=row.section_name, is_group=row.is_group,
            parent_chantier_section=created[int(row.parent_row)-1] if row.parent_row else None))
        section.insert()
        created.append(section.name)
    return dict(count=len(created))
