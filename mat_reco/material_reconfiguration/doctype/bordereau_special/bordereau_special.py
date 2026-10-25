from frappe.model.document import Document
from mat_reco.material_reconfiguration.services import special_b

class BordereauSpecial(Document):
    def validate(self):
        special_b.delivery_validate(self)

    def on_submit(self):
        special_b.delivery_on_submit(self)

    def before_cancel(self):
        special_b.delivery_before_cancel(self)

