<script setup>
import {ref,reactive,computed,onMounted,onBeforeUnmount,nextTick,watch} from 'vue';
import Icon from './commercial-icon.vue';
import Field from './commercial-action-field.vue';
import {formatCommercialAmount} from './commercial-layout.js';
import {actionIsPayment,actionRequestKey,normaliseActionRows,selectActionRow,selectAllActionRows,updateActionQuantity,proposeActionSerials,buildActionSelections,buildActionValues,actionLineAmount,actionTotals,actionSubmissionButtons,validateActionEditor} from './commercial-action.js';
import './commercial-action.css';

const props=defineProps({source:{type:Object,required:true},action:{type:String,required:true}});
const emit=defineEmits(['close','completed','busy']);
const frappe=window.frappe,api='mat_reco.material_reconfiguration.services.commercial_actions.';
const dialog=ref(null),preparation=ref(null),rows=ref([]),values=reactive({}),loading=ref(true),busy=ref(false),errors=ref([]),notice=ref('');
const fieldRefs=new Map(),dimensionRefs=new Map();
let alive=true,lastFocus=null,request=0,requestKey=actionRequestKey(),lastAttempt='';
const payment=computed(()=>actionIsPayment(preparation.value||{}));
const delivery=computed(()=>preparation.value?.target_doctype==='Bordereau Special');
const fields=computed(()=>(preparation.value?.fields||[]).filter(field=>!field.hidden&&!['Section Break','Column Break','Tab Break','Table','HTML'].includes(field.fieldtype)));
const dimensions=computed(()=>preparation.value?.dimensions||[]);
const selectable=computed(()=>rows.value.filter(row=>!row._derived));
const allSelected=computed(()=>selectable.value.length>0&&selectable.value.every(row=>row.selected));
const someSelected=computed(()=>selectable.value.some(row=>row.selected)&&!allSelected.value);
const totals=computed(()=>actionTotals(rows.value,values,payment.value));
const buttons=computed(()=>actionSubmissionButtons(preparation.value?.submission||{}));
const title=computed(()=>preparation.value?.title||({quotation:'Préparer le devis',order:'Préparer la commande',delivery:'Préparer le bordereau spécial',payment:'Recevoir un règlement',edit:'Modifier le brouillon',validate:'Valider le document'})[props.action]||'Opération commerciale');
const currency=computed(()=>values.currency||preparation.value?.currency||props.source.currency||rows.value.find(row=>row.currency)?.currency||'');
const fieldContext=computed(()=>({...values,currency:currency.value,company:values.company||preparation.value?.company||props.source.company,customer:values.customer||preparation.value?.customer||props.source.customer}));
const targetLabel=computed(()=>({'Quotation':'Devis','Sales Order':'Commande','Bordereau Special':'Bordereau spécial','Reglement Special':'Règlement spécial'})[preparation.value?.target_doctype]||'Document commercial');
const sourceName=computed(()=>preparation.value?.source?.name||props.source.name);
const description=computed(()=>preparation.value?.description||'');
const amountField=computed(()=>fields.value.find(field=>field.fieldname==='amount'));
const showLines=computed(()=>payment.value||rows.value.length>0||props.action!=='validate');
function qty(value){return value===null||value===undefined?'—':new Intl.NumberFormat('fr-FR',{maximumFractionDigits:6}).format(Number(value)||0);}
function money(value,code=currency.value){return formatCommercialAmount(value,code);}
function plain(value){return new DOMParser().parseFromString(String(value||''),'text/html').body.textContent||'';}
function errorText(error){const response=error?.responseJSON||error;let text=response?.message||'L’opération n’a pas pu être terminée.';try{const messages=JSON.parse(response._server_messages||'[]');if(messages.length)text=JSON.parse(messages[0]).message||text;}catch{}return plain(typeof text==='string'?text:'L’opération n’a pas pu être terminée.');}
function setFieldRef(name,component,dimension=false){const refs=dimension?dimensionRefs:fieldRefs;if(component)refs.set(name,component);else refs.delete(name);}
function setDimension(name,value){values.accounting_dimensions||={};values.accounting_dimensions[name]=value;}
function warehouseField(row){return {fieldname:'warehouse',label:'Dépôt de la ligne',fieldtype:'Link',options:'Warehouse',filters:{company:values.company||preparation.value?.company||props.source.company,is_group:0}};}
function rowCandidates(row){return (row.serials||[]).map(serial=>typeof serial==='string'?{name:serial}:serial).filter(serial=>!row.warehouse||!serial.warehouse||serial.warehouse===row.warehouse);}
function selectedSerials(row){return String(row.serial_no||'').split(/[\n,]+/).map(value=>value.trim()).filter(Boolean);}
function selectSerial(row,name,selected){row._serials_manual=true;const serials=new Set(selectedSerials(row));selected?serials.add(name):serials.delete(name);row.serial_no=[...serials].join('\n');}
function proposeSerials(row){
 if(delivery.value)proposeActionSerials(rows.value,row);
}
function changeQuantity(row,value){updateActionQuantity(rows.value,row.id,value);proposeSerials(row);}
function changeWarehouse(row,value){row.warehouse=value;proposeSerials(row);}
function changeSelection(row,checked){selectActionRow(rows.value,row.id,checked,payment.value);if(checked)proposeSerials(row);}
function toggleAll(selected){selectAllActionRows(rows.value,selected,payment.value);if(selected)rows.value.filter(row=>row.selected).forEach(proposeSerials);}
function useAllocatedTotal(){values.amount=totals.value.allocated;}
function close(){if(busy.value)return;emit('close');}
function buttonLabel(button){return button.intent==='save'&&preparation.value?.target_doctype===props.source.doctype?'Enregistrer les modifications':button.label;}
async function prepare(){
 const current=++request;loading.value=true;errors.value=[];notice.value='';
 try{
  const response=await frappe.call({method:api+'prepare_action',args:{source_doctype:props.source.doctype,source_name:props.source.name,action:props.action},type:'POST',silent:true});
  if(!alive||current!==request)return;
  const payload=response.message||{};preparation.value=payload;
  for(const key of Object.keys(values))delete values[key];Object.assign(values,payload.values||{});
  for(const field of payload.fields||[])if(values[field.fieldname]===undefined&&field.default!==undefined)values[field.fieldname]=field.default;
  if(payload.dimensions?.length||values.accounting_dimensions){
   values.accounting_dimensions={...(values.accounting_dimensions||{})};
   for(const field of payload.dimensions||[])if(values.accounting_dimensions[field.fieldname]===undefined&&field.default!==undefined)values.accounting_dimensions[field.fieldname]=field.default;
  }
  rows.value=normaliseActionRows(payload.rows||[],actionIsPayment(payload),{deriveChildren:payload.target_doctype!=='Bordereau Special'});
  requestKey=actionRequestKey();lastAttempt='';
  await nextTick();dialog.value?.querySelector('input:not([disabled]),select:not([disabled]),textarea:not([disabled]),button:not([disabled])')?.focus();
 }catch(error){frappe.hide_msgprint?.();if(alive&&current===request)errors.value=[errorText(error)];}
 finally{if(alive&&current===request)loading.value=false;}
}
async function execute(button){
 if(busy.value||loading.value||!preparation.value)return;
 for(const [name,component] of fieldRefs)values[name]=component.getValue();
 for(const [name,component] of dimensionRefs)setDimension(name,component.getValue());
 errors.value=validateActionEditor(preparation.value,rows.value,values);
 if(errors.value.length){await nextTick();dialog.value?.querySelector('[role="alert"]')?.focus();return;}
 const selections=buildActionSelections(rows.value,payment.value,preparation.value);
 const submittedValues=buildActionValues(preparation.value,values);
 const signature=JSON.stringify({selections,values:submittedValues,intent:button.intent,workflow_action:button.workflow_action||''});
 if(lastAttempt&&lastAttempt!==signature)requestKey=actionRequestKey();lastAttempt=signature;
 busy.value=true;emit('busy',true);notice.value='';
 try{
  const response=await frappe.call({method:api+'execute_action',type:'POST',silent:true,args:{source_doctype:props.source.doctype,source_name:props.source.name,action:props.action,selections:JSON.stringify(selections),values:JSON.stringify(submittedValues),source_modified:preparation.value.source?.modified||props.source.modified,request_key:requestKey,intent:button.intent,workflow_action:button.workflow_action||null}});
  if(!alive)return;
  emit('completed',response.message||{});
 }catch(error){frappe.hide_msgprint?.();if(alive)errors.value=[errorText(error)];}
 finally{if(alive)busy.value=false;emit('busy',false);}
}
onMounted(async()=>{lastFocus=document.activeElement;await nextTick();dialog.value?.showModal();prepare();});
watch(()=>[props.source.doctype,props.source.name,props.action],()=>{if(!busy.value)prepare();});
onBeforeUnmount(()=>{alive=false;request++;dialog.value?.close();if(lastFocus?.isConnected)lastFocus.focus();});
defineExpose({busy,loading,prepare,execute,rows,values});
</script>

<template>
 <Teleport to="body">
  <dialog ref="dialog" class="ugc-action-modal" aria-labelledby="ugc-action-title" :aria-busy="busy||loading" @cancel.prevent="close" @click="event=>{if(event.target===dialog)close()}">
   <header class="ugc-action-header"><div><small>{{sourceName}}</small><h2 id="ugc-action-title">{{title}}</h2><p v-if="description">{{plain(description)}}</p></div><button type="button" class="ugc-action-icon" aria-label="Fermer la fenêtre" :disabled="busy" @click="close"><Icon name="close"/></button></header>
   <div class="ugc-action-body">
    <div v-if="loading" class="ugc-action-loading" role="status"><Icon name="refresh"/><strong>Préparation des lignes disponibles…</strong></div>
    <template v-else>
     <div v-if="errors.length" class="ugc-action-errors" role="alert" tabindex="-1"><strong>L’opération demande une correction.</strong><ul><li v-for="(error,index) in errors" :key="index">{{error}}</li></ul><button v-if="!preparation" type="button" :disabled="busy" @click="prepare">Réessayer</button></div>
     <p v-if="notice" class="ugc-action-notice" role="status">{{notice}}</p>
     <template v-if="preparation">
      <div class="ugc-action-context"><span v-if="fieldContext.customer"><Icon name="client"/>{{values.customer_name||preparation.customer_name||props.source.subtitle||fieldContext.customer}}</span><span v-if="currency">{{currency}}</span><span v-if="fieldContext.company">{{fieldContext.company}}</span><span>{{targetLabel}}</span></div>
      <section v-if="fields.length" class="ugc-action-fields" aria-label="Informations du document"><Field v-for="field in fields" :key="field.fieldname" :ref="component=>setFieldRef(field.fieldname,component)" :field="field" :model-value="values[field.fieldname]" :context="fieldContext" :disabled="busy" @update:model-value="value=>values[field.fieldname]=value"/></section>
      <section v-if="dimensions.length" class="ugc-action-dimensions"><h3>Informations du dépôt</h3><div class="ugc-action-fields"><Field v-for="field in dimensions" :key="field.fieldname" :ref="component=>setFieldRef(field.fieldname,component,true)" :field="field" :model-value="values.accounting_dimensions?.[field.fieldname]" :context="values" :disabled="busy" @update:model-value="value=>setDimension(field.fieldname,value)"/></div></section>
      <section v-if="showLines" class="ugc-action-line-section" :aria-label="payment?'Affectation du règlement':'Choix des lignes'"><div class="ugc-action-line-heading"><div><h3>{{payment?'Affecter le règlement aux bordereaux':'Sélectionner les lignes et les quantités'}}</h3><small v-if="payment">Les bordereaux A et B du même compte peuvent être réglés ensemble.</small><small v-else-if="rows.some(row=>row._derived)">Les services associés suivent la sélection et la quantité de leur ouvrage.</small></div><div class="ugc-action-select-tools"><button type="button" :disabled="busy||!rows.length" @click="toggleAll(true)">Tout sélectionner</button><button type="button" :disabled="busy||!rows.length" @click="toggleAll(false)">Tout désélectionner</button></div></div>
       <div v-if="!rows.length" class="ugc-action-empty">{{payment?'Aucun bordereau restant à régler. Vous pouvez enregistrer une avance.':'Aucune ligne disponible pour cette opération.'}}</div>
       <div v-else class="ugc-action-table-wrap"><table class="ugc-action-table"><thead><tr><th class="ugc-action-select"><input type="checkbox" :checked="allSelected" :indeterminate="someSelected" :disabled="busy" aria-label="Sélectionner toutes les lignes" @change="toggleAll($event.target.checked)"/></th><th>{{payment?'Bordereau spécial':'Désignation'}}</th><template v-if="!payment"><th>Commandé</th><th>Déjà traité</th><th>Restant</th><th>Quantité à traiter</th><th>Unité</th><th>Montant</th></template><template v-else><th>Circuit</th><th>Solde disponible</th><th>Montant affecté</th></template></tr></thead><tbody><template v-for="row in rows" :key="row.id"><tr :class="{'ugc-action-row-selected':row.selected,'ugc-action-child':row._parent_id}"><td class="ugc-action-select"><input type="checkbox" :checked="row.selected" :disabled="busy||row._derived" :aria-label="'Sélectionner '+(row.label||row.item_code||row.id)" @change="changeSelection(row,$event.target.checked)"/></td><td class="ugc-action-designation"><strong>{{row._parent_id?'↳ ':''}}{{row.label||row.item_name||row.item_code||row.id}}</strong><small v-if="row.description&&plain(row.description)!==row.label">{{plain(row.description)}}</small><small v-if="row.item_code&&row.item_code!==row.label">{{row.item_code}}</small><small v-if="row._derived">Quantité liée à l’ouvrage</small><small v-if="payment&&row.sales_order">{{row.sales_order}}</small></td><template v-if="!payment"><td>{{qty(row.ordered_qty)}}</td><td>{{qty(row.processed_qty??row.delivered_qty)}}</td><td>{{qty(row.remaining_qty)}}</td><td><input class="ugc-action-qty" type="number" :value="row.qty" min="0.000001" :max="row.remaining_qty" :step="row.must_be_whole_number?1:'any'" :disabled="busy||!row.selected||row._derived" :aria-label="'Quantité de '+(row.label||row.id)" @input="changeQuantity(row,$event.target.value)"/></td><td>{{row.uom||'—'}}</td><td class="ugc-action-money">{{money(actionLineAmount(row),row.currency||currency)}}</td></template><template v-else><td><span class="ugc-action-circuit" :class="{'ugc-action-b':row.order_type==='B'}">{{row.order_type||'—'}}</span></td><td class="ugc-action-money">{{money(row.remaining_amount??row.balance??row.remaining_qty,row.currency||currency)}}</td><td><input class="ugc-action-allocation" v-model="row.amount" type="number" min="0" :max="row.remaining_amount??row.balance??row.remaining_qty" step="any" :disabled="busy||!row.selected" :aria-label="'Montant affecté à '+(row.label||row.id)"/></td></template></tr>
        <tr v-if="delivery&&row.selected&&(row.warehouse!==undefined||row.has_serial_no||row.batch_no)" class="ugc-action-stock-row"><td></td><td :colspan="payment?4:7"><details :open="row.has_serial_no&&selectedSerials(row).length===0"><summary><Icon name="truck"/><span>{{row.warehouse||'Choisir le dépôt'}}<template v-if="row.has_serial_no"> · {{selectedSerials(row).length}} série(s) sélectionnée(s)</template></span></summary><div class="ugc-action-stock-fields"><Field :field="warehouseField(row)" :model-value="row.warehouse" :context="values" :disabled="busy" @update:model-value="value=>changeWarehouse(row,value)"/><Field v-if="row.has_batch_no||row.batch_no" :field="{fieldname:'batch_no',label:'Lot',fieldtype:'Link',options:'Batch',filters:{item:row.item_code}}" :model-value="row.batch_no" :context="values" :disabled="busy" @update:model-value="value=>row.batch_no=value"/></div><div v-if="row.has_serial_no" class="ugc-action-serials"><div v-if="rowCandidates(row).length" class="ugc-action-serial-options"><label v-for="serial in rowCandidates(row)" :key="serial.name"><input type="checkbox" :checked="selectedSerials(row).includes(serial.name)" :disabled="busy" @change="selectSerial(row,serial.name,$event.target.checked)"/><span>{{serial.name}}<small v-if="serial.warehouse">{{serial.warehouse}}</small></span></label></div><label class="ugc-action-serial-input">Numéros de série, un par ligne<textarea v-model="row.serial_no" rows="3" :disabled="busy" @input="row._serials_manual=true"/></label></div></details></td></tr>
       </template></tbody></table></div>
      </section>
      <section v-if="showLines" class="ugc-action-totals" aria-label="Récapitulatif de la sélection"><template v-if="payment"><div><small>Montant encaissé</small><strong>{{money(values.amount)}}</strong></div><div><small>Affecté aux BL A</small><strong>{{money(totals.amount_a)}}</strong></div><div><small>Affecté aux BL B</small><strong>{{money(totals.amount_b)}}</strong></div><div :class="{'ugc-action-total-error':totals.unallocated<0}"><small>Montant non affecté / avance</small><strong>{{money(totals.unallocated)}}</strong></div><button v-if="amountField&&!amountField.read_only" type="button" :disabled="busy||!totals.allocated" @click="useAllocatedTotal">Encaisser le total affecté</button></template><template v-else><div><small>Lignes sélectionnées</small><strong>{{totals.parent_count}}</strong></div><div><small>Quantités par unité</small><strong v-for="value in totals.quantities" :key="value.uom">{{qty(value.qty)}} {{value.uom}}</strong></div><div><small>{{preparation.amount_label||'Montant des lignes sélectionnées'}}</small><strong v-for="value in totals.amounts" :key="value.currency">{{money(value.amount,value.currency)}}</strong><strong v-if="totals.unknown_amount">Montant à déterminer</strong></div></template></section>
      <p v-if="preparation.submission?.workflow_name&&!preparation.submission?.workflow_actions?.length" class="ugc-action-workflow">Workflow {{preparation.submission.workflow_name}} : enregistrez le brouillon pour accéder aux transitions autorisées.</p><p v-if="preparation.notice" class="ugc-action-notice">{{plain(preparation.notice)}}</p>
     </template>
    </template>
   </div>
   <footer class="ugc-action-footer"><button type="button" class="ugc-action-cancel" :disabled="busy" @click="close">Fermer</button><div><span v-if="busy" class="ugc-action-saving" role="status">Enregistrement en cours…</span><button v-for="button in buttons" :key="button.key" type="button" :class="{'ugc-action-primary':button.primary}" :disabled="busy||loading" :title="button.next_state?('État suivant : '+button.next_state):''" @click="execute(button)">{{buttonLabel(button)}}</button></div></footer>
  </dialog>
 </Teleport>
</template>
