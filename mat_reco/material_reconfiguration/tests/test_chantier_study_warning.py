import unittest
from mat_reco.material_reconfiguration.services.chantier_service import _chantier_study_stale


class ChantierStudyWarningTests(unittest.TestCase):
    def test_order_snapshot_is_not_compared_to_its_upstream_chantier(self):
        self.assertFalse(_chantier_study_stale(dict(sales_order='SO',source_hash='order-hash'),'chantier-hash'))

    def test_legacy_direct_chantier_sheet_still_detects_changes(self):
        self.assertTrue(_chantier_study_stale(dict(source_hash='old'),'new'))
        self.assertFalse(_chantier_study_stale(dict(source_hash='same'),'same'))
        self.assertFalse(_chantier_study_stale(None,'any'))
