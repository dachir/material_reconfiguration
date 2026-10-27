"""Only submitted technical studies may contribute workshop demand."""
import unittest
from collections import defaultdict
from unittest.mock import MagicMock, patch

import frappe
from mat_reco.material_reconfiguration.services import workshop_service as service
from mat_reco.material_reconfiguration.services.workshop_planner import Pool
from mat_reco.material_reconfiguration.tests.test_workshop_service import Doc


class WorkshopStudyVisibilityTests(unittest.TestCase):
    def test_missing_draft_cancelled_and_submitted_study(self):
        row=frappe._dict()
        self.assertFalse(service._has_validated_study(frappe._dict(),row))
        for status in (None,0,1,2):
            with patch.object(frappe,'db',new=MagicMock()) as db:
                db.get_value.return_value=status
                self.assertEqual(service._has_validated_study(frappe._dict(custom_technical_study='FT'),row,lock=True),status==1)
                db.get_value.assert_called_once_with('Chantier Technical Study','FT','docstatus',for_update=True)

    def test_current_draft_takes_precedence_over_old_frozen_study(self):
        order=frappe._dict(custom_technical_study='DRAFT')
        row=frappe._dict(custom_technical_snapshot='{"technical_study":"OLD"}')
        with patch.object(frappe,'db',new=MagicMock()) as db:
            db.get_value.return_value=0
            self.assertFalse(service._has_validated_study(order,row))
            self.assertEqual(db.get_value.call_args.args[1],'DRAFT')

    def test_frozen_and_legacy_chantier_study_supported(self):
        with patch.object(frappe,'db',new=MagicMock()) as db:
            db.get_value.return_value=1
            self.assertTrue(service._has_validated_study(frappe._dict(),frappe._dict(custom_technical_snapshot='{"technical_study":"FT"}')))
            db.get_value.side_effect=['LEGACY-FT',1]
            self.assertTrue(service._has_validated_study(frappe._dict(custom_chantier='CH'),frappe._dict()))

    def test_load_excludes_unvalidated_rows_before_tree_and_totals(self):
        rows=[frappe._dict(name=n,item_code='CUT',item_name=n,qty=2) for n in ('valid','draft','cancelled','missing')]
        order=Doc(name='SO',company='UG',customer='Client',status='To Deliver',delivery_date=None,transaction_date='2026-10-27',items=rows)
        with patch.object(service,'_permission'),patch.object(frappe,'get_list',return_value=[frappe._dict(name='SO')]), \
             patch.object(frappe,'get_doc',return_value=order),patch.object(service,'_receipts',return_value=(defaultdict(int),defaultdict(int),defaultdict(int),{})), \
             patch.object(frappe,'db',new=MagicMock()) as db,patch.object(frappe,'get_cached_value',return_value='DECOUPE'), \
             patch.object(service,'_has_validated_study',side_effect=lambda so,row,**kw:row.name=='valid'), \
             patch.object(service,'_tree',side_effect=frappe.ValidationError('Composition à corriger')) as tree, \
             patch.object(service,'_inventory',return_value=(Pool(),Pool())), \
             patch('mat_reco.material_reconfiguration.services.chantier_work_types.logical_section',return_value=None):
            db.get_values.return_value=[]
            roots,errors,_=service._load()
        self.assertEqual(len(roots),1)
        self.assertEqual(roots[0]['required_qty'],2)
        self.assertEqual([n['sales_order_item'] for n in roots[0]['children']],['valid'])
        self.assertEqual([e['sales_order_item'] for e in errors],['valid'])
        self.assertEqual(tree.call_count,1)
