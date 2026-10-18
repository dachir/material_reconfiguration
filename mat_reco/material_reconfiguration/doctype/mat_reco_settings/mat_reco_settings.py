from urllib.parse import urlsplit

import frappe
from frappe.model.document import Document
from frappe.utils import cint, flt


class MatRecoSettings(Document):
    def on_update(self):
        from mat_reco.material_reconfiguration.services.task_notifications import install_workspace_tasks
        install_workspace_tasks()

    def validate(self):
        self.api_base_url = (self.api_base_url or '').strip().rstrip('/')
        self.model = (self.model or '').strip()
        if self.enabled and (not self.api_base_url or not self.model):
            frappe.throw('Renseigner l’URL de l’API et le modèle avant d’activer le LLM.')
        if self.api_base_url:
            try:
                url = urlsplit(self.api_base_url)
                valid = (url.scheme in ('http', 'https') and url.hostname
                    and not url.username and not url.password and not url.query and not url.fragment)
                url.port  # Also validate the port syntax.
            except ValueError:
                valid = False
            if not valid:
                frappe.throw('Utiliser une URL HTTP ou HTTPS sans identifiants, paramètres ni fragment.')
        if cint(self.timeout_seconds) <= 0 or cint(self.timeout_seconds) > 600:
            frappe.throw('Le délai de réponse doit être compris entre 1 et 600 secondes.')
        if cint(self.max_output_tokens) <= 0:
            frappe.throw('Le nombre maximal de tokens doit être positif.')
        if not 0 <= flt(self.temperature) <= 2:
            frappe.throw('La température doit être comprise entre 0 et 2.')
