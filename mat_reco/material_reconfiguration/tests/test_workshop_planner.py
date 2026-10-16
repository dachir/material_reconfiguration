"""Acceptance invariants independent of a Frappe site."""
import unittest
from copy import deepcopy
from mat_reco.material_reconfiguration.services.workshop_planner import Pool,plan,capacity,whole,stock_key,annotate


def node(name,children=(),kind='DECOUPE',ratio=1,line='line-a'):
    return dict(id=name,item_code=name,item_type=kind,children=list(children),ratio=ratio,
                sales_order_item=line,length_mm=100,width_mm=200,thickness_mm=6)


def stock(n,qty=1,owner=None,**extra):
    return dict(item_code=n['item_code'],qty=qty,owner=owner,length_mm=100,width_mm=200,thickness_mm=6,**extra)


class WorkshopPlannerTests(unittest.TestCase):
    def test_shared_stock_never_promises_eight_from_five(self):
        cut=node('cut');pool=Pool([stock(cut,5)])
        first=plan(cut,4,pool);second=plan({**cut,'sales_order_item':'line-b'},4,pool)
        self.assertEqual(sum(r['qty'] for r in first['stock']),4)
        self.assertEqual(sum(r['qty'] for r in second['stock']),1)
        self.assertEqual(second['shortages'][0]['qty'],3)

    def test_partial_one_of_three_is_fabricable(self):
        cut=node('cut',ratio=2);work=node('double',[cut],kind='OUVRAGE');pool=Pool([stock(cut,2)])
        self.assertEqual(capacity(work,3,pool,consume_existing=False),1)
        self.assertFalse(plan(work,1,pool,consume_existing=False)['shortages'])

    def test_postorder_triplex_before_double(self):
        cut=node('cut',ratio=2);triplex=node('triplex',[cut],kind='OUVRAGE')
        double=node('double',[triplex],kind='OUVRAGE')
        request=plan(double,1,Pool([stock(cut,2)]),consume_existing=False)
        self.assertEqual([t['node_id'] for t in request['tasks']],['triplex','double'])

    def test_existing_intermediate_avoids_cutting(self):
        cut=node('cut');triplex=node('triplex',[cut],kind='OUVRAGE');double=node('double',[triplex],kind='OUVRAGE')
        request=plan(double,1,Pool([stock(triplex)]),consume_existing=False)
        self.assertFalse(request['shortages'])
        self.assertEqual([t['node_id'] for t in request['tasks']],['double'])

    def test_missing_leaf_requests_cutting_without_executing(self):
        cut=node('cut');work=node('work',[cut],kind='OUVRAGE');request=plan(work,1,Pool(),consume_existing=False)
        self.assertEqual(request['shortages'][0]['kind'],'cutting')
        self.assertNotIn('stock_entries',request)

    def test_accessory_shortage_is_not_cutting(self):
        accessory=node('argon',kind='ACCESSOIRE');request=plan(accessory,1,Pool())
        self.assertEqual(request['shortages'][0]['kind'],'stock')

    def test_other_order_assignment_is_unavailable(self):
        cut=node('cut');self.assertEqual(capacity(cut,1,Pool([stock(cut,1,'other-line')])),0)

    def test_thickness_and_dimensions_are_required(self):
        cut=node('cut');wrong={**stock(cut),'thickness_mm':8}
        self.assertEqual(capacity(cut,1,Pool([wrong])),0)
        rotated={**stock(cut),'length_mm':200,'width_mm':100}
        self.assertEqual(capacity(cut,1,Pool([rotated])),1)

    def test_repeated_components_cannot_reuse_serials(self):
        cut=node('cut');second={**cut,'id':'other-path'};work=node('work',[cut,second],kind='OUVRAGE')
        self.assertEqual(capacity(work,1,Pool([stock(cut)]),consume_existing=False),0)

    def test_parent_stock_does_not_prove_final_production(self):
        cut=node('cut');work=node('work',[cut],kind='OUVRAGE')
        self.assertEqual(capacity(work,1,Pool([stock(work)]),consume_existing=False),0)

    def test_direct_cut_stock_requires_attribution_repack(self):
        cut=node('cut');request=plan(cut,1,Pool([stock(cut)]),consume_existing=False)
        self.assertFalse(request['shortages']);self.assertEqual(request['produce_qty'],1)
        self.assertEqual(len(request['assignment_inputs']),1)

    def test_invalid_or_fractional_quantity_is_rejected(self):
        for value in [-1,.5,float('nan'),float('inf')]:
            with self.assertRaises(ValueError):whole(value)

    def test_preview_capacity_does_not_consume_pool(self):
        cut=node('cut');pool=Pool([stock(cut,5)]);before=deepcopy(pool.records)
        capacity(cut,10,pool);self.assertEqual(pool.records,before)

    def test_annotation_keeps_numeric_partial_status(self):
        cut=node('cut');work=node('work',[cut],kind='OUVRAGE');pool=Pool([stock(cut)])
        allocation=plan(work,3,deepcopy(pool),consume_existing=False)
        annotate(work,allocation,pool,final=True)
        self.assertEqual(work['state'],'partial');self.assertEqual(work['fabricable_qty'],1)
        self.assertEqual(cut['allocatable_qty'],1)


if __name__=='__main__':unittest.main()
