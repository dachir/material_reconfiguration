"""Commercial provenance, frozen geometry and native ERPNext mapping boundaries."""
import json
import unittest

import frappe
from frappe.utils import add_days, nowdate
from mat_reco.material_reconfiguration.services import chantier_service as service
from mat_reco.material_reconfiguration.services.order_explosion_service import explode_frozen_decoupes


def node(code, children=None, ratio=1):
    return dict(item_code=code,label=code,item_type='OUVRAGE' if children else 'DECOUPE',
        children=children or [],ratio=ratio,length_mm=1000,width_mm=1200,thickness_mm=6,stock_uom='Nos')


class ChantierServiceTests(unittest.TestCase):
    def test_occurrences_of_identical_cut_items_keep_unique_origin(self):
        tree=node('DOUBLE',[node('CUT'),node('CUT')])
        ctx=dict(sales_order='SO',sales_order_item='ROW',root_item_code='DOUBLE',root_item_name='Double',chantier='C',repere='V1')
        results=explode_frozen_decoupes(tree,2,ctx)
        self.assertEqual(len(results),4)
        self.assertEqual(len({r['piece_uid'] for r in results}),4)
        self.assertTrue(all(r['source_context']['chantier']=='C' for r in results))

    def test_nested_ratios_and_component_thickness_are_preserved(self):
        cut=node('CUT',ratio=2);cut['thickness_mm']=4
        tree=node('DOUBLE',[node('TRIPLEX',[cut])])
        ctx=dict(sales_order='SO',sales_order_item='ROW',root_item_code='DOUBLE',root_item_name='Double')
        results=explode_frozen_decoupes(tree,3,ctx)
        self.assertEqual(len(results),6)
        self.assertTrue(all(r['thickness_mm']==4 and r['length_mm']==1000 for r in results))

    def test_noninteger_cut_quantities_rejected(self):
        ctx=dict(sales_order='SO',sales_order_item='ROW',root_item_code='CUT',root_item_name='Cut')
        with self.assertRaises(frappe.ValidationError):
            explode_frozen_decoupes(node('CUT'),1.5,ctx)

    def test_mapping_conflict_preserves_target(self):
        target=frappe._dict(custom_chantier='A')
        with self.assertRaises(frappe.ValidationError):
            service.map_chantier(target,'after_mapping',frappe._dict(doctype='Quotation',custom_chantier='B'))
        self.assertEqual(target.custom_chantier,'A')

    def test_legacy_quote_cannot_be_added_to_chantier_order(self):
        with self.assertRaises(frappe.ValidationError):
            service.map_chantier(frappe._dict(custom_chantier='A'),'after_mapping',frappe._dict(doctype='Quotation'))

    def test_mapping_does_not_touch_standard_project(self):
        target=frappe._dict(project='ERP-PROJECT',items=[])
        service.map_chantier(target,'after_mapping',frappe._dict(doctype='Quotation',custom_chantier='C'))
        self.assertEqual(target.custom_chantier,'C')
        self.assertEqual(target.project,'ERP-PROJECT')

    def test_legacy_order_workflow_unchanged(self):
        service.validate_commercial(frappe._dict(items=[frappe._dict(item_code='LEGACY')]))

    def test_unchained_snapshot_cannot_bypass_chantier_controls(self):
        with self.assertRaises(frappe.ValidationError):
            service.validate_commercial(frappe._dict(items=[frappe._dict(custom_technical_snapshot='{}')]))

    def test_geometry_must_match_accepted_quote(self):
        source=frappe._dict(item_code='A',uom='Nos',custom_client_length_mm=1000)
        target=frappe._dict(item_code='A',uom='Nos',custom_client_length_mm=1100)
        with self.assertRaises(frappe.ValidationError):
            service._check_source(target,source)

    def test_tampered_snapshot_is_rejected(self):
        source=frappe._dict(item_code='A',uom='Nos',custom_technical_snapshot='{}',custom_technical_hash='forged')
        with self.assertRaises(frappe.ValidationError):
            service._check_source(source,source)

    def test_summary_counts_final_lines_and_area_not_layers(self):
        lines=[dict(qty=2,produced=2,remaining=0,area=4,conform_area=4,state='completed',pending_quality=0),
               dict(qty=1,produced=0,remaining=1,area=6,conform_area=0,state='blocked',pending_quality=0)]
        result=service.summarize(lines)
        self.assertEqual(result['progress'],40)
        self.assertEqual(result['ouvrages'],2)
        self.assertEqual(result['remaining_qty'],1)
        self.assertEqual(result['blocked'],1)

    def test_empty_summary_has_no_division_by_zero(self):
        self.assertEqual(service.summarize([])['progress'],0)


class NativeChantierTests(unittest.TestCase):
    """Run against a glass-enabled site's real commercial configuration; all changes roll back."""
    def test_quote_order_mpp_and_sections_with_immutable_composition(self):
        from mat_reco.material_reconfiguration.services.workshop_service import _tree, get_dashboard
        from erpnext.selling.doctype.quotation.quotation import make_sales_order
        frappe.db.savepoint('native_chantier')
        parent_name=None
        try:
            source=candidate=None
            for name in frappe.get_all('Quotation',filters={'docstatus':1},pluck='name',limit=100):
                quote=frappe.get_doc('Quotation',name)
                row=next((r for r in quote.items if frappe.get_cached_value('Item',r.item_code,'custom_item_types')=='DECOUPE' and all(r.get(f) for f,n in service.DIMENSIONS)),None)
                if not row:continue
                try:_tree(frappe._dict(name='QA',company=quote.company),row,item_code=row.item_code)
                except frappe.ValidationError:continue
                source,candidate=quote,row
                break
            if not candidate:
                self.skipTest('Requires one configured glass quotation as commercial test fixture')
            chantier=frappe.get_doc(dict(doctype='Chantier',reference='QA-CHANTIER-TEST',designation='Test transactionnel',company=source.company,customer=source.party_name)).insert()
            root=frappe.get_doc(dict(doctype='Chantier Section',chantier=chantier.name,section_name='Bâtiment',is_group=1)).insert()
            child=frappe.get_doc(dict(doctype='Chantier Section',chantier=chantier.name,section_name='Étage',parent_chantier_section=root.name,is_group=1)).insert()
            self.assertEqual(service.section_scope(root.name,chantier.name),{root.name,child.name})
            bad=frappe.get_doc('Chantier Section',root.name);bad.parent_chantier_section=child.name
            frappe.db.savepoint('section_cycle')
            with self.assertRaises(frappe.ValidationError):bad.save()
            frappe.db.rollback(save_point='section_cycle')
            other=frappe.get_doc(dict(doctype='Chantier',reference='QA-CHANTIER-OTHER',designation='Autre chantier',company=source.company,customer=source.party_name)).insert()
            with self.assertRaises(frappe.ValidationError):service.section_matches(child.name,other.name)
            parent=frappe.copy_doc(frappe.get_doc('Item',candidate.item_code));parent.item_code='QA-CHANTIER-COMPOSITE';parent.item_name='QA composite';parent.name=None;parent.custom_item_types='OUVRAGE';parent.custom_is_composite=1
            parent.set('custom_composite_items',[])
            for _ in range(2):parent.append('custom_composite_items',dict(component_item_code=candidate.item_code,qty_factor=1))
            parent.insert();parent_name=parent.name
            chantier.currency=source.currency;chantier.selling_price_list=source.selling_price_list
            chantier.append('lines',dict(repere='V-001',designation='QA composite',section=child.name,proposed_item=parent.name,
                length_mm=1234,width_mm=987,thickness_mm=candidate.custom_client_thickness_mm,qty=2,uom=parent.stock_uom,rate=candidate.rate,rate_set=1))
            chantier.save()
            from mat_reco.material_reconfiguration.services.technical_study_service import prepare_study
            study=frappe.get_doc('Chantier Technical Study',prepare_study(chantier.name));study.submit();chantier.reload();chantier.submit()
            quote=frappe.copy_doc(source);quote.custom_project=None;quote.custom_chantier=chantier.name;quote.amended_from=None;quote.valid_till=add_days(nowdate(),30)
            quote.set('items',[]);row=quote.append('items',candidate.as_dict());row.name=None;row.item_code=parent.name;row.item_name=parent.item_name;row.qty=2;row.ordered_qty=0;row.is_alternative=0;row.custom_is_service_row=0;row.custom_is_accessory_row=0;row.custom_client_length_mm=1234;row.custom_client_width_mm=987;row.custom_repere='V-001';row.custom_chantier_section=child.name
            quote.insert(set_name='QA-CHANTIER-QUOTE');quote.submit()
            snapshot=quote.items[0].custom_technical_snapshot
            self.assertEqual(len(json.loads(snapshot)['children']),2)
            order=make_sales_order(quote.name);order.delivery_date=add_days(nowdate(),7)
            for r in order.items:r.delivery_date=order.delivery_date
            order.custom_customer_acceptance='QA accord client';order.insert(set_name='QA-CHANTIER-ORDER');order.submit()
            self.assertEqual(order.custom_chantier,chantier.name)
            self.assertEqual(order.items[0].custom_technical_snapshot,snapshot)
            # Master-data edits must affect neither assembly nor MCP demand explosion.
            table=frappe.get_meta('Item').get_field('custom_composite_items').options
            frappe.db.set_value(table,parent.custom_composite_items[0].name,'qty_factor',3)
            frappe.clear_document_cache('Item',parent.name)
            frozen=_tree(order,order.items[0])
            self.assertEqual([c['ratio'] for c in frozen['children']],[1,1])
            from mat_reco.material_reconfiguration.services.order_explosion_service import explode_sales_orders_into_cutting_demands
            demands=explode_sales_orders_into_cutting_demands([order.name])
            self.assertEqual(len(demands),4)
            self.assertEqual(len({d['piece_uid'] for d in demands}),4)
            plan=service.create_mpp(order.name,order.items[0].name)
            self.assertEqual(service.create_mpp(order.name,order.items[0].name),plan)
            self.assertEqual(len(frappe.get_doc('Material Production Plan',plan).nodes),3)
            dossier=service.get_dossier(chantier.name)
            self.assertEqual(dossier['summary']['ordered_qty'],2)
            self.assertEqual(dossier['summary']['remaining_qty'],2)
            self.assertEqual(dossier['by_section'][root.name]['ordered_qty'],2)
            dashboard=get_dashboard({'chantier':chantier.name,'section':root.name},expanded_orders=[order.name])
            self.assertEqual([r['id'] for r in dashboard['roots']],[order.name])
            tampered=frappe.copy_doc(order);tampered.items[0].quotation_item=None
            with self.assertRaises(frappe.ValidationError):service.validate_commercial(tampered)
            tampered=frappe.copy_doc(order);tampered.items[0].custom_client_width_mm+=10
            with self.assertRaises(frappe.ValidationError):service.validate_commercial(tampered)
            duplicate=frappe.copy_doc(order)
            with self.assertRaises(frappe.ValidationError):service.validate_commercial(duplicate)
            # Exercise the real stock hooks and the existing cockpit executor.
            from mat_reco.material_reconfiguration.services.workshop_service import preview_action, execute_action, _serials
            from mat_reco.material_reconfiguration.services.serial_creation_service import _create_or_update_serial_no
            leaf=frozen['children'][0]
            warehouse=leaf['warehouse']
            if not warehouse:
                self.fail('Configured glass quotation requires a default warehouse for native stock QA')
            serials=[]
            for index in range(4):
                serial='QA-CHANTIER-CUT-'+str(index)
                _create_or_update_serial_no(serial,leaf['item_code'],order.company,'finished_good',leaf['length_mm'],leaf['width_mm'])
                frappe.db.set_value('Serial No',serial,'custom_dimension_thickness_mm',leaf['thickness_mm'])
                serials.append(serial)
            dimensions={'branch':source.get('branch') or 'Kinshasa'}
            receipt=frappe.new_doc('Stock Entry');receipt.stock_entry_type='Material Receipt';receipt.company=order.company
            receipt.update(dimensions)
            receipt.append('items',dict(item_code=leaf['item_code'],t_warehouse=warehouse,qty=4,basic_rate=100,
                serial_no='\n'.join(serials),use_serial_batch_fields=1,quality_status='A',to_quality_status='A',
                custom_dimension_length_mm=leaf['length_mm'],custom_dimension_width_mm=leaf['width_mm'],custom_dimension_thickness_mm=leaf['thickness_mm']))
            receipt.insert();receipt.submit()
            preview=preview_action(order.name,frozen['id'],1,dimensions=dimensions)
            self.assertEqual(preview['action'],'repack')
            first=execute_action(order.name,frozen['id'],1,'qa-chantier-partial',preview['version'],dimensions=dimensions)
            self.assertEqual(execute_action(order.name,frozen['id'],1,'qa-chantier-partial',preview['version'],dimensions=dimensions),first)
            self.assertEqual(service.get_dossier(chantier.name)['summary']['progress'],50)
            with self.assertRaises(frappe.ValidationError):service.protect_produced_order(order)
            preview=preview_action(order.name,frozen['id'],1,dimensions=dimensions)
            last=execute_action(order.name,frozen['id'],1,'qa-chantier-complete',preview['version'],dimensions=dimensions)
            self.assertEqual(get_dashboard({'chantier':chantier.name})['roots'],[])
            self.assertEqual(service.get_dossier(chantier.name)['summary']['progress'],100)
            final=frappe.get_doc('Stock Entry',last['stock_entries'][-1])
            output=next(d for d in final.items if d.t_warehouse)
            issue=frappe.new_doc('Stock Entry');issue.stock_entry_type='Material Issue';issue.company=order.company;issue.update(dimensions)
            issue.append('items',dict(item_code=output.item_code,s_warehouse=output.t_warehouse,qty=1,use_serial_batch_fields=1,
                serial_no='\n'.join(_serials(output)),quality_status='A',to_quality_status='A'))
            issue.insert();issue.submit()
            self.assertEqual(service.get_dossier(chantier.name)['summary']['progress'],100)
            self.assertEqual(get_dashboard({'chantier':chantier.name})['roots'],[])
            ref=frappe.get_doc(dict(doctype='Workshop Refabrication',sales_order=order.name,sales_order_item=order.items[0].name,
                qty=1,source_stock_entry=final.name,incident_reference='QA-CHANTIER-INCIDENT',reason='QA casse explicitement déclarée'))
            ref.insert();ref.submit()
            self.assertEqual(service.get_dossier(chantier.name)['summary']['remaining_qty'],1)
            self.assertEqual(service.get_dossier(chantier.name)['summary']['progress'],50)
        finally:
            frappe.db.rollback(save_point='native_chantier')
            if parent_name:frappe.clear_document_cache('Item',parent_name)
            frappe.clear_messages()
