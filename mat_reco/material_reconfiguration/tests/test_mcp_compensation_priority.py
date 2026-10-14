import unittest
from mat_reco.material_reconfiguration.services.mcp_compensation_service import propose_compensation
from mat_reco.material_reconfiguration.tests.test_mcp_compensation_geometry import sheet, need


def source(serial, priority, l=1200, w=1000):
    return dict(serial_no=serial, priority=priority, origin="stock_leftover" if priority==2 else "stock_sheet",
        item_code="RAW",warehouse="WH",company="CO",length_mm=l,width_mm=w,area_mm2=l*w,thickness_mm=6,
        material_status="Partial" if priority==2 else "Full")


class TestCompensationPriority(unittest.TestCase):
    def test_a_internal_sufficient_never_adds_selected_stock(self):
        out=propose_compensation({"nodes":[sheet()]},[need()],[source("STOCK",2)],selected_sources=["STOCK"])
        self.assertEqual(len(out["placements"]),1)
        self.assertEqual(out["used_stock_sources"],[])
        self.assertEqual(len(out["effective_tree"]["nodes"]),1)

    def test_b_stock_leftover_precedes_full_sheet(self):
        out=propose_compensation({"nodes":[sheet(2000,400)]},[need()],[source("FULL",3),source("LEFT",2)])
        self.assertEqual(out["used_stock_sources"][0]["serial_no"],"LEFT")
        self.assertEqual(out["placements"][0]["origin"],"stock_leftover")

    def test_c_full_sheet_last_resort(self):
        out=propose_compensation({"nodes":[sheet(2000,400)]},[need()],[source("LEFT",2,2000,400),source("FULL",3)])
        self.assertEqual(out["used_stock_sources"][0]["serial_no"],"FULL")

    def test_d_partial_is_reported(self):
        out=propose_compensation({"nodes":[sheet(800,600)]},[need("p"),need("q")])
        self.assertEqual(out["summary"]["remaining"],1)

    def test_f_single_stock_respects_cutout(self):
        src=source("L",2);src.update(removed_length_mm=800,removed_width_mm=600,area_mm2=720000)
        out=propose_compensation({"nodes":[sheet(2000,400)]},[need()],[src])
        self.assertFalse(out["placements"])

    def test_submitted_input_sheet_not_reused(self):
        out=propose_compensation({"nodes":[sheet()]},[need()],consumed_inputs=["SN"])
        self.assertFalse(out["placements"])

    def test_manual_override_requires_justification(self):
        with self.assertRaises(ValueError):
            propose_compensation({"nodes":[sheet()]},[need()],[source("FULL",3)],strategy="manual",selected_sources=["FULL"])
        out=propose_compensation({"nodes":[sheet()]},[need()],[source("FULL",3)],strategy="manual",selected_sources=["FULL"],override_reason="Chute physiquement inaccessible")
        self.assertEqual(out["used_stock_sources"][0]["serial_no"],"FULL")

    def test_stale_selection_rejected(self):
        with self.assertRaises(ValueError):propose_compensation({"nodes":[sheet()]},[need()],selected_sources=["gone"])

    def test_equal_priority_prefers_one_source_covering_all_units(self):
        out=propose_compensation({"nodes":[sheet(2000,400)]},[need("p"),need("q")],
            [source("SMALL",2,800,600),source("LARGE",2,1600,600)])
        self.assertEqual(len(out["used_stock_sources"]),1)
        self.assertEqual(out["used_stock_sources"][0]["serial_no"],"LARGE")
        self.assertFalse(out["remaining_requirements"])

    def test_automatic_selection_cannot_bypass_stock_leftover_without_reason(self):
        with self.assertRaises(ValueError):
            propose_compensation({"nodes":[sheet(2000,400)]},[need()],
                [source("LEFT",2),source("FULL",3)],selected_sources=["FULL"])

    def test_manual_can_select_a_single_arm_of_an_l_shaped_leftover(self):
        child=dict(id="L",node_type="leftover",geometry_type="single",x=0,y=0,length_mm=1200,width_mm=1000,removed_length_mm=800,removed_width_mm=600)
        out=propose_compensation({"nodes":[sheet(children=[child])]},[need(l=400,w=600)],
            strategy="manual",selected_sources=["SN/L/1"])
        self.assertEqual(len(out["placements"]),1)
