<script setup>
import {ref,watch,onMounted,onBeforeUnmount} from 'vue';
const props=defineProps({name:String,active:Boolean});
const emit=defineEmits(['updated']);
const frappe=window.frappe,users=ref([]),details=ref({});
let joined='',mounted=false;
function leave(){if(joined){frappe.realtime?.doc_close?.('Chantier',joined);frappe.realtime?.doc_unsubscribe?.('Chantier',joined);}joined='';users.value=[];}
function join(){leave();if(!mounted||!props.active||!props.name)return;joined=props.name;users.value=frappe.session?.user?[frappe.session.user]:[];frappe.realtime?.doc_subscribe?.('Chantier',joined);frappe.realtime?.doc_open?.('Chantier',joined);}
async function viewers(event){
 if(event?.doctype!=='Chantier'||event.docname!==joined||!joined)return;
 const name=joined;users.value=[...new Set(event.users||[])];
 const unknown=users.value.filter(user=>!frappe.boot?.user_info?.[user]&&!details.value[user]);
 if(unknown.length)try{const response=await frappe.call({method:'frappe.desk.form.load.get_user_info_for_viewers',args:{users:unknown}});if(joined===name)details.value={...details.value,...response.message};}catch{/* The user ID remains available if profile lookup fails. */}
}
function updated(event){if(event?.doctype==='Chantier'&&(event.name||event.docname)===joined)emit('updated',event);}
function info(user){return details.value[user]||frappe.boot?.user_info?.[user]||{};}
function label(user){return (info(user).fullname||info(user).full_name||user)+(user===frappe.session?.user?' (vous)':'');}
function initials(user){return (info(user).fullname||info(user).full_name||user).split(/[\s@._-]+/).filter(Boolean).slice(0,2).map(s=>s[0]).join('').toUpperCase();}
watch(()=>[props.name,props.active],join);
onMounted(()=>{mounted=true;frappe.realtime?.on('doc_viewers',viewers);frappe.realtime?.on('doc_update',updated);frappe.realtime?.socket?.on('connect',join);join();});
onBeforeUnmount(()=>{mounted=false;leave();frappe.realtime?.off('doc_viewers',viewers);frappe.realtime?.off('doc_update',updated);frappe.realtime?.socket?.off('connect',join);});
</script>
<template><div v-if="active&&users.length" class="chantier-viewers" aria-label="Utilisateurs présents sur ce chantier"><span v-for="user in users" :key="user" class="viewer-avatar" :title="label(user)" :aria-label="label(user)"><img v-if="info(user).user_image" :src="info(user).user_image" alt="" /><span v-else>{{initials(user)}}</span></span></div></template>
<style scoped>.chantier-viewers{display:flex;align-items:center;padding-left:5px}.viewer-avatar{display:inline-flex;align-items:center;justify-content:center;width:30px;height:30px;border:2px solid #06283c;border-radius:50%;background:#176080;color:#fff;font:600 11px system-ui;margin-left:-5px;overflow:hidden}.viewer-avatar img{width:100%;height:100%;object-fit:cover}</style>
