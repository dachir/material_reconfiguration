"""Frappe Document class for Material Reconfiguration.

This document orchestrates the cutting of raw material sheets into
finished goods and by-product chutes.  When the document is saved,
it proposes a cutting plan based on the requested finished good
dimensions and quantity.  It leverages the cutting engine from
``mat_reco.mat_reco.engines`` and the selection logic from
``mat_reco.mat_reco.engines.selection_engine`` to choose the best
available sheet or chute to satisfy the demand.  The resulting
detail lines are appended to the document automatically.

Note: This implementation focuses on the planning stage and does not
perform any stock ledger updates.  The actual consumption of raw
material and creation of finished goods must be handled by a Stock
Entry of type ``Repack`` or ``Manufacture`` during submission.
"""

from __future__ import absolute_import, unicode_literals

import frappe
from frappe import _
from frappe.utils import flt
from frappe.model.document import Document

# Import get_reco_settings from the application-specific utils path.  Though
# not used directly in this module, it may be referenced by other
# hooks or future enhancements.
from mat_reco.material_reconfiguration.utils.settings import get_reco_settings
# Import engine and service functions from the public-facing ``material_reconfiguration``
# package.  These modules are re-exported from ``mat_reco/material_reconfiguration``
# to provide a stable API surface that matches the DocType's namespace.
from mat_reco.material_reconfiguration.engines.selection_engine import pick_best_candidate
from mat_reco.material_reconfiguration.services.serial_service import get_available_serials,generate_chute_serials
from mat_reco.material_reconfiguration.services.mr_service import build_mr_lines


class MaterialReconfiguration(Document):
    """Custom logic for the Material Reconfiguration DocType.

    When saving a draft document this class will propose a cutting plan
    based on the finished good dimensions and requested quantity.  It
    fetches available sheets or chutes from the Serial No table, chooses
    the best candidate using the selection engine and then builds the
    detail lines accordingly.  The plan only reserves material on paper;
    the actual stock movement should occur via a Stock Entry upon
    submission.
    """

    def before_save(self):  # noqa: D401
        """Propose cutting plan and populate detail lines before saving.

        This hook runs whenever the document is saved (including submit)
        and ensures that the ``detail`` table reflects the current
        requirements.  It only acts when the necessary fields are set
        (source item, warehouse, finished good dimensions and quantity).
        If any of these are missing or invalid, the proposal is skipped.
        """
        # Only attempt to propose when key fields are present
        if not self.source_item or not self.source_warehouse:
            return
        # Retrieve finished good dimensions and quantity
        try:
            a = float(self.get("fg_length_mm") or 0)
            b = float(self.get("fg_width_mm") or 0)
        except Exception:
            a = 0.0
            b = 0.0
        qty = int(self.get("fg_total_qty") or 0)
        if a <= 0 or b <= 0 or qty <= 0:
            return
        # Fetch available serials (sheets/chutes) for this source item
        candidates = list(get_available_serials(self.source_item, self.source_warehouse))
        if not candidates:
            frappe.msgprint(
                _("No available sheets found for item {0} in warehouse {1}.").format(
                    self.source_item, self.source_warehouse
                ),
                indicator="orange",
            )
            return
        # Choose the best candidate sheet and compute a plan
        best_id, plan = pick_best_candidate(candidates, (a, b), qty, kerf=self.kerf_mm)
        if plan is None or plan.produced_qty <= 0:
            frappe.msgprint(
                _("Unable to generate a cutting plan for the requested dimensions."),
                indicator="orange",
            )
            return
        # Build Material Reconfiguration lines
        lines = build_mr_lines(
            source_serial=best_id,
            plan=plan,
            target_warehouse=self.source_warehouse,
            fg_item_code=self.fg_item_code,
        )
        # Clear existing detail rows and populate with new lines
        self.set("detail", [])
        for line in lines:
            self.append("detail", line)
        # Compute summary fields on save
        raw_serials = 0
        total_fg_area = 0.0
        total_waste_area = 0.0
        for row in self.get("detail", []) or []:
            try:
                length_mm = float(row.get("length_mm") or 0)
                width_mm = float(row.get("width_mm") or 0)
                qty = int(row.get("planned_pieces") or 0)
            except Exception:
                length_mm = 0.0
                width_mm = 0.0
                qty = 0
            cat = (row.get("categorie") or "").strip()
            if cat == "Raw Material":
                raw_serials += 1
            elif cat == "Finished Good":
                total_fg_area += length_mm * width_mm * qty
            elif cat == "By Product":
                if min(length_mm, width_mm) < 500:
                    total_waste_area += length_mm * width_mm * max(qty, 1)
        try:
            self.total_required_pieces = raw_serials
        except Exception:
            pass
        try:
            self.total_required_area_mm2 = total_fg_area
        except Exception:
            pass
        try:
            self.total_estimated_waste_mm2 = total_waste_area
        except Exception:
            pass
        # Update document status to reflect proposal
        self.status = "Proposed"

    def on_cancel(self):
        # 1. Annuler et supprimer le Stock Entry associé
        if self.stock_entry_reference:
            se = frappe.get_doc("Stock Entry", self.stock_entry_reference)
            if se.docstatus == 1:
                se.cancel()
            frappe.delete_doc("Stock Entry", se.name)

        # 2. Supprimer bundles et numéros de série créés
        for bundle_name in (self.bundle_names or []):
            frappe.delete_doc("Serial and Batch Bundle", bundle_name)
        for row in self.get("detail"):
            if row.categorie == "By Product" and row.serial_no:
                frappe.delete_doc("Serial No", row.serial_no)

        # 3. Rétablir l’état brouillon pour recalculer les lignes
        self.docstatus = 0
        self.detail = []
        self.before_save()   # ou votre fonction propose_*()
        self.save()

        # 4. Relancer l’annulation
        self.reload()
        super().on_cancel()

    def before_submit(self):
        # Marquer la matière première comme consommée
        for row in self.detail:
            if (row.get('categorie') or '').strip() == 'Raw Material' and row.serial_no:
                frappe.db.set_value(
                    'Serial No', row.serial_no,
                    {
                        'custom_material_status': 'Consumed',
                        'custom_dimension_length_mm': 0,
                        'custom_dimension_width_mm': 0,
                    }
                )

        # Regrouper les chutes par serial parent
        groups = {}
        for row in self.detail:
            if (row.get('categorie') or '').strip() == 'By Product':
                parent = row.related_input_serial_no
                if not parent:
                    # Récupérer le serial de la première ligne 'Raw Material'
                    parent = next((r.serial_no for r in self.detail
                                if (r.categorie or '').strip() == 'Raw Material'), None)
                if not parent:
                    continue
                groups.setdefault(parent, []).append(row)

        # Pour chaque groupe, générer les numéros de série via le service
        for parent_serial, rows in groups.items():
            children = []
            for row in rows:
                children.append({
                    'length_mm': row.length_mm,
                    'width_mm': row.width_mm,
                    'material_status': row.material_status,
                    'quality_rating': row.quality_rating,
                })
            # min_keep_dimension_mm=0 => générer un serial pour chaque chute, quelle que soit sa taille
            new_serials = generate_chute_serials(
                parent_serial=parent_serial,
                children=children,
                item_code=self.source_item,
                min_keep_dimension_mm=0,
            )
            # Affecter le numéro à la ligne
            for row, sn in zip(rows, new_serials):
                row.serial_no = sn

        # Enregistrer les modifications
        #self.save(ignore_permissions=True)
        #    frappe.db.set_value(
        #        "Material Reconfiguration Line",
        #        row.name,
        #        "serial_no",
        #        new_serial,
        #        update_modified=False
        #    )

    def create_serials_bunch_bundles(self):
        """Crée deux bundles (produits finis et chutes) et renseigne les lignes."""
        fg_serials = []
        chute_serials = []

        # 1. Séparer les sérials par catégorie
        for row in self.detail:
            if (row.get("categorie") or "").strip() == "Finished Good" and row.serial_no:
                fg_serials.append(row.serial_no)
            elif (row.get("categorie") or "").strip() == "By Product" and row.serial_no:
                chute_serials.append(row.serial_no)

        fg_bundle = None
        if fg_serials:
            res = frappe.call("mat_reco.material_reconfiguration.api.create_serial_batch_bundle", {
                "company": self.company,
                "voucher_type": "Stock Entry",
                "item_code": self.fg_item_code,
                "warehouse": self.warehouse,
                "serials": fg_serials,
                "transaction_type": "Inward",
                "custom_sales_order": self.sales_order,
            })
            fg_bundle = res.get("message")
            # Associer le bundle aux lignes FG
            for row in self.detail:
                if (row.categorie or "").strip() == "Finished Good" and row.serial_no:
                    row.serial_bundle = fg_bundle

        chute_bundle = None
        if chute_serials:
            res = frappe.call("mat_reco.material_reconfiguration.api.create_serial_batch_bundle", {
                "company": self.company,
                "voucher_type": "Stock Entry",
                "item_code": self.source_item,
                "warehouse": self.warehouse,
                "serials": chute_serials,
                "transaction_type": "Inward",
                "custom_sales_order": self.sales_order,
            })
            chute_bundle = res.get("message")
            # Associer le bundle aux lignes chute
            for row in self.detail:
                if (row.categorie or "").strip() == "By Product" and row.serial_no:
                    row.serial_bundle = chute_bundle

        # 2. Lorsque vous construisez le Stock Entry, utilisez les bundles
        #    pour regrouper les sorties plutôt que d’ajouter une ligne par chute.
        #    Exemple (à placer dans votre logique de création du Stock Entry):
        # se.append("items", {
        #     "item_code": self.fg_item_code,
        #     "qty": len(fg_serials),
        #     ...
        #     "serial_and_batch_bundle": fg_bundle,
        # })
        # se.append("items", {
        #     "item_code": self.source_item,
        #     "qty": len(chute_serials),
        #     ...
        #     "serial_and_batch_bundle": chute_bundle,
        # })
        # et n'oubliez pas d'appeler se.insert() puis se.submit()

#////////////////////////////////////////////////////////////////////////


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def get_reconfigurable_fg_items(doctype, txt, searchfield, start, page_len, filters):
    """Link query for fg_item_code: only SO items where Item.custom_is_reconfigurable = 1."""
    so_name = (filters or {}).get("sales_order")
    if not so_name:
        return []

    like_txt = f"%{txt}%"

    return frappe.db.sql(
        """
        SELECT DISTINCT soi.item_code
        FROM `tabSales Order Item` soi
        INNER JOIN `tabItem` it ON it.name = soi.item_code
        WHERE soi.parent = %s
          AND IFNULL(it.custom_requires_dimensions, 0) = 1
          AND (soi.item_code LIKE %s)
        ORDER BY soi.item_code
        LIMIT %s OFFSET %s
        """,
        (so_name, like_txt, page_len, start),
    )


@frappe.whitelist()
def get_first_so_item_row(sales_order: str, item_code: str):
    """Return the first Sales Order Item rowname for this SO + item_code (idx ascending)."""
    if not sales_order or not item_code:
        return None

    rowname = frappe.db.get_value(
        "Sales Order Item",
        {"parent": sales_order, "item_code": item_code},
        "name",
        order_by="idx asc",
    )
    return rowname


@frappe.whitelist()
def get_fg_from_so_item_row(so_item_row: str):
    """Return dims (and qty) from a specific Sales Order Item row."""
    if not so_item_row:
        return {"item_code": None, "qty": 0, "length_mm": 0, "width_mm": 0}

    row = frappe.db.get_value(
        "Sales Order Item",
        so_item_row,
        ["item_code", "qty", "custom_client_length_mm", "custom_client_width_mm"],
        as_dict=True,
    ) or {}

    return {
        "item_code": row.get("item_code"),
        "qty": flt(row.get("qty")),
        "length_mm": flt(row.get("custom_client_length_mm")),
        "width_mm": flt(row.get("custom_client_width_mm")),
    }


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def get_reconfigurable_so_item_rows(doctype, txt, searchfield, start, page_len, filters):
    so_name = (filters or {}).get("sales_order")
    item_code = (filters or {}).get("item_code")

    if not so_name:
        return []

    like_txt = f"%{txt}%"

    cond_item = ""
    params = [so_name, like_txt, like_txt, page_len, start]

    if item_code:
        cond_item = " AND soi.item_code = %s "
        params = [so_name, item_code, like_txt, like_txt, page_len, start]

        return frappe.db.sql(
            f"""
            SELECT
                soi.name,
                CONCAT(soi.description, ' | Qty: ', soi.qty, ' | Row: ', soi.idx) as description
            FROM `tabSales Order Item` soi
            INNER JOIN `tabItem` it ON it.name = soi.item_code
            WHERE soi.parent = %s
              AND soi.item_code = %s
              AND (soi.item_code LIKE %s OR soi.name LIKE %s)
            ORDER BY soi.idx
            LIMIT %s OFFSET %s
            """,
            tuple(params),
        )

    return frappe.db.sql(
        """
        SELECT
            soi.name,
            CONCAT(soi.description, ' | Qty: ', soi.qty, ' | Row: ', soi.idx) as description
        FROM `tabSales Order Item` soi
        INNER JOIN `tabItem` it ON it.name = soi.item_code
        WHERE soi.parent = %s
          AND (soi.item_code LIKE %s OR soi.name LIKE %s)
        ORDER BY soi.idx
        LIMIT %s OFFSET %s
        """,
        (so_name, like_txt, like_txt, page_len, start),
    )
