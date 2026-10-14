<script setup>
import {ref,computed,onMounted,onUnmounted} from 'vue';import {useCuttingStore} from './stores/cutting.js';import {copy} from './lib/geometry.js';
import CompensationPanel from './components/CompensationPanel.vue';
import EditorHeader from './components/EditorHeader.vue';import SheetNavigator from './components/SheetNavigator.vue';import CuttingCanvas from './components/CuttingCanvas.vue';import ContextMenu from './components/ContextMenu.vue';import SelectionPanel from './components/SelectionPanel.vue';import PreviewFooter from './components/PreviewFooter.vue';import './styles/editor.css';
const props=defineProps({onApplyPreview:Function,onReset:Function,onToggleExpand:Function,context:Object});const store=useCuttingStore(),applying=ref(false),appliedSignature=ref(null),editorElement=ref(null),ownsKeyboard=ref(false);
const previewStatus=computed(()=>store.confirmedCompensation&&!store.isDirty&&!store.activeAction?'Compensation enregistrée':store.locked?'Document soumis · Modifications terminées':store.documentVersion?(store.pendingIncidents.length||store.activeAction?'Prévisualisation non enregistrée':'Enregistré'):appliedSignature.value===null?(store.isDirty?'Simulation modifiée':'Simulation locale'):appliedSignature.value===JSON.stringify(store.simulationTree)?'Aperçu actualisé':'Aperçu à actualiser');
function trackEditor(e){if(e.target!==document.body)ownsKeyboard.value=!!editorElement.value?.contains(e.target);}
function escape(e){
 const modal=document.querySelector('.mcp20-modal-inner');
 if(modal&&!modal.contains(editorElement.value))return;
 if(store.locked||(!editorElement.value?.contains(e.target)&&!(e.target===document.body&&ownsKeyboard.value)))return;
 if((e.ctrlKey||e.metaKey)&&!e.altKey&&!e.target.closest?.('input,textarea,select,[contenteditable]')){
  const key=e.key.toLowerCase();
  if(!store.compensationOpen&&(key==='z'||key==='y')){e.preventDefault();e.stopImmediatePropagation();if(key==='y'||e.shiftKey)store.redo();else store.undo();return;}
 }
if(e.key==='Escape'&&store.compensationOpen){e.preventDefault();e.stopImmediatePropagation();store.closeCompensation();return;}
if(e.key==='Escape'&&(store.activeAction||store.menuOpen)){e.preventDefault();e.stopImmediatePropagation();store.cancel();}}
onMounted(()=>{document.addEventListener('keydown',escape,true);document.addEventListener('pointerdown',trackEditor,true);document.addEventListener('focusin',trackEditor,true);});onUnmounted(()=>{document.removeEventListener('keydown',escape,true);document.removeEventListener('pointerdown',trackEditor,true);document.removeEventListener('focusin',trackEditor,true);});
async function reset(){
 if(store.locked||store.isSaving||store.compensationOpen)return;
 const message='Réinitialiser l’atelier ? Tous les incidents et compensations seront supprimés, ainsi que les modifications en attente. Le plan initial, juste après Planification, sera restauré. Cette action ne peut pas être annulée.';
 const confirmed=typeof window.frappe?.confirm==='function'
  ?await new Promise(resolve=>window.frappe.confirm(message,()=>resolve(true),()=>resolve(false)))
  :window.confirm(message);
 if(confirmed&&await store.resetPlanning()){appliedSignature.value=null;props.onReset?.();}
}
async function apply(){if(store.locked||applying.value||store.isPreviewing)return;applying.value=true;store.isSaving=true;try{const tree=copy(store.simulationTree);const saved=await props.onApplyPreview?.(tree,{pendingIncidents:copy(store.pendingIncidents),documentVersion:copy(store.documentVersion)});if(saved?.effective_tree){store.isSaving=false;store.load(saved.effective_tree);store.documentVersion=saved.document_version;}appliedSignature.value=JSON.stringify(store.simulationTree);}catch(e){store.error=e.message;}finally{applying.value=false;store.isSaving=false;}}
</script>
<template>
 <div ref="editorElement" class="mcpv-app">
  <EditorHeader :context="context" :compensating="store.compensationOpen" @expand="props.onToggleExpand?.()"/>
  <SheetNavigator @reset="reset"/>
  <div class="mcpv-grid" :class="{'mcpv-panel-collapsed':store.panelCollapsed&&!store.compensationOpen}">
   <div class="mcpv-main">
    <CuttingCanvas :readonly="store.locked||store.compensationOpen"><ContextMenu v-if="!store.compensationOpen&&store.menuOpen&&store.actionOptions.length"/></CuttingCanvas>
    <div class="mcpv-canvas-status">
     <span>{{store.compensationOpen?(store.compensationPreview?'Compensation proposée':'Compensation'):store.locked?'Document soumis · Modifications terminées':store.activeAction?'Confirmez ou annulez l’opération dans le panneau.':'Clic sur une pièce pour agir'}}</span>
     <button v-if="store.panelCollapsed&&!store.compensationOpen" @click="store.panelCollapsed=false">Afficher la sélection ‹</button>
    </div>
   </div>
   <CompensationPanel v-if="store.compensationOpen"/>
   <SelectionPanel v-else-if="!store.panelCollapsed"/>
  </div>
  <PreviewFooter :applying="applying" :status="previewStatus" @apply="apply"/>
 </div>
</template>
