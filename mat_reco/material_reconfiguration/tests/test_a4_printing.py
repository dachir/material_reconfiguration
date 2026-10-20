import unittest
from mat_reco.printing import detail, structured, physical_regions, cutting_html


class TestA4Printing(unittest.TestCase):
    def test_nested_definition_preserves_children_and_escapes_html(self):
        html = detail({'item_code': '<script>bad()</script>', 'children': [{'qty_factor': 0, 'quality_required': False}]})
        self.assertIn('&lt;script&gt;', html)
        self.assertNotIn('<script>', html)
        self.assertIn('Quantité par parent', html)
        self.assertIn('>0<', html)
        self.assertIn('Non', html)

    def test_double_encoded_legacy_payload(self):
        self.assertEqual(structured('"{\\"nodes\\": []}"'), {'nodes': []})

    def test_single_notch_is_not_drawn_as_available_material(self):
        regions = physical_regions(dict(x=0, y=0, length_mm=100, width_mm=80,
                                        removed_length_mm=20, removed_width_mm=30))
        self.assertEqual(sum(w*h for x,y,w,h in regions), 7400)
        self.assertTrue(all(x >= 20 or y >= 30 for x,y,w,h in regions))

    def test_effective_plan_takes_precedence_over_planning(self):
        doc = dict(result_json={'nodes':[{'node_type':'input_serial','serial_no':'OLD'}]},
                   effective_result_json={'nodes':[{'node_type':'input_serial','serial_no':'NEW',
                       'length_mm':100,'width_mm':80,'children':[{'node_type':'leftover',
                       'length_mm':100,'width_mm':80,'removed_length_mm':20,'removed_width_mm':30}]}]})
        html = cutting_html(doc)
        self.assertIn('NEW', html)
        self.assertNotIn('OLD', html)
        self.assertIn('x="20"', html)
