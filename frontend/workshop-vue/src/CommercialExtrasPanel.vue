<script setup>
import {ref,computed,onMounted,onBeforeUnmount} from 'vue';
const props=defineProps({chantier:Object,parentLineIds:Array,disabled:Boolean,beforeApply:Function});
const emit=defineEmits(['applied']);
let active=true;onBeforeUnmount(()=>{active=false;});
const frappe=window.frappe,api='mat_reco.material_reconfiguration.services.chantier_extras.';
const catalogue=ref([]),settings=ref({}),search=ref(''),kind=ref(''),loading=ref(false),applying=ref(false),error=ref(''),notice=ref('');
const entries=computed(()=>catalogue.value.filter(r=>(!kind.value||r.custom_item_types===kind.value)&&(`${r.name} ${r.item_name} ${r.basis}`).toLowerCase().includes(search.value.toLowerCase())));
const selection=computed(()=>catalogue.value.filter(r=>settings.value[r.name]?.selected));
function describe(e){try{return JSON.parse(JSON.parse(e._server_messages)[0]).message;}catch{return e.message||'Opération impossible.';}}
async function load(){loading.value=true;error.value='';try{
 catalogue.value=(await frappe.call({method:api+'catalogue',type:'GET'})).message;
 for(const r of catalogue.value)settings.value[r.name]||={selected:false,manual_qty:r.basis==='MANUEL',qty:1,rate:'',rate_set:false};
}catch(e){error.value=describe(e);}finally{loading.value=false;}}
async function apply(){
 if(applying.value||props.disabled||!selection.value.length||!props.parentLineIds.length)return;
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
  notice.value=`${result.rows.length} affectation(s) ajoutée(s). ${result.skipped} déjà présente(s), conservée(s). Enregistrer les ouvrages pour sauvegarder.`;
 }catch(e){error.value=describe(e);}finally{applying.value=false;}
}
onMounted(load);
</script>
<template>
<aside class="extras-panel" aria-label="Affectation des services et accessoires">
 <h2>Services / Accessoires</h2>
 <p>Cochez les ouvrages à gauche, puis les compléments à leur affecter.</p>
 <div class="catalogue-filters"><input v-model="search" aria-label="Rechercher un service ou accessoire" placeholder="Rechercher…" /><select v-model="kind" aria-label="Type de complément"><option value="">Tous les types</option><option value="SERVICE">Services</option><option value="ACCESSOIRE">Accessoires</option></select></div>
 <div v-if="error" class="panel-error" role="alert" v-text="error"></div>
 <div v-if="notice" class="panel-notice" role="status">{{notice}}</div>
 <p v-if="loading">Chargement du catalogue…</p>
 <div class="catalogue-list"><article v-for="item in entries" :key="item.name" class="catalogue-item" :class="{picked:settings[item.name].selected}">
  <label class="catalogue-choice"><input v-model="settings[item.name].selected" type="checkbox" :disabled="applying||disabled" :aria-label="'Sélectionner '+item.item_name" /><span><strong>{{item.item_name}}</strong><small>{{item.name}} · {{item.custom_item_types}} · {{item.basis}}</small></span></label>
  <div v-if="settings[item.name].selected" class="item-settings">
   <label v-if="item.basis!=='MANUEL'" class="inline-check"><input v-model="settings[item.name].manual_qty" type="checkbox" :disabled="applying||disabled" /> Quantité manuelle identique</label>
   <label v-if="settings[item.name].manual_qty">Quantité totale par ligne d’ouvrage<input v-model.number="settings[item.name].qty" type="number" min="0.000001" step="any" :disabled="applying||disabled" /></label>
   <p v-else>Calcul {{item.basis.toLowerCase()}} propre à chaque ouvrage.</p>
   <label>Prix unitaire commun ({{chantier.currency}} / {{item.stock_uom}})<input v-model="settings[item.name].rate" type="number" min="0" step="any" placeholder="Liste de prix sinon à confirmer" @input="settings[item.name].rate_set=false" :disabled="applying||disabled" /></label>
   <label v-if="settings[item.name].rate!==''" class="inline-check"><input v-model="settings[item.name].rate_set" type="checkbox" :disabled="applying||disabled" /> Prix commun confirmé (facultatif)</label>
  </div>
 </article><p v-if="!loading&&!entries.length">Aucun complément trouvé.</p></div>
 <div class="assignment-footer"><strong>{{parentLineIds.length}} ouvrage(s) · {{selection.length}} complément(s)</strong><button type="button" :disabled="disabled||applying||!parentLineIds.length||!selection.length" @click="apply">{{applying?'Calcul en cours…':'Affecter aux ouvrages sélectionnés'}}</button><small>Les affectations déjà présentes sont conservées. Les quantités automatiques sont calculées séparément pour chaque ouvrage.</small></div>
</aside>
</template>
<style scoped>
.extras-panel{position:sticky;top:16px;align-self:start;background:#071e2b;border:1px solid #204255;border-radius:8px;padding:16px;min-width:0;color:#dcecf7;font:13px/1.5 Inter,system-ui,sans-serif}.extras-panel h2{color:#edf3ff;font-size:17px;margin:0 0 10px}.extras-panel p,.extras-panel small{color:#9eb9cc}.extras-panel input,.extras-panel select,.extras-panel button{font:inherit;background:#0a283a;color:#edf3ff;border:1px solid #204255;border-radius:6px;padding:8px;width:100%;min-width:0}.catalogue-filters{display:grid;gap:8px;margin-bottom:12px}.catalogue-list{max-height:55vh;overflow:auto;padding-right:4px}.catalogue-item{border:1px solid #204255;border-radius:6px;padding:10px;margin-bottom:8px}.catalogue-item.picked{border-color:#00caff;background:#092536}.catalogue-choice,.inline-check{display:flex;gap:8px;align-items:flex-start;cursor:pointer}.extras-panel input[type=checkbox]{width:auto;flex-shrink:0;accent-color:#008cff;margin-top:4px}.catalogue-choice strong{display:block;color:#edf3ff;overflow-wrap:anywhere}.catalogue-choice small{display:block;font-size:10px;overflow-wrap:anywhere}.item-settings{margin-top:12px;border-top:1px solid #204255;padding-top:10px}.item-settings label{display:flex;flex-direction:column;gap:4px;margin-bottom:10px;color:#a3bdd1}.item-settings .inline-check{flex-direction:row}.item-settings p{margin:4px 0 12px}.assignment-footer{display:grid;gap:10px;padding-top:14px;border-top:1px solid #204255}.assignment-footer button{background:#006aff;cursor:pointer}.extras-panel button:disabled{opacity:.5;cursor:default}.extras-panel :focus-visible{outline:2px solid #00caff;outline-offset:2px}.panel-error,.panel-notice{padding:10px;border:1px solid #b65b6f;background:#452430;border-radius:6px;margin-bottom:12px}.panel-notice{background:#08352e;border-color:#00aa7b;color:#bff5df}@media(max-width:1350px){.extras-panel{position:static}.catalogue-list{max-height:420px}}
</style>
