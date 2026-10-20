import {test} from 'node:test';
import assert from 'node:assert/strict';
import {applyTechnicalDefinition} from '../src/technical-batch.js';
const fixture=()=>[
 {line_id:'A',repere:'V1',length_mm:1200,width_mm:800,thickness_mm:24,tree:{mode:'new',proposed_code:'DOUBLE',children:[{item_type:'AIR',thickness_mm:12}]}},
 {line_id:'B',repere:'V2',length_mm:900,width_mm:600,thickness_mm:6,qty:3,tree:{proposed_code:'OTHER'}},
 {line_id:'C',repere:'V3',length_mm:700,width_mm:400,thickness_mm:8,tree:{proposed_code:'UNCHANGED'}}
];
test('copies composition and thickness to checked recipients only, preserving dimensions and identity',()=>{
 const lines=fixture();const untouched=JSON.stringify(lines[2]);
 assert.equal(applyTechnicalDefinition(lines,'A',['A','B']),1);
 assert.deepEqual(lines[1].tree,lines[0].tree);assert.equal(lines[1].thickness_mm,24);
 assert.equal(lines[1].line_id,'B');assert.equal(lines[1].repere,'V2');assert.equal(lines[1].length_mm,900);assert.equal(lines[1].width_mm,600);assert.equal(lines[1].qty,3);
 assert.equal(JSON.stringify(lines[2]),untouched);
});
test('the active source may be unchecked; copied trees are independent at every depth',()=>{
 const lines=fixture();assert.equal(applyTechnicalDefinition(lines,'A',['B','C','B','foreign']),2);
 lines[1].tree.children[0].thickness_mm=16;
 assert.equal(lines[0].tree.children[0].thickness_mm,12);assert.equal(lines[2].tree.children[0].thickness_mm,12);
});
test('empty selection, source-only selection and missing source make no changes',()=>{
 for(const [source,targets] of [['A',[]],['A',['A']],['missing',['B']]]){
  const lines=fixture(),before=JSON.stringify(lines);assert.equal(applyTechnicalDefinition(lines,source,targets),0);assert.equal(JSON.stringify(lines),before);
 }
});
