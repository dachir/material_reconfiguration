/* MCP UX 2.0 — real contextual editor. Geometry remains under existing Python authority. */
(function(root){'use strict';
const ns=root.MatRecoMCPUX20=root.MatRecoMCPUX20||{};
const LABEL={Move:'Déplacer',Merge:'Fusionner',Single:'Chute en L',Resize:'Redimensionner',Destroy:'Détruire'};
const SYMBOL={Move:'↗',Merge:'⊞',Single:'⌞',Resize:'⤢',Destroy:'×'};
const el=(tag,txt,cls)=>{const n=document.createElement(tag);if(txt!==undefined&&txt!==null)n.textContent=txt;if(cls)n.className=cls;return n;};
const style=`
.mcp20-editor{--b:#dce4ef;font-family:inherit;border:1px solid var(--b);border-radius:12px;background:#fff;margin:10px 0;overflow:hidden;color:#1e293b}
.mcp20-editor *{box-sizing:border-box}
.mcp20-head{display:flex;justify-content:space-between;align-items:center;padding:13px 17px;background:#f8fafc;border-bottom:1px solid var(--b);gap:12px;flex-wrap:wrap}
.mcp20-head strong{font-size:15px;color:#16315b}.mcp20-head small{color:#64748b}
.mcp20-grid{display:grid;grid-template-columns:minmax(0,1fr) 300px;min-height:560px}
.mcp20-main{position:relative;min-width:0;background:#fff}
.mcp20-main .mcpux-canvas{padding:12px 16px 22px!important;min-height:540px}
.mcp20-main .mcpux-canvas>div:nth-child(2){min-height:475px!important}
.mcp20-side{border-left:1px solid var(--b);background:#fbfcff;padding:17px;font-size:13px;min-width:0}
.mcp20-side h4{font-size:15px;margin:0 0 12px;color:#1d3557;font-weight:700}
.mcp20-line{margin:9px 0;word-break:break-word}.mcp20-k{display:block;color:#64748b;font-size:11px;margin-bottom:3px}
.mcp20-actions{display:none;position:absolute;z-index:30;gap:4px;flex-wrap:wrap;padding:6px;border-radius:11px;border:1px solid #d7e3f4;background:#fff;box-shadow:0 10px 28px #1e293b24;max-width:min(96%,600px)}
.mcp20-actions button{border:0;border-radius:7px;background:transparent;padding:7px 8px;color:#1e293b;font-size:12px;cursor:pointer;white-space:nowrap}
.mcp20-actions button:hover,.mcp20-actions button[data-current=true]{background:#e8f0ff;color:#175aca}.mcp20-actions button:last-child{color:#b91c1c}.mcp20-actions button:disabled{opacity:.4;cursor:not-allowed}.mcp20-selected{border:1px solid #dbeafe;background:#eff6ff;border-radius:8px;padding:10px;margin:12px 0}.mcp20-status{display:inline-block;padding:4px 8px;border-radius:99px;background:#e2e8f0;color:#334155;font-size:11px;font-weight:600}.mcp20-foot{padding:9px 16px;border-top:1px solid var(--b);font-size:11px;color:#64748b;background:#f8fafc}
.mcp20-action-icon{font-size:15px;margin-right:5px}
.mcp20-primary{background:#2563eb;color:white;border:0;border-radius:7px;padding:9px 12px;cursor:pointer;font-weight:600;margin-top:12px}
.mcp20-primary:disabled{opacity:.5;cursor:not-allowed}
.mcp20-secondary{background:white;color:#334155;border:1px solid #cbd5e1;border-radius:7px;padding:7px 12px;cursor:pointer;margin:10px 8px 0 0}
.mcp20-note{background:#eff6ff;padding:10px;border-radius:8px;color:#334155;line-height:1.5;margin-top:10px}
.mcp20-error{color:#b91c1c;padding:8px;background:#fef2f2;border-radius:6px}
.mcp20-field{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px}.mcp20-field label{font-size:11px;color:#64748b;flex:1;min-width:90px}.mcp20-field input{display:block;width:100%;border:1px solid #cbd5e1;border-radius:6px;padding:7px;color:#0f172a}
.mcp20-editor{box-shadow:0 6px 25px rgba(17,37,70,.08)}
.mcp20-head{padding:16px 22px;background:#fff}.mcp20-head strong{font-size:19px;letter-spacing:-.35px}
.mcp20-grid{grid-template-columns:minmax(0,1fr) 320px;min-height:670px}
.mcp20-main{background:#f9fbfe}.mcp20-main .mcpux-canvas{padding:22px!important;min-height:650px}
.mcp20-main .mcpux-canvas>div:nth-child(2){min-height:555px!important;background:#fff!important;border:1px solid #e0e8f2!important;box-shadow:0 2px 7px #2637500b}
.mcp20-side{padding:22px;background:#fff}.mcp20-side h4{font-size:16px}
.mcp20-actions{width:max-content;max-width:calc(100% - 16px);flex-wrap:nowrap;overflow-x:auto;box-shadow:0 13px 28px #172b4b30;border-radius:10px}
.mcp20-actions button{font-size:12px;padding:9px 10px}.mcp20-actions button:hover{background:#dbeafe}
.mcp20-selected{background:#f2f7ff}.mcp20-note{background:#eff6ff;border:1px solid #d9e8fe}
.mcp20-foot{padding:12px 20px;background:#fafbfd}
.mcp20-nav-business{border:1px solid #bfdbfe!important;border-radius:7px;background:#eff6ff!important;color:#1d4ed8!important;padding:7px 10px!important;cursor:pointer;font-size:12px;font-weight:600;white-space:nowrap}
.mcp20-nav-business:hover{background:#dbeafe!important}
.mcp20-main .mcpux-canvas>div:first-child{gap:6px!important}
.mcp20-main .mcpux-nav-controls{gap:6px!important}
.mcp20-reset-warning{border:1px solid #f59e0b!important;border-radius:7px;background:#fff7ed!important;color:#9a3412!important;padding:7px 10px!important;cursor:pointer;font-size:12px;font-weight:600}
.mcp20-reset-warning:hover{background:#ffedd5!important;border-color:#ea580c!important}
@media(max-width:800px){.mcp20-grid{grid-template-columns:1fr}.mcp20-side{border-left:0;border-top:1px solid var(--b)}.mcp20-actions{position:sticky;top:4px;left:5px!important;margin:5px}}
`;
function mount(frm,mountAt,opts){
 if(!opts||opts.enabled!==true)return null;
 if(!ns.createWorkspace||!ns.createCanvasRenderer||!ns.createUX04Guide)throw new Error('Modules MCP UX-02 à UX-04 non chargés');
 const ws=ns.createWorkspace(frm,{enabled:true});ws.mount();let disposed=false,guide=null,tree=null;
 const section=el('section',null,'mcp20-editor');const css=el('style');css.textContent=style;section.appendChild(css);
 // Le titre est déjà présent dans l'en-tête natif de frappe.ui.Dialog.

 const grid=el('div',null,'mcp20-grid'),main=el('div',null,'mcp20-main'),side=el('aside',null,'mcp20-side'),actions=el('div',null,'mcp20-actions');
 actions.setAttribute('aria-label','Actions de découpe');main.appendChild(actions);grid.append(main,side);section.appendChild(grid);const foot=el('div','Simulation locale · Aucun incident, Stock Entry ou Serial No ne sera modifié','mcp20-foot');section.appendChild(foot);mountAt.appendChild(section);
 const canvas=ns.createCanvasRenderer(main,(node,sheet)=>{if(!guide)return; if(node)guide.select(node,sheet);else guide.cancel();});
 const navControls=main.querySelector('.mcpux-nav-controls');
 if(navControls){
  if(typeof opts.onReset==='function'){
   const reset=el('button','Réinitialiser','mcp20-reset-warning');reset.type='button';
   reset.title='Attention : annule toutes les modifications locales de la simulation';
   reset.addEventListener('click',()=>opts.onReset());navControls.appendChild(reset);
  }
 }
 function parse(){const raw=typeof opts.getTree==='function'?opts.getTree():(frm.doc.mcp_mode==='Retour Terrain'?(frm.doc.effective_result_json||frm.doc.result_json):(frm.doc.result_json||frm.doc.effective_result_json));const value=typeof raw==='string'?JSON.parse(raw||'{}'):(raw||{});if(!Array.isArray(value.nodes))throw new Error('Résultat MCP indisponible');return value;}
 function line(key,value){const r=el('div',null,'mcp20-line');r.append(el('span',key,'mcp20-k'),el('span',value==null?'—':String(value)));side.appendChild(r);}
 function button(text,fn,cls){const b=el('button',text,cls||'mcp20-secondary');b.type='button';b.addEventListener('click',fn);side.appendChild(b);return b;}
 function locate(){const state=ws.store.getState();if(!state.sourceNodeId||!actions.children.length){actions.style.display='none';return;}const group=[...main.querySelectorAll('svg [data-node-id]')].find(n=>n.getAttribute('data-node-id')===state.sourceNodeId);const bounds=main.getBoundingClientRect();if(!group||!bounds.width){actions.style.display='none';return;}const b=group.getBoundingClientRect();actions.style.display='flex';const width=actions.offsetWidth||430;const left=Math.max(6,Math.min((b.left+b.right)/2-bounds.left-width/2,Math.max(6,bounds.width-width-6)));const proposed=b.top-bounds.top-actions.offsetHeight-12;const below=b.bottom-bounds.top+12;const top=proposed>=6?proposed:Math.min(below,Math.max(6,bounds.height-actions.offsetHeight-6));actions.style.left=left+'px';actions.style.top=top+'px';}
 function highlight(){const state=ws.store.getState();const meta=guide&&guide.stateInfo();const candidates=new Set(meta?meta.candidateIds:[]),targets=new Set(state.targetNodeIds||[]);for(const group of main.querySelectorAll('svg [data-node-id]')){const id=group.getAttribute('data-node-id'),rect=group.querySelector('rect');if(!rect)continue;const chosen=id===state.sourceNodeId||targets.has(id),suggested=candidates.has(id);rect.setAttribute('stroke',id===state.sourceNodeId?'#2563eb':targets.has(id)?'#16a34a':suggested?'#0d9488':'#94a3b8');rect.setAttribute('stroke-width',chosen||suggested?'9':'5');rect.setAttribute('stroke-dasharray',suggested&&!targets.has(id)?'16 10':'none');group.style.cursor=state.status==='selecting_target'&&!suggested?'not-allowed':'pointer';}}
 function render(){if(disposed)return;const s=ws.store.getState();canvas.setSelection(s.sourceNodeId);actions.replaceChildren();side.replaceChildren();
 side.appendChild(el('h4','Action en cours'));const status=el('span',s.busy?'Enregistrement…':s.preview?'Aperçu à valider':s.status==='selecting_target'?'Choisir une cible':s.sourceNodeId?'Zone sélectionnée':'En attente','mcp20-status');side.appendChild(status);
 if(s.sourceNodeId){for(const name of ws.controller.actions){if(!ws.controller.canStart(name,s.sourceNodeType))continue;const b=el('button');const sym=el('span',SYMBOL[name]||'·','mcp20-action-icon');b.append(sym,document.createTextNode(LABEL[name]||name));b.type='button';b.disabled=s.busy;b.dataset.current=String(s.action===name);b.addEventListener('click',()=>guide.begin(name));actions.appendChild(b);}}
 if(!s.sourceNodeId){side.appendChild(el('div','1. Cliquez sur une pièce ou une chute pour afficher les actions disponibles.','mcp20-note'));}
 else {const selected=el('div',null,'mcp20-selected');const src=guide.getItem(s.sourceNodeId);const n=src&&src.node||{};selected.append(el('span','Sélection actuelle','mcp20-k'),el('strong',n.label||s.sourceNodeId));if(n.length_mm&&n.width_mm)selected.append(el('div',`${n.length_mm} × ${n.width_mm} mm`));side.appendChild(selected);line('Action',LABEL[s.action]||'Choisissez une action sur la plaque');if(s.targetNodeIds.length)line('Cibles',s.targetNodeIds.map(id=>{const entry=guide.getItem(id);return entry&&entry.node.label||id;}).join(', '));}
 if(s.status==='selecting_target')side.appendChild(el('div','2. Cliquez sur une cible indiquée par un contour turquoise. La compatibilité géométrique sera contrôlée avant enregistrement.','mcp20-note'));
 if(s.action==='Resize'&&s.status==='action_active'){
  const info=guide.getItem(s.sourceNodeId),n=info&&info.node||{};const container=el('div',null,'mcp20-field');let inputs=[];
  for(const [label,value] of [['Longueur (mm)',n.effective_length_mm||n.length_mm],['Largeur (mm)',n.effective_width_mm||n.width_mm]]){const l=el('label',label),input=el('input');input.type='number';input.min='1';input.step='any';input.value=String(value||'');l.appendChild(input);container.appendChild(l);inputs.push(input);}side.appendChild(container);button('Prévisualiser',()=>guide.setResize(inputs[0].value,inputs[1].value),'mcp20-primary');
 }
 if(s.action==='Merge'&&s.status==='selecting_target'&&s.targetNodeIds.length)button('Prévisualiser la fusion',()=>guide.buildPreview(),'mcp20-primary');
 if(s.action==='Destroy'&&s.status==='action_active')button('Prévisualiser la destruction',()=>guide.buildPreview(),'mcp20-primary');
 if(s.preview){side.appendChild(el('div',(LABEL[s.preview.action]||s.preview.action)+' · '+s.preview.title,'mcp20-note'));side.appendChild(el('p',s.preview.detail));side.appendChild(el('p','Simulation graphique locale, non validée par Python.'));const apply=button('Appliquer à l’aperçu',async()=>{if(typeof opts.onApply!=='function')return;apply.disabled=true;try{await opts.onApply({preview:s.preview,guide,tree,workspace:ws});}catch(e){ws.controller.setError(String(e.message||e));}finally{apply.disabled=false;}},'mcp20-primary');apply.disabled=!!s.busy||typeof opts.onApply!=='function';}
 if(s.error)side.appendChild(el('div',s.error,'mcp20-error'));
 if(s.sourceNodeId)button('Annuler la sélection',()=>guide.cancel());
 highlight();locate();
 }
 function load(){tree=parse();canvas.setTree(tree);if(guide)guide.refresh(tree);else guide=ns.createUX04Guide(ws.store,ws.controller,tree);render();return canvas.getSheets().length;}
 const onKey=e=>{if(e.key==='Escape'&&!disposed&&ws.store.getState().sourceNodeId){guide.cancel();}};section.addEventListener('keydown',onKey);
 const unsub=ws.store.subscribe(render);const update=()=>locate();window.addEventListener('resize',update);main.addEventListener('scroll',update,true);load();
 return {refresh:load,getState:()=>ws.store.getState(),destroy(){if(disposed)return;disposed=true;unsub();window.removeEventListener('resize',update);main.removeEventListener('scroll',update,true);section.removeEventListener('keydown',onKey);canvas.destroy();section.remove();ws.destroy();}};
}
ns.mountUX20Editor=mount;
})(typeof window!=='undefined'?window:globalThis);
