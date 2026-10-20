"""Read-model invariants. Run with unittest; no test records are inserted."""
import unittest
from unittest.mock import patch
from mat_reco.material_reconfiguration.services import glass_stock as s

ITEMS = {'RAW':dict(item_name='Clair',custom_item_types='PRIMAIRE'),
         'CUT':dict(item_name='Pièce',custom_item_types='DECOUPE',custom_parent_item='RAW')}

def serial(name='SN1', **kw):
    return dict(name=name,item_code='RAW',warehouse='A',status='Active',custom_material_status='Full',
                custom_dimension_length_mm=2000,custom_dimension_width_mm=1000,
                custom_dimension_thickness_mm=6,**kw)

class GlassStockTest(unittest.TestCase):
    def test_geometry_lineage_and_dedup(self):
        cut=serial('SN2');cut.update(item_code='CUT',custom_removed_length_mm=500,custom_removed_width_mm=400)
        rows,issues=s.physical_rows([serial(),serial(),cut],ITEMS,{'A'})
        self.assertEqual(len(rows),2)
        self.assertEqual(rows[1]['classification'],'chutes')
        self.assertAlmostEqual(rows[1]['area_m2'],1.8)
        result=s.overview(rows,ITEMS)
        self.assertEqual((result['volumes'],result['chutes']),(1,1))
        self.assertAlmostEqual(result['surface_m2'],3.8)
        self.assertFalse(issues)

    def test_warehouse_consumption_and_search(self):
        other=serial('SN2');other['warehouse']='B'
        consumed=serial('SN3');consumed['status']='Consumed'
        partial=serial('SN4');partial['custom_material_status']='Partial'
        rows,_=s.physical_rows([serial(),other,consumed,partial],ITEMS,{'A'},'SN4')
        self.assertEqual([r['serial_no'] for r in rows],['SN4'])
        self.assertEqual(rows[0]['classification'],'chutes')

    def test_invalid_geometry_never_uses_bounding_rectangle(self):
        bad=serial();bad.update(custom_removed_length_mm=2000,custom_removed_width_mm=500)
        rows,issues=s.physical_rows([bad],ITEMS,{'A'})
        self.assertIsNone(rows[0]['area_m2'])
        self.assertEqual(s.overview(rows,ITEMS)['surface_m2'],0)
        self.assertEqual(issues['invalid_geometry'],1)

    def test_missing_and_cyclic_lineage(self):
        items={**ITEMS,'BAD':dict(custom_item_types='DECOUPE',custom_parent_item='BAD')}
        self.assertIsNone(s.primary_for('BAD',items))
        self.assertIsNone(s.primary_for('ABSENT',items))

    def test_pagination(self):
        rows=[dict(serial_no=f'SN{i:04}',primary_item='RAW',classification='chutes') for i in range(240)]
        with patch.object(s,'_inventory',return_value=(rows,{},ITEMS)):
            first=s.get_stock_serials.__wrapped__('RAW',page_size=100)
            second=s.get_stock_serials.__wrapped__('RAW',cursor=first['next_cursor'],page_size=100)
            last=s.get_stock_serials.__wrapped__('RAW',cursor=second['next_cursor'],page_size=100)
        self.assertEqual(len(first['rows']),100)
        self.assertEqual(len(last['rows']),40)
        self.assertIsNone(last['next_cursor'])
        self.assertEqual(len({r['serial_no'] for p in (first,second,last) for r in p['rows']}),240)

    def test_permissions_and_warehouse_rejection(self):
        with patch.object(s.frappe,'has_permission',return_value=False),patch.object(s.frappe,'throw',side_effect=PermissionError):
            with self.assertRaises(PermissionError):s._check()
        with patch.object(s,'_check'),patch.object(s,'_read_all',return_value=[{'name':'A'}]),patch.object(s.frappe,'throw',side_effect=PermissionError):
            with self.assertRaises(PermissionError):s._inventory(warehouse='SECRET')

    def test_queries_preserve_permission_checks(self):
        with patch.object(s.frappe,'get_list',return_value=[]) as query:
            self.assertEqual(s._read_all('Serial No',['name']),[])
            self.assertNotIn('ignore_permissions',query.call_args.kwargs)

    def test_ten_thousand_serials(self):
        rows,issues=s.physical_rows([serial(f'SN{i:05}') for i in range(10000)],ITEMS,{'A'})
        result=s.overview(rows,ITEMS)
        self.assertEqual(result['total'],10000)
        self.assertEqual(result['surface_m2'],20000)
        self.assertFalse(issues)

    def test_commit_notification_discloses_no_stock(self):
        with patch.object(s.frappe,'publish_realtime') as publish:
            s.notify_stock_change(None)
            publish.assert_called_once_with('glass_stock_updated',{},after_commit=True)

    def test_missing_dimensions_and_unrounded_total(self):
        missing=serial();missing['custom_dimension_length_mm']=0
        rows,issues=s.physical_rows([missing],ITEMS,{'A'})
        self.assertIsNone(rows[0]['area_m2'])
        self.assertEqual(issues['invalid_geometry'],1)
        records=[]
        for i in range(3):
            sn=serial(str(i));sn.update(custom_dimension_length_mm=333,custom_dimension_width_mm=333)
            records.append(sn)
        rows,_=s.physical_rows(records,ITEMS,{'A'})
        self.assertAlmostEqual(s.overview(rows,ITEMS)['surface_m2'],.332667)

    def test_serial_detail_only_contains_cuts(self):
        cut=serial('CUT-FULL');cut.update(item_code='CUT')
        partial=serial('PARTIAL');partial['custom_material_status']='Partial'
        rows,_=s.physical_rows([serial('WHOLE'),cut,partial],ITEMS,{'A'})
        totals=s.overview(rows,ITEMS)
        self.assertEqual((totals['volumes'],totals['chutes'],totals['total']),(1,2,3))
        with patch.object(s,'_inventory',return_value=(rows,{},ITEMS)):
            details=s.get_stock_serials.__wrapped__('RAW')
        self.assertEqual(details['total'],2)
        self.assertEqual({r['serial_no'] for r in details['rows']},{'CUT-FULL','PARTIAL'})
        with patch.object(s,'_inventory',return_value=([r for r in rows if r['classification']=='volumes'],{},ITEMS)):
            self.assertEqual(s.get_stock_serials.__wrapped__('RAW')['rows'],[])
