from frappe.model.document import Document
from mat_reco.material_reconfiguration.services.chantier_service import validate_chantier
from mat_reco.material_reconfiguration.services.technical_study_service import (
    validate_macro, submit_chantier, cancel_chantier, before_insert_chantier, clone_sections,
)

class Chantier(Document):
    def before_insert(self):
        before_insert_chantier(self)

    def before_validate(self):
        if self.is_new():
            self.reference = self.name

    def validate(self):
        validate_chantier(self)
        validate_macro(self)

    def before_submit(self):
        submit_chantier(self)

    def before_cancel(self):
        cancel_chantier(self)

    def after_insert(self):
        clone_sections(self)
