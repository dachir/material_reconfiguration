/* UX 2.0 modal: browser-only simulation, NO Frappe document mutation. */
(function(root){'use strict';
const ns=root.MatRecoMCPUX20=root.MatRecoMCPUX20||{};
const clone=v=>JSON.parse(JSON.stringify(v));
const num=v=>Number(v)||0;
function originalTree(frm){
 const raw=frm.doc.mcp_mode==='Retour Terrain'?(frm.doc.effective_result_json||frm.doc.result_json):(frm.doc.result_json||frm.doc.effective_result_json);
 const value=typeof raw==='string'?JSON.parse(raw||'{}'):clone(raw||{});
 if(!Array.isArray(value.nodes))throw new Error('Aucun plan de découpe disponible pour cette simulation.');
 return clone(value);
}
function updateSimulation(tree,preview){
 if(!root.MatRecoMCPVue?.simulate)throw new Error('Aperçu non disponible : moteur de simulation Vue inaccessible.');
 return root.MatRecoMCPVue.simulate(tree,preview);
}
async function loadBackend(frm){
 if(typeof frappe.call!=='function')return null;
 const client=root.MatRecoMCPVue.createFrappeClient(frappe,frm.doc.name);
 const loaded=await client.load();
 frm.__mcp_ux20_backend={client,loaded};return loaded;
}
function serverOptions(frm){
 const backend=frm.__mcp_ux20_backend;
 return backend?{baseTree:clone(backend.loaded.effective_tree),documentVersion:backend.loaded.document_version,allowRotation:!!backend.loaded.allow_rotation,previewAction:payload=>backend.client.preview(payload),
  compensationLoad:()=>backend.client.compensationLoad(),compensationPreview:payload=>backend.client.compensationPreview(payload),
  compensationApply:async payload=>{
   if(frm.is_dirty?.())throw new Error('Enregistrez les modifications du formulaire avant de confirmer.');
   if(frm.__mcp_ux20_saving)throw new Error('Un enregistrement est déjà en cours.');
   frm.__mcp_ux20_saving=true;
   try{
    const result=await backend.client.compensationApply(payload);
    if(!result.applied)throw new Error('Application non confirmée par Python.');
    backend.loaded=result;frm.__mcp_ux20_visual=clone(result.effective_tree);
    frm.__mcp_ux20_base_signature=JSON.stringify(result.effective_tree);
    const modal=frm.__mcp_ux20_modal_state;
    if(modal){modal.tree=clone(result.effective_tree);modal.base=clone(result.effective_tree);}
    // The form refresh must keep the current modal mounted. The active store
    // returns to the workshop only after this confirmed response resolves.
    try{await frm.reload_doc();}catch(error){frappe.show_alert({message:'Compensation enregistrée. Rechargez le formulaire pour actualiser son affichage.',indicator:'orange'});}
    if(!frm.__mcp_ux20_preview_instance?.store?.compensationOpen)renderPreviewField(frm,{useCurrent:false});
    return result;
   }finally{frm.__mcp_ux20_saving=false;}
  }}:null;
}
async function savePending(frm,tree,session){
 if(Number(frm.doc.docstatus||0)!==0)throw new Error('Document soumis : modification impossible.');
 const backend=frm.__mcp_ux20_backend;
 if(!backend){frm.__mcp_ux20_visual=clone(tree);return null;}
 if(frm.__mcp_ux20_saving)throw new Error('Un enregistrement est déjà en cours.');
 if(frm.is_dirty?.())throw new Error('Enregistrez d’abord les autres modifications du formulaire, puis rechargez l’éditeur.');
 if(!session?.pendingIncidents?.length){const saved=await backend.client.load();backend.loaded=saved;frm.__mcp_ux20_visual=clone(saved.effective_tree);return saved;}
 frm.__mcp_ux20_saving=true;
 const previous=clone(frm.doc.material_plan_incidents||[]);
 const wasUnsaved=frm.doc.__unsaved;let persisted=false;
 try{
  const prepared=await backend.client.prepare({pending_incidents:session.pendingIncidents,document_version:session.documentVersion});
  for(const payload of prepared.incidents){const row=frm.add_child('material_plan_incidents');Object.assign(row,payload);}
  frm.refresh_field('material_plan_incidents');
  await frm.save();
  if(frm.is_dirty?.())throw new Error('La sauvegarde du MCP n’a pas été confirmée.');
  persisted=true;
  const saved=await backend.client.load();
  backend.loaded=saved;frm.__mcp_ux20_visual=clone(saved.effective_tree);frm.__mcp_ux20_base_signature=JSON.stringify(originalTree(frm));
  frappe.show_alert({message:'Incidents enregistrés. Résultat Python rechargé.',indicator:'green'});
  return saved;
 }catch(error){
  if(!persisted){frm.doc.material_plan_incidents=previous;frm.doc.__unsaved=wasUnsaved;frm.refresh_field('material_plan_incidents');}
  else throw new Error('Les incidents sont enregistrés, mais le résultat n’a pas pu être rechargé. Rechargez le formulaire avant de poursuivre.');
  throw error;
 }finally{frm.__mcp_ux20_saving=false;}
}
function renderPreviewField(frm,{useCurrent=true}={}){
 const data=(useCurrent?frm.__mcp_ux20_preview_instance?.store?.simulationTree:null)||frm.__mcp_ux20_visual,field=frm.fields_dict?.cutting_plan_preview;
 if(!data||!field?.$wrapper?.length)return false;
 const wrapper=field.$wrapper[0];
 const priorStore=useCurrent?frm.__mcp_ux20_preview_instance?.store:null;
 const session=priorStore?{tree:clone(priorStore.simulationTree),pendingIncidents:clone(priorStore.pendingIncidents||[]),documentVersion:priorStore.documentVersion}:null;
 frm.__mcp_ux20_preview_instance?.unmount();
 if(root.MatRecoMCPVue?.renderPreview){
   frm.__mcp_ux20_preview_instance=root.MatRecoMCPVue.renderPreview(wrapper,clone(data),{
     server:serverOptions(frm),session,
     readonly:Number(frm.doc.docstatus||0)!==0||!!(frm.__mcp_ux20_backend&&!frm.__mcp_ux20_backend.loaded.editable),submitted:Number(frm.doc.docstatus||0)!==0,
     context:{reference:frm.doc.name,material:frm.doc.source_item||''},
     onToggleExpand:()=>openModal(frm),
     onApplyPreview:async (tree,session)=>{
       const saved=await savePending(frm,tree,session);
       if(!saved)frappe.show_alert({message:'Aperçu actualisé.',indicator:'blue'});
       return saved;
     },
   });
 }else{
   wrapper.replaceChildren();const heading=document.createElement('p');heading.textContent='Simulation locale · Non enregistrée · Non validée par Python';wrapper.appendChild(heading);
   const renderer=ns.createCanvasRenderer(wrapper,null);renderer.setTree(data);
 }

 return true;
}
const vueJS='/assets/mat_reco/js/mcp_vue_dist/mcp_vue.iife.js';
const vueCSS='/assets/mat_reco/js/mcp_vue_dist/mat-reco-mcp-ux20-vue.css';
let vueAssetsPromise=null;
function loadVueAssets(){
 if(typeof root.MatRecoMCPVue?.mount==='function'&&root.MatRecoMCPVue.version==='20261014_move_cursor_1')return Promise.resolve();
 if(vueAssetsPromise)return vueAssetsPromise;
 vueAssetsPromise=new Promise((resolve,reject)=>{
   const existingStyle=document.querySelector('link[data-mcp-vue-style]');
   if(existingStyle)existingStyle.href=vueCSS+'?ux20_vue=20261014_move_cursor_1';
   if(!existingStyle){
     const css=document.createElement('link');css.rel='stylesheet';css.href=vueCSS+'?ux20_vue=20261014_move_cursor_1';css.dataset.mcpVueStyle='1';document.head.appendChild(css);
   }
   const script=document.createElement('script');
   // Bypass intermediary and browser caches during the current migration.
   script.src=vueJS+'?ux20_vue=20261014_move_cursor_1';script.async=true;
   script.onload=()=>typeof root.MatRecoMCPVue?.mount==='function'?resolve():reject(new Error('Le fichier Vue est chargé mais MatRecoMCPVue.mount est absent. Reconstruire le bundle Vite.'));
   script.onerror=()=>reject(new Error('Bundle Vue inaccessible : '+vueJS+' (404 ou CSP).'));
   document.head.appendChild(script);
 }).catch(error=>{vueAssetsPromise=null;throw error;});
 return vueAssetsPromise;
}
function openModal(frm){
 console.info('[MCP UX20] Ouverture modal Vue — build 20261014_move_cursor_1');
 if(frm.__mcp_ux20_modal?.$wrapper?.is(':visible'))return frm.__mcp_ux20_modal;
 const latest=frm.__mcp_ux20_preview_instance?.store?.simulationTree||frm.__mcp_ux20_visual||originalTree(frm);
 const priorStore=frm.__mcp_ux20_preview_instance?.store;
 const session=priorStore?{tree:clone(priorStore.simulationTree),pendingIncidents:clone(priorStore.pendingIncidents||[]),documentVersion:priorStore.documentVersion}:null;
 const state={base:clone(latest),tree:null,vue:null,editor:null,closed:false};state.tree=clone(state.base);
 const dlg=new frappe.ui.Dialog({title:'Atelier de découpe',size:'extra-large',fields:[{fieldtype:'HTML',fieldname:'ux20_editor'}]});
 frm.__mcp_ux20_modal=dlg;frm.__mcp_ux20_modal_state=state;dlg.show();
 const wrapper=dlg.fields_dict.ux20_editor.$wrapper[0];
 const css=document.createElement('style');css.textContent=`
 .modal-dialog:has(.mcp20-modal-inner){width:70vw!important;max-width:70vw!important;margin:2vh auto!important}
 .modal:has(.mcp20-modal-inner) .modal-body{padding:0!important;max-height:calc(90vh - 30px)!important;overflow:auto}
 .modal:has(.mcp20-modal-inner) .modal-content{max-height:90vh!important}
 .modal:has(.mcp20-modal-inner) .modal-header,.modal:has(.mcp20-modal-inner) .modal-footer{display:none!important}
 .modal-dialog.mcp20-expanded{width:96vw!important;max-width:96vw!important}
 @media(max-width:900px){.modal-dialog:has(.mcp20-modal-inner){width:96vw!important;max-width:96vw!important}}
 .mcp20-modal-inner{min-height:300px}
 .mcp20-modal-inner .mcpv-grid{min-height:350px}
 .mcp20-modal-inner .mcpv-canvas svg{height:min(48vh,530px)}
 `;wrapper.appendChild(css);
 const host=document.createElement('div');host.className='mcp20-modal-inner';wrapper.appendChild(host);
 const close=document.createElement('button');close.type='button';close.textContent='×';close.setAttribute('aria-label','Fermer l’atelier');close.style.cssText='position:absolute;right:8px;top:4px;z-index:3;background:transparent;border:0;color:#aaa';close.onclick=()=>dlg.hide();wrapper.style.position='relative';wrapper.appendChild(close);
 const message=document.createElement('div');message.style.cssText='padding:24px;color:#64748b';message.textContent='Chargement de Vue 3 + Pinia…';host.appendChild(message);
 dlg.$wrapper.on('hidden.bs.modal.mcpUX20',()=>{
   state.closed=true;
   try{state.vue?.unmount();}catch(err){console.warn('[MCP Vue] unmount',err);}
   try{state.editor?.destroy();}catch(err){console.warn('[MCP UX legacy] destroy',err);}
   state.vue=null;state.editor=null;frm.__mcp_ux20_modal=null;frm.__mcp_ux20_modal_state=null;
   dlg.$wrapper.off('hidden.bs.modal.mcpUX20');
 });
 loadVueAssets().then(async()=>{
   if(!frm.__mcp_ux20_backend)await loadBackend(frm);
   if(state.closed)return;
   host.replaceChildren();
   const vueHost=document.createElement('div');vueHost.id='mcp-ux20-vue-root';host.appendChild(vueHost);
   state.vue=root.MatRecoMCPVue.mount(vueHost,{
      tree:clone(state.tree),
      readonly:Number(frm.doc.docstatus||0)!==0||!!(frm.__mcp_ux20_backend&&!frm.__mcp_ux20_backend.loaded.editable),
      server:serverOptions(frm),session,
      onReset:()=>{state.tree=clone(state.base);},
      context:{reference:frm.doc.name,material:frm.doc.source_item||frm.doc.material_name||frm.doc.item_name||frm.doc.item_code||''},
      onToggleExpand:()=>dlg.$wrapper.find('.modal-dialog').toggleClass('mcp20-expanded'),
      onApplyPreview:async (tree,session)=>{
        const saved=await savePending(frm,tree,session);
        state.tree=clone(saved?.effective_tree||tree);state.base=clone(state.tree);
        frm.__mcp_ux20_visual=clone(state.tree);renderPreviewField(frm,{useCurrent:false});
        if(!saved)frappe.show_alert({message:'Aperçu actualisé.',indicator:'blue'});
        return saved;
      },
   });
   if(!vueHost.hasAttribute('data-v-app'))throw new Error('Vue mount() a été appelé mais aucun composant Vue n’est monté.');

 }).catch(error=>{
   state.vue?.unmount();state.vue=null;
   console.error('[MCP UX 2.0 Vue]',error);
   if(state.closed)return;
   // Keep the legacy editor as a temporary fallback if Vue assets are unavailable.
   host.replaceChildren();
   const warning=document.createElement('div');warning.className='alert alert-warning';warning.textContent='Interface classique (secours) : Vue n’a pas pu démarrer. '+String(error.message||error);host.appendChild(warning);
   if(Number(frm.doc.docstatus||0)!==0)return;
   const legacy=document.createElement('div');host.appendChild(legacy);
   state.editor=ns.mountUX20Editor(frm,legacy,{enabled:true,getTree:()=>state.tree,onReset:()=>{state.tree=clone(state.base);state.editor.refresh();},onApply:async ({preview})=>{
     if(Number(frm.doc.docstatus||0)!==0)throw new Error('Document soumis : modification impossible.');
     state.tree=updateSimulation(state.tree,preview);state.editor.refresh();
     frm.__mcp_ux20_visual=clone(state.tree);renderPreviewField(frm,{useCurrent:false});
   }});
 });
 return dlg;
}

async function initializePreview(frm){
 if(frm.__mcp_ux20_saving)return false;
 let base;
 try{base=originalTree(frm);}catch{return false;}
 const documentName=frm.doc.name;
 await loadVueAssets();
 if(frm.__mcp_ux20_saving)return false;
 const loaded=await loadBackend(frm);
 if(loaded)base=loaded.effective_tree;
 if(frm.doc.name!==documentName)return false;
 const signature=JSON.stringify(base);
 if(frm.__mcp_ux20_base_signature&&frm.__mcp_ux20_base_signature!==signature){
   frm.__mcp_ux20_modal?.hide();
   frm.__mcp_ux20_preview_instance?.unmount();frm.__mcp_ux20_preview_instance=null;
   frm.__mcp_ux20_visual=null;
 }
 frm.__mcp_ux20_base_signature=signature;
 if(!frm.__mcp_ux20_visual)frm.__mcp_ux20_visual=clone(base);
 if(Number(frm.doc.docstatus||0)!==0){lockEditors(frm);return true;}
 return renderPreviewField(frm);
}
function lockEditors(frm){
 if(Number(frm.doc.docstatus||0)===0)return;
 const modal=frm.__mcp_ux20_modal_state;
 const latest=modal?.vue?.store?.simulationTree||frm.__mcp_ux20_preview_instance?.store?.simulationTree||frm.__mcp_ux20_visual;
 if(latest)frm.__mcp_ux20_visual=clone(latest);
 modal?.vue?.store?.setLocked(true);
 if(modal?.editor)frm.__mcp_ux20_modal?.hide();
 frm.__mcp_ux20_preview_instance?.store?.setLocked(true);
 if(frm.__mcp_ux20_visual)renderPreviewField(frm,{useCurrent:false});
}
ns.version='20261014_move_cursor_1';
ns.initializeUX20Preview=initializePreview;
ns.lockUX20Editors=lockEditors;
ns.openUX20Modal=openModal;ns.renderUX20ReadOnly=renderPreviewField;ns.simulateUX20Operation=updateSimulation;
})(typeof window!=='undefined'?window:globalThis);
