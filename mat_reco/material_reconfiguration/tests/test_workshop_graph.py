import unittest
from unittest.mock import patch

import frappe
from mat_reco.material_reconfiguration.services import workshop_graph as graph


class WorkshopGraphTest(unittest.TestCase):
    def setUp(self):
        self.leaves=[dict(id='LINE:0',sales_order='SO1',sales_order_item='LINE',item_code='CUT',primary_item='RAW'),
                     dict(id='LINE:1',sales_order='SO1',sales_order_item='LINE',item_code='CUT',primary_item='RAW'),
                     dict(id='OTHER:root',sales_order='SO2',sales_order_item='OTHER',item_code='CUT',primary_item='RAW')]

    def test_draft_links_every_compatible_occurrence_of_selected_orders(self):
        doc={'source_item':'RAW','selected_sales_orders':[{'sales_order':'SO1'}]}
        self.assertEqual(graph.linked_stocks(doc,self.leaves),['LINE:0:stock','LINE:1:stock'])
        doc['selected_sales_orders'].append({'sales_order':'SO2'})
        self.assertEqual(len(graph.linked_stocks(doc,self.leaves)),3)
        doc['source_item']='OTHER'
        self.assertEqual(graph.linked_stocks(doc,self.leaves),[])

    def test_scoped_mcp_does_not_link_other_occurrences(self):
        doc={'workshop_request_json':{'sales_order':'SO1','needs':[{'node_id':'LINE:1','qty':2},{'node_id':'LINE:0','qty':0}]}}
        self.assertEqual(graph.linked_stocks(doc,self.leaves),['LINE:1:stock'])

    def test_standard_and_cockpit_piece_identity(self):
        piece={'node_type':'finished_good','sales_order':'SO1','sales_order_item':'LINE','item_code':'CUT','workshop_node_id':'LINE:0'}
        doc={'result_json':{'nodes':[{'children':[piece,piece]}]}}
        self.assertEqual(graph.linked_stocks(doc,self.leaves),['LINE:0:stock'])
        piece.pop('workshop_node_id')
        self.assertEqual(graph.linked_stocks(doc,self.leaves),['LINE:0:stock','LINE:1:stock'])

    def test_permission_check_avoids_disclosing_mcp_names(self):
        with patch.object(graph.frappe,'has_permission',return_value=False),patch.object(graph.frappe,'get_list') as query:
            self.assertEqual(graph.get_workshop_mcps([{'company':'UG'}]),[])
            query.assert_not_called()
