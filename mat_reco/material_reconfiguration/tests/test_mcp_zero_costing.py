"""Unvalued inventory stays at zero through cutting and assembly."""
from contextlib import ExitStack
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock, patch

import frappe
from mat_reco import stock_hooks
from mat_reco.material_reconfiguration.utils import mcp_costing
from mat_reco.material_reconfiguration.services import repack_draft_service


class Doc(SimpleNamespace):
    def get(self, key, default=None):
        return getattr(self, key, default)


class MCPZeroCostingTests(TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        def reject(message, *args, **kwargs):
            raise frappe.ValidationError(message)
        self.stack.enter_context(patch.object(frappe, 'throw', side_effect=reject))
        self.dimensions = self.stack.enter_context(patch.object(frappe, 'get_all', return_value=[
            frappe._dict(name='SHEET', custom_dimension_length_mm=1000, custom_dimension_width_mm=1000)]))
        self.input = frappe._dict(item_code='RAW', qty=1, transfer_qty=1,
                                 s_warehouse='Stores', serial_no='SHEET', basic_amount=0)
        self.output = frappe._dict(item_code='CUT', qty=2, conversion_factor=1,
                                  t_warehouse='Stores', custom_cutting_node_type='finished_good',
                                  custom_dimension_length_mm=200, custom_dimension_width_mm=200,
                                  allow_zero_valuation_rate=0, set_basic_rate_manually=0)
        self.leftover = frappe._dict(item_code='RAW', qty=1, conversion_factor=1,
                                    t_warehouse='Stores', custom_cutting_node_type='leftover',
                                    custom_dimension_length_mm=800, custom_dimension_width_mm=1000,
                                    allow_zero_valuation_rate=0, set_basic_rate_manually=0)
        self.doc = Doc(items=[self.input,self.output,self.leftover], docstatus=0,
                       stock_entry_type='Repack', custom_material_cutting_plan='MCP',
                       set_total_amount=MagicMock(), set_total_incoming_outgoing_value=MagicMock())

    def allocate(self):
        return mcp_costing._allocate_area_repack_costs_from_stock_entry(self.doc)

    def test_zero_cost_is_allocated_as_zero_to_pieces_and_leftovers(self):
        result = self.allocate()
        self.assertEqual(result['total_input_cost'], 0)
        self.assertEqual(result['total_input_area_mm2'], 1000000)
        self.assertEqual(result['unit_cost_per_mm2'], 0)
        self.assertEqual([r['valuation_rate'] for r in result['lines']], [0,0])
        self.assertEqual([r['line_amount'] for r in result['lines']], [0,0])

    def test_positive_cost_still_balances_to_the_consumed_value(self):
        self.input.basic_amount=100
        result=self.allocate()
        self.assertEqual(result['total_input_cost'], 100)
        self.assertAlmostEqual(sum(r['line_amount'] for r in result['lines']),100)
        self.assertGreater(result['lines'][0]['valuation_rate'],0)

    def test_zero_cost_does_not_skip_serial_dimension_validation(self):
        self.dimensions.return_value=[]
        with self.assertRaisesRegex(frappe.ValidationError,'input area is zero'):
            self.allocate()

    def test_zero_cost_does_not_skip_output_geometry_validation(self):
        self.output.custom_dimension_length_mm=0
        with self.assertRaisesRegex(frappe.ValidationError,'Missing output dimensions'):
            self.allocate()

    def test_missing_inputs_and_uninitialized_amount_are_rejected(self):
        self.doc.items=[self.output]
        with self.assertRaisesRegex(frappe.ValidationError,'No input rows'):
            self.allocate()
        self.doc.items=[self.input,self.output]
        self.input.basic_amount=None
        with self.assertRaisesRegex(frappe.ValidationError,'basic_amount is missing'):
            self.allocate()

    def test_following_sales_order_assembly_also_accepts_zero_cost(self):
        result=mcp_costing.allocate_sales_order_repack_costs_from_stock_entry(self.doc)
        self.assertEqual(result['total_input_cost'],0)
        self.assertEqual([r['valuation_rate'] for r in result['lines']],[0,0])

    def test_mcp_validation_preserves_zero_and_marks_outputs_as_allowed(self):
        mcp=Doc(docstatus=1,source_item='RAW',source_warehouse='Stores',check_permission=MagicMock())
        with patch.object(frappe,'get_doc',return_value=mcp), \
             patch.object(mcp_costing,'_get_mcp_serial_dimension_map',return_value={}):
            stock_hooks._apply_mcp_costing(self.doc)
        self.assertEqual(self.input.basic_amount,0)
        for row in (self.output,self.leftover):
            self.assertEqual(row.basic_rate,0)
            self.assertEqual(row.basic_amount,0)
            self.assertEqual(row.valuation_rate,0)
            self.assertEqual(row.allow_zero_valuation_rate,1)
            self.assertEqual(row.set_basic_rate_manually,1)
        self.doc.set_total_incoming_outgoing_value.assert_called_once()

    def test_rate_helpers_enable_zero_and_reset_flag_for_positive_values(self):
        for apply in (stock_hooks._apply_rate_on_row,repack_draft_service._apply_rate_on_row):
            apply(self.output,0)
            self.assertEqual(self.output.allow_zero_valuation_rate,1)
            self.assertEqual(self.output.basic_amount,0)
            apply(self.output,12)
            self.assertEqual(self.output.allow_zero_valuation_rate,0)
            self.assertEqual(self.output.basic_amount,24)
