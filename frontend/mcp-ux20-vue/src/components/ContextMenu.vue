<script setup>
import {computed,ref,onMounted,onUnmounted,nextTick,watch} from 'vue';
import {useCuttingStore} from '../stores/cutting.js';import {labels} from '../lib/geometry.js';
const store=useCuttingStore(),menu=ref(null),position=ref({left:'8px',top:'8px'});let observer;
const icons={Move:'↗',Merge:'⊕',Single:'∟',Resize:'⤢',Destroy:'×'};
async function place(){await nextTick();if(!menu.value)return;const parent=menu.value.parentElement,p=store.menuPoint||{x:20,y:20},w=menu.value.offsetWidth,h=menu.value.offsetHeight;position.value={left:`${Math.max(8,Math.min(p.x-w/2,parent.clientWidth-w-8))}px`,top:`${Math.max(8,Math.min(p.y+h+20<parent.clientHeight?p.y+20:p.y-h-20,parent.clientHeight-h-8))}px`};}
watch(()=>store.menuPoint,place);onMounted(()=>{place();observer=new ResizeObserver(place);observer.observe(menu.value.parentElement);});onUnmounted(()=>observer?.disconnect());
</script>
<template><div ref="menu" class="mcpv-menu" :style="position" role="toolbar" aria-label="Actions sur la pièce"><button v-for="action in store.actionOptions" :key="action" :class="{'mcpv-danger':action==='Destroy'}" @click="store.choose(action)">{{labels[action]}}<span aria-hidden="true">{{icons[action]}}</span></button></div></template>
