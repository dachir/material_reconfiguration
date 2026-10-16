<script setup>
import {printDocument} from "./printing.js";
import {ref,computed} from 'vue';
const frappe=window.frappe,api='mat_reco.material_reconfiguration.services.technical_study_service.';
const data=ref({studies:[],permissions:{}}),name=ref(''),lines=ref([]),activeId=ref(''),path=ref([]),busy=ref(false),error=ref(''),dirty=ref(false);
const study=computed(()=>data.value.study),dossier=computed(()=>data.value.chantier);
const active=computed(()=>lines.value.find(l=>l.line_id===activeId.value));
const canWrite=computed(()=>study.value?.docstatus===0&&data.value.permissions?.write);
const selected=computed(()=>{let node=active.value?.tree;for(const index of path.value)node=node?.children?.[index];return node;});
const inherited=computed(()=>{let node=active.value?.tree;for(const i of path.value){if(node?.mode==='existing')return true;node=node?.children?.[i];}return false;});
const editable=computed(()=>canWrite.value&&!inherited.value);
function nodeEditable(entry){
 if(!canWrite.value||entry.node.item_type!=='OUVRAGE')return false;
 let node=active.value?.tree;
 for(const i of entry.path){if(node?.mode==='existing')return false;node=node?.children?.[i];}
 return true;
}
function nodeWritable(entry){return nodeEditable(entry)&&entry.node.mode==='new';}
function addComponent(entry){
 if(!nodeEditable(entry))return;
 if(entry.node.mode==='existing'){
  frappe.confirm('Cet ouvrage utilise un article existant. Créer une nouvelle variante pour ajouter des composants sans modifier cet article ?',()=>{
   if(!nodeEditable(entry))return;
   path.value=[...entry.path];variant();addComponent(entry);
  });return;
 }
 const lineId=activeId.value,target=entry.node,targetPath=[...entry.path];
 const dialog=new frappe.ui.Dialog({title:'Ajouter un composant à '+(target.item_name||displayCode(target)),fields:[
  {fieldname:'kind',label:'Type de composant',fieldtype:'Select',options:'OUVRAGE\nDECOUPE',default:'OUVRAGE',reqd:1,onchange:()=>dialog.set_value('item','')},
  {fieldname:'item',label:'Article existant (facultatif)',fieldtype:'Link',options:'Item',description:'Laisser vide pour définir un nouvel article.',get_query:()=>({filters:{custom_item_types:dialog.get_value('kind'),has_serial_no:1,disabled:0}})},
  {fieldname:'qty',label:'Quantité par ouvrage parent',fieldtype:'Int',default:1,reqd:1}
 ],primary_action_label:'Ajouter',async primary_action(v){
  if(!Number.isInteger(Number(v.qty))||Number(v.qty)<=0){frappe.msgprint('Saisir une quantité entière positive.');return;}
  dialog.disable_primary_action();
  try{
   const definition=v.item?await call('get_item_definition',{item_code:v.item}):null;
   if(activeId.value!==lineId||!nodeWritable(entry)||!nodes.value.some(e=>e.node===target))throw new Error('La sélection a changé. Recommencer l’ajout.');
   path.value=targetPath;add(v.kind);
   if(definition)Object.assign(selected.value,definition);
   selected.value.qty_factor=Number(v.qty);mark();dialog.hide();
  }catch(e){frappe.msgprint(describe(e));}finally{dialog.enable_primary_action();}
 }});dialog.show();
}
function flatten(node,p=[],out=[]){if(!node)return out;out.push({node,path:p,key:p.join('.')||'root'});for(const [i,c] of (node.children||[]).entries())flatten(c,[...p,i],out);return out;}
const nodes=computed(()=>flatten(active.value?.tree));
const counts=computed(()=>({works:lines.value.length,pieces:dossier.value?.lines?.reduce((a,l)=>a+Number(l.qty||0),0)||0,newItems:lines.value.reduce((n,l)=>n+flatten(l.tree).filter(x=>x.node.mode==='new').length,0),missing:lines.value.filter(l=>!l.length_mm||!l.width_mm||!l.thickness_mm||flatten(l.tree).some(({node:n})=>!(n.mode==='existing'?n.item_code:n.proposed_code)||(n.mode==='new'&&(!n.item_name||!n.stock_uom||!n.item_group||!n.warehouse))||(n.item_type==='OUVRAGE'&&!n.children?.length)||(n.item_type==='DECOUPE'&&n.children?.length!==1)||(n.item_type==='PRIMAIRE'&&(!n.length_mm||!n.width_mm||!n.thickness_mm)))).length}));
const macro=computed(()=>dossier.value?.lines?.find(l=>l.line_id===activeId.value));
const displayCode=(n)=>n?.mode==='existing'?n.item_code:(n?.proposed_code||'Code à définir');
const sectionName=(id)=>data.value.sections?.find(s=>s.name===id)?.section_name||'Sans section';
async function call(method,args={},write=false){return(await frappe.call({method:api+method,args,type:write?'POST':'GET'})).message;}
function describe(e){try{return JSON.parse(JSON.parse(e._server_messages)[0]).message;}catch{return e.message||'Opération impossible.';}}
function apply(value){data.value=value;lines.value=(value.study?.lines||[]).map(l=>({...l,tree:JSON.parse(l.tree_json||'{}')}));if(!lines.value.some(l=>l.line_id===activeId.value))activeId.value=lines.value[0]?.line_id||'';path.value=[];dirty.value=false;}
async function refresh(){busy.value=true;error.value='';try{apply(await call('get_study',{name:name.value||null}));}catch(e){error.value=describe(e);}finally{busy.value=false;}}
function mark(){dirty.value=true;}
function chooseLine(id){activeId.value=id;path.value=[];}
async function save(){if(!canWrite.value)return;busy.value=true;error.value='';try{const value=await call('save_study',{name:name.value,modified:study.value.modified,notes:study.value.notes,lines:JSON.stringify(lines.value.map(l=>({...l,tree_json:JSON.stringify(l.tree)})))},true);apply(value);return true;}catch(e){error.value=describe(e);return false;}finally{busy.value=false;}}
function submit(){frappe.confirm('Valider l’étude et créer les Items manquants ? Les articles compatibles seront réutilisés. Aucune fabrication ne sera déclenchée.',async()=>{if(dirty.value&&!(await save()))return;busy.value=true;error.value='';try{await frappe.call({method:'frappe.client.submit',args:{doc:study.value}});await refresh();}catch(e){error.value=describe(e);}finally{busy.value=false;}});}
function pick(field,doctype,filters={}){if(!editable.value)return;const dialog=new frappe.ui.Dialog({title:doctype,fields:[{fieldname:'value',label:doctype,fieldtype:'Link',options:doctype,reqd:1,get_query:()=>({filters})}],primary_action_label:'Choisir',async primary_action(v){dialog.disable_primary_action();try{if(field==='item_code'){const ratio=selected.value.qty_factor||1;const node=await call('get_item_definition',{item_code:v.value});Object.assign(selected.value,node,{qty_factor:ratio});}else{selected.value[field]=v.value;}mark();dialog.hide();}catch(e){frappe.msgprint(describe(e));}finally{dialog.enable_primary_action();}}});dialog.show();}
function chooseItem(){const kind=selected.value.item_type;pick('item_code','Item',{custom_item_types:kind,disabled:0,...(['OUVRAGE','DECOUPE','PRIMAIRE'].includes(kind)?{has_serial_no:1}:{})});}
function variant(){selected.value.mode='new';selected.value.proposed_code='';mark();}
function add(kind){if(!editable.value||selected.value.mode!=='new')return;const node={mode:'new',proposed_code:'',item_name:'',item_type:kind,stock_uom:active.value.tree.stock_uom||'',item_group:'',warehouse:'',qty_factor:1,children:[]};selected.value.children||=[];selected.value.children.push(node);path.value=[...path.value,selected.value.children.length-1];mark();}
function blankTree(source=macro.value){return {mode:'new',proposed_code:'',item_name:source?.designation||'',item_type:'OUVRAGE',stock_uom:source?.uom||'',item_group:'',qty_factor:1,children:[]};}
function resetStudy(){if(!canWrite.value)return;frappe.confirm('Effacer les compositions de tous les ouvrages et reprendre toute l’étude ?',()=>{if(!canWrite.value)return;for(const line of lines.value){const source=dossier.value.lines.find(r=>r.line_id===line.line_id);line.tree=blankTree(source);line.length_mm=source?.length_mm||0;line.width_mm=source?.width_mm||0;line.thickness_mm=source?.thickness_mm||0;}study.value.notes='';path.value=[];mark();});}
function resetComposition(){if(!canWrite.value)return;frappe.confirm('Effacer toute la composition de cet ouvrage et la reprendre à zéro ?',()=>{if(!canWrite.value)return;active.value.tree=blankTree();path.value=[];mark();});}
function remove(){
 if(!canWrite.value||!path.value.length)return;
 const target=selected.value,line=active.value,indices=[...path.value];
 frappe.confirm('Retirer cet article et tous ses enfants ? Les parents existants concernés deviendront des variantes à compléter avec de nouveaux codes.',()=>{
  if(!canWrite.value||active.value!==line||selected.value!==target)return;
  const p=[...indices],index=p.pop();let parent=line.tree;
  for(const i of [...p,null]){
   if(parent.mode==='existing'){parent.mode='new';parent.proposed_code='';}
   if(i!==null)parent=parent.children[i];
  }
  parent.children.splice(index,1);path.value=p;mark();
 });
}
function deleteStudy(){frappe.confirm('Supprimer définitivement cette étude et sa composition ? Vous pourrez préparer une nouvelle étude depuis le chantier.',async()=>{
 busy.value=true;error.value='';try{const chantier=await call('delete_study',{name:study.value.name,modified:study.value.modified},true);sessionStorage.setItem('univers-chantier-selected',chantier);frappe.set_route('chantiers');}catch(e){error.value=describe(e);}finally{busy.value=false;}
});}
function cancelStudy(){frappe.confirm('Annuler cette étude validée ?',async()=>{busy.value=true;error.value='';try{await frappe.call({method:'frappe.client.cancel',args:{doctype:'Chantier Technical Study',name:study.value.name}});await refresh();}catch(e){error.value=describe(e);}finally{busy.value=false;}});}
function show(){name.value=frappe.get_route()[1]||sessionStorage.getItem('univers-technical-study')||'';sessionStorage.removeItem('univers-technical-study');refresh();}
function hide(){}
function back(){const leave=()=>{sessionStorage.setItem('univers-chantier-selected',dossier.value.name);frappe.set_route('chantiers');};if(dirty.value)frappe.confirm('Quitter sans enregistrer les modifications techniques ?',leave);else leave();}
defineExpose({show,hide});
</script>
<template>
<div class="ug-tech">
 <header><div><p>UNIVERS GLASS · PRÉPARATION TECHNIQUE</p><h1>Étude technique <span v-if="study" class="badge">{{['Brouillon','Validée','Annulée'][study.docstatus]}}</span></h1><span>{{dossier?.designation}} <small v-if="dossier">· {{dossier.name}}</small></span></div><div class="actions"><button v-if="study" :disabled="busy||dirty" title="Enregistrer les modifications avant impression" @click="printDocument('Chantier Technical Study',study.name)">Imprimer A4</button><button v-if="dossier" @click="back">← Retour au chantier</button><button :disabled="busy" @click="refresh">Actualiser</button><button v-if="study?.docstatus===1&&data.permissions?.cancel" :disabled="busy||dirty" @click="cancelStudy">Annuler l’étude</button><button v-if="study&&study.docstatus!==1&&data.permissions?.delete" class="danger" :disabled="busy" @click="deleteStudy">Supprimer l’étude</button><button v-if="canWrite" class="danger" :disabled="busy" @click="resetStudy">Reprendre toute l’étude</button><button v-if="canWrite" class="blue" :disabled="busy||!dirty" @click="save">Enregistrer</button><button v-if="canWrite&&data.permissions?.submit" class="green" :disabled="busy||data.stale" @click="submit">Valider l’étude</button></div></header>
 <section class="toolbar"><label>Étude<select v-model="name" :disabled="busy||dirty" @change="refresh"><option value="">Sélectionner une étude</option><option v-for="s in data.studies" :key="s.name" :value="s.name">{{s.chantier}} · {{s.name}} · {{['Brouillon','Validée','Annulée'][s.docstatus]}}</option></select></label><button v-if="study" @click="frappe.set_route('Form','Chantier Technical Study',study.name)">Document ERPNext</button></section>
 <div v-if="error" class="alert" role="alert" v-text="error"></div><div v-if="data.stale" class="alert">Les besoins commerciaux ont changé. Préparer une nouvelle étude depuis le chantier avant validation.</div>
 <div class="info">Le devis sera disponible après validation de l’étude technique et du chantier commercial.</div>
 <template v-if="study">
 <section class="cards"><article><strong>{{counts.works}}</strong><span>ouvrages à étudier</span></article><article><strong>{{counts.pieces}}</strong><span>pièces prévues</span></article><article><strong>{{counts.newItems}}</strong><span>nouvelles définitions d’articles</span></article><article class="orange"><strong>{{counts.missing}}</strong><span>ouvrages à compléter</span></article></section>
 <div class="columns"><aside class="panel works"><h2>Ouvrages à étudier</h2><button v-for="line in lines" :key="line.line_id" :class="{selected:activeId===line.line_id}" @click="chooseLine(line.line_id)"><strong>{{line.repere}} · {{dossier.lines.find(l=>l.line_id===line.line_id)?.designation}}</strong><small>{{sectionName(dossier.lines.find(l=>l.line_id===line.line_id)?.section)}}</small><span>{{line.length_mm||'—'}} × {{line.width_mm||'—'}} mm · {{dossier.lines.find(l=>l.line_id===line.line_id)?.qty}} pièces</span></button></aside>
 <main v-if="active" class="panel definition"><h2>{{active.repere}} — Définition technique</h2><div class="fields"><label>Longueur (mm)<input v-model.number="active.length_mm" type="number" min="1" :disabled="!canWrite" @input="mark" /></label><label>Hauteur (mm)<input v-model.number="active.width_mm" type="number" min="1" :disabled="!canWrite" @input="mark" /></label><label>Épaisseur totale (mm)<input v-model.number="active.thickness_mm" type="number" min="0.01" step="any" :disabled="!canWrite" @input="mark" /></label><label>Lame d’air (mm)<input v-model.number="active.tree.air_gap_mm" type="number" min="0" step="any" placeholder="0" :disabled="!canWrite" @input="mark" /></label><label>Quantité commerciale<input :value="macro?.qty" disabled /></label></div><p class="muted">Double vitrage 6/12/6 : épaisseur totale 24 mm, lame d’air 12 mm, deux découpes de verre de 6 mm dans la composition. La lame d’air ne consomme aucun stock.</p>
 <h3>Composition de fabrication</h3><button v-if="canWrite" class="danger" :disabled="busy" @click="resetComposition">Reprendre toute la composition</button><p class="muted">Cliquez sur le + d’un ouvrage pour lui ajouter plusieurs articles ou ouvrages de compositions différentes.</p>
 <div class="tree"><div v-for="entry in nodes" :key="entry.key" class="tree-node" :style="{marginLeft:entry.path.length*16+'px'}">
 <button class="node-select" :class="{selected:path.join('.')===entry.path.join('.')}" @click="path=entry.path"><span class="icon">{{entry.node.item_type==='PRIMAIRE'?'▱':entry.node.item_type==='DECOUPE'?'▯':'◇'}}</span><span><strong>{{entry.node.item_name||displayCode(entry.node)}}</strong><small>{{displayCode(entry.node)}} · {{entry.node.item_type}} <template v-if="entry.path.length">· × {{entry.node.qty_factor||1}}</template></small></span><span v-if="entry.node.item_type==='OUVRAGE'" class="component-count">{{entry.node.children?.length||0}} composant(s)</span><span class="tag" :class="entry.node.mode==='existing'?'valid':'new'">{{entry.node.mode==='existing'?'Item existant':'À créer'}}</span></button>
 <button v-if="canWrite&&entry.node.item_type==='OUVRAGE'" :disabled="!nodeEditable(entry)" class="node-add" :aria-label="'Ajouter un composant à '+(entry.node.item_name||displayCode(entry.node))" title="Ajouter un composant" @click="addComponent(entry)">+</button>
 </div></div>
 <div v-if="editable&&selected?.mode==='new'&&selected.item_type==='DECOUPE'&&!selected.children?.length" class="actions"><button @click="add('PRIMAIRE')">+ Matière primaire</button></div><p v-if="inherited||selected?.mode==='existing'" class="muted">La composition d’un article existant est conservée. Sélectionner cet ouvrage et utiliser « Définir un nouvel article » pour créer une variante modifiable.</p>
 <label class="notes">Notes techniques<textarea v-model="study.notes" :disabled="!canWrite" @input="mark"></textarea></label></main>
 <aside v-if="selected" class="panel inspector"><h2>Article et contrôles</h2><div class="actions" v-if="editable"><button @click="chooseItem">Rechercher un Item existant</button><button v-if="selected.mode==='existing'" @click="variant">Définir un nouvel article</button></div>
 <label>Type d’article<select v-model="selected.item_type" :disabled="!editable||selected.mode==='existing'" @change="mark"><option>OUVRAGE</option><option>DECOUPE</option><option v-if="path.length">PRIMAIRE</option><option v-if="selected.mode==='existing'&&selected.item_type==='ACCESSOIRE'">ACCESSOIRE</option></select></label>
 <label>{{selected.mode==='existing'?'Code article existant':'Code article proposé'}}<input v-if="selected.mode==='new'" v-model="selected.proposed_code" :disabled="!editable" @input="mark" /><input v-else :value="selected.item_code" disabled /></label><label>Désignation<input v-model="selected.item_name" :disabled="!editable||selected.mode==='existing'" @input="mark" /></label>
 <div class="fields"><label>Unité<button :disabled="!editable||selected.mode==='existing'" @click="pick('stock_uom','UOM')">{{selected.stock_uom||'Choisir'}}</button></label><label>Groupe d’articles<button :disabled="!editable||selected.mode==='existing'" @click="pick('item_group','Item Group',{is_group:0})">{{selected.item_group||'Choisir'}}</button></label></div>
 <label v-if="path.length">Quantité par parent<input v-model.number="selected.qty_factor" type="number" min="1" step="1" :disabled="!editable" @input="mark" /></label>
 <template v-if="selected.item_type==='PRIMAIRE'"><h3>Format nominal de la plaque</h3><div class="fields"><label>Longueur (mm)<input v-model.number="selected.length_mm" type="number" :disabled="!editable||selected.mode==='existing'" @input="mark" /></label><label>Hauteur (mm)<input v-model.number="selected.width_mm" type="number" :disabled="!editable||selected.mode==='existing'" @input="mark" /></label><label>Épaisseur (mm)<input v-model.number="selected.thickness_mm" type="number" step="any" :disabled="!editable||selected.mode==='existing'" @input="mark" /></label></div></template>
 <label v-if="selected.mode==='new'">Entrepôt par défaut<button :disabled="!editable" @click="pick('warehouse','Warehouse',{company:dossier.company,is_group:0})">{{selected.warehouse||'Choisir un entrepôt'}}</button></label>
 <div class="serial">✓ Suivi Serial No pour les articles vitrés</div><div class="glass-preview" aria-hidden="true"><i></i><i></i><i></i></div><p class="muted">À la validation, les Items manquants sont créés des composants vers le parent. Aucun Item existant n’est écrasé.</p><button v-if="canWrite&&path.length" class="danger" :disabled="busy" @click="remove">Retirer cet article et ses enfants</button></aside></div>
 </template><div v-else class="empty">Préparer une étude depuis un chantier commercial pour définir ses ouvrages.</div><footer>États standards : Brouillon → Validé → Annulé. Aucune fabrication déclenchée par cette validation.</footer>
</div>
</template>
<style scoped>
.ug-tech{background:#03131e;color:#edf3ff;padding:22px;min-height:85vh;border-radius:8px;font:13px/1.5 Inter,system-ui,sans-serif}.ug-tech *{box-sizing:border-box}.ug-tech h1,.ug-tech h2,.ug-tech h3,.ug-tech strong{color:#edf3ff}header,.actions,.toolbar{display:flex;align-items:center;gap:10px;flex-wrap:wrap}header{justify-content:space-between}header p{color:#00caff;font-size:11px;letter-spacing:2px;margin:0}h1{font-size:28px;margin:4px 0}h2{font-size:16px;margin:0 0 16px}h3{font-size:13px;margin:20px 0 10px}.badge,.tag{font-size:11px;border:1px solid #204255;border-radius:6px;padding:4px 8px;white-space:nowrap}.badge{vertical-align:middle;background:#103348}.toolbar{padding:18px 0}.toolbar label{display:flex;gap:10px;align-items:center}button,input,select,textarea{font:inherit;color:#edf3ff;border:1px solid #204255;border-radius:6px;background:#092536;padding:9px;width:auto}button{cursor:pointer}button:hover,button.selected{border-color:#00caff;background:#103c54}button:disabled{opacity:.5;cursor:default}button.blue{background:#008cff;color:white}button.green{background:#00aa7b;color:white}.danger{color:#ff788e}.info{background:#082c40;border:1px solid #185675;padding:10px 14px;border-radius:6px;margin-bottom:14px}.alert{background:#4a2833;color:#ffe1e5;padding:12px;border:1px solid #b65b6f;margin:10px 0}.cards{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:16px}.cards article,.panel{background:#061c29;border:1px solid #17394d;border-radius:8px;padding:16px}.cards article{display:flex;gap:12px;align-items:center}.cards strong{font-size:28px;color:#00caff}.cards .orange strong{color:#ffb53e}.cards span{color:#a3bdd1}.columns{display:grid;grid-template-columns:minmax(200px,.8fr) minmax(360px,1.4fr) minmax(270px,1fr);gap:14px;align-items:start}.works>button{width:100%;text-align:left;margin-bottom:10px;display:flex;flex-direction:column;gap:5px}.works small,.works span,.muted,small,footer{color:#a3bdd1}.fields{display:grid;grid-template-columns:1fr 1fr;gap:12px}label{display:flex;flex-direction:column;gap:6px;margin-bottom:12px;color:#a3bdd1}label>input,label>select,label>button,textarea{width:100%}.tree{padding:5px 0 15px}.tree-node{display:flex;align-items:stretch;gap:6px;margin-bottom:8px}.tree-node>.node-select{flex:1;min-width:0;display:flex;justify-content:flex-start;gap:10px;align-items:center;text-align:left;margin-bottom:8px;padding:10px}.tree small{display:block;font-size:10px}.tree .icon{color:#00caff;font-size:24px;flex:0 0 26px;width:26px;height:auto;display:inline-block}.tree-node>.node-select>span:nth-child(2){flex:1;min-width:0}.tag{margin-left:auto;font-size:9px}.valid{color:#00d48c;border-color:#00d48c44}.new{color:#00caff}.check{flex-direction:row;align-items:center}.check input{width:auto}.serial{color:#00d48c;margin:15px 0}.glass-preview{height:130px;position:relative;overflow:hidden;border:1px solid #17394d;background:#041520;border-radius:8px}.glass-preview i{position:absolute;left:30%;top:20px;width:95px;height:95px;border:2px solid #38ceff;background:#00baff22;transform:skewY(-18deg)}.glass-preview i:nth-child(2){left:38%;top:25px}.glass-preview i:nth-child(3){left:46%;top:30px}.component-count{color:#a3bdd1;font-size:10px}.node-add{flex:0 0 36px;padding:4px;color:#00caff;font-size:24px;line-height:1}.node-add:hover{background:#103c54}.notes{margin-top:20px}textarea{min-height:90px}footer{padding-top:18px;font-size:11px}.empty{padding:80px;text-align:center}@media(max-width:1200px){.columns{grid-template-columns:200px minmax(300px,1fr)}.inspector{grid-column:2}.cards{grid-template-columns:repeat(2,1fr)}}@media(max-width:750px){.ug-tech{padding:12px}.columns{display:block}.panel{margin-bottom:12px}.cards{gap:8px}.cards article{padding:10px}.fields{grid-template-columns:1fr}.toolbar label{display:block}.toolbar select{max-width:100%}.tree-node{display:flex;align-items:stretch;gap:6px;margin-bottom:8px}.tree-node>.node-select{flex:1;min-width:0;gap:5px}.tag{white-space:normal}}
</style>
