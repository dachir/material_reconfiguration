from frappe.utils.nestedset import NestedSet
from mat_reco.material_reconfiguration.services.chantier_service import validate_section

class ChantierSection(NestedSet):
    def validate(self):
        validate_section(self)
