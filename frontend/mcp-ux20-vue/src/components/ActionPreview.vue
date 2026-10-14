<script setup>
import {computed} from 'vue';
import {useCuttingStore} from '../stores/cutting.js';
import {labels,area,rect,findPiece,mergePlan,nodeId} from '../lib/geometry.js';
const store=useCuttingStore();
const needsTarget=computed(()=>['Move','Merge','Single'].includes(store.activeAction));
const instruction=computed(()=>{
 if(store.previewState)return 'Vérifiez le résultat proposé, puis confirmez ou annulez.';
 if(store.activeAction==='Resize')return 'Saisissez les nouvelles dimensions. Seules les réductions sont disponibles.';
 if(store.activeAction==='Destroy')return 'Vérifiez la surface qui deviendra indisponible avant de confirmer.';
 if(!store.candidateNodeIds.length)return {Move:store.allowRotation?'Aucune zone ne peut accueillir cette découpe dans l’orientation choisie.':'Aucune zone ne convient. La rotation à 90° est désactivée sur ce MCP.',Merge:'Aucune région adjacente ne permet d’étendre la chute source en rectangle.',Single:'Aucune seconde chute ne forme un L compatible avec une encoche supérieure gauche.'}[store.activeAction];
 return {Move:'Choisissez une destination verte, sur cette plaque ou une autre.',Merge:'La première chute sélectionnée s’étend. Choisissez une chute ou un déchet vert ; seule la bande alignée sera récupérée si la cible dépasse la source.',Single:'Choisissez la seconde chute verte pour former une seule chute en L.'}[store.activeAction];
});
const consequence=computed(()=>{
 const node=store.selected?.node;if(!node)return '';
 if(store.activeAction==='Destroy')return `${(area(node)/1e6).toLocaleString('fr-FR',{maximumFractionDigits:3})} m² deviendront détruits et indisponibles.`;
 if(!store.previewState)return '';
 if(store.activeAction==='Resize'){const after=findPiece(store.previewState.tree,store.sourceNodeId)?.node;return after?`${rect(node).length_mm} × ${rect(node).width_mm} → ${rect(after).length_mm} × ${rect(after).width_mm} mm. ${((area(node)-area(after))/1e6).toLocaleString('fr-FR',{maximumFractionDigits:3})} m² libérés.`:'';}
 if(store.activeAction==='Merge'){
  const target=findPiece(store.simulationTree,store.targetNodeIds[0]);
  if(target){const plan=mergePlan(node,target.node);if(plan.reclaimed)return `${(plan.reclaimed.length_mm*plan.reclaimed.width_mm/1e6).toLocaleString('fr-FR',{maximumFractionDigits:3})} m² ${plan.donor.node_type==='waste'?'de déchet récupérés':'ajoutés depuis la chute cible'}. La chute ${nodeId(plan.base)} s’étend à ${plan.geometry.length_mm} × ${plan.geometry.width_mm} mm ; ${plan.donor.node_type==='waste'?'le reste demeure rouge':'le reste de la cible est conservé'}.`;if(plan.node_type==='waste')return 'Les deux déchets deviennent une seule zone rouge rectangulaire.';}
 }
 if(store.activeAction==='Move'){
  const moved=findPiece(store.previewState.tree,store.sourceNodeId);if(!moved)return '';
  const before=rect(node),after=rect(moved.node);
  const rotation=moved.node.__move_rotation_degrees===90?` Rotation à 90° : ${before.length_mm} × ${before.width_mm} → ${after.length_mm} × ${after.width_mm} mm.`:'';
  return `Destination : ${moved.sheet.serial_no||nodeId(moved.sheet)}. La zone d’origine est libérée.${rotation}`;
 }
 return store.activeAction==='Single'?'Les deux régions deviennent une seule chute physique. L’encoche reste indisponible.':`La chute ${store.sourceNodeId} conserve son identifiant et absorbe la région cible.`;
});
</script>
<template>
 <section class="mcpv-action">
  <h3>{{labels[store.activeAction]}}</h3>
  <ol class="mcpv-steps" aria-label="Étapes de l’opération"><li class="complete">Source</li><li :class="{complete:!!store.previewState,current:!store.previewState}">{{needsTarget?'Destination':'Paramètres'}}</li><li :class="{current:!!store.previewState}">Vérification</li></ol>
  <p>Source : <b>{{store.sourceNodeId}}</b></p><p v-if="store.targetNodeIds.length">Cible : <b>{{store.targetNodeIds.join(', ')}}</b></p>
  <p class="mcpv-guidance" role="status" aria-live="polite">{{instruction}}</p>
  <label v-if="store.activeAction==='Move'" class="mcpv-move-orientation">Orientation
   <select v-model="store.parameters.rotation_degrees" aria-label="Orientation de la découpe" :disabled="!store.allowRotation" @change="store.updateMoveOrientation">
    <option value="auto">Automatique</option><option :value="0">Actuelle</option><option :value="90">Tourner à 90°</option>
   </select>
   <small v-if="!store.allowRotation">Rotation à 90° désactivée sur ce MCP.</small>
  </label>
  <template v-if="store.activeAction==='Resize'"><label>Longueur (mm)<input v-model.number="store.parameters.length_mm" type="number" min="1" @input="store.updatePreview()"/></label><label>Largeur (mm)<input v-model.number="store.parameters.width_mm" type="number" min="1" @input="store.updatePreview()"/></label></template>
  <div v-if="store.previewState" class="mcpv-comparison" role="group" aria-label="Comparer la simulation"><button v-for="mode in [{id:'before',label:'Avant'},{id:'after',label:'Après'},{id:'overlay',label:'Superposer'}]" :key="mode.id" :aria-pressed="store.comparisonMode===mode.id" @click="store.comparisonMode=mode.id">{{mode.label}}</button></div>
  <p v-if="consequence" class="mcpv-consequence">{{consequence}}</p>
  <p v-if="store.previewState" class="mcpv-comparison-caption">{{store.comparisonMode==='before'?'État avant l’opération.':store.comparisonMode==='after'?'Résultat proposé, avant confirmation.':'Pointillés orange : état initial. Contours violets : résultat proposé.'}}</p>
  <p v-else-if="store.error">Aperçu non disponible.</p>
  <small>Aucune modification métier n’est enregistrée.</small>

 </section>
</template>

<style>.mcpv-move-orientation{display:block;font-size:12px;margin:10px 0}.mcpv-move-orientation select{display:block;width:100%;margin-top:6px}</style>
