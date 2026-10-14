import test from 'node:test';import assert from 'node:assert/strict';import {createPinia,setActivePinia} from 'pinia';import {useCuttingStore} from '../src/stores/cutting.js';import {createFrappeClient} from '../src/services/frappeClient.js';
const tree={nodes:[{id:'SN',serial_no:'SN',length_mm:1200,width_mm:1000,children:[]}]};
const requirement={piece_uid:'p',requirement_id:'p',compensation_qty:1};
const loaded={valid:true,effective_tree:tree,document_version:{modified:'v1',signature:'1'},compensation_requirements:[requirement],summary:{requested:1,to_compensate:1},internal_candidates:[],stock_candidates:[],warnings:[]};
const preview={valid:true,effective_tree:tree,placements:[{id:'CP-1',piece_uid:'p'}],proposal_id:'hash',options:{strategy:'automatic',selected_sources:[],override_reason:''},document_version:loaded.document_version};
function store(server={}){setActivePinia(createPinia());const s=useCuttingStore();s.load(tree);s.configureServer({compensationLoad:async()=>loaded,compensationPreview:async()=>preview,...server});return s;}

test('opening compensation loads authoritative needs without staging incidents',async()=>{const s=store();assert.equal(s.canCompensate,true);await s.openCompensation();assert.equal(s.compensationOpen,true);assert.deepEqual(s.compensationRequirements,[requirement]);assert.deepEqual(s.pendingIncidents,[]);assert.equal(s.isDirty,false);});
test('pending edits and submitted documents cannot open compensation',async()=>{const s=store();s.isDirty=true;await s.openCompensation();assert.equal(s.compensationOpen,false);s.isDirty=false;s.setLocked(true);assert.equal(s.canCompensate,false);});
test('preview never changes recorded state and source changes invalidate it',async()=>{const s=store();await s.openCompensation();await s.calculateCompensation();assert.equal(s.compensationPreview.proposal_id,'hash');assert.deepEqual(s.simulationTree,tree);assert.equal(s.confirmedCompensation,null);s.invalidateCompensation();assert.equal(s.compensationPreview,null);});
test('apply reports success only after server confirmation',async()=>{let resolve;const s=store({compensationApply:()=>new Promise(r=>{resolve=r;})});await s.openCompensation();await s.calculateCompensation();const pending=s.applyCompensation();assert.equal(s.isApplying,true);assert.equal(s.confirmedCompensation,null);resolve({applied:true,effective_tree:tree,document_version:loaded.document_version});await pending;assert.equal(s.confirmedCompensation.applied,true);assert.equal(s.isApplying,false);assert.equal(s.compensationPreview,null);assert.equal(s.compensationOpen,false);});
test('unconfirmed application is never treated as success',async()=>{const s=store({compensationApply:async()=>({valid:true})});await s.openCompensation();await s.calculateCompensation();await s.applyCompensation();assert.equal(s.confirmedCompensation,null);assert.match(s.compensationError,/non confirmée/);});
test('conflict discards proposal and reloads current requirements',async()=>{let reads=0;const s=store({compensationLoad:async()=>{reads++;return loaded;},compensationApply:async()=>{const e=new Error('Stock changé');e.conflict=true;throw e;}});await s.openCompensation();await s.calculateCompensation();await s.applyCompensation();assert.equal(reads,2);assert.equal(s.compensationPreview,null);assert.equal(s.confirmedCompensation,null);assert.match(s.compensationError,/Stock changé/);});
test('Frappe client uses compensation endpoints and structured source lists',async()=>{let call;const client=createFrappeClient({call:async payload=>{call=payload;return {message:preview};}},'MCP');await client.compensationPreview({selected_sources:['STOCK']});assert.match(call.method,/mcp_compensation_service.preview_compensation$/);assert.equal(call.args.mcp_name,'MCP');assert.deepEqual(call.args.selected_sources,['STOCK']);});

test('cancel restores workshop navigation without saving or keeping stock preview sheets',async()=>{
 const base={nodes:[tree.nodes[0],{...tree.nodes[0],id:'SN2',serial_no:'SN2'}]};
 const extra={id:'STOCK',serial_no:'STOCK',length_mm:1500,width_mm:1000,children:[]};
 let applies=0;
 const s=store({compensationLoad:async()=>({...loaded,effective_tree:base}),compensationPreview:async()=>({...preview,effective_tree:{nodes:[...base.nodes,extra]}}),compensationApply:async()=>{applies++;}});
 s.load(base);s.setSheet(1);s.setZoom(2);s.panelCollapsed=true;
 await s.openCompensation();assert.equal(s.sheetIndex,1);await s.calculateCompensation();
 s.setSheet(2);assert.equal(s.displaySheet.serial_no,'STOCK');assert.equal(s.sheets.length,3);
 assert.equal(s.simulationTree.nodes.length,2);
 s.closeCompensation();assert.equal(s.compensationOpen,false);assert.equal(s.sheets.length,2);
 assert.equal(s.sheetIndex,1);assert.equal(s.zoom,2);assert.equal(s.panelCollapsed,true);assert.equal(applies,0);
});
test('validated compensation returns to the same workshop with the server tree',async()=>{
 const updated={nodes:[tree.nodes[0],{...tree.nodes[0],id:'STOCK',serial_no:'STOCK'}]};
 const s=store({compensationPreview:async()=>({...preview,effective_tree:updated}),compensationApply:async()=>({applied:true,effective_tree:updated,document_version:loaded.document_version})});
 s.setZoom(1.5);await s.openCompensation();await s.calculateCompensation();s.setSheet(1);
 await s.applyCompensation();assert.equal(s.compensationOpen,false);assert.equal(s.sheets.length,2);
 assert.equal(s.sheetIndex,0);assert.equal(s.zoom,1.5);assert.deepEqual(s.simulationTree,updated);
});
test('ordinary cutting actions cannot alter a compensation preview',async()=>{
 const base={nodes:[{...tree.nodes[0],children:[{id:'piece',node_type:'finished_good',x:0,y:0,length_mm:800,width_mm:600}]}]};
 const s=store({compensationLoad:async()=>({...loaded,effective_tree:base})});await s.openCompensation();
 s.select('piece');s.choose('Destroy');s.confirm();s.undo();s.redo();
 assert.equal(s.selectedNodeId,null);assert.equal(s.activeAction,null);assert.deepEqual(s.simulationTree,base);
 assert.equal(s.isDirty,false);
});
