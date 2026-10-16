"""Service acceptance boundaries; stock writes are represented by ERP adapters."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch, MagicMock
import frappe
from mat_reco.material_reconfiguration.services import workshop_service as service
from mat_reco.material_reconfiguration.services.workshop_planner import Pool, plan


class Doc(SimpleNamespace):
    def get(self,key,default=None):return getattr(self,key,default)


def work(name, children=(), ratio=1, final=False):
    return dict(id=name,item_code=name,label=name,item_type='OUVRAGE' if children else 'DECOUPE',
        sales_order='SO-1',sales_order_item='line',ratio=ratio,children=list(children),
        length_mm=100,width_mm=200,thickness_mm=6,is_final=final,quality_required=False,
        warehouse='Stores',has_serial_no=True)


class WorkshopServiceTests(unittest.TestCase):
    def test_recursive_repack_consumes_new_intermediate_then_parent(self):
        cut=work('cut');triplex=work('triplex',[cut]);parent=work('double',[triplex],final=True)
        root={'id':'SO-1','children':[parent]};pool=Pool([{**cut,'qty':1,'serial_no':'CUT-1','warehouse':'Stores'}])
        request=plan(parent,1,pool,consume_existing=False)
        calls=[]
        def repack(root,n,qty,inputs,op,sequence):
            calls.append((n['id'],[s.get('serial_no') for _,stocks in inputs for s in stocks]))
            return frappe._dict(name='SE-'+n['id']),[{**n,'qty':qty,'serial_no':'NEW-'+n['id'],'warehouse':'Stores'}]
        with patch.object(service,'_repack',side_effect=repack),patch.object(service,'_prepare_mcp') as cutting:
            result=service._assemble(root,parent,request,frappe._dict(name='OP-1'))
        self.assertEqual(calls,[('triplex',['CUT-1']),('double',['NEW-triplex'])])
        self.assertEqual(result['stock_entries'],['SE-triplex','SE-double']);cutting.assert_not_called()

    def test_order_action_executes_each_work_without_a_fake_order_repack(self):
        first=work('first',[work('cut-a')],final=True)
        second=work('second',[work('cut-b')],final=True)
        root={'id':'SO-1','item_type':'ORDER','children':[first,second]}
        pool=Pool([{**work('cut-a'),'qty':1},{**work('cut-b'),'qty':1}])
        requests=[plan(n,1,pool,consume_existing=False) for n in root['children']]
        request={'children':requests}
        def repack(r,n,qty,inputs,op,sequence):return frappe._dict(name='SE-'+n['id']),[]
        with patch.object(service,'_repack',side_effect=repack) as adapter:
            result=service._assemble(root,root,request,frappe._dict(name='OP'))
        self.assertEqual(result['stock_entries'],['SE-first','SE-second'])
        self.assertEqual(adapter.call_count,2)

    def test_intermediate_quality_requires_its_own_approval(self):
        cut=work('cut');triplex={**work('triplex',[cut]),'quality_required':True}
        parent=work('double',[triplex],final=True)
        request=plan(parent,1,Pool([{**cut,'qty':1}]),consume_existing=False)
        preview=service._preview({'id':'SO-1','children':[parent]},parent,request)
        self.assertEqual(preview['action'],'blocked')
        self.assertIn('quality',[s['kind'] for s in preview['shortages']])

    def test_mcp_has_priority_over_planned_assemblies(self):
        cut=work('cut');parent=work('double',[cut],final=True);root={'id':'SO-1','children':[parent]}
        preview=service._preview(root,parent,plan(parent,1,Pool(),consume_existing=False))
        self.assertEqual(preview['action'],'mcp');self.assertEqual(preview['qty'],1)

    def test_missing_accessory_is_contextual_block(self):
        leaf={**work('argon'),'item_type':'ACCESSOIRE'};parent=work('double',[leaf],final=True)
        preview=service._preview({'id':'SO-1','children':[parent]},parent,plan(parent,1,Pool(),consume_existing=False))
        self.assertEqual(preview['action'],'blocked')

    def test_repack_failure_propagates_without_committing(self):
        cut=work('cut');parent=work('double',[cut],final=True)
        request=plan(parent,1,Pool([{**cut,'qty':1}]),consume_existing=False)
        with patch.object(service,'_repack',side_effect=RuntimeError('Stock modifié')),patch.object(frappe,'db',new=MagicMock()) as db:
            with self.assertRaisesRegex(RuntimeError,'Stock modifié'):
                service._assemble({'id':'SO-1','children':[parent]},parent,request,frappe._dict(name='OP'))
            db.commit.assert_not_called()

    def test_submitted_output_attribution_ignores_inputs_and_other_items(self):
        line=frappe._dict(name='line',item_code='double')
        so=Doc(name='SO-1',items=[line])
        se=Doc(name='SE-1',items=[
            frappe._dict(item_code='cut',qty=8,s_warehouse='Stores',custom_sales_order_item='line'),
            frappe._dict(item_code='triplex',qty=4,t_warehouse='Stores',custom_sales_order_item='line'),
            frappe._dict(item_code='double',qty=6,t_warehouse='Stores',custom_sales_order_item='line')])
        with patch.object(frappe,'db',new=MagicMock()) as db,patch.object(frappe,'get_doc',return_value=se),\
             patch.object(frappe,'get_all',return_value=[]),patch.object(service,'_quality_qty',side_effect=lambda d,s,lock=False:d.qty),\
             patch.object(service,'_serials',return_value=[]),patch.object(service,'_pending_qty',side_effect=lambda d,se,good,lock=False:max(0,d.qty-good)):
            db.sql.return_value=['SE-1'];accepted,pending,history,owners=service._receipts([so])
            query=db.sql.call_args.args[0]
        self.assertIn('se.docstatus=1',query)
        self.assertEqual(accepted['line'],6);self.assertEqual(pending['line'],0)
        # No delivery or stock balance appears in the manufacturing query.
        self.assertNotIn('Delivery',query);self.assertNotIn('tabBin',query)

    def test_saved_mcp_attribution_survives_later_tree_changes(self):
        line=frappe._dict(name='line',item_code='cut');so=Doc(name='SO-1',items=[line])
        se=Doc(name='SE',custom_material_cutting_plan='MCP',
            custom_workshop_allocations_json='{"CUT-1":{"sales_order_item":"line","item_code":"cut"}}',
            items=[frappe._dict(item_code='cut',qty=1,t_warehouse='Stores')])
        with patch.object(frappe,'db',new=MagicMock()) as db,patch.object(frappe,'get_doc',return_value=se),\
             patch.object(frappe,'get_all',return_value=[]),patch.object(service,'_quality_qty',return_value=1),\
             patch.object(service,'_serials',return_value=['CUT-1']),patch.object(service,'_mcp_output_mapping') as mutable_tree:
            db.sql.return_value=['SE'];accepted,_,_,owners=service._receipts([so])
        self.assertEqual(accepted['line'],1);self.assertEqual(owners['CUT-1'],'line')
        mutable_tree.assert_not_called()

    def test_quality_pending_does_not_prove_conformity(self):
        line=frappe._dict(name='line',item_code='double');so=Doc(name='SO-1',items=[line])
        se=Doc(name='SE',items=[frappe._dict(item_code='double',qty=10,t_warehouse='Stores',custom_sales_order_item='line')])
        with patch.object(frappe,'db',new=MagicMock()) as db,patch.object(frappe,'get_doc',return_value=se),\
             patch.object(frappe,'get_all',return_value=[]),patch.object(service,'_quality_qty',return_value=6),\
             patch.object(service,'_serials',return_value=[]),patch.object(service,'_pending_qty',side_effect=lambda d,se,good,lock=False:max(0,d.qty-good)):
            db.sql.return_value=['SE'];accepted,pending,_,_=service._receipts([so])
        self.assertEqual(accepted['line'],6);self.assertEqual(pending['line'],4)

    def test_completed_root_is_removed_and_stale_node_rejected(self):
        with patch.object(frappe,'throw',side_effect=frappe.ValidationError):
            with self.assertRaises(frappe.ValidationError):service._select([],'SO-1','line:root')

    def test_permission_failure_precedes_stock_actions(self):
        with patch.object(frappe,'has_permission',return_value=False),patch.object(frappe,'throw',side_effect=frappe.PermissionError):
            with self.assertRaises(frappe.PermissionError):service._permission('Stock Entry','submit')

    def test_changed_stock_changes_confirmation_signature(self):
        root={'id':'SO-1'};n=work('double');request={'qty':1,'stock':[{'serial_no':'SN-1'}]}
        with patch('frappe.utils.password.get_encryption_key',return_value='test-only-key'),\
             patch.object(frappe,'session',frappe._dict(user='test'),create=True):
            first=service._version(root,n,request)
            second=service._version(root,n,{**request,'stock':[{'serial_no':'SN-2'}]})
        self.assertNotEqual(first,second)

    def test_mcp_scope_tampering_changes_signature(self):
        scope={'sales_order':'SO','needs':[{'node_id':'line:0','qty':1}]}
        with patch('frappe.utils.password.get_encryption_key',return_value='test-only-key'):
            first=service._scope_signature(scope);scope['needs'][0]['qty']=5
            self.assertNotEqual(first,service._scope_signature(scope))


if __name__=='__main__':unittest.main()
