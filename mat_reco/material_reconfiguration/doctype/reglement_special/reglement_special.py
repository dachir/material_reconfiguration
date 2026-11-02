from frappe.model.document import Document
from mat_reco.material_reconfiguration.services import special_b

class ReglementSpecial(Document):
    def get_invalid_links(self, is_submittable=False):
        invalid, cancelled = super().get_invalid_links(is_submittable)
        if self.get('payment_kind') == 'Remboursement' and self.get('refund_of'):
            # Retain the historical order link when refunding a cancelled sale.
            # Only this exact, existing order may be cancelled; every other link
            # keeps Frappe's standard checks. Financial validation runs normally.
            import frappe
            source = frappe.get_doc('Reglement Special', self.refund_of)
            source.check_permission('read')
            if source.docstatus == 1 and source.get('payment_kind') != 'Remboursement' and source.sales_order == self.get('sales_order'):
                cancelled = [link for link in cancelled if link[0] != 'sales_order']
        return invalid, cancelled

    def validate(self):
        special_b.payment_validate(self)

    def on_submit(self):
        special_b.payment_on_submit(self)

    def on_update_after_submit(self):
        special_b.payment_after_update_after_submit(self)

    def before_cancel(self):
        special_b.payment_before_cancel(self)

    def before_update_after_submit(self):
        special_b.payment_before_update_after_submit(self)

    def on_cancel(self):
        from mat_reco.material_reconfiguration.services import special_refunds
        if special_refunds.is_refund(self):
            special_refunds.sync_source(self)
