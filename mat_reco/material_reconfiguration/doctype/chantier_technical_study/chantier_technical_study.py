from frappe.model.document import Document
from mat_reco.material_reconfiguration.services.technical_study_service import validate_study, submit_study, cancel_study

class ChantierTechnicalStudy(Document):
    def validate(self):
        validate_study(self)

    def before_submit(self):
        submit_study(self)

    def before_cancel(self):
        cancel_study(self)
