<script setup>
import {computed,watch} from 'vue';
import {useCuttingStore} from '../stores/cutting.js';
const store=useCuttingStore();
const busy=computed(()=>store.isCalculating||store.isApplying||store.isLoadingCompensation);
const preview=computed(()=>store.compensationPreview);
const currentSerial=computed(()=>store.sheet?.serial_no||store.sheet?.id);
const internal=computed(()=>store.internalCandidates.filter(c=>c.source_serial_no===currentSerial.value));
const placements=computed(()=>preview.value?.placements?.filter(p=>p.source_serial_no===currentSerial.value)||[]);
watch([()=>store.selectedSources.slice(),()=>store.compensationStrategy,()=>store.compensationReason],()=>store.invalidateCompensation());
function toggleSource(id){
 if(busy.value)return;
 store.selectedSources=store.selectedSources.includes(id)?store.selectedSources.filter(s=>s!==id):[...store.selectedSources,id];
}
function sourceName(origin){return {internal:'Chute MCP',stock_leftover:'Chute stock',stock_sheet:'Plaque entière'}[origin]||origin;}
function area(value){return ((value||0)/1e6).toLocaleString('fr-FR',{maximumFractionDigits:3})+' m²';}
</script>
<template>
 <aside class="mcpv-side mcpv-compensation-side" aria-label="Compensation" :aria-busy="busy">
  <div class="mcpv-panel-heading"><h3>Compensation</h3></div>
  <div class="mcpv-side-body">
   <p v-if="store.isLoadingCompensation" role="status">Chargement…</p>
   <p v-else-if="!store.compensationRequirements.length&&!store.compensationError" role="status">Aucune pièce à compenser.</p>
   <template v-else>
    <small>À compenser</small><strong>{{store.compensationCoverage.to_compensate||0}} pièce(s)</strong>
    <div v-for="r in store.compensationRequirements" :key="r.requirement_id" class="mcpv-compensation-need">
     <b>{{r.piece_item_code}} × {{r.compensation_qty}}</b>
     <span>{{r.length_mm}} × {{r.width_mm}} mm<template v-if="r.thickness_mm"> · {{r.thickness_mm}} mm</template></span>
     <small>{{r.sales_order}}</small>
    </div>
   </template>
   <hr/>
   <label class="mcpv-compensation-mode">Mode
    <select v-model="store.compensationStrategy" aria-label="Mode de compensation" :disabled="busy">
     <option value="automatic">Automatique</option><option value="manual">Manuel</option>
    </select>
   </label>
   <template v-if="store.compensationStrategy==='manual'">
    <div v-if="internal.length" class="mcpv-compensation-internal"><small>Chutes de cette plaque</small>
     <label v-for="c in internal" :key="c.candidate_id" class="mcpv-compensation-choice"><input type="checkbox" :checked="store.selectedSources.includes(c.candidate_id)" :disabled="busy" @change="toggleSource(c.candidate_id)"/><span>{{c.length_mm}} × {{c.width_mm}} mm</span></label>
    </div>
    <label class="mcpv-compensation-reason">Justification du choix<textarea v-model="store.compensationReason" :disabled="busy" rows="2" maxlength="1000"/></label>
   </template>
   <hr/>
   <div class="mcpv-panel-heading"><h3>Stock disponible</h3><button :disabled="busy" aria-label="Actualiser le stock" @click="store.loadCompensation">↻</button></div>
   <div class="mcpv-compensation-stock"><table><thead><tr><th>Matière</th><th>Dimensions</th></tr></thead><tbody>
    <tr v-for="c in store.stockCandidates" :key="c.serial_no"><td>
     <label class="mcpv-compensation-choice"><input type="checkbox" :checked="store.selectedSources.includes(c.serial_no)" :disabled="busy||c.compatible===false" @change="toggleSource(c.serial_no)"/><b>{{c.serial_no}}</b></label>
     <small>{{sourceName(c.origin)}} · {{c.warehouse}}</small><small v-if="c.compatible===false" class="mcpv-error">Incompatible</small>
    </td><td>{{c.length_mm}} × {{c.width_mm}}<small>{{c.thickness_mm}} mm</small><small v-if="c.removed_length_mm">Encoche {{c.removed_length_mm}} × {{c.removed_width_mm}}</small></td></tr>
    <tr v-if="!store.stockCandidates.length"><td colspan="2">Aucune matière disponible.</td></tr>
   </tbody></table></div>
   <template v-if="placements.length"><hr/><h3>Placements sur cette plaque</h3><div v-for="p in placements" :key="p.id" class="mcpv-compensation-need"><b>{{p.piece_item_code}}</b><span>{{p.length_mm}} × {{p.width_mm}} mm</span><small>{{sourceName(p.origin)}} · {{p.source_serial_no}}</small></div></template>
   <template v-if="preview"><hr/><h3>Résultat</h3><div class="mcpv-consequence mcpv-compensation-result"><p>{{preview.summary.replaced}} remplacement(s) proposé(s)</p><p>{{preview.summary.remaining}} pièce(s) restante(s)</p><p>Matières ajoutées : {{preview.summary.additional_materials}}</p><small>Utilisée : {{area(preview.summary.used_area_mm2)}} · Restante : {{area(preview.summary.remaining_area_mm2)}}</small></div></template>
   <p v-for="warning in store.compensationWarnings" :key="warning">{{warning}}</p>
   <p v-if="store.compensationError" class="mcpv-error" role="alert">{{store.compensationError}}</p>
  </div>
 </aside>
</template>
<style>
.mcpv-compensation-side .mcpv-compensation-need{display:flex;flex-direction:column;gap:4px;padding:8px 0;border-bottom:1px solid #292929;font-size:12px}.mcpv-compensation-side .mcpv-compensation-need small{margin:0}.mcpv-compensation-mode{display:flex;align-items:center;justify-content:space-between;gap:8px;font-size:12px}.mcpv-compensation-mode select{min-width:0;max-width:70%}.mcpv-compensation-side .mcpv-compensation-choice{display:flex;align-items:center;gap:6px;cursor:pointer}.mcpv-compensation-side .mcpv-compensation-choice input{width:14px;height:14px;margin:0;padding:0;flex-shrink:0;accent-color:#60a5fa}.mcpv-compensation-reason{display:block;font-size:11px;margin-top:10px}.mcpv-compensation-reason textarea{display:block;width:100%;padding:7px;margin-top:5px;border:1px solid #3b3b3b;background:#171717;color:inherit;border-radius:7px;font:inherit;resize:vertical}.mcpv-compensation-stock{overflow:auto;max-height:260px}.mcpv-compensation-stock table{border-collapse:collapse;width:100%;font-size:10px;color:inherit}.mcpv-compensation-stock th{white-space:nowrap;text-align:left;font-weight:600;color:#bfbfbf;padding:6px 4px;border-bottom:1px solid #3b3b3b}.mcpv-compensation-stock td{padding:8px 4px;border-bottom:1px solid #292929;vertical-align:top;overflow-wrap:anywhere}.mcpv-compensation-side .mcpv-compensation-stock small{font-size:10px;margin:3px 0 0}.mcpv-compensation-side .mcpv-compensation-result p{margin:0 0 5px}.mcpv-compensation-internal{margin:10px 0}.mcpv-compensation-internal label{margin-bottom:8px}
</style>
