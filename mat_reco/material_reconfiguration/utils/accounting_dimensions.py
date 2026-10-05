from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint

from erpnext.accounts.doctype.accounting_dimension.accounting_dimension import (
    get_accounting_dimensions,
    get_checks_for_pl_and_bs_accounts,
)


def get_active_accounting_dimension_fields() -> list[str]:
    """Return active custom Accounting Dimension fieldnames from ERPNext."""
    return list(get_accounting_dimensions() or [])


def get_company_dimension_config(company: str) -> dict[str, frappe._dict]:
    """Return Accounting Dimension configuration keyed by fieldname for one company.

    The returned rows include the company default and the mandatory flags used by
    ERPNext for Profit & Loss and Balance Sheet accounts.
    """
    config: dict[str, frappe._dict] = {}

    for row in get_checks_for_pl_and_bs_accounts() or []:
        if row.get("company") != company:
            continue
        fieldname = (row.get("fieldname") or "").strip()
        if not fieldname:
            continue
        config[fieldname] = frappe._dict(row)

    return config


def resolve_accounting_dimensions(
    source_doc,
    company: str,
    *,
    fallback_docs: list | tuple | None = None,
    validate_mandatory: bool = True,
) -> dict[str, str]:
    """Resolve active Accounting Dimension values for a transaction.

    Resolution order for each dimension:
    1. value on ``source_doc``;
    2. value on any ``fallback_docs`` in the supplied order;
    3. company default configured on Accounting Dimension.

    When a dimension is mandatory for either Balance Sheet or P&L accounts and no
    value can be resolved, a clear validation error is raised before ERPNext tries
    to create the GL Entry.
    """
    if not company:
        return {}

    fallback_docs = list(fallback_docs or [])
    config = get_company_dimension_config(company)
    values: dict[str, str] = {}
    missing: list[str] = []

    for fieldname in get_active_accounting_dimension_fields():
        value = _get_value(source_doc, fieldname)

        if not value:
            for doc in fallback_docs:
                value = _get_value(doc, fieldname)
                if value:
                    break

        dim_config = config.get(fieldname) or frappe._dict()
        if not value:
            value = dim_config.get("default_dimension")

        if value:
            values[fieldname] = value
            continue

        is_mandatory = cint(dim_config.get("mandatory_for_bs")) or cint(
            dim_config.get("mandatory_for_pl")
        )
        if validate_mandatory and is_mandatory:
            label = dim_config.get("label") or fieldname.replace("_", " ").title()
            missing.append(label)

    if missing:
        frappe.throw(
            _(
                "The following mandatory Accounting Dimension(s) have no value for company {0}: {1}. "
                "Set them on the source document or configure a company default in Accounting Dimension."
            ).format(frappe.bold(company), ", ".join(frappe.bold(x) for x in missing))
        )

    return values


def apply_accounting_dimensions(
    target_doc,
    values: dict[str, str],
    *,
    apply_to_children: bool = False,
    child_table_field: str = "items",
    overwrite: bool = False,
) -> None:
    """Apply resolved dimensions to a document and, optionally, its child rows.

    Fields are only assigned when they actually exist in the target metadata.
    Existing values are preserved unless ``overwrite=True``.
    """
    if not target_doc or not values:
        return

    _apply_values(target_doc, values, overwrite=overwrite)

    if not apply_to_children:
        return

    for row in target_doc.get(child_table_field) or []:
        _apply_values(row, values, overwrite=overwrite)


def resolve_and_apply_stock_entry_dimensions(
    stock_entry,
    *,
    source_doc=None,
    fallback_docs: list | tuple | None = None,
    validate_mandatory: bool = True,
    overwrite: bool = False,
) -> dict[str, str]:
    """Resolve dimensions and apply them to Stock Entry + Stock Entry Detail rows."""
    if not stock_entry or not stock_entry.get("company"):
        return {}

    source_doc = source_doc or stock_entry
    fallbacks = list(fallback_docs or [])
    if source_doc is not stock_entry:
        fallbacks.insert(0, stock_entry)

    values = resolve_accounting_dimensions(
        source_doc,
        stock_entry.company,
        fallback_docs=fallbacks,
        validate_mandatory=validate_mandatory,
    )
    apply_accounting_dimensions(
        stock_entry,
        values,
        apply_to_children=True,
        child_table_field="items",
        overwrite=overwrite,
    )
    return values


def _get_value(doc, fieldname: str):
    if not doc:
        return None

    try:
        if hasattr(doc, "meta") and doc.meta.has_field(fieldname):
            return doc.get(fieldname)
    except Exception:
        pass

    if isinstance(doc, dict):
        return doc.get(fieldname)

    try:
        return doc.get(fieldname)
    except Exception:
        return getattr(doc, fieldname, None)


def _apply_values(doc, values: dict[str, str], *, overwrite: bool) -> None:
    meta = getattr(doc, "meta", None)

    for fieldname, value in values.items():
        if not value:
            continue

        if meta is not None and not meta.has_field(fieldname):
            continue

        current_value = doc.get(fieldname) if hasattr(doc, "get") else getattr(doc, fieldname, None)
        if current_value and not overwrite:
            continue

        doc.set(fieldname, value) if hasattr(doc, "set") else setattr(doc, fieldname, value)
