import {test} from 'node:test';
import assert from 'node:assert/strict';
import {inheritTypeExtras} from '../src/type-extras.js';
const make=()=>({work_types:[{type_id:'T',common_extras:JSON.stringify([{key:'EDGE',item_code:'S',rate:10,factor:1}])}],lines:[{line_id:'L',work_type:'T',qty:2,length_mm:1000,width_mm:500}],commercial_extras:[]});
const catalogue=[{name:'S',item_name:'Rabotage',basis:'PERIMETRE',custom_item_types:'SERVICE',stock_uom:'Meter'}];
test('new unsaved work immediately receives type services and calculated amounts',()=>{
 const doc=make();inheritTypeExtras(doc,catalogue);assert.equal(doc.commercial_extras.length,1);assert.equal(doc.commercial_extras[0].qty,6);assert.equal(doc.commercial_extras[0].rate,10);
 doc.lines.push({line_id:'L2',work_type:'T',qty:1,length_mm:500,width_mm:500});inheritTypeExtras(doc,catalogue);assert.equal(doc.commercial_extras.length,2);assert.equal(doc.commercial_extras[1].qty,2);
});
test('dimension and type defaults recalculate while line overrides survive',()=>{
 const doc=make();inheritTypeExtras(doc,catalogue);const id=doc.commercial_extras[0].line_id;
 doc.lines[0].qty=3;inheritTypeExtras(doc,catalogue);assert.equal(doc.commercial_extras[0].qty,9);assert.equal(doc.commercial_extras[0].line_id,id);
 Object.assign(doc.commercial_extras[0],{qty:5,rate:12,inherited_qty_override:1,inherited_rate_override:1});doc.lines[0].qty=10;inheritTypeExtras(doc,catalogue);assert.equal(doc.commercial_extras[0].qty,5);assert.equal(doc.commercial_extras[0].rate,12);
});
test('manual accessories use quantity per piece and preserve independent additions',()=>{
 const doc=make();doc.work_types[0].common_extras=JSON.stringify([{key:'A',item_code:'A',qty:3,factor:2,rate:5,basis:'MANUEL'}]);doc.commercial_extras=[{line_id:'INDEPENDENT',parent_line_id:'L',item_code:'OTHER',qty:1,rate:5}];inheritTypeExtras(doc,[]);assert.equal(doc.commercial_extras[1].qty,12);
 doc.work_types[0].common_extras='[]';inheritTypeExtras(doc,[]);assert.deepEqual(doc.commercial_extras.map(e=>e.line_id),['INDEPENDENT']);
});
