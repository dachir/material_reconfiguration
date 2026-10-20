<script setup>
import {ref,onMounted,onBeforeUnmount,watch} from 'vue';
const props=defineProps({modelValue:[String,Number],doctype:String,disabled:Boolean,filters:Object,autocomplete:Boolean,label:String});
const emit=defineEmits(['update:modelValue']);
let cleanupPlacement=()=>{};
const host=ref(null);let control,syncing=false,timer=null,request=0,active=true,completeOnResponse=false;
onMounted(()=>{
 control=window.frappe.ui.form.make_control({parent:host.value,df:{fieldname:'value',fieldtype:props.autocomplete?'Autocomplete':'Link',options:props.doctype,label:props.label||props.doctype,placeholder:props.label||props.doctype,ignore_validation:!!props.autocomplete,max_items:10,get_query:props.autocomplete?undefined:()=>({filters:props.filters||{}}),change(){if(!syncing&&String(control.get_value()||'')!==String(props.modelValue||'')){emit('update:modelValue',control.get_value());host.value.dispatchEvent(new Event('change',{bubbles:true}));}}},render_input:true,only_input:true});
 sync();
 if(props.autocomplete){
 control.$input.on('awesomplete-selectcomplete.designation',()=>emit('update:modelValue',control.$input.val()||''));
 control.$input.on('keydown.designation',event=>{
  if(event.key==='Tab'&&control.awesomplete.opened){
   if(control.awesomplete.index==null)control.awesomplete.goto(0);
   control.awesomplete.select();
  }
 });
 const place=()=>{
  if(!control.awesomplete.opened)return;
  const rect=control.input.getBoundingClientRect(),list=control.awesomplete.ul;
  Object.assign(list.style,{position:'fixed',left:Math.max(4,Math.min(rect.left,window.innerWidth-rect.width*1.5-8))+'px',top:rect.bottom+'px',width:Math.min(rect.width*1.5,window.innerWidth-16)+'px',minWidth:'0',maxHeight:Math.max(100,Math.min(240,window.innerHeight-rect.bottom-8))+'px',overflowY:'auto',whiteSpace:'normal',zIndex:'1000'});
 };
 control.$input.on('awesomplete-open.designation',place);
 window.addEventListener('resize',place);window.addEventListener('scroll',place,true);
 cleanupPlacement=()=>{window.removeEventListener('resize',place);window.removeEventListener('scroll',place,true);};
 control.$input.on('input.designation focus.designation',event=>{
  completeOnResponse=event.type==='input'&&!event.originalEvent?.inputType?.startsWith('delete');
  const txt=control.$input.val()||'';
  if(txt!==String(props.modelValue||''))emit('update:modelValue',txt);
  clearTimeout(timer);const current=++request;
  timer=setTimeout(async()=>{
   try{
    const result=await window.frappe.call({method:'mat_reco.material_reconfiguration.services.technical_study_service.designation_suggestions',type:'GET',args:{txt}});
    if(!active||current!==request||!control.$input.is(':focus'))return;
    control.set_data((result.message||[]).map(value=>({value,label:window.frappe.utils.escape_html(value)})));
    control.awesomplete.evaluate();place();
    const completion=(result.message||[]).find(value=>txt&&value.toLocaleLowerCase().startsWith(txt.toLocaleLowerCase()));
    if(completeOnResponse&&completion&&control.input.selectionStart===txt.length&&control.input.selectionEnd===txt.length){
     control.$input.val(completion);emit('update:modelValue',completion);
     control.input.setSelectionRange(txt.length,completion.length);
    }
   }catch{if(active&&current===request)control.set_data([]);}
  },180);
 });
 }
});
function sync(){if(!control)return;syncing=true;if(control.$input?.val()!==String(props.modelValue||''))control.set_value(props.modelValue||'');control.$input?.prop('disabled',props.disabled).attr('aria-label',props.label||props.doctype);syncing=false;}
watch(()=>props.modelValue,sync);watch(()=>props.disabled,sync);
onBeforeUnmount(()=>{active=false;cleanupPlacement();request++;clearTimeout(timer);control?.$input?.off('.designation');control?.awesomplete?.destroy?.();control?.$wrapper?.remove();});
</script>
<template><div ref="host" class="frappe-cell" @keydown.enter.stop.prevent></div></template>
<style scoped>.frappe-cell{min-width:65px}.frappe-cell :deep(input){background:#06283c!important;color:#dcecf7!important;border:1px solid #173c52!important;border-radius:5px!important;min-height:28px!important;height:30px!important;padding:5px!important;font-size:12px!important}.frappe-cell :deep(.form-group){margin:0}.frappe-cell :deep(.control-label),.frappe-cell :deep(.help-box){display:none}.frappe-cell :deep(.awesomplete ul){color:#dcecf7;background:#06283c;z-index:20}.frappe-cell :deep(.link-btn){background:#06283c}</style>
