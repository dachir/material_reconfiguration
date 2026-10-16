import frappe
from frappe.model.document import Document
from mat_reco.material_reconfiguration.services.workshop_planner import whole


class WorkshopRefabrication(Document):
    def validate(self):
        if whole(self.qty) <= 0:
            frappe.throw('La quantité de refabrication doit être positive.')
        order = frappe.get_doc('Sales Order', self.sales_order)
        order.check_permission('read')
        self.company=order.company
        row = next((r for r in order.items if r.name == self.sales_order_item), None)
        if not row or order.docstatus != 1:
            frappe.throw('La ligne doit appartenir à une commande validée.')
        se = frappe.get_doc('Stock Entry', self.source_stock_entry)
        se.check_permission('read')
        from mat_reco.material_reconfiguration.services.workshop_service import _quality_qty, _serials, _json, _mcp_output_mapping, _output_matches_line
        outputs = [r for r in se.items if r.t_warehouse and not r.s_warehouse and r.item_code == row.item_code
                   and r.get('custom_sales_order_item') == row.name and _output_matches_line(r,row)]
        accepted=sum(_quality_qty(d,se) for d in outputs)
        if not outputs and se.get('custom_material_cutting_plan'):
            mapping=_json(se.get('custom_workshop_allocations_json')) or _mcp_output_mapping(se)
            for detail in se.items:
                if detail.t_warehouse and not detail.s_warehouse and detail.item_code==row.item_code:
                    # Partial grouped inspection cannot be attributed to an
                    # arbitrary command or serial without explicit evidence.
                    if _output_matches_line(detail,row) and _quality_qty(detail,se)==float(detail.get('transfer_qty') or detail.qty):
                        accepted+=sum(mapping.get(sn,{}).get('sales_order_item')==row.name for sn in _serials(detail))
        if se.docstatus != 1 or se.stock_entry_type != 'Repack' or accepted<=0:
            frappe.throw('La production d’origine doit être validée, conforme et attribuée à cette ligne.')
        if self.docstatus == 1:
            frappe.db.sql('SELECT name FROM `tabStock Entry` WHERE name=%s FOR UPDATE', se.name)
            previous = frappe.db.sql('''SELECT COALESCE(SUM(qty),0) FROM `tabWorkshop Refabrication`
                WHERE source_stock_entry=%s AND sales_order_item=%s AND docstatus=1 AND name!=%s''',
                (se.name, row.name, self.name))[0][0]
            if float(previous) + self.qty > accepted:
                frappe.throw('Les refabrications dépassent la production d’origine. Utilisez la nouvelle production comme référence pour une nouvelle casse.')
