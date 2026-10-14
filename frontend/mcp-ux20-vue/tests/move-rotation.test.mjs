import test from 'node:test';import assert from 'node:assert/strict';
import {createPinia,setActivePinia} from 'pinia';
import {candidateFor,findPiece,simulate,area,regions,overlaps} from '../src/lib/geometry.js';
import {useCuttingStore} from '../src/stores/cutting.js';
const fixture=(l=600,w=800)=>({options:{allow_rotation:true},nodes:[{id:'S1',serial_no:'S1',length_mm:800,width_mm:600,children:[{id:'p',piece_uid:'unit',node_type:'finished_good',x:0,y:0,length_mm:800,width_mm:600,rotation:false}]},{id:'S2',serial_no:'S2',length_mm:l+100,width_mm:w+100,children:[{id:'zone',node_type:'leftover',x:100,y:100,length_mm:l,width_mm:w}]}]});
const move=(parameters={},target='zone')=>({action:'Move',sourceNodeId:'p',targetNodeIds:[target],parameters});
function conserved(before,after){for(let i=0;i<before.nodes.length;i++){assert.equal(after.nodes[i].children.reduce((s,n)=>s+area(n),0),before.nodes[i].children.reduce((s,n)=>s+area(n),0));const rs=after.nodes[i].children.flatMap(regions);assert.equal(rs.some((r,i)=>rs.slice(i+1).some(q=>overlaps(r,q))),false);}}

test('cross-sheet target becomes available only when the permitted rotation fits',()=>{
 const t=fixture(),source=findPiece(t,'p'),target=findPiece(t,'zone');
 assert.equal(candidateFor('Move',source,target),false);
 assert.equal(candidateFor('Move',source,target,{allow_rotation:true}),true);
 assert.equal(candidateFor('Move',source,target,{allow_rotation:true,rotation_degrees:0}),false);
});
test('rotated move keeps the commercial unit and both sheet areas',()=>{
 const t=fixture(),next=simulate(t,move({allow_rotation:true})),p=findPiece(next,'p');
 assert.equal(p.sheet.serial_no,'S2');assert.equal(p.node.piece_uid,'unit');
 assert.equal(p.node.length_mm,600);assert.equal(p.node.width_mm,800);assert.equal(p.node.rotation,true);
 assert.equal(p.node.__move_rotation_degrees,90);conserved(t,next);assert.equal(findPiece(t,'p').sheet.serial_no,'S1');
});
test('automatic placement prefers the current orientation and explicit quarter turn is supported',()=>{
 const t=fixture(1000,1000);assert.equal(findPiece(simulate(t,move({allow_rotation:true})),'p').node.length_mm,800);
 const rotated=findPiece(simulate(t,move({allow_rotation:true,rotation_degrees:90})),'p').node;
 assert.equal(rotated.length_mm,600);assert.equal(rotated.width_mm,800);
 assert.throws(()=>simulate(fixture(),move({allow_rotation:false,rotation_degrees:90})));
});
test('a move into a Single keeps its cutout forbidden and conserves the two physical sheets',()=>{
 const t=fixture();t.nodes[0].width_mm=250;t.nodes[0].children[0].width_mm=250;
 t.nodes[1]={id:'S2',serial_no:'S2',length_mm:1200,width_mm:1000,removed_length_mm:900,removed_width_mm:800,children:[{id:'zone',node_type:'leftover',geometry_type:'single',x:0,y:0,length_mm:1200,width_mm:1000,removed_length_mm:900,removed_width_mm:800}]};
 const next=simulate(t,move({allow_rotation:true})),p=findPiece(next,'p').node;
 assert.equal(p.x,900);assert.equal(p.y,0);assert.equal(p.length_mm,250);assert.equal(p.width_mm,800);conserved(t,next);
 assert.equal(next.nodes[1].children.flatMap(regions).some(r=>overlaps(r,{x:0,y:0,length_mm:900,width_mm:800})),false);
});
test('source selection survives navigation and changing orientation invalidates an impossible preview',async()=>{
 setActivePinia(createPinia());const s=useCuttingStore();s.load(fixture());s.configureServer(null);
 s.select('p');s.choose('Move');assert.deepEqual(s.candidateNodeIds,['zone']);
 s.setSheet(1);assert.equal(s.sourceNodeId,'p');s.select('zone');assert.ok(s.previewState);
 s.parameters.rotation_degrees=0;s.updateMoveOrientation();assert.equal(s.previewState,null);assert.deepEqual(s.targetNodeIds,[]);assert.deepEqual(s.candidateNodeIds,[]);
 s.parameters.rotation_degrees=90;s.updateMoveOrientation();s.select('zone');s.confirm();
 assert.equal(findPiece(s.simulationTree,'p').sheet.serial_no,'S2');assert.equal(s.isDirty,true);
 s.undo();assert.equal(findPiece(s.simulationTree,'p').sheet.serial_no,'S1');s.redo();assert.equal(findPiece(s.simulationTree,'p').node.rotation,true);
});
