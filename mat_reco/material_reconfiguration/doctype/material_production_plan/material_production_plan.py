from frappe.model.document import Document
from mat_reco.material_reconfiguration.services.chantier_service import populate_mpp

class MaterialProductionPlan(Document):
    def validate(self):
        populate_mpp(self)
