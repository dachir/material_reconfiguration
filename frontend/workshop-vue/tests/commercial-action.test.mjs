import {test} from 'node:test';
import assert from 'node:assert/strict';
import {normaliseActionRows,selectActionRow,selectAllActionRows,updateActionQuantity,proposeActionSerials,buildActionSelections,buildActionValues,actionTotals,actionSubmissionButtons,validateActionEditor,actionFieldFilters,actionIsPayment} from '../src/commercial-action.js';

const sourceRows=()=>[
 {id:'work',label:'Vitre',qty:5,ordered_qty:10,remaining_qty:5,uom:'PC',rate:100,amount:500,selected:true},
 {id:'service',label:'Rabotage',qty:20,ordered_qty:40,remaining_qty:20,uom:'ML',rate:5,amount:100,parent_id:'work',selected:false},
 {id:'other',label:'Plaque',qty:2,ordered_qty:2,remaining_qty:2,uom:'PC',rate:40,amount:80,selected:false},
];

test('commercial subsets retain the selected work and its proportional supplements',()=>{
 const rows=normaliseActionRows(sourceRows());
 updateActionQuantity(rows,'work',2);
 assert.equal(rows[1].selected,true);assert.equal(rows[1].qty,8);
 assert.deepEqual(buildActionSelections(rows,false,{target_doctype:'Quotation'}),[{id:'work',qty:2},{id:'service',qty:8}]);
 selectActionRow(rows,'work',false);
 assert(!rows[0].selected&&!rows[1].selected);
});

test('commercial children cannot be independently selected or changed',()=>{
 const rows=normaliseActionRows(sourceRows());
 updateActionQuantity(rows,'service',1);selectActionRow(rows,'service',false);
 assert.equal(rows[1].qty,20);assert.equal(rows[1].selected,true);
 selectAllActionRows(rows,false);assert(rows.every(row=>!row.selected));
 selectAllActionRows(rows,true);assert(rows.every(row=>row.selected));
});

test('delivery lines remain independently editable even when grouped under a parent',()=>{
 const rows=normaliseActionRows(sourceRows(),false,{deriveChildren:false});
 selectActionRow(rows,'service',true);updateActionQuantity(rows,'service',3);updateActionQuantity(rows,'work',1);
 assert.equal(rows[1].qty,3);assert.equal(rows[1]._parent_id,'work');assert.equal(rows[1]._derived,false);
 selectActionRow(rows,'work',false);assert.equal(rows[1].selected,true);
});

test('delivery selections preserve explicit warehouse, serials and batch only for the stock target',()=>{
 const rows=normaliseActionRows([{id:'line',qty:1,remaining_qty:2,selected:true,warehouse:'Stores - UG',serial_no:'SER-1',batch_no:'BATCH-1'}]);
 assert.deepEqual(buildActionSelections(rows,false,{target_doctype:'Bordereau Special'}),[{id:'line',qty:1,warehouse:'Stores - UG',serial_no:'SER-1',batch_no:'BATCH-1'}]);
 assert.deepEqual(buildActionSelections(rows,false,{target_doctype:'Sales Order'}),[{id:'line',qty:1}]);
});

test('values sent to the server contain only prepared headers and BL dimensions',()=>{
 const values={transaction_date:'2026-10-30',currency:'XOF',company:'UG',accounting_dimensions:{branch:'UG',unknown:'private'}};
 assert.deepEqual(buildActionValues({target_doctype:'Quotation',fields:[{fieldname:'transaction_date'}]},values),{transaction_date:'2026-10-30'});
 assert.deepEqual(buildActionValues({target_doctype:'Reglement Special',fields:[]},values),{});
 assert.deepEqual(buildActionValues({target_doctype:'Bordereau Special',fields:[],dimensions:[{fieldname:'branch'}]},values),{accounting_dimensions:{branch:'UG'}});
});

test('mixed A and B allocations count one receipt and retain its unallocated advance',()=>{
 const prep={action:'payment',target_doctype:'Reglement Special',fields:[]};
 const rows=normaliseActionRows([
  {id:'BL-A',selected:true,amount:50,remaining_amount:100,order_type:'A',currency:'XOF'},
  {id:'BL-B',selected:true,amount:30,remaining_amount:80,order_type:'B',currency:'XOF'},
 ],true);
 const totals=actionTotals(rows,{currency:'XOF',amount:100},true);
 assert.equal(totals.allocated,80);assert.equal(totals.amount_a,50);assert.equal(totals.amount_b,30);assert.equal(totals.unallocated,20);
 assert.deepEqual(buildActionSelections(rows,true),[{id:'BL-A',amount:50},{id:'BL-B',amount:30}]);
 assert.deepEqual(validateActionEditor(prep,rows,{amount:100}),[]);
});

test('advances before delivery need an amount and no selected BL',()=>{
 const prep={target_doctype:'Reglement Special',fields:[]};
 assert(actionIsPayment(prep));
 assert.deepEqual(validateActionEditor(prep,[],{amount:100}),[]);
 assert(validateActionEditor(prep,[],{amount:0}).some(error=>error.includes('encaissé')));
});

test('selection and allocation limits reject invalid amounts, NaN and excessive quantities',()=>{
 const commercial={target_doctype:'Sales Order',rows:[{}],fields:[]};
 const rows=normaliseActionRows([{id:'line',label:'Vitre',qty:3,remaining_qty:2,selected:true}]);
 assert(validateActionEditor(commercial,rows,{}).some(error=>error.includes('dépasse')));
 rows[0].qty='bad';assert(validateActionEditor(commercial,rows,{}).some(error=>error.includes('supérieure à zéro')));
 selectAllActionRows(rows,false);assert(validateActionEditor(commercial,rows,{}).some(error=>error.includes('Sélectionner')));
 const paymentRows=normaliseActionRows([{id:'BL',label:'BL',amount:120,remaining_amount:100,selected:true}],true);
 const errors=validateActionEditor({target_doctype:'Reglement Special',fields:[]},paymentRows,{amount:110});
 assert(errors.some(error=>error.includes('solde disponible')));assert(errors.some(error=>error.includes('montant encaissé')));
});

test('totals keep units and currencies separate',()=>{
 const rows=normaliseActionRows(sourceRows());selectAllActionRows(rows,true);
 const total=actionTotals(rows,{currency:'XOF'});
 assert.deepEqual(total.quantities,[{uom:'PC',qty:7},{uom:'ML',qty:20}]);
 assert.equal(total.amounts[0].amount,680);
 const other=normaliseActionRows([{id:'x',qty:1,rate:100,currency:'XOF'},{id:'e',qty:1,rate:2,currency:'EUR'}]);
 assert.deepEqual(actionTotals(other).amounts,[{currency:'XOF',amount:100},{currency:'EUR',amount:2}]);
});

test('workflow buttons expose only transitions prepared by the server without fabricating submit',()=>{
 const buttons=actionSubmissionButtons({can_save:true,can_submit:false,workflow_actions:[{action:'Send for Approval',label:'Envoyer',docstatus:0}]});
 assert.deepEqual(buttons.map(button=>button.intent),['save','workflow']);
 assert.equal(buttons[1].workflow_action,'Send for Approval');
 assert.equal(actionSubmissionButtons({can_save:false,can_submit:false}).length,0);
 assert.equal(actionSubmissionButtons({can_submit:true})[0].intent,'submit');
});

test('required stock dimensions are read from their own map, not flattened into payment headers',()=>{
 const prep={target_doctype:'Bordereau Special',fields:[{fieldname:'posting_date',label:'Date',reqd:1}],dimensions:[{fieldname:'branch',label:'Branche',reqd:1}]};
 const rows=normaliseActionRows([{id:'r',qty:1,remaining_qty:1,selected:true}]);
 assert(validateActionEditor(prep,rows,{posting_date:'2026-10-30'}).some(error=>error.includes('Branche')));
 assert.deepEqual(validateActionEditor(prep,rows,{posting_date:'2026-10-30',accounting_dimensions:{branch:'UG'}}),[]);
});

test('native Link filters resolve current form values without permissions bypass flags',()=>{
 assert.deepEqual(actionFieldFilters({filters:{company:'$company',is_group:0,name:['!=','$excluded']}},{company:'UG',excluded:'WH'}),{company:'UG',is_group:0,name:['!=','WH']});
});


test('serial suggestions exclude every other selected line and preserve manual choices',()=>{
 const candidates=[1,2,3,4].map(index=>({name:'S'+index,warehouse:'Stores - UG'}));
 const rows=normaliseActionRows([
  {id:'one',qty:2,selected:true,has_serial_no:true,warehouse:'Stores - UG',serial_no:'S1\nS2',serials:candidates},
  {id:'two',qty:2,selected:true,has_serial_no:true,warehouse:'Stores - UG',serial_no:'S3\nS4',serials:candidates},
  {id:'unselected',qty:1,selected:false,has_serial_no:true,warehouse:'Stores - UG',serial_no:'S1',serials:candidates},
 ],false,{deriveChildren:false});
 rows[0].qty=3;proposeActionSerials(rows,rows[0]);
 assert.equal(rows[0].serial_no,'S1\nS2','Insufficient candidates cannot reuse another selected line series');
 rows[1].selected=false;proposeActionSerials(rows,rows[0]);assert.equal(rows[0].serial_no,'S1\nS2\nS3');
 rows[0]._serials_manual=true;rows[0].qty=1;proposeActionSerials(rows,rows[0]);assert.equal(rows[0].serial_no,'S1\nS2\nS3');
 rows[0]._serials_manual=false;rows[0].warehouse='Other - UG';proposeActionSerials(rows,rows[0]);assert.equal(rows[0].serial_no,'');
});
