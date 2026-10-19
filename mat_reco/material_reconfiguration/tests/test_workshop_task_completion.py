"""Atelier handoff completion follows validated plans, not their creation."""
import unittest
from unittest.mock import Mock, patch

import frappe
from mat_reco.material_reconfiguration.services import task_notifications as service
from mat_reco.material_reconfiguration.services import workshop_service


class WorkshopTaskCompletionTest(unittest.TestCase):
    def setUp(self):
        self.doc = frappe._dict(docstatus=1, status='Executed', company='UG',
            selected_sales_orders=[frappe._dict(sales_order='SO-A'), frappe._dict(sales_order='SO-B')])
        self.order = Mock(docstatus=1, company='UG')
        self.patches = [
            patch.object(service.frappe, 'get_all', return_value=['SO-A', 'SO-A', 'SO-B']),
            patch.object(service.frappe, 'db', Mock(sql=Mock(return_value=[]))),
            patch.object(service.frappe, 'get_doc', return_value=self.order),
            patch.object(service, 'close_tasks'),
            patch.object(workshop_service, '_load', return_value=([], [], {})),
        ]
        self.tasks, db, self.get_doc, self.close, self.load = [p.start() for p in self.patches]
        self.sql = db.sql
        for p in self.patches:
            self.addCleanup(p.stop)

    def test_creation_and_submission_without_execution_do_not_close(self):
        for status, docstatus in [('Simulated', 0), ('Approved', 1)]:
            self.doc.status, self.doc.docstatus = status, docstatus
            service.mcp_submitted(self.doc)
        self.tasks.assert_not_called()
        self.close.assert_not_called()

    def test_last_validated_mcp_closes_all_recipients_once_per_order(self):
        self.sql.return_value = [frappe._dict(sales_order='SO-A', docstatus=1, status='Executed')]
        self.load.return_value = ([{'id':'SO-A','requires_mcp':False,'children':[]}], [], {})
        service.mcp_submitted(self.doc)
        self.assertEqual(self.close.call_count, 2)
        self.assertEqual({c.args for c in self.get_doc.call_args_list}, {('Sales Order','SO-A'), ('Sales Order','SO-B')})
        for call in self.close.call_args_list:
            self.assertEqual(call.args, (self.order, 'workshop'))

    def test_other_unvalidated_plan_keeps_its_order_open(self):
        self.sql.return_value = [frappe._dict(sales_order='SO-A', docstatus=0, status='Simulated')]
        service.mcp_submitted(self.doc)
        self.get_doc.assert_called_once_with('Sales Order','SO-B')
        self.close.assert_called_once()
        self.assertIn('plan.docstatus < 2', self.sql.call_args.args[0])

    def test_validated_partial_plan_does_not_finish_uncovered_cutting(self):
        self.load.return_value = ([{'id':'SO-A','requires_mcp':True,'children':[]}],
                                 [{'sales_order':'SO-B','message':'Invalid dimensions'}], {})
        service.mcp_submitted(self.doc)
        self.close.assert_not_called()

    def test_invalid_branch_does_not_close(self):
        self.load.return_value = ([{'id':name, 'requires_mcp':False,
            'children':[{'invalid_message':'Invalid tree'}]} for name in ['SO-A','SO-B']], [], {})
        service.mcp_submitted(self.doc)
        self.close.assert_not_called()

    def test_no_open_task_is_idempotent(self):
        self.tasks.return_value = []
        service.mcp_submitted(self.doc)
        self.sql.assert_not_called()
        self.load.assert_not_called()
        self.close.assert_not_called()

    def test_cannot_close_unsubmitted_or_other_company_orders(self):
        self.order.docstatus = 0
        service.mcp_submitted(self.doc)
        self.close.assert_not_called()
        self.order.docstatus, self.order.company = 1, 'OTHER'
        service.mcp_submitted(self.doc)
        self.close.assert_not_called()

    def test_company_lock_serializes_validations(self):
        service.lock_workshop_validation(self.doc)
        self.sql.assert_called_once_with('SELECT name FROM `tabCompany` WHERE name=%s FOR UPDATE', 'UG')
