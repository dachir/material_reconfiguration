"""Native ERPNext tests: draft definitions, atomic serialized Items and approved sales conversion."""
import copy
import json
import unittest

import frappe
from frappe.utils import nowdate, add_days
from mat_reco.material_reconfiguration.services import technical_study_service as service


class TechnicalStudyTests(unittest.TestCase):
    def setUp(self):
        frappe.db.savepoint('qa_technical')
        self.user=frappe.session.user;frappe.set_user('Administrator')
        self.company='Marsavco SA'
        if not frappe.db.exists('Company',self.company) or not frappe.db.exists('Customer','AQUA LOISIR'):
            self.skipTest('Requires glass-enabled site commercial configuration')
        self.warehouse=frappe.db.get_value('Warehouse',{'company':self.company,'is_group':0,'disabled':0},'name')
        self.group=frappe.db.get_value('Item Group',{'is_group':0},'name')
        self.doc=frappe.get_doc(dict(doctype='Chantier',reference='QA-TECHNICAL-TEST',designation='Étude QA',company=self.company,
            customer='AQUA LOISIR',currency='USD',selling_price_list='Standard Selling',lines=[dict(repere='V-1',designation='Vitrage à définir',qty=4,uom='PC',rate=100,rate_set=1,length_mm=1200,width_mm=1500,thickness_mm=8)])).insert()

    def tearDown(self):
        frappe.set_user(self.user);frappe.db.rollback(save_point='qa_technical');frappe.clear_messages()
        for code in ('QA-TECH-RAW','QA-TECH-CUT','QA-TECH-SUB','QA-TECH-FG','QA-EXTRA-SERVICE','QA-EXTRA-ACCESSORY'):
            frappe.clear_document_cache('Item',code)

    def test_commercial_identifiers_are_automatic_unique_and_stable(self):
        original = self.doc.lines[0].repere
        for repere in ('OUV-001', None, None):
            self.doc.append('lines', dict(repere=repere, designation='Ouvrage commercial', qty=1, uom='PC'))
        self.doc.save()
        expected = [original, 'OUV-001', 'OUV-002', 'OUV-003']
        self.assertEqual([r.repere for r in self.doc.lines], expected)
        self.doc.save()
        self.assertEqual([r.repere for r in self.doc.lines], expected)

    def extras(self):
        for code,kind,basis in [('QA-EXTRA-SERVICE','SERVICE','PERIMETRE'),('QA-EXTRA-ACCESSORY','ACCESSOIRE','SURFACE')]:
            frappe.get_doc(dict(doctype='Item',item_code=code,item_name=code,item_group=self.group,stock_uom='PC',
                is_stock_item=0,is_sales_item=1,custom_item_types=kind,custom_service_calc_basis=basis)).insert()
            self.doc.append('commercial_extras',dict(parent_line_id=self.doc.lines[0].line_id,item_code=code,
                qty=8,manual_qty=int(kind=='ACCESSOIRE'),rate=5,rate_set=1))
        self.doc.save()

    def test_extras_follow_parent_into_partial_quote_and_sales_order(self):
        self.extras()
        self.assertAlmostEqual(self.doc.commercial_extras[0].qty,21.6)
        self.assertEqual(self.doc.commercial_extras[1].calculation_basis,'MANUEL')
        study=self.study()
        self.assertEqual(len(study.lines),1)
        study.submit();self.doc.reload();self.doc.submit()
        quote=frappe.get_doc('Quotation',service.generate_quotation(self.doc.name,
            json.dumps([dict(line_id=self.doc.lines[0].line_id,qty=2)]),'qa-extras-quote',submit=True))
        self.assertEqual(len(quote.items),3)
        parent=next(r for r in quote.items if r.item_code=='QA-TECH-FG')
        extras=[r for r in quote.items if r.item_code.startswith('QA-EXTRA-')]
        self.assertEqual([r.qty for r in extras],[10.8,4])
        self.assertTrue(all(r.custom_parent_row==parent.name and not r.custom_technical_snapshot for r in extras))
        order=frappe.get_doc('Sales Order',service.confirm_order(quote.name,'Accord client test',add_days(nowdate(),7),'qa-extras-order'))
        order_parent=next(r for r in order.items if r.item_code=='QA-TECH-FG')
        self.assertTrue(all(r.custom_parent_row==order_parent.name for r in order.items if r.item_code.startswith('QA-EXTRA-')))

    def test_extra_approval_and_quote_tampering(self):
        self.extras();self.approve()
        name=service.generate_quotation(self.doc.name,request_key='qa-extra-tamper')
        quote=frappe.get_doc('Quotation',name)
        extra=next(r for r in quote.items if r.custom_is_service_row)
        extra.rate+=1
        with self.assertRaises(frappe.ValidationError):quote.save()
        quote.reload();quote.set('items',[r for r in quote.items if not r.custom_is_service_row])
        with self.assertRaises(frappe.ValidationError):quote.save()

    def test_service_bases_use_commercial_parent_only(self):
        from mat_reco.material_reconfiguration.services.chantier_extras import quantity
        item=frappe._dict(custom_item_types='SERVICE',custom_service_fixed_qty=7)
        parent=frappe._dict(length_mm=1200,width_mm=1500,qty=4)
        for basis,expected in [('SURFACE',7.2),('PERIMETRE',21.6),('PIECE',4),('FIXE',7),('MANUEL',0)]:
            item.custom_service_calc_basis=basis
            self.assertAlmostEqual(quantity(item,parent)[1],expected)
        item.custom_item_types='ACCESSOIRE'
        self.assertEqual(quantity(item,parent),('MANUEL',0))

    def test_batch_extras_calculate_each_parent_and_skip_existing(self):
        from mat_reco.material_reconfiguration.services.chantier_extras import preview_batch
        self.extras();self.doc.set('commercial_extras',[])
        self.doc.append('lines',dict(designation='Second ouvrage',qty=2,uom='PC',length_mm=1000,width_mm=1000,thickness_mm=8))
        self.doc.save()
        parents=[r.line_id for r in self.doc.lines]
        choices=[dict(item_code='QA-EXTRA-SERVICE',manual_qty=0,rate=15,rate_set=1),
                 dict(item_code='QA-EXTRA-ACCESSORY',manual_qty=1,qty=3,rate=2,rate_set=1)]
        result=preview_batch(self.doc.name,self.doc.modified,parents,choices)
        self.assertEqual(len(result['rows']),4)
        self.assertEqual(result['skipped'],0)
        service_rows=[r for r in result['rows'] if r['item_type']=='SERVICE']
        self.assertEqual([r['qty'] for r in service_rows],[21.6,8])
        self.assertTrue(all(r['rate']==15 for r in service_rows))
        self.assertTrue(all(r['qty']==3 for r in result['rows'] if r['item_type']=='ACCESSOIRE'))
        self.doc.reload();self.assertFalse(self.doc.commercial_extras)  # preview writes nothing
        for row in result['rows']:self.doc.append('commercial_extras',{k:row.get(k) for k in service.chantier_extras.FIELDS})
        self.doc.save()
        repeated=preview_batch(self.doc.name,self.doc.modified,parents,choices)
        self.assertFalse(repeated['rows']);self.assertEqual(repeated['skipped'],4)

    def test_batch_rejects_foreign_parent_and_negative_common_price(self):
        from mat_reco.material_reconfiguration.services.chantier_extras import preview_batch
        self.extras();self.doc.set('commercial_extras',[]);self.doc.save()
        with self.assertRaises(frappe.ValidationError):
            preview_batch(self.doc.name,self.doc.modified,['foreign-line'],[dict(item_code='QA-EXTRA-SERVICE')])
        with self.assertRaises(frappe.ValidationError):
            preview_batch(self.doc.name,self.doc.modified,[self.doc.lines[0].line_id],[dict(item_code='QA-EXTRA-SERVICE',rate=-10)])
        self.doc.reload();self.assertFalse(self.doc.commercial_extras)

    def test_batch_price_confirmation_is_optional_at_submission(self):
        from mat_reco.material_reconfiguration.services.chantier_extras import preview_batch
        self.extras();self.doc.set('commercial_extras',[]);self.doc.save()
        result=preview_batch(self.doc.name,self.doc.modified,[self.doc.lines[0].line_id],
            [dict(item_code='QA-EXTRA-SERVICE',rate=10,rate_set=0)])
        self.assertEqual(result['rows'][0]['rate'],10)
        self.assertEqual(result['rows'][0]['rate_set'],0)
        self.doc.append('commercial_extras',{k:result['rows'][0].get(k) for k in service.chantier_extras.FIELDS})
        self.doc.save();self.study().submit();self.doc.reload()
        self.doc.submit()
        self.assertEqual(self.doc.docstatus,1)
        self.assertEqual(self.doc.commercial_extras[0].rate_set,0)

    def test_browser_integer_numbers_reuse_approved_technical_dimensions(self):
        self.extras();self.doc.set('commercial_extras',[])
        self.doc.lines[0].length_mm=0;self.doc.lines[0].width_mm=0;self.doc.lines[0].thickness_mm=0
        self.doc.save()
        study=self.study();study.lines[0].length_mm=1200;study.lines[0].width_mm=1500;study.lines[0].thickness_mm=8
        study.save();study.submit();self.doc.reload()
        before=service.source_hash(self.doc)
        payload=[{k:r.get(k) for k in service.MACRO_FIELDS+('rate','rate_set','price_source')} for r in self.doc.lines]
        for row in payload:
            for field in ('length_mm','width_mm','thickness_mm'):row[field]=int(row[field])
        result=service.save_commercial(self.doc.name,str(self.doc.modified),json.dumps(payload),currency=self.doc.currency,
            selling_price_list=self.doc.selling_price_list,commercial_extras=json.dumps([dict(parent_line_id=self.doc.lines[0].line_id,
                item_code='QA-EXTRA-SERVICE',manual_qty=0,qty=0,rate=10,rate_set=1)]))
        self.doc.reload()
        self.assertEqual(service.source_hash(self.doc),before)
        self.assertAlmostEqual(result['commercial_extras'][0]['qty'],21.6)
        self.assertEqual(service.approved_study(self.doc).name,study.name)

    def test_commercial_hash_accepts_browser_prices_after_database_round_trip(self):
        self.extras();study=self.study();study.submit();self.doc.reload()
        self.doc.lines[0].rate_set=0
        for row in self.doc.commercial_extras:row.rate=int(row.rate);row.rate_set=0
        self.doc.save();self.doc.submit()
        approved=self.doc.commercial_hash
        self.doc.reload()
        self.assertEqual(service.commercial_hash(self.doc,study),approved)
        for mode in ('stored','browser'):
            self.doc.commercial_hash=service.commercial_hash(self.doc,study,legacy=mode)
            self.assertTrue(service.commercial_hash_matches(self.doc,study))
            self.doc.commercial_extras[0].rate+=1
            self.assertFalse(service.commercial_hash_matches(self.doc,study))
            self.doc.commercial_extras[0].rate-=1
        self.doc.reload()
        quote=service.generate_quotation(self.doc.name,request_key='qa-prices-roundtrip')
        self.assertEqual(len(frappe.get_doc('Quotation',quote).items),3)

    def definition(self):
        def node(code,kind,children=None,ratio=1):
            return dict(mode='new',proposed_code=code,item_type=kind,item_name=code,stock_uom='PC',item_group=self.group,
                warehouse=self.warehouse,quality_required=0,qty_factor=ratio,children=children or [])
        raw=node('QA-TECH-RAW','PRIMAIRE');raw.update(length_mm=3500,width_mm=2600,thickness_mm=4)
        cut=node('QA-TECH-CUT','DECOUPE',[raw],ratio=2)
        sub=node('QA-TECH-SUB','OUVRAGE',[cut])
        return node('QA-TECH-FG','OUVRAGE',[sub])

    def study(self,tree=None):
        name=service.prepare_study(self.doc.name)
        doc=frappe.get_doc('Chantier Technical Study',name)
        doc.lines[0].tree_json=json.dumps(tree or self.definition());doc.save()
        return doc

    def approve(self):
        study=self.study();study.submit();self.doc.reload();self.doc.submit();return study

    def test_draft_definitions_do_not_create_items_and_submit_is_blocked_without_study(self):
        study=self.study()
        self.assertEqual(study.docstatus,0)
        self.assertFalse(frappe.db.exists('Item','QA-TECH-FG'))
        with self.assertRaises(frappe.ValidationError):self.doc.submit()
        with self.assertRaises(frappe.ValidationError):service.generate_quotation(self.doc.name,request_key='too-early')

    def test_submit_creates_serialized_items_bottom_up_without_stock(self):
        study=self.study();study.submit()
        for code,kind in [('QA-TECH-RAW','PRIMAIRE'),('QA-TECH-CUT','DECOUPE'),('QA-TECH-SUB','OUVRAGE'),('QA-TECH-FG','OUVRAGE')]:
            item=frappe.get_doc('Item',code)
            self.assertEqual(item.custom_item_types,kind);self.assertEqual(item.has_serial_no,1);self.assertEqual(item.has_batch_no,0)
            self.assertEqual(frappe.db.count('Serial No',{'item_code':code}),0)
            self.assertEqual(item.item_defaults[0].default_warehouse,self.warehouse)
        self.assertEqual(frappe.get_doc('Item','QA-TECH-CUT').custom_parent_item,'QA-TECH-RAW')
        self.assertEqual(frappe.get_doc('Item','QA-TECH-SUB').custom_composite_items[0].qty_factor,2)
        self.assertTrue(study.lines[0].snapshot_hash)
        self.assertEqual(study.lines[0].result_item,'QA-TECH-FG')

    def test_reused_components_accept_browser_integer_dimensions(self):
        self.study().submit()
        tree=service.seed_item('QA-TECH-FG')
        raw=tree['children'][0]['children'][0]['children'][0]
        for field in ('length_mm','width_mm','thickness_mm'):
            raw[field]=int(raw[field])
        service.validate_node(tree)
        raw['thickness_mm']+=1
        with self.assertRaises(frappe.ValidationError):
            service.validate_node(tree)

    def test_double_glazing_keeps_total_and_glass_thickness_separate(self):
        tree=self.definition()
        cut=tree['children'][0]['children'][0]
        cut['children'][0]['thickness_mm']=6
        tree['children']=[cut]
        tree['air_gap_mm']=12
        study=self.study(tree)
        study.lines[0].thickness_mm=24
        study.notes='Double vitrage 6 / 12 / 6 : lame d’air de 12 mm.'
        study.save();study.submit()
        snapshot=json.loads(study.lines[0].snapshot_json)
        self.assertEqual(snapshot['air_gap_mm'],12)
        self.assertEqual(snapshot['thickness_mm'],24)
        self.assertEqual(snapshot['children'][0]['thickness_mm'],6)
        self.assertEqual(snapshot['children'][0]['ratio'],2)
        self.assertEqual(frappe.get_doc('Item','QA-TECH-RAW').custom_thickness_mm,6)

    def test_total_thickness_must_include_glass_and_air(self):
        tree=self.definition();tree['air_gap_mm']=12
        study=self.study(tree)
        study.lines[0].thickness_mm=24
        study.save()
        with self.assertRaisesRegex(frappe.ValidationError,'20 mm calculés'):
            study.submit()
        self.assertFalse(frappe.db.exists('Item','QA-TECH-FG'))
        study.reload();study.lines[0].thickness_mm=20
        study.save();study.submit()

    def test_air_gap_must_fit_inside_total_thickness(self):
        for gap in (-1,24,25):
            with self.subTest(gap=gap):
                tree=self.definition();tree['air_gap_mm']=gap
                study=self.study(tree);study.lines[0].thickness_mm=24
                study.save()
                with self.assertRaises(frappe.ValidationError):study.submit()
                study.reload()

    def test_failed_parent_creation_rolls_back_all_new_children(self):
        tree=self.definition();tree['proposed_code']='CVC0001'
        study=self.study(tree)
        with self.assertRaises(frappe.ValidationError):study.submit()
        self.assertFalse(frappe.db.exists('Item','QA-TECH-RAW'))
        self.assertFalse(frappe.db.exists('Item','QA-TECH-CUT'))
        self.assertEqual(frappe.db.get_value('Chantier Technical Study',study.name,'docstatus'),0)

    def test_source_change_requires_new_technical_validation(self):
        study=self.study();self.doc.lines[0].qty=5;self.doc.save()
        with self.assertRaises(frappe.ValidationError):study.submit()
        self.assertFalse(frappe.db.exists('Item','QA-TECH-FG'))

    def test_old_nonserialized_test_item_is_not_a_model(self):
        with self.assertRaises(frappe.ValidationError):service.seed_item('TVH0002')
        self.assertEqual(frappe.db.get_value('Item','TVH0002','has_serial_no'),0)

    def test_empty_and_cyclic_definitions_are_rejected(self):
        with self.assertRaises(frappe.ValidationError):service.validate_node(dict(mode='new',proposed_code='EMPTY',item_type='OUVRAGE'))
        tree=self.definition();tree['children'][0]['proposed_code']='QA-TECH-FG'
        with self.assertRaises(frappe.ValidationError):service.validate_node(tree)

    def test_existing_code_is_reused_only_for_equal_definition(self):
        study=self.study();study.submit()
        before=frappe.db.count('Item')
        self.assertEqual(service._resolve(self.definition(),self.company,[]),'QA-TECH-FG')
        self.assertEqual(frappe.db.count('Item'),before)
        legacy=self.definition();legacy['quality_required']=1
        self.assertEqual(service._resolve(legacy,self.company,[]),'QA-TECH-FG')
        different=self.definition();different['children'][0]['qty_factor']=2
        with self.assertRaises(frappe.ValidationError):service._resolve(different,self.company,[])

    def test_partial_quote_idempotence_capacity_and_confirmed_order(self):
        study=self.approve();line=self.doc.lines[0]
        part=[dict(line_id=line.line_id,qty=2)]
        quote=service.generate_quotation(self.doc.name,json.dumps(part),'qa-quote-partial',submit=True)
        self.assertEqual(service.generate_quotation(self.doc.name,json.dumps(part),'qa-quote-partial',submit=True),quote)
        with self.assertRaises(frappe.ValidationError):service.generate_quotation(self.doc.name,json.dumps([dict(line_id=line.line_id,qty=1)]),'qa-quote-partial',submit=True)
        document=frappe.get_doc('Quotation',quote)
        self.assertEqual(document.docstatus,1);self.assertEqual(document.items[0].qty,2)
        self.assertEqual(document.items[0].custom_technical_snapshot,study.lines[0].snapshot_json)
        with self.assertRaises(frappe.ValidationError):service.generate_quotation(self.doc.name,json.dumps([dict(line_id=line.line_id,qty=3)]),'qa-over-capacity')
        with self.assertRaises(frappe.ValidationError):service.confirm_order(quote,'',add_days(nowdate(),7),'qa-no-client')
        name=service.confirm_order(quote,'QA acceptation client',add_days(nowdate(),7),'qa-so-confirm')
        order=frappe.get_doc('Sales Order',name)
        self.assertEqual(order.docstatus,1);self.assertEqual(order.custom_technical_study,study.name)
        self.assertEqual(order.items[0].custom_chantier_line,line.line_id)
        self.assertEqual(service.confirm_order(quote,'QA acceptation client',add_days(nowdate(),7),'qa-so-confirm'),name)
        self.assertFalse(frappe.db.count('Serial No',{'item_code':'QA-TECH-FG'}))

    def test_commercial_approval_preserves_unconfirmed_price(self):
        study=self.study();study.submit();self.doc.reload();self.doc.lines[0].rate_set=0;self.doc.save()
        self.doc.submit()
        self.assertEqual(self.doc.lines[0].rate_set,0)
        quote=frappe.get_doc('Quotation',service.generate_quotation(self.doc.name,request_key='qa-optional-price'))
        self.assertEqual(quote.items[0].rate,100)

    def test_sales_cannot_be_created_while_only_technical_is_approved(self):
        study=self.study();study.submit()
        with self.assertRaises(frappe.ValidationError):service.generate_quotation(self.doc.name,request_key='qa-no-commercial')

    def test_guest_cannot_read_technical_documents(self):
        study=self.study();frappe.set_user('Guest')
        with self.assertRaises(frappe.PermissionError):service.get_study(study.name)

    def test_standard_cancel_amend_clones_sections_without_a_circular_lock(self):
        section=frappe.get_doc(dict(doctype='Chantier Section',chantier=self.doc.name,section_name='Bâtiment QA',is_group=1)).insert()
        self.doc.lines[0].section=section.name;self.doc.save()
        study=self.approve()
        study.cancel();self.doc.reload();self.doc.cancel()
        amendment=frappe.copy_doc(self.doc,ignore_no_copy=False);amendment.amended_from=self.doc.name;amendment.docstatus=0;amendment.insert()
        self.assertEqual(amendment.docstatus,0)
        self.assertNotEqual(amendment.name,self.doc.name)
        self.assertNotEqual(amendment.lines[0].section,section.name)
        self.assertEqual(frappe.db.get_value('Chantier Section',amendment.lines[0].section,'chantier'),amendment.name)

    def test_draft_save_rejects_stale_browser_version(self):
        study=self.study();stamp=str(study.modified)
        rows=[dict(line_id=r.line_id,length_mm=r.length_mm,width_mm=r.width_mm,thickness_mm=r.thickness_mm,tree_json=r.tree_json) for r in study.lines]
        result=service.save_study(study.name,stamp,json.dumps(rows),'Notes QA')
        self.assertEqual(result['study']['notes'],'Notes QA')
        with self.assertRaises(frappe.ValidationError):service.save_study(study.name,stamp,json.dumps(rows),'Écrasement ancien écran')
        self.assertFalse(frappe.db.exists('Item','QA-TECH-FG'))

    def test_catalog_lookup_and_approved_zero_price(self):
        study=self.study();study.submit()
        price=frappe.get_doc(dict(doctype='Item Price',item_code='QA-TECH-FG',price_list='Standard Selling',price_list_rate=125,uom='PC'))
        price.insert()
        found=service.get_rate(self.doc.name,'QA-TECH-FG','PC')
        self.assertTrue(found['found']);self.assertEqual(found['rate'],125)
        self.doc.reload();self.doc.lines[0].rate=0;self.doc.lines[0].rate_set=1;self.doc.save();self.doc.submit()
        name=service.generate_quotation(self.doc.name,request_key='qa-free-price')
        quote=frappe.get_doc('Quotation',name)
        self.assertEqual(quote.items[0].rate,0)
        self.assertEqual(quote.grand_total,0)

    def test_new_study_carries_forward_definition_after_macro_revision(self):
        previous=self.study()
        self.doc.lines[0].qty=5;self.doc.save()
        name=service.prepare_study(self.doc.name)
        current=frappe.get_doc('Chantier Technical Study',name)
        self.assertNotEqual(name,previous.name)
        self.assertEqual(json.loads(current.lines[0].tree_json),json.loads(previous.lines[0].tree_json))
        current.submit()
        self.assertEqual(current.lines[0].result_item,'QA-TECH-FG')

    def test_delete_draft_study_and_prepare_again(self):
        study=self.study()
        self.assertEqual(service.delete_study(study.name,str(study.modified)),self.doc.name)
        self.assertFalse(frappe.db.exists(study.doctype,study.name))
        self.assertFalse(frappe.db.exists('Item','QA-TECH-FG'))
        replacement=self.study()
        self.assertEqual(replacement.docstatus,0)

    def test_approved_study_must_be_cancelled_before_deletion(self):
        study=self.study();study.submit()
        with self.assertRaises(frappe.ValidationError):
            service.delete_study(study.name,str(study.modified))
        study.cancel()
        service.delete_study(study.name,str(study.modified))
        self.assertFalse(frappe.db.exists(study.doctype,study.name))
        self.assertTrue(frappe.db.exists('Item','QA-TECH-FG'))

    def test_cancel_draft_chantier_requires_no_active_study(self):
        study=self.study()
        with self.assertRaises(frappe.ValidationError):
            service.cancel_dossier(self.doc.name,str(self.doc.modified))
        service.delete_study(study.name,str(study.modified))
        service.cancel_dossier(self.doc.name,str(self.doc.modified))
        self.doc.reload()
        self.assertEqual(self.doc.status,'Cancelled')
        with self.assertRaises(frappe.ValidationError):service.prepare_study(self.doc.name)
        self.doc.designation='Modification interdite'
        with self.assertRaises(frappe.ValidationError):self.doc.save()

    def test_cancel_chantier_rejects_uncancelled_quotation(self):
        self.approve()
        quote=service.generate_quotation(self.doc.name,request_key='qa-cancel-block')
        with self.assertRaises(frappe.ValidationError):
            service.cancel_dossier(self.doc.name,str(self.doc.modified))
        self.assertTrue(frappe.db.exists('Quotation',quote))

    def test_designation_suggestions_are_unique_and_limited_to_ten(self):
        for i in range(12):
            self.doc.append('lines',dict(designation=f'QA-AUTOCOMPLETE-{i:02}',qty=1,uom='PC'))
        self.doc.append('lines',dict(designation='QA-AUTOCOMPLETE-00',qty=1,uom='PC'))
        self.doc.save()
        result=service.designation_suggestions('QA-AUTOCOMPLETE-')
        self.assertEqual(result,[f'QA-AUTOCOMPLETE-{i:02}' for i in range(10)])

    def test_air_component_counts_thickness_without_creating_stock_item(self):
        tree=self.definition()
        tree['children'].append(dict(mode='air',item_type='AIR',thickness_mm=12,qty_factor=1,children=[]))
        study=self.study(tree);study.lines[0].thickness_mm=20
        study.save();study.submit()
        snapshot=json.loads(study.lines[0].snapshot_json)
        self.assertEqual(snapshot['air_gap_mm'],12)
        self.assertEqual(snapshot['air_layers'][0]['thickness_mm'],12)
        self.assertEqual(len(frappe.get_doc('Item','QA-TECH-FG').custom_composite_items),1)
        self.assertEqual(len(snapshot['children']),1)
        existing=service.seed_item('QA-TECH-FG')
        existing['children'].append(dict(mode='air',item_type='AIR',thickness_mm=12,qty_factor=1,children=[]))
        service.validate_node(existing)
        self.assertEqual(service._resolve(existing,self.company,[]),'QA-TECH-FG')

    def test_air_component_requires_positive_thickness_and_no_children(self):
        for thickness,children in [(0,[]),(-2,[]),(12,[dict(item_type='AIR')])]:
            tree=self.definition()
            tree['children'].append(dict(mode='air',item_type='AIR',thickness_mm=thickness,children=children))
            with self.assertRaises(frappe.ValidationError):service.validate_node(tree)
