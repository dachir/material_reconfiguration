"""Default quotation quantities and retry behavior without a live ERP database."""
import json
from contextlib import ExitStack
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock, patch

import frappe
from mat_reco.material_reconfiguration.services import chantier_service, technical_study_service as service


class Doc(SimpleNamespace):
    def get(self, key, default=None):
        return getattr(self, key, default)


class QuotationRemainingTests(TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.lines = [frappe._dict(line_id='L1', repere='V1', section=None, qty=5, rate=100),
                      frappe._dict(line_id='L2', repere='V2', section=None, qty=2, rate=50)]
        self.dossier = Doc(name='CHANTIER', docstatus=1, lines=self.lines, customer='CUSTOMER',
                           company='UG', currency='USD', selling_price_list='Selling', terms='')
        self.quote = Doc(name='QUO-NEW', items=[], run_method=MagicMock(), insert=MagicMock(),
                         submit=MagicMock(), check_permission=MagicMock())
        self.quote.update = lambda values: self.quote.__dict__.update(values)
        self.quote.append = lambda field, values: getattr(self.quote, field).append(frappe._dict(values))
        tech = frappe._dict(result_item='GLASS', length_mm=1000, width_mm=800, thickness_mm=6)
        self.stack.enter_context(patch.object(service, 'chantier_doc', return_value=self.dossier))
        self.stack.enter_context(patch.object(service, 'approved_study', return_value=Doc(name='STUDY')))
        self.stack.enter_context(patch.object(service, 'quotation_rows', return_value={r.line_id:(r,tech) for r in self.lines}))
        self.usage = self.stack.enter_context(patch.object(service, 'get_quotation_usage', return_value={}))
        self.stack.enter_context(patch.object(service.chantier_extras, 'add_quote_rows'))
        self.stack.enter_context(patch.object(service, 'nowdate', return_value='2026-10-16'))
        self.stack.enter_context(patch.object(frappe.local, 'flags', frappe._dict(in_test=False), create=True))
        self.stack.enter_context(patch.object(frappe, 'session', frappe._dict(user='test'), create=True))
        self.stack.enter_context(patch.object(frappe, 'get_cached_value', return_value='PC'))
        self.new_doc = self.stack.enter_context(patch.object(frappe, 'new_doc', return_value=self.quote))
        self.stack.enter_context(patch.object(frappe, 'get_doc', return_value=self.quote))
        def reject(message, *args, **kwargs):
            raise frappe.ValidationError(message)
        self.stack.enter_context(patch.object(frappe, 'throw', side_effect=reject))
        self.db = self.stack.enter_context(patch.object(frappe, 'db', new=MagicMock()))
        self.db.get_value.return_value = None

    def generate(self, **kwargs):
        return service.generate_quotation('CHANTIER', request_key='request-1', **kwargs)

    def test_first_quotation_defaults_to_every_unit(self):
        self.generate()
        self.assertEqual([r.qty for r in self.quote.items], [5,2])

    def test_partial_quote_defaults_to_the_remainder_and_skips_exhausted_lines(self):
        self.usage.return_value = {'L1':2, 'L2':2}
        self.generate()
        self.assertEqual([(r.custom_chantier_line,r.qty) for r in self.quote.items], [('L1',3)])

    def test_explicit_partial_selection_is_preserved(self):
        self.generate(selections=json.dumps([{'line_id':'L1','qty':1}]))
        self.assertEqual([r.qty for r in self.quote.items], [1])
        self.usage.assert_not_called()

    def test_fully_quoted_dossier_creates_no_extra_single_unit(self):
        self.usage.return_value = {'L1':5,'L2':3}
        with self.assertRaisesRegex(frappe.ValidationError, 'déjà au devis'):
            self.generate()
        self.new_doc.assert_not_called()

    def test_retry_returns_original_quote_after_balance_is_consumed(self):
        self.usage.return_value = {'L1':2,'L2':2}
        self.assertEqual(self.generate(), 'QUO-NEW')
        existing = frappe._dict(name='QUO-NEW', custom_chantier='CHANTIER', docstatus=0,
                               custom_chantier_request_scope=self.quote.custom_chantier_request_scope)
        self.db.get_value.side_effect = lambda dt,*a,**kw: existing if dt=='Quotation' else 'CHANTIER'
        self.usage.return_value = {'L1':5,'L2':2}
        self.assertEqual(self.generate(), 'QUO-NEW')
        self.usage.assert_called_once()
        self.quote.insert.assert_called_once()

    def test_explicit_empty_selection_is_rejected(self):
        with self.assertRaisesRegex(frappe.ValidationError, 'Sélection invalide'):
            self.generate(selections='[]')
        self.new_doc.assert_not_called()

    def test_usage_combines_legacy_reperes_and_stable_line_ids(self):
        self.db.sql.return_value = [frappe._dict(custom_chantier_line='L1',custom_repere='V1',qty=2),
                                    frappe._dict(custom_chantier_line='',custom_repere='V1',qty=1)]
        self.assertEqual(chantier_service.get_quotation_usage(self.dossier), {'L1':3})
        sql, chantier = self.db.sql.call_args.args
        self.assertEqual(chantier, 'CHANTIER')
        self.assertIn('q.docstatus<2', sql)
