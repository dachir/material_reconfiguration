<script setup>
import {ref,computed,watch} from 'vue';
const props=defineProps({modelValue:String,items:{type:Array,default:()=>[]},disabled:Boolean});
const emit=defineEmits(['update:modelValue','change']);
const query=ref(''),opened=ref(false),index=ref(-1);
const label=c=>c.name+' — '+c.designation;
const cancelled=c=>c.docstatus===2||c.status==='Cancelled';
const current=computed(()=>props.items.find(c=>c.name===props.modelValue));
watch(()=>[props.modelValue,props.items],()=>{if(!opened.value)query.value=current.value?label(current.value):props.modelValue||'';},{immediate:true});
const results=computed(()=>{const txt=query.value.trim().toLocaleLowerCase();return props.items.filter(c=>!txt||label(c).toLocaleLowerCase().includes(txt)).slice(0,10);});
function choose(c){query.value=c?label(c):'';opened.value=false;index.value=-1;emit('update:modelValue',c?.name||'');emit('change');}
function key(event){if(event.key==='Escape'){close();return;}if(event.key==='ArrowDown'||event.key==='ArrowUp'){event.preventDefault();opened.value=true;index.value=Math.max(0,Math.min(results.value.length-1,index.value+(event.key==='ArrowDown'?1:-1)));}if(event.key==='Enter'&&opened.value&&results.value[index.value]){event.preventDefault();choose(results.value[index.value]);}}
function close(){opened.value=false;query.value=current.value?label(current.value):props.modelValue||'';index.value=-1;}
</script>
<template>
<div class="chantier-search" @focusout="event=>{if(!event.currentTarget.contains(event.relatedTarget))close()}">
<label>Chantier<input v-model="query" :class="{cancelled:!opened&&current&&cancelled(current)}" :disabled="disabled" role="combobox" aria-autocomplete="list" :aria-expanded="opened" aria-controls="chantier-suggestions" :aria-activedescendant="index>=0?'chantier-option-'+index:undefined" placeholder="Rechercher un chantier…" @focus="opened=true;query='';index=-1" @input="opened=true;index=-1" @keydown="key" /></label>
<div v-if="opened&&!disabled" id="chantier-suggestions" class="suggestions" role="listbox">
<button type="button" @mousedown.prevent @click="choose(null)">Tous les chantiers / effacer</button>
<button v-for="(c,i) in results" :id="'chantier-option-'+i" :key="c.name" type="button" role="option" :aria-selected="i===index" :class="{cancelled:cancelled(c),active:i===index}" @mousedown.prevent @click="choose(c)">{{label(c)}}<small v-if="cancelled(c)"> · Annulé</small></button>
<span v-if="!results.length">Aucun chantier trouvé</span>
</div></div>
</template>
<style scoped>
.chantier-search{position:relative;min-width:320px;max-width:100%}label{display:flex;gap:10px;align-items:center}input{width:100%;min-width:240px;background:#0a283a;border:1px solid #204255;color:#edf3ff;border-radius:5px;padding:9px;font:inherit}.suggestions{position:absolute;top:100%;left:0;right:0;background:#0a283a;border:1px solid #204255;z-index:30;max-height:350px;overflow:auto}.suggestions button{display:block;width:100%;padding:10px;text-align:left;color:#edf3ff;background:transparent;border:0;cursor:pointer}.suggestions button:hover,.suggestions .active{background:#103c54}.suggestions span{display:block;padding:10px}.cancelled{text-decoration:line-through;text-decoration-color:#ff334f;text-decoration-thickness:2px}
</style>
