import base64
import io
import json
import unittest
from unittest.mock import Mock, patch

import frappe
from PIL import Image
from mat_reco.material_reconfiguration.tests import test_chantier_templates as fixtures
from mat_reco.material_reconfiguration.services import section_generation as generation


class TestSectionGeneration(unittest.TestCase):
    setUp = fixtures.TestChantierTemplates.setUp
    tearDown = fixtures.TestChantierTemplates.tearDown
    chantier = fixtures.TestChantierTemplates.chantier
    section = fixtures.TestChantierTemplates.section

    def configure(self):
        settings = frappe.get_single('Mat Reco Settings')
        settings.update(dict(enabled=1,api_base_url='https://example.invalid/v1',model='test-model',
            api_key='test-only-secret',supports_images=1,timeout_seconds=120,
            max_output_tokens=4096,temperature=0.2))
        settings.save()

    def test_proposal_requires_confirmation_and_keeps_existing_sections(self):
        self.configure()
        target = self.chantier()
        existing = self.section(target.name, 'Existante')
        response = Mock(status_code=200)
        response.json.return_value = {'choices':[{'finish_reason':'stop','message':{'content':json.dumps({
            'sections':[{'section_name':'Bâtiment','parent_row':0},{'section_name':'Étage','parent_row':1}],
            'warnings':['Libellé à vérifier']})}}]}
        image = io.BytesIO()
        Image.new('RGB',(2,2)).save(image,format='PNG')
        plan = 'data:image/png;base64,'+base64.b64encode(image.getvalue()).decode()
        with patch.object(generation.requests,'post',return_value=response) as post:
            proposal = generation.generate_proposal(target.name,'Un bâtiment avec un étage',[plan])
        self.assertEqual(frappe.db.count('Chantier Section',{'chantier':target.name}),1)
        args = post.call_args
        self.assertEqual(args.args[0],'https://example.invalid/v1/chat/completions')
        self.assertEqual(args.kwargs['headers']['Authorization'],'Bearer test-only-secret')
        self.assertEqual(args.kwargs['json']['messages'][1]['content'][1]['type'],'image_url')
        self.assertNotIn('test-only-secret',json.dumps(proposal))
        self.assertEqual(generation.apply_generated_sections(target.name,proposal['sections'])['count'],2)
        self.assertTrue(frappe.db.exists('Chantier Section',existing.name))

    def test_invalid_tree_images_and_timeout(self):
        self.configure()
        target = self.chantier()
        for rows in [[],[{'section_name':'A','parent_row':1}],[{'section_name':'A','parent_row':-1}]]:
            with self.assertRaises(frappe.ValidationError):
                generation.apply_generated_sections(target.name,rows)
        with self.assertRaises(frappe.ValidationError):
            generation.image_parts(['https://example.invalid/image.png'])
        with patch.object(generation.requests,'post',side_effect=generation.requests.Timeout):
            with self.assertRaises(frappe.ValidationError):
                generation.generate_proposal(target.name,'Description')
        self.assertEqual(frappe.db.count('Chantier Section',{'chantier':target.name}),0)

    def test_background_result_is_private(self):
        self.configure()
        target=self.chantier()
        with patch.object(generation.frappe,'enqueue') as enqueue:
            job=generation.generate_sections(target.name,'Description')
        token=job['job_id']
        try:
            self.assertEqual(generation.get_generation(token)['status'],'pending')
            with patch.object(generation,'generate_proposal',return_value={'sections':[], 'warnings':[]}):
                generation.run_generation(token,frappe.session.user,target.name,'Description',None)
            self.assertEqual(generation.get_generation(token)['status'],'done')
            frappe.set_user('Guest')
            with self.assertRaises(frappe.PermissionError):
                generation.get_generation(token)
            self.assertTrue(enqueue.called)
        finally:
            frappe.set_user('Administrator')
            frappe.cache.delete_value('section-generation:'+token)
