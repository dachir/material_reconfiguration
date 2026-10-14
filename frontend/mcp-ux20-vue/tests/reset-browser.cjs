const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const assert=require('node:assert/strict'),path=require('node:path'),fs=require('node:fs');
const base=path.resolve(__dirname,'../../../mat_reco/public/js');
const planning={nodes:[{id:'SN',serial_no:'SN',length_mm:1000,width_mm:1000,children:[{id:'p',node_type:'finished_good',x:0,y:0,length_mm:1000,width_mm:1000}]}]};
const fixture={planning,loaded:{effective_tree:{nodes:[{...planning.nodes[0],children:[{...planning.nodes[0].children[0],node_type:'destroyed'}]}],compensation_events:[{id:'old'}]},document_version:{signature:'v1'}}};
(async()=>{const browser=await chromium.launch({args:['--no-sandbox']});try{
 const page=await browser.newPage({viewport:{width:1600,height:1100}}),errors=[];
 page.on('pageerror',e=>errors.push(e.message));
 await page.setContent('<div id="preview"></div>');
 await page.addStyleTag({path:path.join(base,'mcp_vue_dist/mat-reco-mcp-ux20-vue.css')});
 await page.addScriptTag({path:path.join(base,'mcp_vue_dist/mcp_vue.iife.js')});
 await page.addScriptTag({path:path.join(base,'mcp_ux20.bundle.js')});
 await page.evaluate(data=>{
  let current=data.loaded;window.requests=[];window.applyCount=0;window.reloadCount=0;window.failApply=false;window.stockPreview=false;
  window.frappe={show_alert(){},call:async request=>{
   requests.push(request);let message;const proposed=stockPreview?data.stock_preview:data.preview;
   if(request.method.endsWith('.load_mcp_effective_plan'))message={valid:true,editable:true,effective_tree:current.effective_tree,document_version:current.document_version};
   else if(request.method.endsWith('.reset_mcp_incidents')){await new Promise(r=>setTimeout(r,80));if(window.resetConflict)message={valid:false,conflict:true,errors:['Version changée']};else{current={...current,effective_tree:data.planning,document_version:{signature:'v2'}};message={valid:true,reset:true,editable:true,effective_tree:data.planning,document_version:current.document_version};}}
   else if(request.method.endsWith('.load_compensation'))message=current;
   else if(request.method.endsWith('.preview_compensation'))message=proposed;
   else if(request.method.endsWith('.apply_compensation')){
    applyCount++;await new Promise(r=>setTimeout(r,60));
    if(failApply)message={valid:false,conflict:true,errors:['Stock modifié']};
    else{current={...data.loaded,effective_tree:proposed.effective_tree,compensation_requirements:[],summary:{...data.loaded.summary,to_compensate:0,planned:1}};
     message={valid:true,editable:true,applied:true,effective_tree:proposed.effective_tree,document_version:proposed.document_version};}
   }else throw Error('Unexpected request '+request.method);
   return {message};
  },ui:{Dialog:class{constructor(){this.dom=document.createElement('div');this.dom.className='modal-dialog';const field=document.createElement('div');this.dom.appendChild(field);document.body.appendChild(this.dom);this.fields_dict={ux20_editor:{$wrapper:[field]}};this.$wrapper={is:()=>this.visible,on:(event,callback)=>this.closed=callback,off(){},find:()=>({toggleClass:name=>this.dom.classList.toggle(name)})};}show(){this.visible=true}hide(){this.visible=false;this.closed?.();this.dom.remove()}}}};
  window.frm={doc:{name:'MCP-TEST',modified:'v1',mcp_mode:'Retour Terrain',docstatus:0,result_json:JSON.stringify(data.planning),material_plan_incidents:[{incident_action:"Destroy"}]},
    fields_dict:{cutting_plan_preview:{$wrapper:[document.querySelector('#preview')]}},is_dirty(){return false;},async reload_doc(){reloadCount++;this.doc.material_plan_incidents=[];this.doc.effective_result_json=JSON.stringify(current.effective_tree);await MatRecoMCPUX20.initializeUX20Preview(this);}};
 },fixture);
 await page.evaluate(()=>MatRecoMCPUX20.initializeUX20Preview(frm));
 await page.locator('#preview').getByRole('button',{name:'Agrandir ou réduire l’éditeur'}).click();
 const modal=page.locator('.mcp20-modal-inner');await modal.locator('[data-v-app]').waitFor();

 let confirmationText='';page.once('dialog',async dialog=>{confirmationText=dialog.message();await dialog.dismiss();});
 const resetRequests=()=>page.evaluate(()=>requests.filter(r=>r.method.endsWith('.reset_mcp_incidents')).length);
 await modal.getByRole('button',{name:'Réinitialiser'}).click();
 assert.match(confirmationText,/Tous les incidents et compensations seront supprimés/);assert.match(confirmationText,/juste après Planification/);
 assert.equal(await resetRequests(),0);assert.equal(await page.evaluate(()=>frm.doc.material_plan_incidents.length),1);
 page.on('dialog',dialog=>dialog.accept());
 const before=await page.evaluate(()=>JSON.stringify(frm.__mcp_ux20_modal_state.vue.store.simulationTree));
 await page.evaluate(()=>window.resetConflict=true);await modal.getByRole('button',{name:'Réinitialiser'}).click();await page.waitForFunction(()=>!frm.__mcp_ux20_modal_state.vue.store.isSaving);
 assert.equal(await page.evaluate(()=>JSON.stringify(frm.__mcp_ux20_modal_state.vue.store.simulationTree)),before);assert.equal(await page.evaluate(()=>frm.doc.material_plan_incidents.length),1);
 await page.evaluate(()=>window.resetConflict=false);await modal.getByRole('button',{name:'Réinitialiser'}).click();await page.waitForFunction(()=>frm.__mcp_ux20_modal_state.vue.store.documentVersion.signature==='v2');
 assert.equal(await page.evaluate(()=>frm.doc.material_plan_incidents.length),0);assert.equal(await page.evaluate(()=>reloadCount),1);
 assert.deepEqual(await page.evaluate(()=>JSON.parse(JSON.stringify(frm.__mcp_ux20_modal_state.vue.store.simulationTree))),planning);
 assert.equal(await page.evaluate(()=>frm.__mcp_ux20_modal_state.vue.store.canUndo),false);assert.equal(await modal.count(),1);assert.deepEqual(errors,[]);
 await page.getByRole('button',{name:'Fermer l’atelier'}).click();await page.evaluate(()=>MatRecoMCPUX20.openUX20Modal(frm));await modal.locator('[data-v-app]').waitFor();assert.deepEqual(await page.evaluate(()=>JSON.parse(JSON.stringify(frm.__mcp_ux20_modal_state.vue.store.simulationTree))),planning);
 console.log('PASS: warning shown and cancellation sends no request; reset click preserves state on conflict; confirmed reset deletes incidents, restores planning in modal and form, clears undo, stays open and survives reopening.');
 }finally{await browser.close();}})().catch(e=>{console.error(e);process.exit(1)});
