/* UX-07: opt-in Frappe integration, server save is the authority. */
(function(root){'use strict';
const ns=root.MatRecoMCPUX20=root.MatRecoMCPUX20||{};
function create(frm){let mounted=null,host=null,inFlight=false;
function active(){return Boolean(frm.__mcp_ux20_enabled);}
function readOnly(){return frm.doc.mcp_mode!=='Retour Terrain'||Number(frm.doc.docstatus)!==0;}
async function apply(ctx){if(inFlight)return;if(readOnly())throw new Error('Les actions nécessitent un MCP Retour Terrain en brouillon');
 const p=ctx.preview,g=ctx.guide,t=ctx.tree;let payload;
 try{
 if(p.action==='Move'){
   const target=p.targetNodeIds&&p.targetNodeIds[0];const item=g.getItem(target);if(!item)throw new Error('Select a destination');
   const node=item.node, params=p.parameters||{};
   payload=ns.createUX06MoveDraft({tree:t,sourceNodeId:p.sourceNodeId,targetSerialNo:item.sheet,targetZoneId:target,targetX:params.target_x_mm??node.x,targetY:params.target_y_mm??node.y}).payload;
 }else{
   const src=g.getItem(p.sourceNodeId);if(!src)throw new Error('Selected source no longer exists');
   const targets=(p.targetNodeIds||[]).map(id=>{const item=g.getItem(id);if(!item)throw new Error('Unknown target '+id);return item.node;});
   payload=ns.buildUX05Incident(p.action,src.node,targets,p.parameters||{},{source_serial_no:src.sheet,min_leftover_dimension_mm:500});
 }
 }catch(e){frappe.msgprint({title:'UX 2.0 — Vérification',message:String(e.message||e),indicator:'orange'});return;}
 const existing=(frm.doc.material_plan_incidents||[]).filter(r=>r.is_active&&String(r.plan_node_id)===String(payload.plan_node_id));
 if(existing.length){frappe.msgprint({title:'UX 2.0 — Action existante',message:'Une action active existe déjà sur cette source. Annulez-la dans les incidents avant d’en créer une autre.',indicator:'orange'});return;}
 inFlight=true;ctx.workspace.controller.setBusy(true);let row=null;
 try{
   row=frm.add_child('material_plan_incidents');Object.assign(row,payload);frm.refresh_field('material_plan_incidents');
   await frm.save();
   if(frm.is_dirty())throw new Error('Le MCP reste non enregistré');
   frappe.show_alert({message:'Incident enregistré. La validation définitive sera faite par Python.',indicator:'green'});
   ctx.workspace.controller.cancel();
   if(mounted)mounted.refresh();
 }catch(e){
   if(row){const rows=frm.doc.material_plan_incidents||[];const i=rows.indexOf(row);if(i>=0)rows.splice(i,1);frm.refresh_field('material_plan_incidents');}
   frappe.msgprint({title:'UX 2.0 — Enregistrement refusé',message:String(e.message||e),indicator:'red'});
 }finally{inFlight=false;ctx.workspace.controller.setBusy(false);}
}
function mount(){if(!active()||!frm.fields_dict.cutting_plan_preview)return false;
 // Frappe refreshes on save: do not destroy a workspace during its own transaction.
 if(inFlight&&mounted)return true;
 if(mounted){mounted.destroy();mounted=null;}const wrapper=frm.fields_dict.cutting_plan_preview.$wrapper;
 if(!wrapper||!wrapper.length)return false;
 wrapper.empty();host=document.createElement('div');host.className='mcp-ux20-host';wrapper[0].appendChild(host);
 mounted=ns.mountUX20Editor(frm,host,{enabled:true,onApply:apply});return Boolean(mounted);
}
function dispose(){if(mounted){mounted.destroy();mounted=null;}if(host){host.remove();host=null;}}
return {mount,dispose,active};}
ns.createUX07FrappeBridge=create;
})(typeof window!=='undefined'?window:globalThis);
