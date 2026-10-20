const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const assert=require('node:assert/strict'),path=require('node:path'),fs=require('node:fs');
const base=path.resolve(__dirname,'../../../mat_reco/public/js');
const fixture=JSON.parse(fs.readFileSync(path.join(__dirname,'fixtures/compensation.json'),'utf8'));
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
  window.frm={doc:{name:'MCP-TEST',modified:'v1',mcp_mode:'Retour Terrain',docstatus:0,result_json:JSON.stringify(data.loaded.effective_tree),material_plan_incidents:[]},
    fields_dict:{cutting_plan_preview:{$wrapper:[document.querySelector('#preview')]}},is_dirty(){return false;},async reload_doc(){reloadCount++;this.doc.effective_result_json=JSON.stringify(current.effective_tree);await MatRecoMCPUX20.initializeUX20Preview(this);}};
 },fixture);
 await page.evaluate(()=>MatRecoMCPUX20.initializeUX20Preview(frm));
 await page.locator('#preview').getByRole('button',{name:'Agrandir ou réduire l’éditeur'}).click();
 const modal=page.locator('.mcp20-modal-inner');await modal.locator('[data-v-app]').waitFor();
 const navigation=modal.locator('.mcpv-nav-actions');
 assert.equal(await navigation.getByRole('button').count(),2);
 const reset=await navigation.getByRole('button',{name:'Réinitialiser'}).boundingBox();
 const compensate=await navigation.getByRole('button',{name:'Compenser',exact:true}).boundingBox();
 assert.equal(reset.y,compensate.y);
 const originalBox=await modal.locator('.mcpv-grid').boundingBox();
 const background=()=>modal.locator('.mcpv-app').evaluate(n=>getComputedStyle(n).backgroundColor);
 assert.equal(await background(),'rgb(16, 16, 16)');
 await modal.getByRole('button',{name:'Compenser',exact:true}).click();
 await modal.getByRole('heading',{name:'Stock disponible'}).waitFor();
 assert.equal(await background(),'rgb(16, 16, 16)');
 assert.equal(await modal.locator('.mcpv-grid').boundingBox().then(b=>b.width),originalBox.width);
 assert.equal(await modal.locator('.mcpv-canvas svg').count(),1);
 assert.equal(await modal.locator('.comp-panel,.comp-sheet-grid').count(),0);
 assert.equal(await modal.locator('.mcpv-compensation-side .mcpv-compensation-stock').count(),1);
 assert.doesNotMatch(await modal.innerText(),/Chercher dans les chutes|Priorité [123]|Retour Terrain →/);
 await modal.getByRole('button',{name:'Calculer',exact:true}).click();
 await modal.getByText('1 remplacement(s) proposé(s)').waitFor();
 assert.equal(await page.evaluate(()=>applyCount),0);
 const replacement=fixture.preview.placements[0].id;
 assert.equal(await modal.locator(`[data-node-id="${replacement}"]`).getAttribute('fill'),'#bbf7d0');
 await page.evaluate(()=>failApply=true);
 await modal.getByRole('button',{name:'Valider la compensation'}).click();
 await modal.getByRole('alert').filter({hasText:'Stock modifié'}).waitFor();
 assert.equal(await page.evaluate(()=>reloadCount),0);
 assert.equal(await modal.getByRole('button',{name:'Valider la compensation'}).isDisabled(),true);
 await modal.getByRole('button',{name:'Annuler',exact:true}).click();
 await modal.getByRole('button',{name:'Compenser',exact:true}).waitFor();
 assert.equal(await modal.locator('.mcpv-compensation-side').count(),0);
 assert.equal(await modal.locator(`[data-node-id="${replacement}"]`).count(),0);
 assert.equal(await page.evaluate(()=>frm.__mcp_ux20_modal_state.vue.store.simulationTree.nodes.length),1);
 await page.evaluate(()=>{failApply=false;stockPreview=true;});
 async function proposeStock(){
  await modal.getByRole('button',{name:'Compenser',exact:true}).click();
  await modal.getByLabel('Mode de compensation').selectOption('manual');
  await modal.getByLabel('Justification du choix').fill('Chute écartée pour la recette');
  await modal.getByLabel('PLC-1052',{exact:true}).check();
  await modal.getByRole('button',{name:'Calculer',exact:true}).click();
  await modal.getByText('1 remplacement(s) proposé(s)').waitFor();
  assert.equal(await modal.getByLabel('Choisir une plaque').locator('option').count(),2);
  await modal.getByLabel('Choisir une plaque').selectOption('1');
  assert.equal(await modal.locator('.mcpv-canvas svg').count(),1);
  await modal.locator(`[data-node-id="${fixture.stock_preview.placements[0].id}"]`).waitFor();
 }
 await proposeStock();
 assert.equal(await page.evaluate(()=>frm.__mcp_ux20_modal_state.vue.store.simulationTree.nodes.length),1);
 await modal.screenshot({path:'/tmp/mcp-compensation-dark-modal.png'});
 await modal.getByRole('button',{name:'Annuler',exact:true}).click();
 assert.equal(await modal.getByLabel('Choisir une plaque').locator('option').count(),1);
 await proposeStock();
 await modal.getByRole('button',{name:'Valider la compensation'}).dblclick();
 await modal.getByText('Compensation enregistrée',{exact:false}).waitFor();
 assert.equal(await page.evaluate(()=>applyCount),2);assert.equal(await page.evaluate(()=>reloadCount),1);
 assert.equal(await page.evaluate(()=>frm.__mcp_ux20_modal.$wrapper.is(':visible')),true);
 assert.equal(await modal.locator('.mcpv-compensation-side').count(),0);
 assert.equal(await modal.getByLabel('Choisir une plaque').locator('option').count(),2);
 assert.equal(await modal.getByLabel('Choisir une plaque').inputValue(),'0');
 await modal.getByLabel('Choisir une plaque').selectOption('1');
 await modal.locator(`[data-node-id="${fixture.stock_preview.placements[0].id}"]`).waitFor();
 assert.equal(await modal.getByRole('button',{name:'Compenser',exact:true}).isVisible(),true);
 for(const width of [1600,420]){
  await page.setViewportSize({width,height:1100});
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
  const buttons=modal.locator('.mcpv-nav-actions');const a=await buttons.getByRole('button',{name:'Réinitialiser'}).boundingBox(),b=await buttons.getByRole('button',{name:'Compenser',exact:true}).boundingBox();assert.equal(a.y,b.y);
 }
 assert.deepEqual(errors,[]);
 console.log('PASS: same dark workshop/modal/canvas; Compenser beside reset; one stock sheet per page; conflict preserved; cancel restores workshop; confirmed apply once returns to the still-open modal; desktop/mobile, no JS errors.');
}finally{await browser.close();}})().catch(e=>{console.error(e);process.exit(1);});
