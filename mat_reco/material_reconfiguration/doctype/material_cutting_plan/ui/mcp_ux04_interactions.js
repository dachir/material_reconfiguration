/* MCP UX-04 — advisory candidates and immutable intention previews; no ERPNext writes. */
(function(root){'use strict';
const ns=root.MatRecoMCPUX20=root.MatRecoMCPUX20||{};
const num=v=>Number(v)||0;
const TARGET_ACTIONS=new Set(['Move','Merge','Single']);
const normalType=n=>String(n&&n.node_type||'').toLowerCase();
function validPiece(n){return n&&n.id&&!n.is_preexisting_cutout&&!n.is_single_cutout&&!n.single_logical_cutout&&num(n.effective_length_mm||n.length_mm)>0&&num(n.effective_width_mm||n.width_mm)>0;}
function candidate(source,target,action,sourceSheet,targetSheet){
 if(!validPiece(source)||!validPiece(target)||String(source.id)===String(target.id))return false;
 if(action==='Move')return normalType(source)==='finished_good'&&['leftover','waste'].includes(normalType(target));
 if(action==='Merge'||action==='Single')return ['leftover','waste'].includes(normalType(source))&&['leftover','waste'].includes(normalType(target))&&String(sourceSheet)===String(targetSheet);
 return false;
}
function indexTree(tree){const sheets=(tree&&Array.isArray(tree.nodes)?tree.nodes:[]).filter(s=>s&&s.node_type==='input_serial');const byId=new Map();for(const sheet of sheets){const key=String(sheet.serial_no||sheet.id);for(const child of sheet.children||[])if(child&&child.id)byId.set(String(child.id),{node:child,sheet:key});}return {sheets,byId};}
function description(action,source,targets,parameters){const t=targets||[];const p=parameters||{};if(action==='Resize')return {title:'Redimensionnement à vérifier',detail:`${num(p.length_mm)} × ${num(p.width_mm)} mm demandés. Aucune géométrie n’est encore recalculée.`,ready:num(p.length_mm)>0&&num(p.width_mm)>0&&num(p.length_mm)<=num(source&&source.effective_length_mm||source&&source.length_mm)&&num(p.width_mm)<=num(source&&source.effective_width_mm||source&&source.width_mm)};
if(action==='Destroy')return {title:'Destruction envisagée',detail:'La pièce sélectionnée sera proposée pour destruction après validation métier.',ready:!!source};
if(action==='Single')return {title:'Single envisagé',detail:'Deux zones résiduelles candidates. L’encoche, la surface et les collisions seront vérifiées côté Python.',ready:t.length===1};
if(action==='Merge')return {title:'Fusion envisagée',detail:'Zones résiduelles candidates. Adjacence et géométrie non validées à ce stade.',ready:t.length>=1};
if(action==='Move')return {title:'Déplacement envisagé',detail:'Zone réceptrice candidate. Placement précis, swap/swing et chevauchements non validés.',ready:t.length===1};
return {title:'Sélection',detail:'Choisissez une action.',ready:false};}
function createGuide(store,controller,tree){let index=indexTree(tree);let params={};function item(id){return index.byId.get(String(id))||null;}
 function candidates(){const s=store.getState();const source=item(s.sourceNodeId);if(!source||!TARGET_ACTIONS.has(s.action))return [];
 return [...index.byId.entries()].filter(([id,target])=>candidate(source.node,target.node,s.action,source.sheet,target.sheet)).map(([id])=>id);}
 function select(node,sheet){const s=store.getState();if(s.status==='preview')return false;if(s.status==='selecting_target'){
 const source=item(s.sourceNodeId);const target=item(node&&node.id);if(!source||!target||!candidate(source.node,target.node,s.action,source.sheet,target.sheet)){store.update({error:'Zone non candidate pour cette action.'});return false;}
 if(s.action==='Move'||s.action==='Single'){if(s.targetNodeIds.length)return false;controller.addTarget(node);return buildPreview();}
 return controller.addTarget(node);
 }return controller.select(node,sheet&& (sheet.serial_no||sheet.id)||null);}
 function begin(action){params={};return controller.begin(action);}
 function setResize(length,width){params={length_mm:num(length),width_mm:num(width)};return buildPreview();}
 function buildPreview(){const s=store.getState();if(!s.action)return false;const source=item(s.sourceNodeId);const targets=s.targetNodeIds.map(item).filter(Boolean).map(x=>x.node);const result=description(s.action,source&&source.node,targets,params);if(!result.ready){store.update({error:'Paramètres ou cibles insuffisants pour l’aperçu.'});return false;}
 return controller.showPreview({kind:'intention_only',action:s.action,sourceNodeId:s.sourceNodeId,targetNodeIds:s.targetNodeIds.slice(),parameters:Object.assign({},params),title:result.title,detail:result.detail,verifiedByServer:false,committed:false});}
 function cancel(){params={};return controller.cancel();}
 function refresh(treeNext){index=indexTree(treeNext);params={};controller.cancel();}
 function stateInfo(){const s=store.getState();const source=item(s.sourceNodeId);const targets=s.targetNodeIds.map(item).filter(Boolean).map(x=>x.node);return {candidateIds:candidates(),preview:s.preview,parameters:Object.assign({},params),description:description(s.action,source&&source.node,targets,params)};}
 return {select,begin,setResize,buildPreview,cancel,refresh,stateInfo,candidateIds:candidates,getItem:item};}
ns.createUX04Guide=createGuide;ns.ux04Candidate=candidate;ns.ux04Description=description;ns.ux04IndexTree=indexTree;
})(typeof window!=='undefined'?window:globalThis);
