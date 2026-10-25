from frappe.model.document import Document
from mat_reco.material_reconfiguration.services import special_b

class ReglementSpecial(Document):
    def validate(self):
        special_b.payment_validate(self)

    def before_cancel(self):
        special_b.payment_before_cancel(self)

    def before_update_after_submit(self):
        special_b.payment_before_update_after_submit(self)

