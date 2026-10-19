<script setup>
import {ref,computed,onMounted,onBeforeUnmount} from 'vue';
const props=defineProps({chantier:Object,workType:Object,parentLineIds:{type:Array,default:()=>[]},disabled:Boolean,beforeApply:Function});
const emit=defineEmits(['applied','type-applied','updated','close']);
let active=true;onBeforeUnmount(()=>{active=false;});
const frappe=window.frappe,api='mat_reco.material_reconfiguration.services.chantier_extras.';
const catalogue=ref([]),settings=ref({}),search=ref(''),kind=ref(''),loading=ref(false),applying=ref(false),error=ref(''),notice=ref('');
const entries=computed(()=>catalogue.value.filter(r=>(!kind.value||r.custom_item_types===kind.value)&&(`${r.name} ${r.item_name} ${r.basis}`).toLowerCase().includes(search.value.toLowerCase())));
const assigned=computed(()=>(props.chantier.commercial_extras||[]).filter(e=>props.parentLineIds.includes(e.parent_line_id)));
function adjust(extra,field,event){const value=event.target.valueAsNumber;if(!Number.isFinite(value))return;emit('updated',{line_id:extra.line_id,field:field==='amount'?'rate':field,value:field==='amount'?value/Number(extra.qty):value});}
const selection=computed(()=>catalogue.value.filter(r=>settings.value[r.name]?.selected));
function describe(e){try{return JSON.parse(JSON.parse(e._server_messages)[0]).message;}catch{return e.message||'Opération impossible.';}}
async function load(){loading.value=true;error.value='';try{
 catalogue.value=(await frappe.call({method:api+'catalogue',type:'GET'})).message;
 for(const r of catalogue.value){const existing=JSON.parse(props.workType?.common_extras||'[]').find(e=>e.item_code===r.name);settings.value[r.name]||={selected:!!existing,manual_qty:r.basis==='MANUEL',qty:existing?.qty||1,factor:existing?.factor||1,rate:existing?.rate??(props.workType?0:''),rate_set:false,key:existing?.key};}
}catch(e){error.value=describe(e);}finally{loading.value=false;}}
async function apply(){
 if(applying.value||props.disabled)return;
 if(props.workType){
  error.value='';notice.value='';
  const definitions=selection.value.map(r=>{const setting=settings.value[r.name];setting.key||=globalThis.crypto?.randomUUID?.()||'extra-'+Date.now()+'-'+Math.random().toString(16).slice(2);return {item_code:r.name,key:setting.key,item_name:r.item_name,item_type:r.custom_item_types,basis:r.basis,uom:r.stock_uom,fixed_qty:r.custom_service_fixed_qty,qty:Number(setting.qty),factor:Number(setting.factor),rate:Number(setting.rate)};});
  if(definitions.some(d=>!Number.isFinite(d.rate)||d.rate<0||!Number.isFinite(d.qty)||d.qty<=0||!Number.isFinite(d.factor)||d.factor<=0)){error.value='Saisir un prix positif ou nul, une quantité et un coefficient positifs.';return;}
  emit('type-applied',definitions);emit('close');return;
 }
 if(!selection.value.length||!props.parentLineIds.length)return;
 applying.value=true;error.value='';notice.value='';
 const parents=[...props.parentLineIds],assignments=selection.value.map(r=>({item_code:r.name,...settings.value[r.name]}));
 try{
  if(props.beforeApply&&!(await props.beforeApply()))return;
  if(!active)return;
  const snapshot=JSON.stringify(props.chantier);
  const result=(await frappe.call({method:api+'preview_batch',type:'POST',args:{chantier:props.chantier.name,modified:props.chantier.modified,parent_line_ids:JSON.stringify(parents),assignments:JSON.stringify(assignments)}})).message;
  if(!active)return;
  if(snapshot!==JSON.stringify(props.chantier))throw new Error('Le chantier a été modifié pendant le calcul. Recommencer l’affectation.');
  emit('applied',result.rows);
  emit('close');
 }catch(e){error.value=describe(e);}finally{applying.value=false;}
}
onMounted(load);
</script>
<template>
<aside class="extras-panel" aria-label="Affectation des services et accessoires">
 <div class="drawer-heading"><h2>Services / Accessoires</h2><button type="button" aria-label="Fermer les prestations" :disabled="applying" @click="emit('close')">×</button></div>
 <p v-if="workType"><strong>{{workType.designation}}</strong> · Compléments communs à tous les ouvrages de ce type</p><p v-else>Affectation à {{parentLineIds.length}} ouvrage(s)</p><p v-if="!workType&&parentLineIds.length===1">{{chantier.lines.find(r=>r.line_id===parentLineIds[0])?.designation}}</p>

 <section v-if="!workType&&assigned.length" class="assigned-extras"><h3>Compléments de ces lignes</h3><article v-for="extra in assigned" :key="extra.line_id" class="catalogue-item"><strong>{{extra.item_name||extra.item_code}}</strong><small>{{chantier.lines.find(r=>r.line_id===extra.parent_line_id)?.repere}} · {{extra.inherited_from?'Valeurs proposées par le type, ajustables ici':'Complément de la ligne'}}</small><label>Quantité<input type="number" :value="extra.qty" min="0.000001" step="any" :disabled="disabled||applying" :aria-label="'Quantité de '+extra.item_code+' pour '+extra.parent_line_id" @change="adjust(extra,'qty',$event)" /></label><label>Prix unitaire ({{chantier.currency}})<input type="number" :value="extra.rate" min="0" step="any" :disabled="disabled||applying" :aria-label="'Prix de '+extra.item_code+' pour '+extra.parent_line_id" @change="adjust(extra,'rate',$event)" /></label><label>Montant ({{chantier.currency}})<input type="number" :value="Number(extra.qty)*Number(extra.rate)" min="0" step="any" :disabled="disabled||applying||!(Number(extra.qty)>0)" :aria-label="'Montant de '+extra.item_code+' pour '+extra.parent_line_id" @change="adjust(extra,'amount',$event)" /></label></article><small>Enregistrer le chantier pour conserver ces ajustements.</small></section>
 <div class="catalogue-filters"><input v-model="search" aria-label="Rechercher un service ou accessoire" placeholder="Rechercher…" /><select v-model="kind" aria-label="Type de complément"><option value="">Tous les types</option><option value="SERVICE">Services</option><option value="ACCESSOIRE">Accessoires</option></select></div>
 <div v-if="error" class="panel-error" role="alert" v-text="error"></div>
 <div v-if="notice" class="panel-notice" role="status">{{notice}}</div>
 <p v-if="loading">Chargement du catalogue…</p>
 <div class="catalogue-list"><article v-for="item in entries" :key="item.name" class="catalogue-item" :class="{picked:settings[item.name].selected}">
  <label class="catalogue-choice"><input v-model="settings[item.name].selected" type="checkbox" :disabled="applying||disabled" :aria-label="'Sélectionner '+item.item_name" /><span><strong>{{item.item_name}}</strong><small>{{item.name}} · {{item.custom_item_types}} · {{item.basis}}</small></span></label>
  <div v-if="settings[item.name].selected" class="item-settings">
   <label v-if="!workType&&item.basis!=='MANUEL'" class="inline-check"><input v-model="settings[item.name].manual_qty" type="checkbox" :disabled="applying||disabled" /> Quantité manuelle identique</label>
   <label v-if="settings[item.name].manual_qty">{{workType?'Quantité par pièce par défaut':'Quantité totale par ligne d’ouvrage'}}<input v-model.number="settings[item.name].qty" type="number" min="0.000001" step="any" :disabled="applying||disabled" /></label>
   <p v-else>Calcul {{item.basis.toLowerCase()}} propre à chaque ouvrage.</p>
   <label v-if="workType">Coefficient<input v-model.number="settings[item.name].factor" type="number" min="0.000001" step="any" :disabled="applying||disabled" /></label><label>{{workType?'Prix unitaire par défaut':'Prix unitaire commun'}} ({{chantier.currency}} / {{item.stock_uom}})<input v-model="settings[item.name].rate" type="number" min="0" step="any" placeholder="Liste de prix sinon à confirmer" @input="settings[item.name].rate_set=false" :disabled="applying||disabled" /></label>
   <label v-if="!workType&&settings[item.name].rate!==''" class="inline-check"><input v-model="settings[item.name].rate_set" type="checkbox" :disabled="applying||disabled" /> Prix commun confirmé (facultatif)</label>
  </div>
 </article><p v-if="!loading&&!entries.length">Aucun complément trouvé.</p></div>
 <div class="assignment-footer"><strong>{{workType?'Type : '+workType.designation:parentLineIds.length+' ouvrage(s)'}} · {{selection.length}} complément(s)</strong><button type="button" :disabled="disabled||applying||(!workType&&(!parentLineIds.length||!selection.length))" @click="apply">{{applying?'Calcul en cours…':workType?'Appliquer au type':parentLineIds.length===1?'Affecter à cet ouvrage':'Affecter aux ouvrages sélectionnés'}}</button><small>{{workType?'Cochez ou décochez les compléments communs. Les quantités seront calculées pour chaque ouvrage à l’enregistrement.':'Les affectations déjà présentes sont conservées. Les quantités automatiques sont calculées séparément pour chaque ouvrage.'}}</small></div>
</aside>
</template>
<style scoped>
.assigned-extras{max-height:45%;overflow:auto;margin-bottom:10px}.assigned-extras h3{font-size:14px;margin:4px 0}.assigned-extras label,.assigned-extras small{display:block}.assigned-extras label{margin-top:5px}.drawer-heading{display:flex;align-items:center;justify-content:space-between;gap:8px}.drawer-heading button{width:auto!important}.extras-panel{position:sticky;top:0;height:100dvh;display:flex;flex-direction:column;overflow:hidden;align-self:start;background:#071e2b;border:1px solid #204255;border-radius:0;padding:16px;min-width:0;color:#dcecf7;font:13px/1.5 Inter,system-ui,sans-serif}.extras-panel h2{color:#edf3ff;font-size:17px;margin:0 0 10px}.extras-panel p,.extras-panel small{color:#9eb9cc}.extras-panel input,.extras-panel select,.extras-panel button{font:inherit;background:#0a283a;color:#edf3ff;border:1px solid #204255;border-radius:6px;padding:8px;width:100%;min-width:0}.catalogue-filters{display:grid;gap:8px;margin-bottom:12px}.extras-panel>*{flex-shrink:0}.catalogue-list{flex:1;min-height:0;overflow:auto;padding-right:4px}.catalogue-item{border:1px solid #204255;border-radius:6px;padding:10px;margin-bottom:8px}.catalogue-item.picked{border-color:#00caff;background:#092536}.catalogue-choice,.inline-check{display:flex;gap:8px;align-items:flex-start;cursor:pointer}.extras-panel input[type=checkbox]{width:auto;flex-shrink:0;accent-color:#008cff;margin-top:4px}.catalogue-choice strong{display:block;color:#edf3ff;overflow-wrap:anywhere}.catalogue-choice small{display:block;font-size:10px;overflow-wrap:anywhere}.item-settings{margin-top:12px;border-top:1px solid #204255;padding-top:10px}.item-settings label{display:flex;flex-direction:column;gap:4px;margin-bottom:10px;color:#a3bdd1}.item-settings .inline-check{flex-direction:row}.item-settings p{margin:4px 0 12px}.assignment-footer{display:grid;gap:10px;padding-top:14px;border-top:1px solid #204255}.assignment-footer button{background:#006aff;cursor:pointer}.extras-panel button:disabled{opacity:.5;cursor:default}.extras-panel :focus-visible{outline:2px solid #00caff;outline-offset:2px}.panel-error,.panel-notice{padding:10px;border:1px solid #b65b6f;background:#452430;border-radius:6px;margin-bottom:12px}.panel-notice{background:#08352e;border-color:#00aa7b;color:#bff5df}
</style>
