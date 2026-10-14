<script setup>
import {useCuttingStore} from '../stores/cutting.js';
import {rect,area,nodeId} from '../lib/geometry.js';
import ActionPreview from './ActionPreview.vue';
const store=useCuttingStore();const types={finished_good:'Produit fini',leftover:'Chute',waste:'Déchet',destroyed:'Zone détruite'};
</script>
<template>
 <aside class="mcpv-side">
  <div class="mcpv-panel-heading"><h3>{{store.activeAction?'Opération':'Sélection'}}</h3><button aria-label="Masquer le panneau" @click="store.panelCollapsed=true">›</button></div>
  <div class="mcpv-side-body">
   <template v-if="store.selected">
    <component :is="store.activeAction?'details':'div'" class="mcpv-source-details">
     <summary v-if="store.activeAction">Dimensions et matière source</summary>
     <small>{{types[store.selected.node.node_type]||store.selected.node.node_type}}</small><b>{{nodeId(store.selected.node)}}</b><hr/>
     <small>Dimensions extérieures</small><strong>{{rect(store.selected.node).length_mm}} × {{rect(store.selected.node).width_mm}} mm</strong>
     <template v-if="store.selected.node.geometry_type==='single'"><small>Dimensions retirées</small><strong>{{store.selected.node.removed_length_mm}} × {{store.selected.node.removed_width_mm}} mm</strong></template><small>Surface disponible</small><strong>{{((store.selected.node.effective_area_mm2??area(store.selected.node))/1e6).toLocaleString('fr-FR',{maximumFractionDigits:3})}} m²</strong>
     <template v-if="store.selected.node.source_serial_no || store.selected.sheet.source_serial_no || store.selected.sheet.serial_no"><small>Serial No source</small><b>{{store.selected.node.source_serial_no||store.selected.sheet.source_serial_no||store.selected.sheet.serial_no}}</b></template>
    </component>
    <hr/><ActionPreview v-if="store.activeAction"/><template v-else><h3>Action en cours</h3><p>Sélectionnez une action dans le menu flottant.</p></template>
   </template><p v-else>{{store.locked?'Document soumis : les modifications sont terminées.':'Cliquez sur une pièce pour agir.'}}</p>
   <p v-if="store.isPreviewing" role="status">Validation Python en cours…</p><p v-for="warning in store.warnings" :key="warning">{{warning}}</p><p v-if="store.error" class="mcpv-error" role="alert">{{store.error}}</p>
  </div>
  <div v-if="store.activeAction" class="mcpv-buttons mcpv-panel-actions"><button @click="store.cancel()">Annuler</button><button class="mcpv-primary" :disabled="store.isPreviewing || store.isSaving || !store.previewState" @click="store.confirm()">{{store.activeAction==='Destroy'?'Confirmer la destruction':'Confirmer'}}</button></div>
  <small class="mcpv-local">{{store.documentVersion?'Les opérations sont validées par Python. Appliquer enregistre les incidents.':'Les modifications sont simulées localement.'}}</small>
 </aside>
</template>
