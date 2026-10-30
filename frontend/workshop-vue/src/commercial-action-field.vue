<script setup>
import {ref,onMounted,onBeforeUnmount,watch,nextTick} from 'vue';
import {actionFieldFilters} from './commercial-action.js';
const props=defineProps({field:{type:Object,required:true},modelValue:[String,Number,Boolean,Array,Object],context:{type:Object,default:()=>({})},disabled:Boolean});
const emit=defineEmits(['update:modelValue']);
const host=ref(null);let control=null,alive=true,syncing=false,cleanupPlacement=()=>{};
function clear(){cleanupPlacement();cleanupPlacement=()=>{};control?.$input?.off('.ugcAction');control?.datepicker?.destroy?.();control?.awesomplete?.destroy?.();control?.$wrapper?.remove();control=null;}
function containPicker(){
 const picker=control?.datepicker,modal=host.value?.closest('dialog');if(!picker?.$datepicker||!modal)return;
 // Frappe v15 uses AirDatepicker 2, whose popup otherwise lives under body,
 // outside the native dialog's top layer. Reparent this instance only.
 picker.$datepicker.appendTo(modal);
 picker.setPosition=()=>{
  if(!alive||!control?.input)return;
  const input=control.input.getBoundingClientRect(),box=modal.getBoundingClientRect();
  const width=picker.$datepicker.outerWidth()||270,height=picker.$datepicker.outerHeight()||290;
  const above=box.bottom-input.bottom<height+12&&input.top-box.top>height+12;
  const left=Math.max(8,Math.min(input.left-box.left,box.width-width-10));
  const top=above?input.top-box.top-height-7:input.bottom-box.top+7;
  picker._setPositionClasses?.(above?'top left':'bottom left');
  picker.$datepicker.css({position:'absolute',left:left+'px',top:Math.max(8,top)+'px',zIndex:120});
 };
 const reposition=()=>{if(picker.visible)picker.setPosition();};
 const scroll=()=>{if(picker.visible)picker.hide();};
 const escape=event=>{if(event.key==='Escape'&&picker.visible){picker.hide();event.preventDefault();event.stopPropagation();}};
 window.addEventListener('resize',reposition);modal.addEventListener('scroll',scroll,true);host.value.addEventListener('keydown',escape,true);
 cleanupPlacement=()=>{window.removeEventListener('resize',reposition);modal.removeEventListener('scroll',scroll,true);host.value?.removeEventListener('keydown',escape,true);};
}
function sync(){if(!control)return;syncing=true;const value=props.modelValue??props.field.default??'';if(String(control.get_value?.()??'')!==String(value))control.set_value(value);control.$wrapper?.find('input,select,textarea').prop('disabled',Boolean(props.disabled||props.field.read_only));control.$input?.attr('aria-label',props.field.label||props.field.fieldname);syncing=false;}
async function create(){
 clear();await nextTick();if(!alive||!host.value)return;
 const field={...props.field};delete field.ignore_user_permissions;delete field.ignore_permissions;
 if(field.fieldtype==='Currency'&&field.precision===undefined&&['XOF','XAF'].includes(props.context.currency))field.precision=0;
 if(field.fieldtype==='Link'){field.only_select=true;field.get_query=()=>({filters:actionFieldFilters(props.field,props.context)});}
 field.change=()=>{if(!control||syncing)return;const value=control.get_value();if(String(value??'')!==String(props.modelValue??''))emit('update:modelValue',value);};
 control=window.frappe.ui.form.make_control({parent:host.value,df:field,render_input:true});containPicker();sync();
}
onMounted(create);watch(()=>props.modelValue,sync,{deep:true});watch(()=>props.disabled,sync);watch(()=>JSON.stringify(props.field),create);
onBeforeUnmount(()=>{alive=false;clear();});
defineExpose({getValue:()=>control?.get_value?.()??props.modelValue});
</script>
<template><div ref="host" class="ugc-action-field" @keydown.enter.stop></div></template>
