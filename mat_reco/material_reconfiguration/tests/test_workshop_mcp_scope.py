"""Cutting demand handoff, partial coverage and grouped-order regression tests."""
from collections import defaultdict
from contextlib import ExitStack
import hashlib
import json
import unittest
from unittest.mock import MagicMock, patch

import frappe
from mat_reco.material_reconfiguration.services import workshop_service as service
from mat_reco.material_reconfiguration.services import repack_draft_service, mcp_compensation_service, stock_candidate_service
from mat_reco.material_reconfiguration.services.cutting_plan_service import generate_material_cutting_plan
from mat_reco.material_reconfiguration.tests.test_workshop_service import Doc, work


class WorkshopMCPScopeTests(unittest.TestCase):
    def setUp(self):
        receipts = patch.object(mcp_compensation_service, 'submitted_receipts', return_value=(set(), set()))
        self.receipts = receipts.start()
        self.addCleanup(receipts.stop)
        self.orders = {}
        self.roots = []
        self.trees = {}
        for order, line in [('SO-1', 'line-1'), ('SO-2', 'line-2')]:
            row = frappe._dict(name=line, item_code='DOUBLE', item_name='Double vitrage', qty=5)
            self.orders[order] = Doc(name=order, company='UG', docstatus=1, items=[row],
                                     check_permission=lambda action: None)
            cut = {**work(line+':0', ratio=2), 'item_code': 'CUT', 'primary_item': 'RAW',
                   'sales_order': order, 'sales_order_item': line,
                   'remaining_qty': 10, 'allocatable_qty': 0, 'missing_qty': 10}
            parent = {**work(line+':root', [cut], final=True), 'sales_order_item': line}
            self.trees[order] = parent
            self.roots.append({'id': order, 'children': [parent]})

    def scope(self, orders=('SO-1',), qty=10, operation='OP-1'):
        return {'sales_order': 'SO-1', 'orders': list(orders), 'operation': operation,
                'needs': [{'sales_order': order, 'node_id': f'line-{order[-1]}:0', 'qty': qty}
                          for order in orders], 'signature': 'signed'}

    def demands(self, spec, selected=None, coverage=None, mode="Planification"):
        doc = Doc(name='MCP-NEW', company='UG', source_item='RAW', mcp_mode=mode,
                  selected_sales_orders=[frappe._dict(sales_order=order)
                                         for order in (selected or spec['orders'])],
                  workshop_request_json=json.dumps(spec))
        with ExitStack() as stack:
            stack.enter_context(patch.object(service, '_scope_signature', return_value='signed'))
            stack.enter_context(patch.object(service, '_load', return_value=(self.roots, [], {})))
            stack.enter_context(patch.object(service, '_open_mcp_coverage',
                                              return_value=defaultdict(int, coverage or {})))
            stack.enter_context(patch.object(service, '_tree', side_effect=lambda so, row, **kw: self.trees[so.name]))
            stack.enter_context(patch.object(frappe, 'get_doc', side_effect=lambda dt, name: self.orders[name]))
            stack.enter_context(patch.object(frappe, 'get_cached_value', return_value='OUVRAGE'))
            stack.enter_context(patch.object(frappe, 'get_cached_doc',
                                              return_value=Doc(name='CUT', item_name='Cut', stock_uom='PC')))
            db = stack.enter_context(patch.object(frappe, 'db', new=MagicMock()))
            db.sql.return_value = [[0]]
            demands = service.workshop_cutting_demands(doc)
        return demands, doc

    def test_five_doubles_transfer_ten_panes_and_pack_them_all(self):
        demands, _ = self.demands(self.scope())
        self.assertEqual(len(demands), 10)
        self.assertEqual(len({d['piece_uid'] for d in demands}), 10)
        result = generate_material_cutting_plan('MCP', demands,
            [{'serial_no': 'SHEET', 'length_mm': 1000, 'width_mm': 1000}])
        self.assertEqual(result['summary']['requested_piece_count'], 10)
        self.assertEqual(result['summary']['planned_piece_count'], 10)
        self.assertEqual(result['summary']['missing_piece_count'], 0)
        self.assertTrue(all(p['workshop_node_id']=='line-1:0'
                            for n in result['tree']['nodes'] for p in n['children']
                            if p['node_type']=='finished_good'))

    def test_one_line_can_fill_two_mcps_without_repeating_the_first_four_cuts(self):
        first, _ = self.demands(self.scope())
        result = generate_material_cutting_plan('MCP-1', first,
            [{'serial_no': 'SHEET-1', 'length_mm': 200, 'width_mm': 400}])
        self.assertEqual(result['summary']['planned_piece_count'], 4)
        self.assertEqual(result['summary']['missing_piece_count'], 6)
        existing = Doc(workshop_request_json=json.dumps(self.scope()))
        with patch.object(frappe, 'get_all', return_value=[frappe._dict(name='MCP-1')]), \
             patch.object(frappe, 'get_doc', return_value=existing), \
             patch.object(repack_draft_service, 'build_effective_nodes', return_value=result['tree']['nodes']):
            coverage = service._open_mcp_coverage('UG')
        self.assertEqual(coverage[('SO-1', 'line-1:0')], 4)
        request = {'qty': 10, 'shortages': [{'kind': 'cutting', 'node_id': 'line-1:0', 'qty': 10}]}
        with patch.object(service, '_open_mcp_coverage', return_value=coverage):
            request = service._uncovered_request({'company': 'UG', 'id': 'SO-1'}, request)
        self.assertEqual(request['shortages'][0]['qty'], 6)
        second, _ = self.demands(self.scope(qty=6, operation='OP-2'), coverage=coverage)
        self.assertEqual(len(second), 6)
        self.assertFalse({d['piece_uid'] for d in first} & {d['piece_uid'] for d in second})
        packed = generate_material_cutting_plan('MCP-2', second,
            [{'serial_no': 'SHEET-2', 'length_mm': 1000, 'width_mm': 1000}])
        self.assertEqual(packed['summary']['planned_piece_count'], 6)

    def test_grouping_adds_all_residual_cuts_from_another_order(self):
        demands, doc = self.demands(self.scope(), selected=['SO-1', 'SO-2'],
                                   coverage={('SO-2', 'line-2:0'): 3})
        self.assertEqual(sum(d['sales_order']=='SO-1' for d in demands), 10)
        self.assertEqual(sum(d['sales_order']=='SO-2' for d in demands), 7)
        self.assertEqual(json.loads(doc.workshop_request_json)['orders'], ['SO-1', 'SO-2'])
        # Resaving does not add the second order a second time.
        again, _ = self.demands(json.loads(doc.workshop_request_json),
                               coverage={('SO-2', 'line-2:0'): 3})
        self.assertEqual([d['piece_uid'] for d in demands], [d['piece_uid'] for d in again])
        packed = generate_material_cutting_plan('MCP', demands,
            [{'serial_no': 'SHEET', 'length_mm': 1000, 'width_mm': 1000}])
        self.assertEqual(packed['summary']['planned_piece_count'], 17)

    def test_removing_order_removes_its_demands(self):
        demands, doc = self.demands(self.scope(orders=('SO-1', 'SO-2')), selected=['SO-2'])
        self.assertEqual(len(demands), 10)
        self.assertTrue(all(d['sales_order']=='SO-2' for d in demands))
        self.assertEqual(json.loads(doc.workshop_request_json)['orders'], ['SO-2'])

    def test_final_loose_piece_does_not_recut_existing_assignment_stock(self):
        self.trees['SO-1']['children'][0].update(missing_qty=6)
        demands, _ = self.demands(self.scope())
        self.assertEqual(len(demands), 6)

    def test_fully_covered_request_cannot_turn_into_an_assembly(self):
        leaf = self.trees['SO-1']['children'][0]
        request = service.plan(leaf, 10, service.Pool())
        with patch.object(service, '_open_mcp_coverage',
                          return_value=defaultdict(int, {('SO-1', 'line-1:0'): 10})):
            request = service._uncovered_request({'id':'SO-1', 'company':'UG'}, request)
        preview = service._preview(self.roots[0], leaf, request)
        self.assertEqual(preview['action'], 'blocked')
        self.assertIn('déjà planifiées', preview['message'])

    def test_produced_panes_are_not_counted_again_as_future_cuts(self):
        doc = Doc(workshop_request_json='')
        self.receipts.return_value = ({'PRODUCED'}, {'SHEET'})
        pieces = [dict(node_type='finished_good', id=uid, piece_uid=uid,
                       sales_order='SO-1', workshop_node_id='line-1:0')
                  for uid in ('PRODUCED', 'PENDING')]
        with patch.object(frappe, 'get_all', return_value=[frappe._dict(name='MCP')]), \
             patch.object(frappe, 'get_doc', return_value=doc), \
             patch.object(repack_draft_service, 'build_effective_nodes', return_value=[{'children':pieces}]):
            self.assertEqual(dict(service._open_mcp_coverage('UG')), {('SO-1','line-1:0'):1})

    def test_creation_accepts_a_second_mcp_for_the_same_line(self):
        root = {**self.roots[0], 'company':'UG'}
        leaf = self.trees['SO-1']['children'][0]
        request = {'qty':10, 'shortages':[{'kind':'cutting', 'node_id':leaf['id'], 'qty':6}]}
        mcp = MagicMock()
        mcp.name = 'MCP-2'
        bins = [dict(serial_no='SHEET-2', item_code='RAW', warehouse='Stores',
                     length_mm=1000, width_mm=1000, thickness_mm=6)]
        with patch.object(service, '_permission'), \
             patch.object(service, 'now_datetime', return_value='2026-10-16 19:00:00'), \
             patch.object(service, '_raw_bins', return_value=bins), \
             patch.object(service, '_scope_signature', return_value='signed'), \
             patch.object(frappe, 'db', new=MagicMock()), \
             patch.object(frappe, 'new_doc', return_value=mcp), \
             patch.object(frappe, 'get_all', return_value=[Doc(name='MCP-1', workshop_request_json=json.dumps(self.scope()))]):
            result = service._prepare_mcp(root, leaf, request, Doc(name='OP-2'))
        self.assertEqual(result['mcps'], ['MCP-2'])
        scope = json.loads(mcp.update.call_args.args[0]['workshop_request_json'])
        self.assertEqual(scope['needs'][0]['qty'], 6)
        mcp.insert.assert_called_once()

    def test_unused_candidate_sheet_remains_free_but_active_input_is_blocked(self):
        row = dict(serial_no='SHEET', item_code='RAW', warehouse='Stores', thickness_mm=6)
        serial = Doc(warehouse='Stores', status='Active', custom_material_status='Full',
                     has_permission=lambda action: True)
        warehouse = Doc(check_permission=lambda action: None)
        for active in (False, True):
            with self.subTest(active=active), \
                 patch.object(stock_candidate_service, 'get_available_cutting_bins', return_value=[row]), \
                 patch.object(frappe, 'get_all', return_value=[]), \
                 patch.object(frappe, 'get_cached_value', return_value=6), \
                 patch.object(frappe, 'get_doc', side_effect=lambda dt, *a, **kw: serial if dt=='Serial No' else warehouse), \
                 patch.object(frappe, 'db', new=MagicMock()) as db:
                db.get_value.return_value = 'UG'
                def query(sql, *args, **kwargs):
                    if 'tabMCP Stock Candidate' in sql:
                        self.assertIn('c.is_active_input=1', sql)
                        return ['BUSY'] if active else []
                    return []
                db.sql.side_effect = query
                self.assertEqual(service._raw_bins('RAW','UG'), [] if active else [row])

    def test_terrain_keeps_original_scope_after_pieces_enter_inventory(self):
        self.trees['SO-1']['children'][0].update(missing_qty=0)
        demands, _ = self.demands(self.scope(), mode='Retour Terrain')
        self.assertEqual(len(demands), 10)

    def test_resaving_partial_plan_keeps_its_cuts_and_caps_only_other_coverage(self):
        demands, doc = self.demands(self.scope(), coverage={('SO-1','line-1:0'):6})
        self.assertEqual(len(demands), 4)
        again, _ = self.demands(json.loads(doc.workshop_request_json),
                               coverage={('SO-1','line-1:0'):6})
        self.assertEqual([d['piece_uid'] for d in demands], [d['piece_uid'] for d in again])

    def test_legacy_scope_counts_placed_cuts_and_excludes_current_cancelled_executed(self):
        spec = self.scope()
        uid = 'WC-' + hashlib.sha256(b'OP-1:SO-1:line-1:0:0').hexdigest()[:28]
        doc = Doc(workshop_request_json=json.dumps(spec))
        pieces = [{'node_type':'finished_good', 'piece_uid':uid},
                  {'node_type':'destroyed', 'piece_uid':'broken'},
                  {'node_type':'leftover', 'piece_uid':'leftover'}]
        with patch.object(frappe, 'get_all', return_value=[frappe._dict(name='OTHER')]) as listing, \
             patch.object(frappe, 'get_doc', return_value=doc), \
             patch.object(repack_draft_service, 'build_effective_nodes', return_value=[{'children':pieces}]):
            coverage = service._open_mcp_coverage('UG', exclude='SELF')
        self.assertEqual(dict(coverage), {('SO-1','line-1:0'):1})
        filters = listing.call_args.kwargs['filters']
        self.assertEqual(filters['name'], ['!=','SELF'])
        self.assertEqual(filters['status'], ['not in',['Cancelled','Executed']])
        self.assertEqual(filters['docstatus'], ['<',2])


if __name__ == '__main__':
    unittest.main()
