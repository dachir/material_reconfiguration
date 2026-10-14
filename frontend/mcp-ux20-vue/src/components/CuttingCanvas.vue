<script setup>
import {computed} from 'vue';
import {useCuttingStore} from '../stores/cutting.js';
import {rect,pathFor,nodeId,regions,findPiece} from '../lib/geometry.js';
import {actionCursor,pieceCursor} from '../lib/cursors.js';
import {canvasColors,canvasPatternPrefix} from '../lib/palette.js';
const props=defineProps({readonly:Boolean});const store=useCuttingStore();const pattern=canvasPatternPrefix();const wastePattern=pattern+'-waste';const lPattern=pattern+'-single';
const targetCursor=computed(()=>props.readonly?'default':actionCursor(store.activeAction)||'default');
const cursorCandidates=computed(()=>new Set(store.candidateNodeIds));
const sheet=computed(()=>store.displaySheet),size=computed(()=>rect(sheet.value||{}));
const nodes=computed(()=>(sheet.value?.children||[]).filter(n=>n.node_type!=='preexisting_cutout'&&!n.__preexisting_cutout));
const viewBox=computed(()=>{const focus=store.focusedNodeId?findPiece(store.displayTree,store.focusedNodeId)||findPiece(store.simulationTree,store.focusedNodeId):null;const bounds=focus&&focus.sheet===store.displaySheet?rect(focus.node):size.value,w=bounds.length_mm||1,h=bounds.width_mm||1,z=store.zoom,p=Math.max(w,h)*.025;return `${bounds.x+w/2-(w+2*p)/z/2} ${bounds.y+h/2-(h+2*p)/z/2} ${(w+2*p)/z} ${(h+2*p)/z}`;});
const originals=computed(()=>store.previewState&&!props.readonly?(store.sheet?.children||[]).filter(n=>[store.sourceNodeId,...store.targetNodeIds].includes(nodeId(n))):[]);
const changedIds=computed(()=>{
 if(!store.previewState||props.readonly||store.comparisonMode==='before')return [];
 const previous=new Map((store.sheet?.children||[]).map(n=>[nodeId(n),`${pathFor(n)}:${n.node_type}`]));
 return nodes.value.filter(n=>previous.get(nodeId(n))!==`${pathFor(n)}:${n.node_type}`).map(nodeId);
});
function select(e,n){if(props.readonly)return;const box=e.currentTarget.closest('.mcpv-canvas').getBoundingClientRect();store.select(nodeId(n),{x:Number.isFinite(e.clientX)?e.clientX-box.left:box.width/2,y:Number.isFinite(e.clientY)?e.clientY-box.top:box.height/2});}
const replacementIds=computed(()=>new Set(store.compensationOpen?(store.compensationPreview?.placements||[]).map(n=>n.id):[]));
function fill(n){if(replacementIds.value.has(nodeId(n)))return canvasColors.single;return n.node_type==='finished_good'?canvasColors.piece:n.node_type==='leftover'?`url(#${n.geometry_type==='single'||(Number(n.removed_length_mm)>0&&Number(n.removed_width_mm)>0)?lPattern:pattern})`:n.node_type==='waste'?`url(#${wastePattern})`:n.node_type==='destroyed'?canvasColors.destroyed:'#cbd5e1';}
function pieceLabel(n){return replacementIds.value.has(nodeId(n))?'Remplacement':n.node_type==='leftover'?'Chute':nodeId(n);}
function labelRegion(n){return regions(n).reduce((a,b)=>a.length_mm*a.width_mm>b.length_mm*b.width_mm?a:b);}
</script>
<template>
 <div class="mcpv-canvas" :style="{cursor:targetCursor}"><p v-if="!sheet">Aucune plaque disponible.</p>
 <svg v-else :viewBox="viewBox" preserveAspectRatio="xMidYMid meet" role="img" aria-label="Plan de découpe" @click="!readonly && !store.activeAction && store.clear()">
 <defs><pattern :id="pattern" patternUnits="userSpaceOnUse" width="70" height="70"><rect width="70" height="70" :fill="canvasColors.leftover"/><path d="M-10 10L10-10M0 70L70 0M60 80L80 60" :stroke="canvasColors.leftoverHatch" stroke-width="7"/></pattern><pattern :id="wastePattern" patternUnits="userSpaceOnUse" width="70" height="70"><rect width="70" height="70" :fill="canvasColors.waste"/><path d="M-10 10L10-10M0 70L70 0M60 80L80 60" :stroke="canvasColors.wasteHatch" stroke-width="7"/></pattern><pattern :id="lPattern" patternUnits="userSpaceOnUse" width="70" height="70"><rect width="70" height="70" :fill="canvasColors.single"/><path d="M-10 10L10-10M0 70L70 0M60 80L80 60" :stroke="canvasColors.singleHatch" stroke-width="7"/></pattern></defs>
 <path :d="pathFor(sheet)" fill="#111827" stroke="#94a3b8" stroke-width="2" vector-effect="non-scaling-stroke"/>
 <g v-for="n in nodes" :key="nodeId(n)">
 <path :d="pathFor(n)" :data-node-id="nodeId(n)" :fill="fill(n)" :stroke-dasharray="replacementIds.has(nodeId(n))?'7 4':undefined" :stroke="replacementIds.has(nodeId(n))?'#22c55e':changedIds.includes(nodeId(n))?'#c084fc':!readonly && store.selectedNodeId===nodeId(n)?'#2563eb':!readonly && store.candidateNodeIds.includes(nodeId(n))?'#22c55e':'#94a3b8'" :stroke-width="replacementIds.has(nodeId(n))||changedIds.includes(nodeId(n))||(!readonly && store.selectedNodeId===nodeId(n))?4:1.2" vector-effect="non-scaling-stroke" :style="{cursor:pieceCursor(store.activeAction,cursorCandidates.has(nodeId(n)),readonly)}" :class="{'mcpv-piece':!readonly}" :tabindex="readonly?undefined:0" :role="readonly?undefined:'button'" :aria-label="`${nodeId(n)} ${n.node_type}`" v-on="readonly?{}:{click:event=>{event.stopPropagation();select(event,n)},keydown:event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();select(event,n)}}}"><title>{{nodeId(n)}} · {{n.node_type}}</title></path>
 <text v-if="labelRegion(n).length_mm>200 && labelRegion(n).width_mm>180" :x="labelRegion(n).x+labelRegion(n).length_mm/2" :y="labelRegion(n).y+labelRegion(n).width_mm/2" :font-size="Math.min(70,labelRegion(n).length_mm/Math.max(8,pieceLabel(n).length),labelRegion(n).width_mm/6)" text-anchor="middle" fill="#1e40af" pointer-events="none"><tspan>{{pieceLabel(n)}}</tspan><tspan :x="labelRegion(n).x+labelRegion(n).length_mm/2" dy="1.6em">{{rect(n).length_mm}} × {{rect(n).width_mm}}</tspan></text>
 </g><g v-if="!readonly && store.previewState && store.comparisonMode==='overlay'" pointer-events="none" aria-label="Emprise avant l’opération"><path v-for="n in originals" :key="nodeId(n)" :d="pathFor(n)" class="mcpv-before-outline" fill="none" stroke="#fbbf24" stroke-width="2.5" stroke-dasharray="7 5" vector-effect="non-scaling-stroke"/></g></svg><slot/></div>
</template>
