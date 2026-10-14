import unittest
from copy import deepcopy
from mat_reco.material_reconfiguration.services.mcp_compensation_geometry import propose_internal, internal_candidates


def sheet(l=1200,w=1000,children=None):
    return dict(id="SN", serial_no="SN", node_type="input_serial", length_mm=l,width_mm=w,thickness_mm=6,
                children=children if children is not None else [dict(id="left",node_type="leftover",x=0,y=0,length_mm=l,width_mm=w)])


def need(uid="p",l=800,w=600):
    return dict(piece_uid=uid, piece_item_code="FG",length_mm=l,width_mm=w,thickness_mm=6,broken_operation_ids=["broken"])


class TestInternalGeometry(unittest.TestCase):
    def test_internal_only_and_immutable(self):
        nodes=[sheet()]; before=deepcopy(nodes)
        out=propose_internal(nodes,[need()],seed="v1")
        self.assertEqual(len(out["placements"]),1)
        self.assertEqual(out["remaining"],[])
        self.assertEqual(nodes,before)
        self.assertEqual(out,propose_internal(nodes,[need()],seed="v1"))

    def test_area_does_not_imply_geometric_fit(self):
        out=propose_internal([sheet(2000,400)],[need()])
        self.assertEqual(out["placements"],[])

    def test_rotation(self):
        nodes=[sheet(600,800)]
        self.assertEqual(len(propose_internal(nodes,[need()],allow_rotation=True)["placements"]),1)
        self.assertFalse(propose_internal(nodes,[need()],allow_rotation=False)["placements"])

    def test_waste_and_submitted_leftover_are_excluded(self):
        nodes=[sheet()];nodes[0]["children"][0]["node_type"]="waste"
        self.assertFalse(propose_internal(nodes,[need()])["placements"])
        nodes[0]["children"][0]["node_type"]="leftover"
        self.assertFalse(propose_internal(nodes,[need()],frozen_ids=["left"])["placements"])

    def test_partial(self):
        out=propose_internal([sheet(800,600)],[need("p"),need("q")])
        self.assertEqual(len(out["placements"]),1)
        self.assertEqual(len(out["remaining"]),1)

    def test_decimal_dimensions_are_not_truncated(self):
        self.assertFalse(propose_internal([sheet(800,600)],[need(l=800.1)])["placements"])
        self.assertTrue(propose_internal([sheet(800.1,600)],[need(l=800.1)])["placements"])

    def test_kerf_prevents_impossible_adjacency(self):
        nodes=[sheet(1600,600)]
        self.assertEqual(len(propose_internal(nodes,[need("p"),need("q")],kerf_mm=3)["placements"]),1)
        self.assertEqual(len(propose_internal([sheet(1603,600)],[need("p"),need("q")],kerf_mm=3)["placements"]),2)

    def test_single_cutout_and_untouched_arm(self):
        child=dict(id="L",node_type="leftover",geometry_type="single",x=0,y=0,length_mm=1200,width_mm=1000,removed_length_mm=800,removed_width_mm=600)
        out=propose_internal([sheet(children=[child])],[need(l=400,w=600)])
        self.assertEqual(len(out["placements"]),1)
        self.assertFalse(any(c.get("geometry_type")=="single" for c in out["nodes"][0]["children"]))
        self.assertFalse(propose_internal([sheet(children=[child])],[need(l=800,w=600)])["placements"])

    def test_successful_coordinates_remain_identical(self):
        good=dict(id="good",piece_uid="good",node_type="finished_good",x=0,y=0,length_mm=400,width_mm=1000)
        free=dict(id="left",node_type="leftover",x=400,y=0,length_mm=800,width_mm=1000)
        out=propose_internal([sheet(children=[good,free])],[need()])
        self.assertEqual(out["nodes"][0]["children"][0],good)

    def test_collisions_and_invalid_parameters_rejected(self):
        nodes=[sheet()];nodes[0]["children"].append(dict(id="bad",node_type="finished_good",x=0,y=0,length_mm=100,width_mm=100))
        with self.assertRaises(ValueError):internal_candidates(nodes)
        with self.assertRaises(ValueError):propose_internal([sheet()],[need()],kerf_mm=float("nan"))

    def test_incompatible_thickness_is_excluded(self):
        nodes=[sheet()];nodes[0]["thickness_mm"]=8
        self.assertFalse(propose_internal(nodes,[need()])["placements"])
