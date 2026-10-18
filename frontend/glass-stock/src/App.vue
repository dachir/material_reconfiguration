<script setup>
import {printDocument} from "./printing.js";
import {ref,computed,nextTick,onBeforeUnmount} from 'vue';
const api='mat_reco.material_reconfiguration.services.glass_stock.';
const search=ref(''),warehouse=ref(''),warehouses=ref([]),data=ref({groups:[],volumes:0,chutes:0,total:0,surface_m2:0,diagnostics:{}});
const expanded=ref({}),selected=ref(''),error=ref(''),busy=ref(false),active=ref(false),connected=ref(false),scroll=ref(0),viewport=ref(null),height=ref(500);
let generation=0,timer,debounce,observer,filterKey;
const fmt=(v,d=0)=>v==null?'—':new Intl.NumberFormat('fr-FR',{maximumFractionDigits:d,minimumFractionDigits:d}).format(v);
const stamp=computed(()=>data.value.as_of?data.value.as_of.replace(/\.\d+$/,''):'—');
const diagnostics=computed(()=>Object.entries(data.value.diagnostics||{}).filter(([,n])=>n).map(([k,n])=>`${n} ${ {unresolved_lineage:'série(s) sans filiation primaire accessible',invalid_geometry:'surface(s) inconnue(s)',unknown_classification:'série(s) non classée(s)'}[k]||k}`).join(' · '));
const flat=computed(()=>{let y=0;const rows=[];for(const g of data.value.groups){rows.push({kind:'group',g,key:g.item_code,y,h:48});y+=48;const detail=expanded.value[g.item_code];if(detail){for(const r of detail.rows){rows.push({kind:'serial',r,key:r.serial_no,y,h:30});y+=30;}if(detail.next||detail.loading||detail.error){rows.push({kind:'more',g,detail,key:g.item_code+'-more',y,h:38});y+=38;}}}return {rows,total:y};});
const visible=computed(()=>flat.value.rows.filter(r=>r.y+r.h>=scroll.value-180&&r.y<=scroll.value+height.value+180));
async function call(method,args={}){const r=await frappe.call({method:api+method,args});return r.message;}
async function refresh(){
 const args={search:search.value,warehouse:warehouse.value};
 const key=JSON.stringify(args),reset=key!==filterKey;
 const token=++generation;
 filterKey=key;busy.value=true;error.value='';
 if(reset){expanded.value={};selected.value='';data.value={groups:[],diagnostics:{},total:0};scroll.value=0;if(viewport.value)viewport.value.scrollTop=0;}
 try{
  const result=await call('get_stock_overview',args);
  if(token!==generation)return;
  // Refresh every already loaded page while the existing table stays visible.
  const updates=await Promise.all(result.groups.filter(g=>g.chutes>0&&expanded.value[g.item_code]).map(async g=>{
   const state=expanded.value[g.item_code],rows=[];
   const count=Math.max(100,state.rows.length);
   let cursor=null;
   do{
    const page=await call('get_stock_serials',{...args,item_code:g.item_code,cursor,page_size:Math.min(100,count-rows.length)});
    if(token!==generation)return null;
    rows.push(...page.rows);cursor=page.next_cursor;
   }while(cursor&&rows.length<count);
   return {code:g.item_code,state,rows,next:cursor};
  }));
  if(token!==generation)return;
  const top=viewport.value?.scrollTop||0;
  const groups=new Set(result.groups.filter(g=>g.chutes>0).map(g=>g.item_code));
  for(const code of Object.keys(expanded.value)){if(!groups.has(code))delete expanded.value[code];}
  for(const update of updates){
   if(update&&expanded.value[update.code]===update.state){Object.assign(update.state,{rows:update.rows,next:update.next,loading:false,error:''});}
  }
  data.value=result;
  if(selected.value&&!Object.values(expanded.value).some(s=>s.rows.some(r=>r.serial_no===selected.value)))selected.value='';
  await nextTick();
  if(token===generation&&viewport.value){viewport.value.scrollTop=top;scroll.value=viewport.value.scrollTop;}
 }catch(e){if(token===generation)error.value='Actualisation impossible. Les données affichées datent de la dernière mise à jour réussie. Vérifiez vos droits puis réessayez.';}
 finally{if(token===generation)busy.value=false;}
}
function queueRefresh(){clearTimeout(debounce);debounce=setTimeout(()=>{if(active.value)refresh();},350);}
async function load(g){const token=generation;const state=expanded.value[g.item_code];if(!state||state.loading)return;state.loading=true;state.error='';try{const result=await call('get_stock_serials',{item_code:g.item_code,search:search.value,warehouse:warehouse.value,cursor:state.next,page_size:100});if(token===generation&&expanded.value[g.item_code]===state){state.rows.push(...result.rows);state.next=result.next_cursor;}}catch(e){state.error='Chargement impossible — réessayer';}finally{state.loading=false;}}
function toggle(g){if(!g.chutes)return;if(expanded.value[g.item_code])delete expanded.value[g.item_code];else{expanded.value[g.item_code]={rows:[],next:null,loading:false,error:''};load(g);}}
function stockChanged(){if(!busy.value)queueRefresh();}
function connection(){connected.value=true;}
function disconnection(){connected.value=false;}
async function show(){if(active.value)return;active.value=true;frappe.realtime.on('workshop_updated',stockChanged);frappe.realtime.on('glass_stock_updated',stockChanged);const socket=frappe.realtime.socket;connected.value=!!socket?.connected;socket?.on('connect',connection);socket?.on('disconnect',disconnection);timer=setInterval(()=>{if(!busy.value)refresh();},60000);observer=new ResizeObserver(()=>{height.value=viewport.value?.clientHeight||500;});if(viewport.value)observer.observe(viewport.value);try{warehouses.value=await call('get_warehouses');}catch(e){error.value='Liste des Warehouse inaccessible.';}if(active.value)refresh();}
function hide(){active.value=false;++generation;busy.value=false;clearInterval(timer);clearTimeout(debounce);observer?.disconnect();frappe.realtime.off('workshop_updated',stockChanged);frappe.realtime.off('glass_stock_updated',stockChanged);frappe.realtime.socket?.off('connect',connection);frappe.realtime.socket?.off('disconnect',disconnection);}
onBeforeUnmount(hide);defineExpose({show,hide});
</script>
<template>
 <main class="ug-glass">
  <section class="glass-content">
   <div class="glass-filters"><label class="glass-search"><span aria-hidden="true">⌕</span><input v-model="search" aria-label="Rechercher Item ou numéro de série" placeholder="Rechercher Item, N° série…" @input="queueRefresh"></label><label class="glass-warehouse">⌂ <span>Warehouse :</span><select v-model="warehouse" aria-label="Warehouse" @change="refresh"><option value="">Tous</option><option v-for="w in warehouses" :key="w" :value="w">{{w}}</option></select></label><div class="glass-live" :class="{offline:!connected}"><i></i>{{connected?'Mise à jour en direct':'Actualisation chaque minute'}}</div><button class="glass-refresh" aria-label="Actualiser" :disabled="busy" @click="refresh">⟳</button><div class="glass-stamp">Dernière mise à jour<strong>{{stamp}}</strong></div></div>
   <div class="glass-kpis"><article><svg class="glass-icon" viewBox="0 0 40 40" aria-hidden="true"><path d="M20 3 36 12 36 29 20 38 4 29 4 12ZM4 12 20 21 36 12M20 21V38"/></svg><div>Plaques<strong>{{fmt(data.volumes)}}</strong></div><span class="glass-bars">▂▅▇</span></article><article><svg class="glass-icon" viewBox="0 0 40 40" aria-hidden="true"><path d="M17 6Q20 1 23 6L28 15Q30 20 24 20H15Q10 20 13 15ZM7 24Q10 19 13 24L18 33Q20 38 14 38H5Q0 38 3 33ZM27 24Q30 19 33 24L38 33Q40 38 34 38H25Q20 38 23 33Z"/></svg><div>Chutes<strong>{{fmt(data.chutes)}}</strong></div><span class="glass-bars">▂▅▇</span></article><article title="Surface physique connue, réservations non déduites"><svg class="glass-icon" viewBox="0 0 40 40" aria-hidden="true"><path d="M5 5H35V35H5Z"/></svg><div>Surface en stock<strong>{{fmt(data.surface_m2,2)}} m²</strong></div><span class="glass-bars">▂▅▇</span></article></div>
   <p class="glass-note">Stock physique · réservations non déduites<span v-if="diagnostics"> · {{diagnostics}}</span></p>
   <div v-if="error" class="glass-error" role="alert">{{error}} <button @click="refresh">Réessayer</button></div>
   <section class="glass-table" role="table" aria-label="Stock des plaques et chutes" :aria-busy="busy">
    <div class="glass-grid glass-thead" role="row"><span role="columnheader">Item / N° série</span><span role="columnheader">Dimensions (mm)</span><span role="columnheader">Qté</span><span role="columnheader">m²</span><span role="columnheader">Warehouse</span></div>
    <div ref="viewport" class="glass-viewport" @scroll="scroll=$event.target.scrollTop">
     <div v-if="busy&&!data.groups.length" class="glass-empty" role="status">Chargement du stock…</div><div v-else-if="!data.groups.length" class="glass-empty">{{error?'Stock inaccessible.':'Aucune pièce en stock pour ces filtres.'}}</div>
     <div v-else :style="{height:flat.total+'px',position:'relative'}">
      <div v-for="line in visible" :key="line.key" class="glass-grid glass-row" :class="{'glass-group':line.kind==='group','glass-selected':line.kind==='serial'&&selected===line.r.serial_no}" :style="{position:'absolute',top:line.y+'px',height:line.h+'px',width:'100%'}" role="row" :aria-selected="line.kind==='serial'?selected===line.r.serial_no:undefined">
       <template v-if="line.kind==='group'"><span role="cell"><button class="glass-toggle" :disabled="!line.g.chutes" :title="line.g.chutes?'Afficher les découpes et chutes':'Plaques entières : total regroupé'" :aria-expanded="line.g.chutes?!!expanded[line.g.item_code]:undefined" @click="toggle(line.g)"><span>{{line.g.chutes?(expanded[line.g.item_code]?'⌄':'›'):''}}</span><svg class="glass-thumbnail" viewBox="0 0 40 40" fill="none" aria-hidden="true"><path d="M9 7h24v27H9z" fill="currentColor" fill-opacity=".08" stroke="currentColor" stroke-width="1.8"/><path d="M6 30H4V4h24v3" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" opacity=".55"/><path d="m14 19 7-7m-5 15 12-12" stroke="currentColor" stroke-width="2" stroke-linecap="round"/><path d="M11 32h20" stroke="currentColor" stroke-opacity=".35"/></svg><b>{{line.g.item_name}}</b><small>{{fmt(line.g.volumes)}} plaques · {{fmt(line.g.chutes)}} chutes</small></button></span><span role="cell"></span><span role="cell">{{fmt(line.g.total)}}</span><span role="cell">{{fmt(line.g.surface_m2,2)}}</span><span role="cell">{{line.g.warehouse}}</span></template>
       <template v-else-if="line.kind==='serial'"><span role="cell"><button class="glass-serial" @click="selected=line.r.serial_no"><svg class="glass-offcut-icon" viewBox="0 0 32 32" fill="none" aria-hidden="true"><path d="M5 4h22l-5 6 4 4-6 5 4 5-5 4H5Z" fill="currentColor" fill-opacity=".1" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"/><path d="m9 13 5-5m-4 13 8-8" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/></svg><span>{{line.r.serial_no}}</span></button></span><span role="cell">{{fmt(line.r.length_mm)}} × {{fmt(line.r.width_mm)}} × {{line.r.thickness_mm>0?fmt(line.r.thickness_mm):'—'}}</span><span role="cell">1</span><span role="cell" :title="line.r.geometry_error||''">{{fmt(line.r.area_m2,2)}}</span><span role="cell">{{line.r.warehouse}}</span></template>
       <template v-else><span class="glass-more"><button :disabled="line.detail.loading" @click="load(line.g)">{{line.detail.loading?'Chargement…':line.detail.error||'Charger les pièces suivantes'}}</button></span></template>
      </div>
     </div>
    </div>
    <footer><button :disabled="!selected||busy" @click="printDocument('Serial No',selected)">Imprimer la fiche A4</button><span>Affichage compact · lignes à hauteur réduite</span><span>{{fmt(data.total)}} pièces au total &nbsp; | &nbsp; {{selected?'1 ligne sélectionnée':'Aucune sélection'}}</span></footer>
   </section>
  </section>
 </main>
</template>
