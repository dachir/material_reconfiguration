"""Approved surface prices remain valid after ERPNext currency rounding."""
import unittest
import frappe
from frappe.utils import flt
from mat_reco.material_reconfiguration.services.chantier_discounts import rate_matches

class Row(frappe._dict):
    def precision(self, field):
        return 0

class DiscountPrecisionTests(unittest.TestCase):
    def test_surface_discount_accepts_native_rounded_price_not_changed_price(self):
        doc=frappe._dict(discount_mode='Pourcentage')
        for length,width in [(1400,2000),(700,1360)]:
            macro=frappe._dict(rate=33898,price_per_sqm=1,length_mm=length,width_mm=width,discount_percentage=25)
            surface=length*width/1000000
            gross=33898*surface
            row=Row(rate=flt(gross*.75,0),price_list_rate=flt(gross,0),discount_percentage=25,
                custom_ug_price_per_sqm=1,custom_ug_pricing_rate=33898,custom_ug_pricing_surface=surface)
            self.assertTrue(rate_matches(doc,macro,row))
            row.price_list_rate+=1
            self.assertFalse(rate_matches(doc,macro,row))
            row.price_list_rate=flt(gross,0)
            row.rate+=1
            self.assertFalse(rate_matches(doc,macro,row))

    def test_original_pricing_rate_is_still_protected(self):
        macro=frappe._dict(rate=33898,price_per_sqm=1,length_mm=1400,width_mm=2000,discount_percentage=25)
        row=Row(rate=71186,price_list_rate=94914,discount_percentage=25,
            custom_ug_price_per_sqm=1,custom_ug_pricing_rate=33899,custom_ug_pricing_surface=2.8)
        self.assertFalse(rate_matches(frappe._dict(discount_mode='Pourcentage'),macro,row))
