import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {test} from 'node:test';

const reportsRoot = new URL('../../../mat_reco/material_reconfiguration/report/', import.meta.url);

function report(folder, name) {
 const definitions={};let selected='All';
 const context={frappe:{query_reports:definitions,query_report:{get_filter_value:()=>selected},defaults:{get_user_default:()=>''},datetime:{month_start:()=> '2026-10-01',get_today:()=> '2026-10-30'}},__:value=>value,format_currency:(value,currency,precision)=>({value,currency,precision})};
 const code=fs.readFileSync(new URL(`${folder}/${folder}.js`,reportsRoot),'utf8');
 vm.runInNewContext(code,context);
 return {definition:definitions[name],select:value=>{selected=value;},context};
}

for (const [folder,name] of [['suivi_commandes','Suivi commandes'],['situation_des_comptes_clients','Situation des comptes clients']]) {
 test(`${name} defaults to A + B and permits choosing either type`,()=>{
  const {definition}=report(folder,name);
  assert(definition,'New report name is registered');
  const filter=definition.filters.find(item=>item.fieldname==='order_type');
  assert.equal(filter.default,'All');
  assert.deepEqual(Array.from(filter.options,option=>option.value),['All','A','B']);
  assert.equal(filter.options[0].label,'A + B');
  assert(definition.filters.some(item=>item.fieldname==='sales_order'));
 });
 test(`${name} formats CFA amounts without decimals`,()=>{
  const {definition}=report(folder,name);
  let fallback=false;
  const formatted=definition.formatter(1200,null,{fieldname:'balance',fieldtype:'Currency'},{currency:'XOF'},()=>{fallback=true;});
  assert.equal(formatted.precision,0);
  assert.equal(fallback,false);
 });
 test(`${name} refreshes a type change and clears a conflicting order`,()=>{
  const {definition}=report(folder,name);
  const filter=definition.filters.find(item=>item.fieldname==='order_type');
  let refreshed=0,cleared=0;
  const screen={get_filter_value:()=>'',refresh:()=>refreshed++,set_filter_value:()=>cleared++};
  filter.on_change(screen);
  assert.equal(refreshed,1);
  screen.get_filter_value=()=> 'SO-B';
  filter.on_change(screen);
  assert.equal(cleared,1);
  assert.equal(refreshed,1,'Clearing the order triggers its native refresh');
 });
 test(`${name} preserves unknown financial values instead of displaying a zero`,()=>{
  const {definition}=report(folder,name);
  for(const value of [null,undefined,''])assert.equal(definition.formatter(value,null,{fieldname:'balance',fieldtype:'Currency'},{currency:'XOF'},()=> 'fallback'),'—');
  const zero=definition.formatter(0,null,{fieldname:'balance',fieldtype:'Currency'},{currency:'XOF'},()=> 'fallback');
  assert.equal(zero.value,0);
 });
}
