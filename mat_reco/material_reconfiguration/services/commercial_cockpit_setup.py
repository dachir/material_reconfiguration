"""Install the commercial Desk page without granting any document permissions."""

import json

import frappe

PAGE = "commercial-cockpit"
LABEL = "Cockpit commercial"
SPECIAL_DOCTYPES = ("Bordereau Special", "Reglement Special")


def readable_roles():
    """Include explicit custom module grants as well as the standard roles.

    Page permissions are role based. Actual document access is checked separately
    on every dashboard request, including company, owner and user permissions.
    """
    roles = {"System Manager"}
    for doctype in SPECIAL_DOCTYPES:
        if frappe.db.exists("DocType", doctype):
            roles.update(
                row.role for row in frappe.get_meta(doctype).permissions
                if row.read and not row.permlevel
            )
    return sorted(roles)


def install():
    """Idempotent; also usable after a new special-module role is configured."""
    frappe.reload_doc("material_reconfiguration", "doctype", "commercial_operation")
    frappe.reload_doc("material_reconfiguration", "page", "commercial_cockpit")
    page = frappe.get_doc("Page", PAGE)
    roles = readable_roles()
    if sorted(row.role for row in page.roles) != roles:
        page.set("roles", [{"role": role} for role in roles])
        page.flags.do_not_update_json = True
        page.save(ignore_permissions=True)

    if not frappe.db.exists("Workspace", "Univers Glass"):
        return
    workspace = frappe.get_doc("Workspace", "Univers Glass")
    changed = False
    if not any(row.link_to == PAGE and row.type == "Page" for row in workspace.shortcuts):
        workspace.append("shortcuts", dict(label=LABEL, type="Page", link_to=PAGE, color="Cyan"))
        changed = True
    content = json.loads(workspace.content or "[]")
    if not any(row.get("id") == "ug-commercial-cockpit" for row in content):
        content.insert(2, dict(id="ug-commercial-cockpit", type="shortcut", data=dict(shortcut_name=LABEL, col=4)))
        workspace.content = json.dumps(content, ensure_ascii=False)
        changed = True
    existing_roles = {row.role for row in workspace.roles}
    for role in roles:
        if role not in existing_roles:
            workspace.append("roles", {"role": role})
            changed = True
    if changed:
        workspace.save(ignore_permissions=True)
    # Workspace automatically hides shortcuts to pages outside the user's roles.
    frappe.cache.delete_keys("user:*:has_role:Page")
    frappe.cache.delete_value("domain_restricted_pages")
