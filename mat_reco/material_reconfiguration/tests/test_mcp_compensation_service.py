from copy import deepcopy
import unittest
from unittest.mock import Mock, patch

from mat_reco.material_reconfiguration.services import mcp_compensation_service as api


def demand(uid):
    return dict(piece_uid=uid, qty=1, piece_item_code="FG", length_mm=800, width_mm=600,
                sales_order="SO", sales_order_item="ROW")


def piece(uid, operation=None, kind="finished_good"):
    return dict(demand(uid), id=operation or uid, node_type=kind)


def reconcile(children, demands=None, incidents=(), receipts=()):
    return api.reconcile_requirements(demands or [demand("p")],
        [dict(serial_no="SN", children=children)], incidents, receipts)


class TestCompensationRequirements(unittest.TestCase):
    def test_five_units_one_broken_and_four_produced(self):
        demands = [demand(str(i)) for i in range(5)]
        result = reconcile([piece(str(i), kind="destroyed" if i == 4 else "finished_good") for i in range(5)], demands, receipts=list("0123"))
        self.assertEqual(result["summary"], dict(requested=5, produced=4, planned=0,
            broken_operations=1, to_compensate=1, remaining_to_produce=1))
        self.assertEqual(result["compensation_requirements"][0]["requirement_id"], "4")

    def test_plan_is_not_execution(self):
        result = reconcile([piece("p")])
        self.assertEqual(result["summary"]["produced"], 0)
        self.assertEqual(result["summary"]["remaining_to_produce"], 1)
        self.assertEqual(result["summary"]["to_compensate"], 0)

    def test_planned_replacement_reserves_exactly_one_need(self):
        result = reconcile([piece("p", kind="destroyed"), piece("p", "p::RT1")])
        self.assertEqual(result["summary"]["to_compensate"], 0)
        self.assertEqual(result["requirements"][0]["state"], "replacement_planned")

    def test_replacement_breaks_again_without_duplicate_need(self):
        result = reconcile([piece("p", kind="destroyed"), piece("p", "p::RT1", "destroyed")])
        self.assertEqual(result["summary"]["to_compensate"], 1)
        self.assertEqual(result["summary"]["broken_operations"], 2)
        self.assertEqual(len(result["replacement_pieces"]), 1)

    def test_receipt_matches_operation_not_commercial_identity(self):
        children = [piece("p", kind="destroyed"), piece("p", "p::RT1")]
        self.assertEqual(reconcile(children, receipts=["p"])["summary"]["produced"], 0)
        self.assertEqual(reconcile(children, receipts=["p::RT1"])["summary"]["produced"], 1)

    def test_pending_destroy_on_resolved_tree_is_counted(self):
        incidents = [dict(plan_node_id="p::RT1", incident_action="Destroy", is_active=1)]
        self.assertEqual(reconcile([piece("p", "p::RT1")], incidents=incidents)["summary"]["to_compensate"], 1)
        incidents[0]["is_active"] = 0
        self.assertEqual(reconcile([piece("p", "p::RT1")], incidents=incidents)["summary"]["to_compensate"], 0)

    def test_resize_strips_are_not_extra_broken_pieces(self):
        child = piece("p"); child["effective_length_mm"] = 500
        strip = dict(piece("p", "p__strip", "destroyed"), __generated_from_resize=1)
        result = reconcile([child, strip])
        self.assertEqual(result["summary"]["to_compensate"], 1)
        self.assertEqual(result["summary"]["broken_operations"], 0)

    def test_partial_and_unplanned_needs_are_preserved(self):
        result = reconcile([piece("p", kind="destroyed")], [demand("p"), demand("q")])
        self.assertEqual(result["summary"]["to_compensate"], 2)

    def test_reloading_does_not_mutate_or_duplicate(self):
        children = [piece("p", kind="destroyed"), piece("p", "p::RT1")]
        before = deepcopy(children)
        first = reconcile(children)
        self.assertEqual(first, reconcile(children))
        self.assertEqual(before, children)

    def test_duplicate_units_and_operations_are_rejected(self):
        with self.assertRaises(ValueError):
            reconcile([], [demand("p"), demand("p")])
        with self.assertRaises(ValueError):
            reconcile([piece("p"), piece("p")])

    def test_multiple_live_replacements_warn_without_double_count(self):
        result = reconcile([piece("p", "r1"), piece("p", "r2")], receipts=["r1", "r2"])
        self.assertEqual(result["summary"]["produced"], 1)
        self.assertTrue(result["warnings"])

    def test_endpoint_checks_permissions_and_never_saves(self):
        doc = Mock(docstatus=0)
        doc.get.side_effect = lambda key: {"mcp_mode": "Retour Terrain", "result_json": "{}"}.get(key)
        with patch.object(api.frappe, "get_doc", return_value=doc), patch.object(api, "get_requirements_for_doc", return_value={"ok": True}):
            self.assertEqual(api.get_compensation_requirements.__wrapped__("MCP"), {"ok": True})
        self.assertEqual(doc.check_permission.call_count, 2)
        doc.save.assert_not_called()

    def test_changed_commercial_thickness_does_not_count_old_piece_as_conforming(self):
        expected=dict(demand("p"),thickness_mm=8)
        existing=dict(piece("p"),thickness_mm=6)
        result=reconcile([existing],[expected])
        self.assertEqual(result["summary"]["to_compensate"],1)
        self.assertTrue(result["warnings"])
