from frappe.model.document import Document
from mat_reco.material_reconfiguration.services import special_b

class SoldeInitialClientB(Document):
    def validate(self):
        special_b.opening_validate(self)

    def before_cancel(self):
        special_b.opening_before_cancel(self)

