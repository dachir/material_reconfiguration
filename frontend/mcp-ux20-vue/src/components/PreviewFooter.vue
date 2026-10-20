<script setup>
import {computed} from 'vue';import {useCuttingStore} from '../stores/cutting.js';
const store=useCuttingStore();defineProps({applying:Boolean,status:String});defineEmits(['apply']);
const busy=computed(()=>store.isCalculating||store.isApplying||store.isLoadingCompensation);
const compensationStatus=computed(()=>store.isApplying?'Enregistrement…':store.isCalculating?'Calcul…':store.isLoadingCompensation?'Chargement…':store.compensationPreview?`${store.compensationPreview.summary.replaced} proposée(s) · ${store.compensationPreview.summary.remaining} restante(s)`:'Compensation');
</script>
<template><footer class="mcpv-footer">
 <div class="mcpv-legend"><span><i class="piece"/>Pièce</span><span><i class="leftover"/>Chute</span><span><i class="l-leftover"/>Chute en L</span><span><i class="waste"/>Déchet</span><span><i class="occupied"/>Occupé</span><template v-if="store.compensationOpen"><span><i class="replacement"/>Remplacement</span></template><template v-else><span><i class="selected"/>Sélection</span><span><i class="candidate"/>Cible</span></template></div>
 <small role="status" aria-live="polite">{{store.compensationOpen?compensationStatus:status}}{{store.documentVersion?'':' · Non enregistré'}} · {{Math.round(store.zoom*100)}} %</small>
 <div v-if="store.compensationOpen" class="mcpv-buttons"><button :disabled="busy" @click="store.closeCompensation">Annuler</button><button :disabled="busy||!store.compensationRequirements.length" @click="store.calculateCompensation">{{store.isCalculating?'Calcul…':'Calculer'}}</button><button class="mcpv-primary" :disabled="busy||!store.compensationPreview?.placements?.length" @click="store.applyCompensation">{{store.isApplying?'Enregistrement…':'Valider la compensation'}}</button></div>
 <button v-else class="mcpv-primary" :disabled="store.locked || store.isPreviewing || applying || !!store.activeAction || !store.sheets.length" @click="$emit('apply')">{{applying?'Application…':"Appliquer à l’aperçu →"}}</button>
</footer></template>
<style>.mcpv-legend .replacement{background:#bbf7d0;border:1px solid #22c55e}</style>
