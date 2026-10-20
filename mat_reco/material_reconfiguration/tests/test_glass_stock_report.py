"""Report totals and filters must preserve physical stock and L-cut geometry."""
import unittest
from unittest.mock import patch

from mat_reco.material_reconfiguration.report.ug___stock_de_vitres import ug___stock_de_vitres as report
from mat_reco.material_reconfiguration.services.glass_stock import physical_rows


class GlassStockReportTest(unittest.TestCase):
    def setUp(self):
        self.items = {'RAW': {'item_name': 'Clair', 'custom_item_types': 'PRIMAIRE'},
                      'CUT': {'item_name': 'Découpe', 'custom_item_types': 'DECOUPE', 'custom_parent_item': 'RAW'}}
        serials = []
        for name, code, warehouse, rl, rw in [('P1', 'RAW', 'A', 0, 0), ('P2', 'RAW', 'A', 0, 0),
                                             ('P3', 'RAW', 'B', 0, 0), ('C1', 'CUT', 'A', 500, 400)]:
            serials.append(dict(name=name, item_code=code, warehouse=warehouse, status='Active',
                custom_material_status='Full', custom_dimension_length_mm=2000,
                custom_dimension_width_mm=1000, custom_dimension_thickness_mm=6,
                custom_removed_length_mm=rl, custom_removed_width_mm=rw))
        self.stock, self.issues = physical_rows(serials, self.items, {'A', 'B'})

    def test_summary_keeps_warehouses_separate_and_uses_net_area(self):
        rows, counts = report.build_rows(self.stock, self.items)
        self.assertEqual(len(rows), 4)
        self.assertEqual(rows[-1]['qty'], 4)
        self.assertAlmostEqual(rows[-1]['area_m2'], 7.8)
        cut = next(r for r in rows if r.get('stock_type') == 'Chutes')
        self.assertEqual((cut['removed_length_mm'], cut['removed_width_mm']), (500, 400))
        self.assertAlmostEqual(cut['area_m2'], 1.8)
        self.assertEqual((counts['Plaques'], counts['Chutes']), (3, 1))

    def test_type_filters_and_serial_detail_agree(self):
        plaques, _ = report.build_rows(self.stock, self.items, stock_type='Plaques')
        cuts, _ = report.build_rows(self.stock, self.items, stock_type='Chutes', detail=True)
        self.assertEqual(plaques[-1]['qty'], 3)
        self.assertEqual(cuts[-1]['qty'], 1)
        self.assertEqual(cuts[0]['serial_no'], 'C1')
        self.assertEqual(len({r['serial_no'] for r in report.build_rows(self.stock, self.items, detail=True)[0][:-1]}), 4)

    def test_unknown_geometry_and_empty_filters(self):
        bad = dict(self.stock[0], area_m2=None, geometry_error='Invalid')
        rows, counts = report.build_rows([bad], self.items)
        self.assertIsNone(rows[0]['area_m2'])
        self.assertEqual(rows[-1]['area_m2'], 0)
        self.assertEqual(counts['unknown'], 1)
        self.assertEqual(report.build_rows(self.stock, self.items, primary_item='OTHER')[0], [])

    def test_execute_company_filter_and_columns(self):
        with patch.object(report, '_inventory', return_value=(self.stock, {}, self.items)), \
             patch.object(report, '_read_all', return_value=[{'name': 'A'}]):
            columns, rows, _, _, summary, _ = report.execute({'company': 'Company', 'detail': 'Détail par série'})
        self.assertEqual(rows[-1]['qty'], 3)
        self.assertEqual(summary[0]['value'], 2)
        self.assertIn('serial_no', [c['fieldname'] for c in columns])
        self.assertNotIn('serial_no', [c['fieldname'] for c in report.get_columns()])
