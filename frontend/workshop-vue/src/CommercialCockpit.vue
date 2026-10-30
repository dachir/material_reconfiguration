<script setup>
import {ref,shallowRef,reactive,computed,nextTick,watch,onBeforeUnmount} from 'vue';
import Icon from './commercial-icon.vue';
import CommercialActionModal from './CommercialActionModal.vue';
import {COMMERCIAL_COLUMNS,buildCommercialLayout,formatCommercialAmount,periodRange,connectedPath,nodeCanOpen,commercialRouteFor,commercialStatus,commercialKindLabel} from './commercial-layout.js';
import './commercial-cockpit.css';

const frappe=window.frappe;
const endpoint='mat_reco.material_reconfiguration.services.commercial_cockpit.get_dashboard';
const actionApi='mat_reco.material_reconfiguration.services.commercial_actions.';
const empty=()=>({clients:[],kpis:{orders:0,remaining_qty:0,balances_a:[],balances_b:[]},documents:[],edges:[],details:{},capabilities:{},warnings:[],currencies:[],companies:[]});
const data=shallowRef(empty()),loading=ref(false),refreshing=ref(false),acting=ref(false),error=ref(''),active=ref(false),stale=ref(false);
const filters=reactive({search:'',customer:'',company:'',currency:'',circuit:'all',state:'open',followup:'all',...periodRange('month',frappe.datetime?.get_today?.())});
const period=ref('month'),clientTab=ref('all'),mode=ref('tree'),zoom=ref(.65),selectedId=ref(''),collapsed=ref(new Set()),viewport=ref(null),root=ref(null),lastUpdated=ref('');
const actionOptions=shallowRef([]),actionsLoading=ref(false),actionModal=shallowRef(null),feedback=ref('');
let actionRequest=0;
let poll=null,searchTimer=null,requestId=0,snapshot='',drag=null,hasLoaded=false;
const clients=computed(()=>Array.isArray(data.value.clients)?data.value.clients:[]);
const documents=computed(()=>Array.isArray(data.value.documents)?data.value.documents:[]);
const byId=computed(()=>new Map(documents.value.map(document=>[document.id,document])));
const capabilities=computed(()=>data.value.capabilities||data.value.permissions||{});
const selected=computed(()=>byId.value.get(selectedId.value));
const detail=computed(()=>data.value.details?.[selectedId.value]||{});
const metrics=computed(()=>({...selected.value?.metrics,...detail.value.metrics}));
const scene=computed(()=>buildCommercialLayout(documents.value,data.value.edges||[],{collapsed:collapsed.value}));
const selectedPath=computed(()=>connectedPath(selectedId.value,data.value.edges||[]));
const currentClient=computed(()=>clients.value.find(client=>(client.customer||client.name)===filters.customer));
const clientLabel=computed(()=>currentClient.value?.label||currentClient.value?.customer_name||filters.customer);
const hasFinance=computed(()=>capabilities.value.can_read_deliveries||capabilities.value.can_read_payments);
const clientList=computed(()=>clients.value.filter(client=>clientTab.value!=='followup'||Number(client.remaining_qty||0)>0||[...(client.balances_a||[]),...(client.balances_b||[])].some(value=>Math.abs(Number(value.amount||0))>0)));
const graphDocuments=computed(()=>documents.value.filter(document=>['project','quotation','order','study','delivery','payment'].includes(document.kind)));
const listGroups=computed(()=>COMMERCIAL_COLUMNS.map(column=>({...column,documents:graphDocuments.value.filter(document=>document.kind===column.kind)})));
const detailLinks=computed(()=>{
 const linked=detail.value.linked_documents||[];
 return linked.map(link=>({...link,kind:link.kind||kindForDoctype(link.doctype)})).filter(link=>link.name&&nodeCanOpen(link,capabilities.value));
});
const tasks=computed(()=>(detail.value.tasks||[]).filter(task=>task.status==='Open'||task.status==='Overdue'));
const canCreateClient=computed(()=>canCreate('Customer','can_create_customers','can_create_customer'));
const isOrder=computed(()=>selected.value?.kind==='order');
const selectedA=computed(()=>selected.value?.order_type==='A');
const balanceCards=computed(()=>[
 {key:'a',label:'Solde BL A · TTC',values:data.value.kpis?.balances_a||[],icon:'coins'},
 {key:'b',label:'Solde BL B · HT',values:data.value.kpis?.balances_b||[],icon:'coins'},
]);
const progress=computed(()=>Math.max(0,Math.min(100,100*Number(metrics.value.delivered_qty||0)/(Number(metrics.value.ordered_qty)||1))));
const printOrders=computed(()=>documents.value.filter(document=>document.kind==='order'));
const asOf=computed(()=>lastUpdated.value?String(lastUpdated.value).replace('T',' ').slice(0,19):'');
const showCompanyLabels=computed(()=>data.value.companies?.length>1);
function qty(value){return value===null||value===undefined?'—':new Intl.NumberFormat('fr-FR',{maximumFractionDigits:3}).format(Number(value)||0);}
function money(value,currency){return formatCommercialAmount(value,currency||selected.value?.currency);}
function balanceKey(value){return (value.company||'')+'::'+(value.currency||'');}
function balanceText(value){return money(value.amount,value.currency)+(showCompanyLabels.value&&value.company?' · '+value.company:'');}
function kindForDoctype(doctype){return ({Customer:'customer',Chantier:'project',Quotation:'quotation','Sales Order':'order','Chantier Technical Study':'study','Bordereau Special':'delivery','Reglement Special':'payment','Delivery Note':'native_delivery','Sales Invoice':'invoice','Payment Entry':'native_payment'})[doctype]||'';}
function canCreate(doctype,...keys){for(const key of keys)if(typeof capabilities.value[key]==='boolean')return capabilities.value[key];return Boolean(frappe.model?.can_create?.(doctype));}
function canOpen(node){return nodeCanOpen(node,capabilities.value);}
function statusTone(node){if(node.docstatus===2)return 'cancelled';if(node.docstatus===1)return 'validated';if(['Accepted','Ordered','Accepté'].includes(node.status))return 'validated';return 'pending';}
function nodeIcon(node){return ({project:'project',quotation:'document',order:'document',study:'gear',delivery:'truck',payment:'coins'})[node.kind]||'document';}
function basis(node){return node.basis||(['order','delivery','quotation'].includes(node.kind)?(node.order_type==='B'?'HT':'TTC'):'');}
function selectedMetric(key,fallback){const value=metrics.value[key];return value===undefined?fallback:value;}
function deliveryBalance(metric={}){return metric.delivery_balance===undefined?metric.balance:metric.delivery_balance;}
function errorText(err){
 let text=err?.message||'Impossible de charger le cockpit commercial.';
 try{const payload=JSON.parse(err._server_messages||'[]');if(payload.length)text=JSON.parse(payload[0]).message||text;}catch{}
 return plainText(text)||text;
}
function plainText(value){return new DOMParser().parseFromString(String(value||''),'text/html').body.textContent||'';}
function permissionDenied(err){return err?.httpStatus===403||err?.status===403||err?.xhr?.status===403||err?.response?.status===403||String(err?.exc_type||err?.exception||'').includes('PermissionError');}
async function refresh({background=false,selectFirst=false}={}){
 if(background&&(!active.value||refreshing.value||drag||document.hidden||acting.value||actionModal.value))return;
 if(acting.value){stale.value=true;return;}
 const request=++requestId;refreshing.value=true;loading.value=!background&&!hasLoaded;error.value='';
 try{
  const response=await frappe.call({method:endpoint,args:{filters:JSON.stringify(filters)},type:'GET'});
  if(request!==requestId||(!active.value&&background))return;
  const payload={...empty(),...(response.message||{})},nextSnapshot=JSON.stringify({...payload,as_of:undefined});
  if(nextSnapshot!==snapshot){data.value=payload;snapshot=nextSnapshot;}
  lastUpdated.value=payload.as_of||'';
  if(selectedId.value&&!byId.value.has(selectedId.value))selectedId.value='';
  if(selectFirst&&!selectedId.value)selectedId.value=documents.value.find(document=>document.kind==='order')?.id||'';
  const keep=[...collapsed.value].filter(id=>byId.value.has(id));
  if(keep.length!==collapsed.value.size)collapsed.value=new Set(keep);
  hasLoaded=true;stale.value=false;
 }catch(err){if(request===requestId){if(permissionDenied(err)){data.value=empty();snapshot='';selectedId.value='';collapsed.value=new Set();}error.value=errorText(err);stale.value=true;}}
 finally{if(request===requestId){refreshing.value=false;loading.value=false;}}
}
function search(){clearTimeout(searchTimer);searchTimer=setTimeout(()=>refresh(),350);}
function chooseCustomer(customer){filters.customer=customer;selectedId.value='';feedback.value='';collapsed.value=new Set();zoom.value=.65;data.value={...data.value,documents:[],orders:[],edges:[],details:{}};snapshot='';hasLoaded=false;refresh({selectFirst:Boolean(customer)});}
function changePeriod(){if(period.value!=='custom')Object.assign(filters,periodRange(period.value,frappe.datetime?.get_today?.()));refresh();}
function select(node){selectedId.value=node.id;}
function collapse(node){const next=new Set(collapsed.value);next.has(node.id)?next.delete(node.id):next.add(node.id);collapsed.value=next;}
function openDocument(node){if(!canOpen(node))return;const route=commercialRouteFor(node);if(route)frappe.set_route(...route);}
function openWorkshop(order){if(order&&capabilities.value.can_open_workshop)frappe.set_route('workshop-cockpit',order);}
async function loadActions(){
 const serial=++actionRequest,node=selected.value;actionOptions.value=[];
 if(!node||!['project','quotation','order','delivery','payment'].includes(node.kind)){actionsLoading.value=false;return;}
 actionsLoading.value=true;
 try{
  const response=await frappe.call({method:actionApi+'get_actions',args:{source_doctype:node.doctype,source_name:node.name},type:'GET'});
  if(serial!==actionRequest)return;
  actionOptions.value=Array.isArray(response.message)?response.message:response.message?.actions||[];
 }catch(err){if(serial===actionRequest){if(permissionDenied(err))actionOptions.value=[];error.value=errorText(err);}}
 finally{if(serial===actionRequest)actionsLoading.value=false;}
}
watch([selectedId,()=>selected.value?.modified,()=>selected.value?.docstatus,capabilities],loadActions);
function beginAction(option){
 if(!selected.value||acting.value||option.enabled===false)return;
 feedback.value='';actionModal.value={source:{...selected.value},action:option.action};
}
async function actionCompleted(result){
 actionModal.value=null;acting.value=false;
 const target=result.document||result;
 feedback.value=result.message||`${target.doctype||'Document'} ${target.name||''} ${target.docstatus===1?'validé':'enregistré'}.`;
 if(!active.value){stale.value=true;return;}
 await refresh();
 const identity=target.doctype&&target.name?target.doctype+'::'+target.name:null;
 if(identity&&byId.value.has(identity))selectedId.value=identity;
 else await loadActions();
}
function addClient(){if(canCreateClient.value)frappe.new_doc('Customer');}
function panStart(event){
 if(event.button!==0||event.target.closest('button,a,input,select'))return;
 drag={x:event.clientX,y:event.clientY,left:viewport.value.scrollLeft,top:viewport.value.scrollTop};
 viewport.value.setPointerCapture?.(event.pointerId);
}
function panMove(event){if(!drag)return;viewport.value.scrollLeft=drag.left-event.clientX+drag.x;viewport.value.scrollTop=drag.top-event.clientY+drag.y;}
function panEnd(){drag=null;}
async function setZoom(value,event=null){
 const element=viewport.value;if(!element){zoom.value=Math.max(.3,Math.min(1.5,value));return;}
 const rect=element.getBoundingClientRect(),x=event?event.clientX-rect.left:element.clientWidth/2,y=event?event.clientY-rect.top:element.clientHeight/2;
 const contentX=(element.scrollLeft+x)/zoom.value,contentY=(element.scrollTop+y)/zoom.value;
 zoom.value=Math.round(Math.max(.3,Math.min(1.5,value))*100)/100;await nextTick();
 element.scrollLeft=contentX*zoom.value-x;element.scrollTop=contentY*zoom.value-y;
}
function wheel(event){if(!event.ctrlKey&&!event.metaKey)return;event.preventDefault();setZoom(zoom.value-event.deltaY*.001,event);}
async function fit(){const element=viewport.value;if(!element)return;await setZoom(Math.min((element.clientWidth-24)/scene.value.width,(element.clientHeight-25)/scene.value.height,1));element.scrollLeft=0;element.scrollTop=0;}
async function printOverview(){await nextTick();window.print();}
function show(){if(active.value){refresh({background:true});return;}active.value=true;refresh().then(()=>{if(active.value&&selected.value&&!actionsLoading.value)loadActions();});poll=setInterval(()=>refresh({background:true}),45000);}
function hide(){active.value=false;requestId++;actionRequest++;actionOptions.value=[];actionModal.value=null;actionsLoading.value=false;refreshing.value=false;loading.value=false;clearInterval(poll);clearTimeout(searchTimer);drag=null;}
onBeforeUnmount(hide);
defineExpose({show,hide});
</script>

<template>
 <div ref="root" class="ug-commercial-cockpit" :class="{'ugc-active':active}" :aria-busy="loading">
  <div class="ugc-screen">
   <header class="ugc-toolbar" aria-label="Filtres du cockpit commercial">
    <label class="ugc-search"><Icon name="search"/><input v-model="filters.search" type="search" placeholder="Rechercher client, chantier, document…" aria-label="Rechercher client, chantier ou document" @input="search"/></label>
    <label class="ugc-filter"><span>Client :</span><select :value="filters.customer" aria-label="Client" @change="chooseCustomer($event.target.value)"><option value="">Tous les clients</option><option v-for="client in clients" :key="client.customer||client.name" :value="client.customer||client.name">{{client.label||client.customer_name||client.customer||client.name}}</option></select></label>
    <label class="ugc-filter"><span>Période :</span><select v-model="period" aria-label="Période" @change="changePeriod"><option value="month">Ce mois</option><option value="30days">30 derniers jours</option><option value="year">Cette année</option><option value="all">Toutes les dates</option><option value="custom">Personnalisée</option></select></label>
    <label class="ugc-filter"><span>Circuit :</span><select v-model="filters.circuit" aria-label="Circuit" @change="refresh()"><option value="all">A + B</option><option value="A">A</option><option value="B">B</option></select></label>
    <label class="ugc-filter"><span>État :</span><select v-model="filters.state" aria-label="État des commandes" @change="refresh()"><option value="open">En cours</option><option value="all">Tous les états</option></select></label>
    <label v-if="data.companies?.length>1" class="ugc-filter"><span>Société :</span><select v-model="filters.company" aria-label="Société" @change="refresh()"><option value="">Toutes</option><option v-for="company in data.companies" :key="company.name||company" :value="company.name||company">{{company.name||company}}</option></select></label>
    <label v-if="data.currencies?.length>1" class="ugc-filter"><span>Devise :</span><select v-model="filters.currency" aria-label="Devise" @change="refresh()"><option value="">Toutes</option><option v-for="currency in data.currencies" :key="currency" :value="currency">{{currency}}</option></select></label>
    <div class="ugc-toolbar-actions"><button class="ugc-icon-button" :disabled="refreshing||acting" title="Rafraîchir les données" aria-label="Rafraîchir les données" @click="refresh()"><Icon name="refresh" :class="{'ugc-spinning':refreshing}"/></button><button class="ugc-icon-button" :disabled="loading" title="Imprimer le récapitulatif" aria-label="Imprimer le récapitulatif" @click="printOverview"><Icon name="print"/></button><span class="ugc-live" :class="{stale}"><i/>{{refreshing?'Actualisation…':stale?'À actualiser':'À jour'}}</span></div>
   </header>
   <div v-if="period==='custom'" class="ugc-date-range"><label>Du <input v-model="filters.from_date" type="date" @change="refresh()"/></label><label>Au <input v-model="filters.to_date" type="date" @change="refresh()"/></label></div>
   <div v-if="feedback" class="ugc-feedback" role="status">{{feedback}}<button class="ugc-icon-button" aria-label="Fermer la confirmation" @click="feedback=''"><Icon name="close"/></button></div>
   <div v-if="error" class="ugc-alert" role="alert">{{error}}<button @click="refresh()">Réessayer</button></div>
   <div v-if="data.truncated||data.warnings?.length" class="ugc-notice" role="status"><span v-if="data.truncated">Affichage limité : précisez le client, la période ou la recherche.</span><span v-for="(warning,index) in data.warnings" :key="index">{{warning}}</span></div>
   <section class="ugc-kpis" aria-label="Indicateurs commerciaux">
    <article class="ugc-kpi"><Icon name="document"/><div><span>{{filters.state==='all'?'Commandes':'Commandes en cours'}}</span><strong>{{loading?'—':qty(data.kpis?.orders)}}</strong></div></article>
    <article class="ugc-kpi"><Icon name="truck"/><div><span>Pièces à livrer</span><strong class="ugc-amount">{{loading?'—':qty(data.kpis?.remaining_qty)}}</strong></div></article>
    <article v-for="card in balanceCards" :key="card.key" class="ugc-kpi"><Icon :name="card.icon"/><div><span>{{card.label}}</span><template v-if="hasFinance"><strong v-for="value in card.values" :key="balanceKey(value)" class="ugc-amount">{{money(value.amount,value.currency)}}<small v-if="showCompanyLabels&&value.company" class="ugc-company">{{value.company}}</small></strong><strong v-if="!card.values.length" class="ugc-amount">—</strong></template><strong v-else>—</strong></div></article>
   </section>
   <div class="ugc-content" :class="{'ugc-with-details':selected}">
    <aside class="ugc-clients" aria-label="Clients">
     <div class="ugc-sidebar-heading"><h2>Clients</h2><button v-if="canCreateClient" class="ugc-add-client" @click="addClient"><Icon name="plus"/>Client</button></div>
     <div class="ugc-segment" role="group" aria-label="Clients à afficher"><button :class="{active:clientTab==='all'}" :aria-pressed="clientTab==='all'" @click="clientTab='all'">Tous</button><button :class="{active:clientTab==='followup'}" :aria-pressed="clientTab==='followup'" @click="clientTab='followup'">À suivre</button></div>
     <button v-if="filters.customer" class="ugc-all-clients" @click="chooseCustomer('')">← Tous les clients</button>
     <div class="ugc-client-list"><button v-for="client in clientList" :key="client.customer||client.name" class="ugc-client" :class="{selected:filters.customer===(client.customer||client.name)}" @click="chooseCustomer(client.customer||client.name)"><strong>{{client.label||client.customer_name||client.customer||client.name}}</strong><small>{{Number(client.orders||0)?qty(client.orders)+' commande(s)'+(filters.state==='open'?' en cours':''):'Aucune commande'+(filters.state==='open'?' en cours':'')}}</small><Icon name="chevron"/><div v-if="filters.customer===(client.customer||client.name)" class="ugc-client-counts"><span>Chantiers<b>{{documents.filter(d=>d.kind==='project').length}}</b></span><span>Devis<b>{{documents.filter(d=>d.kind==='quotation').length}}</b></span><span>Commandes<b>{{documents.filter(d=>d.kind==='order').length}}</b></span></div></button><p v-if="!loading&&!clientList.length" class="ugc-empty-small">{{clientTab==='followup'?'Aucun client à suivre pour ces filtres.':'Aucun client pour ces filtres.'}}</p></div>
    </aside>
    <section class="ugc-journey" aria-label="Parcours commercial">
     <div class="ugc-journey-heading"><h2>Parcours commercial</h2><div class="ugc-segment" role="group" aria-label="Mode d’affichage"><button :class="{active:mode==='tree'}" :aria-pressed="mode==='tree'" @click="mode='tree'">Arbre</button><button :class="{active:mode==='list'}" :aria-pressed="mode==='list'" @click="mode='list'">Liste</button></div><span v-if="filters.customer" class="ugc-client-caption">{{clientLabel}}</span></div>
     <div v-if="mode==='tree'" class="ugc-column-headings"><div v-for="column in COMMERCIAL_COLUMNS" :key="column.kind">{{column.label}}</div></div>
     <div v-if="loading" class="ugc-placeholder" role="status"><Icon name="refresh" class="ugc-spinning"/><strong>Chargement du parcours commercial…</strong></div>
     <div v-else-if="!filters.customer" class="ugc-placeholder"><Icon name="client"/><strong>Sélectionner un client</strong><p>Choisissez un client pour retrouver ses chantiers, devis, commandes, bordereaux et règlements.</p></div>
     <div v-else-if="!graphDocuments.length" class="ugc-placeholder"><Icon name="document"/><strong>Aucun document pour ces filtres</strong><p>Modifiez la période ou l’état pour retrouver les documents de ce client.</p><button @click="period='all';changePeriod()">Voir toutes les dates</button></div>
     <template v-else-if="mode==='tree'">
      <div ref="viewport" class="ugc-viewport" @pointerdown="panStart" @pointermove="panMove" @pointerup="panEnd" @pointercancel="panEnd" @lostpointercapture="panEnd" @wheel="wheel">
       <div class="ugc-scene-sizer" :style="{width:scene.width*zoom+'px',height:scene.height*zoom+'px'}"><div class="ugc-scene" :style="{width:scene.width+'px',height:scene.height+'px',transform:`scale(${zoom})`}">
        <svg class="ugc-links" :viewBox="`0 0 ${scene.width} ${scene.height}`" aria-hidden="true"><defs><marker id="ugc-arrow-cyan" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="#00caff"/></marker><marker id="ugc-arrow-green" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="#58e9ad"/></marker></defs><g v-for="edge in scene.edges" :key="edge.id" :class="{'ugc-link-related':selectedPath.has(edge.source)&&selectedPath.has(edge.target),'ugc-link-dimmed':selectedId&&(!selectedPath.has(edge.source)||!selectedPath.has(edge.target))}"><path :d="edge.path" :class="{'ugc-allocation-link':edge.to.kind==='payment'||edge.to.kind==='delivery'}" :marker-end="edge.to.kind==='payment'||edge.to.kind==='delivery'?'url(#ugc-arrow-green)':'url(#ugc-arrow-cyan)'"/><text v-if="edge.amount!==undefined&&edge.amount!==null" :x="edge.label_x" :y="edge.label_y">{{money(edge.amount,edge.currency)}}</text></g></svg>
        <article v-for="node in scene.nodes" :key="node.id" class="ugc-node" :class="[node.kind,{'ugc-selected':selectedId===node.id,'ugc-circuit-b':node.order_type==='B','ugc-node-cancelled':node.docstatus===2,'ugc-node-dimmed':selectedId&&!selectedPath.has(node.id)}]" :style="{left:node.x+'px',top:node.y+'px',width:node.width+'px',minHeight:node.height+'px'}">
         <button v-if="node.has_children" class="ugc-node-collapse" :aria-label="(node.collapsed?'Développer ':'Replier ')+node.name" :aria-expanded="!node.collapsed" @click="collapse(node)">{{node.collapsed?'›':'⌄'}}</button>
         <button class="ugc-node-body" :aria-label="'Sélectionner '+node.name" @click="select(node)"><Icon :name="nodeIcon(node)"/><div class="ugc-node-copy"><strong>{{node.kind==='study'?'Fiche technique':node.title||node.name}}</strong><span v-if="node.kind!=='study'&&node.subtitle">{{node.subtitle}}</span><span v-if="node.amount!==undefined&&node.amount!==null">{{money(node.amount,node.currency)}} <small>{{basis(node)}}</small></span><div class="ugc-node-meta"><span v-if="node.order_type&&node.kind==='order'" class="ugc-circuit-tag" :class="{'ugc-type-b':node.order_type==='B'}">{{node.order_type}}</span><span v-else-if="node.kind==='payment'&&node.order_type==='Mixte'" class="ugc-state-tag mixed">Mixte A + B</span><span v-else class="ugc-state-tag" :class="statusTone(node)">{{commercialStatus(node)}}</span></div><small v-if="node.kind==='order'&&node.metrics?.ordered_qty!==null&&node.metrics?.ordered_qty!==undefined" class="ugc-delivery-count">Livré : {{qty(node.metrics.delivered_qty)}} / {{qty(node.metrics.ordered_qty)}}</small><small v-if="node.kind==='payment'&&node.order_type==='Mixte'">A : {{money(node.metrics?.amount_a??node.metrics?.a_amount,node.currency)}} · B : {{money(node.metrics?.amount_b??node.metrics?.b_amount,node.currency)}}</small><small v-if="node.kind==='delivery'">{{node.order_type==='A'?'BL + facture ERPNext':'Sortie de stock'}}</small><small v-if="node.hidden_count">{{node.hidden_count}} document(s) replié(s)</small></div></button>
         <button v-if="canOpen(node)" class="ugc-node-open" :aria-label="'Ouvrir '+node.name" title="Ouvrir le document" @click="openDocument(node)"><Icon name="external"/></button>
         <button v-if="node.kind==='study'&&node.sales_order&&capabilities.can_open_workshop" class="ugc-study-workshop" @click="openWorkshop(node.sales_order)">Atelier ↗</button>
        </article>
       </div></div>
      </div>
      <div class="ugc-graph-bottom"><small>Glisser pour déplacer · Ctrl + molette pour zoomer</small><div class="ugc-zoom"><button class="ugc-icon-button" title="Réduire le zoom" aria-label="Réduire le zoom" @click="setZoom(zoom-.1)"><Icon name="minus"/></button><span>{{Math.round(zoom*100)}} %</span><button class="ugc-icon-button" title="Augmenter le zoom" aria-label="Augmenter le zoom" @click="setZoom(zoom+.1)"><Icon name="plus"/></button><button class="ugc-icon-button ugc-fit" title="Ajuster le graphe" aria-label="Ajuster le graphe" @click="fit"><Icon name="fit"/></button></div></div>
     </template>
     <div v-else class="ugc-list"><section v-for="group in listGroups" :key="group.kind"><h3>{{group.label}} <small>{{group.documents.length}}</small></h3><div v-for="node in group.documents" :key="node.id" class="ugc-list-row" :class="{'ugc-list-selected':selectedId===node.id}"><button @click="select(node)"><Icon :name="nodeIcon(node)"/><span><strong>{{node.title||node.name}}</strong><small>{{node.subtitle}}</small></span><span class="ugc-state-tag" :class="statusTone(node)">{{commercialStatus(node)}}</span><span>{{money(node.amount,node.currency)}} <small v-if="node.amount!==null&&node.amount!==undefined">{{basis(node)}}</small></span></button><button v-if="canOpen(node)" class="ugc-icon-button" :aria-label="'Ouvrir '+node.name" @click="openDocument(node)"><Icon name="external"/></button></div><p v-if="!group.documents.length" class="ugc-empty-small">Aucun document.</p></section></div>
    </section>
    <aside v-if="selected" class="ugc-details" aria-label="Détails du document sélectionné">
     <div class="ugc-detail-heading"><h2>{{isOrder?'Commande sélectionnée':commercialKindLabel(selected.kind)+' sélectionné'}}</h2><button class="ugc-icon-button" aria-label="Fermer les détails" @click="selectedId=''"><Icon name="close"/></button></div>
     <div class="ugc-detail-title"><Icon :name="nodeIcon(selected)"/><div><h3>{{selected.title||selected.name}}</h3><p>{{selected.subtitle||clientLabel}}</p><span v-if="isOrder" class="ugc-circuit-tag" :class="{'ugc-type-b':!selectedA}">{{selectedA?'A · Facturation ERPNext':'B · Hors facturation ERPNext'}}</span><span v-else class="ugc-state-tag" :class="statusTone(selected)">{{commercialStatus(selected)}}</span></div></div>
     <template v-if="isOrder"><dl class="ugc-detail-amounts"><div><dt>{{selectedA?'Total commande TTC':'Total commande HT'}}</dt><dd>{{money(selectedMetric('order_amount',selected.amount),selected.currency)}}</dd></div><div><dt>{{selectedA?'Livré / facturé':'Bordereaux validés HT'}}</dt><dd>{{money(metrics.delivery_amount,selected.currency)}}</dd></div><div><dt>Règlements reçus</dt><dd>{{money(metrics.received,selected.currency)}}</dd></div><div class="ugc-balance"><dt>Solde des BL</dt><dd>{{money(deliveryBalance(metrics),selected.currency)}}</dd></div></dl><div class="ugc-delivery-progress"><strong>{{qty(metrics.delivered_qty)}} / {{qty(metrics.ordered_qty)}} pièces livrées</strong><div class="ugc-progress-track" role="progressbar" :aria-valuenow="Math.round(progress)" aria-valuemin="0" aria-valuemax="100" aria-label="Progression des livraisons"><span :style="{width:progress+'%'}"/></div><small>Reste à livrer : {{qty(metrics.remaining_qty)}} pièce(s)</small></div></template>
     <template v-else><dl class="ugc-detail-amounts"><div><dt>Montant {{basis(selected)}}</dt><dd>{{money(selected.amount,selected.currency)}}</dd></div><div v-if="selected.kind==='payment'"><dt>Montant non affecté</dt><dd>{{money(metrics.unallocated_amount,selected.currency)}}</dd></div><div v-if="selected.kind==='delivery'"><dt>Solde du bordereau</dt><dd>{{money(deliveryBalance(metrics),selected.currency)}}</dd></div></dl></template>
     <div class="ugc-detail-actions">
      <span v-if="actionsLoading" class="ugc-action-loading" role="status">Chargement des actions…</span>
      <button v-for="option in actionOptions" :key="option.action" :class="{'ugc-primary':['quotation','order','delivery'].includes(option.action)}" :disabled="acting||loading||stale||option.enabled===false" :title="option.reason||''" @click="beginAction(option)"><Icon :name="option.action==='payment'?'card':option.action==='edit'?'document':option.action==='validate'?'check':'plus'"/>{{option.label}}</button>
      <button v-if="canOpen(selected)" @click="openDocument(selected)"><Icon name="external"/>{{isOrder?'Ouvrir la commande':'Ouvrir le document'}}</button>
     </div>
     <section v-if="detailLinks.length" class="ugc-associated"><h3>Documents associés</h3><button v-for="link in detailLinks" :key="link.id||link.doctype+'::'+link.name" :title="link.name" @click="openDocument(link)"><Icon :name="nodeIcon(link)"/><span>{{link.label||commercialKindLabel(link.kind)}}</span><small>{{link.name}}</small><Icon name="external"/></button></section>
     <section v-if="tasks.length" class="ugc-tasks"><h3>À faire</h3><div v-for="task in tasks" :key="task.name"><Icon name="square"/><span>{{plainText(task.description)}}</span></div></section>
    </aside>
   </div>
   <footer class="ugc-footer"><span>Les montants A sont TTC ; les montants B sont HT. Les devises sont présentées séparément.</span><small v-if="asOf">Actualisé : {{asOf}}</small></footer>
  </div>
  <CommercialActionModal v-if="actionModal" :source="actionModal.source" :action="actionModal.action" @close="actionModal=null" @busy="acting=$event" @completed="actionCompleted"/>
  <section class="ugc-print" aria-label="Récapitulatif commercial à imprimer"><h1>Cockpit commercial</h1><p>{{clientLabel||'Tous les clients'}} · {{asOf}} · {{filters.from_date||'Début'}} → {{filters.to_date||'Aujourd’hui'}}</p><p>Commandes : {{qty(data.kpis?.orders)}} · Pièces à livrer : {{qty(data.kpis?.remaining_qty)}}</p><p v-for="card in balanceCards" :key="card.key">{{card.label}} : <span v-for="(value,index) in card.values" :key="balanceKey(value)">{{index?' · ':''}}{{balanceText(value)}}</span></p><table v-if="printOrders.length"><thead><tr><th>Commande</th><th>Circuit</th><th>Montant</th><th>Livré</th><th>Restant</th><th>Solde des BL</th></tr></thead><tbody><tr v-for="order in printOrders" :key="order.id"><td>{{order.name}}</td><td>{{order.order_type}}</td><td>{{money(order.amount,order.currency)}} {{basis(order)}}</td><td>{{qty(order.metrics?.delivered_qty)}}</td><td>{{qty(order.metrics?.remaining_qty)}}</td><td>{{money(deliveryBalance(order.metrics),order.currency)}}</td></tr></tbody></table><template v-for="group in listGroups" :key="group.kind"><h2 v-if="group.documents.length">{{group.label}}</h2><table v-if="group.documents.length"><thead><tr><th>Document</th><th>État</th><th>Montant</th></tr></thead><tbody><tr v-for="node in group.documents" :key="node.id"><td>{{node.name}}</td><td>{{commercialStatus(node)}}</td><td>{{money(node.amount,node.currency)}} {{basis(node)}}</td></tr></tbody></table></template><table v-if="!filters.customer"><thead><tr><th>Client</th><th>Commandes</th><th>Pièces à livrer</th><th>Soldes A TTC</th><th>Soldes B HT</th></tr></thead><tbody><tr v-for="client in clients" :key="client.customer||client.name"><td>{{client.label||client.customer_name}}</td><td>{{qty(client.orders)}}</td><td>{{qty(client.remaining_qty)}}</td><td><span v-for="value in client.balances_a||[]" :key="balanceKey(value)">{{balanceText(value)}} </span></td><td><span v-for="value in client.balances_b||[]" :key="balanceKey(value)">{{balanceText(value)}} </span></td></tr></tbody></table></section>
 </div>
</template>
