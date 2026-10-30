/* Acceptance of the built commercial cockpit's action dialogs.
 * Synthetic documents and API responses exist in Chromium memory only.
 * No ERPNext session, authenticated calls, database changes or external network.
 * Run after npm run build: node tests/commercial-modal-browser.cjs
 */
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const appRoot=path.resolve(__dirname,'../../..');
let chromium;
try{({chromium}=require('playwright'));}catch{({chromium}=require(path.join(appRoot,'../crm/node_modules/playwright')));}
const doctypes={project:'Chantier',quotation:'Quotation',order:'Sales Order',delivery:'Bordereau Special',payment:'Reglement Special'};
const makeDocument=(kind,name,extra={})=>({id:doctypes[kind]+'::'+name,doctype:doctypes[kind],name,kind,title:name,subtitle:'Client fictif de recette',customer:'CLIENT-MODAL-DEMO',company:'Société Fictive',currency:'XOF',docstatus:1,status:'Validé',date:'2026-10-30',modified:'2026-10-30 12:00:00',...extra});
function dashboard(){
 const project=makeDocument('project','CH-MODAL-DEMO');
 const quotation=makeDocument('quotation','Q-MODAL-DEMO');
 const order=makeDocument('order','SO-MODAL-DEMO',{order_type:'A',amount:60000,basis:'TTC',metrics:{ordered_qty:6,delivered_qty:0,remaining_qty:6,can_deliver:true,order_amount:60000,delivery_amount:0,received:0,delivery_balance:0}});
 const workflow=makeDocument('quotation','Q-WORKFLOW-DEMO',{docstatus:0,status:'Brouillon'});
 const documents=[project,quotation,order,workflow];
 return {capabilities:{...Object.fromEntries(['orders','quotations','projects','studies','deliveries','payments','invoices','native_deliveries','native_payments'].map(key=>['can_read_'+key,true])),can_create_delivery:true,can_create_payment:true,can_create_customer:false},clients:[{customer:'CLIENT-MODAL-DEMO',label:'Client fictif de recette',orders:1,remaining_qty:6,balances_a:[],balances_b:[]}],kpis:{orders:1,remaining_qty:6,balances_a:[],balances_b:[]},documents,edges:[{source:project.id,target:quotation.id,kind:'source'},{source:quotation.id,target:order.id,kind:'source'},{source:project.id,target:workflow.id,kind:'source'}],details:Object.fromEntries(documents.map(doc=>[doc.id,{...doc,linked_documents:[],tasks:[]}])),orders:[order],currencies:['XOF'],companies:[{name:'Société Fictive'}],warnings:[],as_of:'2026-10-30 12:00:00'};
}
(async()=>{
 const browser=await chromium.launch({headless:true,args:['--no-sandbox']});
 try{
  const page=await browser.newPage({viewport:{width:1680,height:1050}}),errors=[],externalRequests=[];
  page.on('pageerror',error=>errors.push(error.message));
  await page.route('**/*',route=>{
   if(route.request().url()==='http://commercial-modal.test/')return route.fulfill({contentType:'text/html',body:'<!doctype html><html lang="fr"><head><meta charset="utf-8"><title>Recette locale fictive</title></head><body style="margin:0;background:white"><h1 style="font:22px Arial;margin:15px">Cockpit commercial · Recette fictive</h1><main id="app"></main></body></html>'});
   externalRequests.push(route.request().url());return route.abort();
  });
  await page.goto('http://commercial-modal.test/');
  await page.addStyleTag({path:path.join(appRoot,'mat_reco/public/js/workshop_vue_dist/workshop.css')});
  await page.evaluate(initial=>{
   window.payload=initial;window.requests=[];window.routes=[];window.mode='normal';window.failNext=false;window.hiddenMessages=0;window.nativeControls=[];window.sequence=0;
   function wrapper(element){return {element,find:selector=>({prop:(name,value)=>{for(const el of element.querySelectorAll(selector))el[name]=value;}}),attr:(name,value)=>{element.setAttribute(name,value);return wrapper(element);},off(){},remove(){element.remove();}};}
   function makeControl({parent,df}){
    const group=document.createElement('div');group.className='frappe-control';group.dataset.fieldname=df.fieldname;
    const label=document.createElement('label');label.textContent=df.label||df.fieldname;group.appendChild(label);
    const input=document.createElement(df.fieldtype==='Select'?'select':df.fieldtype==='Text'?'textarea':'input');input.id='fake-native-control-'+nativeControls.length;
    label.htmlFor=input.id;input.setAttribute('aria-label',df.label||df.fieldname);input.required=Boolean(df.reqd);input.readOnly=Boolean(df.read_only);
    if(df.fieldtype==='Select')for(const value of String(df.options||'').split('\n')){const option=document.createElement('option');option.value=value;option.textContent=value;input.appendChild(option);}
    else if(['Currency','Float','Int'].includes(df.fieldtype)){input.type='number';input.step='any';}
    else input.type='text';
    group.appendChild(input);parent.appendChild(group);
    const control={df,input,$input:wrapper(input),$wrapper:wrapper(group),get_value:()=>['Currency','Float','Int'].includes(df.fieldtype)&&input.value!==''?Number(input.value):input.value,set_value:value=>{input.value=value??'';},awesomplete:{destroy(){}},datepicker:null};
    input.addEventListener('input',()=>df.change?.());input.addEventListener('change',()=>df.change?.());nativeControls.push(control);return control;
   }
   function line(id,label,qty,extra={}){return {id,label,item_code:id,description:label,qty,ordered_qty:qty,processed_qty:0,remaining_qty:qty,uom:'PC',rate:1000,amount:qty*1000,currency:'XOF',selected:true,...extra};}
   function prepare(args){
    const source={doctype:args.source_doctype,name:args.source_name,modified:'2026-10-30 12:00:00'};
    const base={action:args.action,source,company:'Société Fictive',customer:'CLIENT-MODAL-DEMO',currency:'XOF',dimensions:[],fields:[],values:{},submission:{can_save:true,can_submit:true,workflow_actions:[]}};
    if(args.action==='quotation'||args.action==='order')return {...base,title:args.action==='quotation'?'Préparer le devis':'Préparer la commande',target_doctype:args.action==='quotation'?'Quotation':'Sales Order',fields:[{fieldname:'transaction_date',fieldtype:'Date',label:'Date du document',reqd:1}],values:{transaction_date:'2026-10-30'},amount_label:'Total lignes HT',rows:[line('PARENT-1','Vitre principale',6,{must_be_whole_number:true}),line('SERVICE-1','Rabotage associé',18,{parent_id:'PARENT-1',uom:'M.L.'}),line('PARENT-2','Autre vitre',4)]};
    if(args.action==='delivery')return {...base,title:'Préparer le bordereau spécial',target_doctype:'Bordereau Special',service_policy:'independent',fields:[{fieldname:'posting_date',fieldtype:'Date',label:'Date de livraison',reqd:1},{fieldname:'warehouse',fieldtype:'Link',options:'Warehouse',label:'Dépôt',filters:{company:'$company'}}],dimensions:[{fieldname:'branch',fieldtype:'Link',options:'Branch',label:'Agence',reqd:1,default:'Agence Fictive'}],values:{posting_date:'2026-10-30',warehouse:'Stores - UG',accounting_dimensions:{branch:'Agence Fictive'}},rows:[line('SO-GLASS','Vitre à livrer',4,{has_serial_no:true,warehouse:'Stores - UG',serial_no:'SER-DEMO-1\nSER-DEMO-2\nSER-DEMO-3\nSER-DEMO-4',serials:[1,2,3,4,5,6,7,8].map(i=>({name:'SER-DEMO-'+i,warehouse:i<=4?'Stores - UG':'Annexe fictive - UG'}))}),line('SO-SERVICE','Service indépendant',12,{parent_id:'SO-GLASS',uom:'M.L.',warehouse:'Stores - UG'}),line('SO-OTHER','Autre article à livrer',2,{warehouse:'Stores - UG'})]};
    if(args.action==='payment')return {...base,title:'Recevoir un règlement',target_doctype:'Reglement Special',fields:[{fieldname:'posting_date',fieldtype:'Date',label:'Date de règlement',reqd:1},{fieldname:'amount',fieldtype:'Currency',label:'Montant reçu',reqd:1},{fieldname:'mode_of_payment',fieldtype:'Link',options:'Mode of Payment',label:'Mode de règlement',reqd:1},{fieldname:'reference',fieldtype:'Data',label:'Référence'}],values:{posting_date:'2026-10-30',amount:300,mode_of_payment:'Espèces fictives',reference:'TEST-FICTIF'},rows:[{id:'BL-A-DEMO',label:'BL-A-DEMO',order_type:'A',currency:'XOF',sales_order:'SO-MODAL-DEMO',amount:100,remaining_amount:100,remaining_qty:100,selected:true},{id:'BL-B-DEMO',label:'BL-B-DEMO',order_type:'B',currency:'XOF',sales_order:'SO-B-DEMO',amount:200,remaining_amount:200,remaining_qty:200,selected:true}]};
    if(args.action==='validate')return {...base,title:'Vérifier le devis',target_doctype:'Quotation',rows:[],submission:{can_save:false,can_submit:false,workflow_name:'Workflow fictif',workflow_actions:[{action:'Demander validation',label:'Demander validation',next_state:'À valider',docstatus:0}]}};
    throw new Error('Unsupported synthetic action '+args.action);
   }
   window.frappe={ui:{form:{make_control:makeControl}},datetime:{get_today:()=> '2026-10-30'},router:{on(){}},get_route:()=>['commercial-cockpit'],set_route:(...route)=>routes.push(route),model:{can_create:()=>true,with_doctype:async()=>{},sync:doc=>[doc]},hide_msgprint:()=>hiddenMessages++,call:async options=>{
    requests.push(JSON.parse(JSON.stringify(options)));
    if(options.method.endsWith('.get_dashboard')){const data=JSON.parse(JSON.stringify(payload)),filters=JSON.parse(options.args.filters);if(!filters.customer){data.documents=[];data.edges=[];data.details={};}return {message:data};}
    if(options.method.endsWith('.get_actions')){const {source_doctype,source_name}=options.args;return {message:source_name==='Q-WORKFLOW-DEMO'?[{action:'validate',label:'Vérifier et valider'}]:source_doctype==='Chantier'?[{action:'quotation',label:'Créer un devis'}]:source_doctype==='Quotation'?[{action:'order',label:'Créer une commande'}]:source_doctype==='Sales Order'?[{action:'delivery',label:'Livrer'},{action:'payment',label:'Enregistrer un règlement'}]:[]};}
    if(options.method.endsWith('.prepare_action'))return {message:prepare(options.args)};
    if(options.method.endsWith('.execute_action')){
     if(failNext){failNext=false;throw {status:417,responseJSON:{_server_messages:JSON.stringify([JSON.stringify({message:'Le dépôt fictif est indisponible. Réessayez.'})])}};}
     const preparation=prepare(options.args),docstatus=options.args.intent==='submit'?1:0,name='DOC-MODAL-DEMO-'+(++sequence),doctype=preparation.target_doctype,kind=Object.keys({quotation:'Quotation',order:'Sales Order',delivery:'Bordereau Special',payment:'Reglement Special'}).find(k=>({quotation:'Quotation',order:'Sales Order',delivery:'Bordereau Special',payment:'Reglement Special'})[k]===doctype);
     if(kind){const doc={id:doctype+'::'+name,doctype,name,kind,title:name,customer:'CLIENT-MODAL-DEMO',company:'Société Fictive',currency:'XOF',docstatus,status:docstatus?'Validé':'Brouillon',date:'2026-10-30',amount:1000};payload.documents.push(doc);payload.details[doc.id]={...doc,linked_documents:[],tasks:[]};payload.edges.push({source:options.args.source_doctype+'::'+options.args.source_name,target:doc.id,kind:'source'});}
     return {message:{document:{doctype,name,docstatus,modified:'2026-10-30 12:01:00'},message:'Document fictif enregistré.'}};
    }
    throw new Error('Unexpected synthetic API '+options.method);
   }};
  },dashboard());
  await page.addScriptTag({path:path.join(appRoot,'mat_reco/public/js/workshop_vue_dist/workshop.js')});
  await page.evaluate(()=>{window.cockpit=UniversWorkshop.mountCommercialCockpit(document.querySelector('#app'));cockpit.show();});
  await page.locator('.ugc-client').first().click();
  const modal=page.locator('dialog.ugc-action-modal');
  const actions=()=>page.evaluate(()=>requests.filter(request=>request.method.endsWith('.execute_action')).map(request=>request.args));
  const dashboards=()=>page.evaluate(()=>requests.filter(request=>request.method.endsWith('.get_dashboard')).length);
  async function open(name,label){await page.getByRole('button',{name:'Sélectionner '+name,exact:true}).click();await page.locator('.ugc-detail-actions').getByRole('button',{name:label,exact:true}).click();await modal.waitFor();await modal.locator('.ugc-action-loading').waitFor({state:'hidden'});}
  async function completed(previous){await modal.waitFor({state:'detached'});await page.waitForFunction(count=>requests.filter(request=>request.method.endsWith('.get_dashboard')).length>count,previous);}
  await open('CH-MODAL-DEMO','Créer un devis');
  await modal.getByRole('checkbox',{name:'Sélectionner Autre vitre',exact:true}).uncheck();
  await modal.getByRole('spinbutton',{name:'Quantité de Vitre principale',exact:true}).fill('2');
  assert.equal(await modal.getByRole('spinbutton',{name:'Quantité de Rabotage associé',exact:true}).inputValue(),'6');
  assert(await modal.getByRole('spinbutton',{name:'Quantité de Rabotage associé',exact:true}).isDisabled());
  let before=await dashboards();await modal.getByRole('button',{name:'Enregistrer le brouillon',exact:true}).click();await completed(before);
  let last=(await actions()).at(-1);assert.equal(last.intent,'save');assert.deepEqual(JSON.parse(last.selections),[{id:'PARENT-1',qty:2},{id:'SERVICE-1',qty:6}]);assert.deepEqual(JSON.parse(last.values),{transaction_date:'2026-10-30'});
  assert.equal(await page.evaluate(()=>routes.length),0,'Creation must refresh without redirecting to ERPNext');
  await open('Q-MODAL-DEMO','Créer une commande');
  await modal.getByRole('checkbox',{name:'Sélectionner Autre vitre',exact:true}).uncheck();before=await dashboards();await modal.getByRole('button',{name:'Valider',exact:true}).click();await completed(before);
  last=(await actions()).at(-1);assert.equal(last.intent,'submit');assert.deepEqual(Object.keys(JSON.parse(last.selections)[0]),['id','qty']);
  await open('SO-MODAL-DEMO','Livrer');
  await modal.getByRole('spinbutton',{name:'Quantité de Vitre à livrer',exact:true}).fill('2');
  assert(!(await modal.getByRole('spinbutton',{name:'Quantité de Service indépendant',exact:true}).isDisabled()),'BL service quantities stay independent');
  await modal.getByRole('spinbutton',{name:'Quantité de Service indépendant',exact:true}).fill('3');
  await modal.getByRole('checkbox',{name:'Sélectionner Autre article à livrer',exact:true}).uncheck();
  await modal.locator('.ugc-action-stock-row').first().locator('summary').click();
  assert.equal(await modal.locator('textarea').first().inputValue(),'SER-DEMO-1\nSER-DEMO-2');
  await modal.getByRole('textbox',{name:'Dépôt de la ligne',exact:true}).first().fill('Annexe fictive - UG');
  await page.evaluate(()=>failNext=true);await modal.getByRole('button',{name:'Valider',exact:true}).click();
  await modal.getByRole('alert').waitFor();assert.match(await modal.getByRole('alert').innerText(),/Le dépôt fictif est indisponible/);
  let previousAttempts=await actions(),failedKey=previousAttempts.at(-1).request_key;
  await page.evaluate(()=>failNext=true);await modal.getByRole('button',{name:'Valider',exact:true}).click();
  await page.waitForFunction(count=>requests.filter(request=>request.method.endsWith('.execute_action')).length>count,previousAttempts.length);
  previousAttempts=await actions();assert.equal(previousAttempts.at(-1).request_key,failedKey,'Identical retry keeps idempotency key');
  await modal.getByRole('spinbutton',{name:'Quantité de Service indépendant',exact:true}).fill('2');
  before=await dashboards();await modal.getByRole('button',{name:'Valider',exact:true}).click();await completed(before);
  last=(await actions()).at(-1);assert.notEqual(last.request_key,failedKey,'Changed payload gets a new idempotency key');
  const selectedDelivery=JSON.parse(last.selections);assert.equal(selectedDelivery.length,2);assert.deepEqual(selectedDelivery.map(row=>[row.id,row.qty]),[['SO-GLASS',2],['SO-SERVICE',2]]);assert.equal(selectedDelivery[0].warehouse,'Annexe fictive - UG');assert.equal(selectedDelivery[0].serial_no,'SER-DEMO-5\nSER-DEMO-6');assert.deepEqual(JSON.parse(last.values).accounting_dimensions,{branch:'Agence Fictive'});
  await open('SO-MODAL-DEMO','Enregistrer un règlement');
  await modal.getByRole('spinbutton',{name:'Montant reçu',exact:true}).fill('350');
  assert.match(await modal.locator('.ugc-action-totals').innerText(),/50\s*XOF/);
  const screenshot=process.env.UG_COMMERCIAL_MODAL_SCREENSHOT;if(screenshot){fs.mkdirSync(path.dirname(screenshot),{recursive:true});await page.screenshot({path:screenshot,fullPage:true});}
  before=await dashboards();await modal.getByRole('button',{name:'Valider',exact:true}).click();await completed(before);
  last=(await actions()).at(-1);assert.deepEqual(JSON.parse(last.selections),[{id:'BL-A-DEMO',amount:100},{id:'BL-B-DEMO',amount:200}]);assert.equal(JSON.parse(last.values).amount,350);assert(!Object.hasOwn(JSON.parse(last.values),'accounting_dimensions'),'Payment cannot send stock dimensions');
  await open('SO-MODAL-DEMO','Enregistrer un règlement');await modal.getByRole('button',{name:'Tout désélectionner',exact:true}).click();await modal.getByRole('spinbutton',{name:'Montant reçu',exact:true}).fill('500');before=await dashboards();await modal.getByRole('button',{name:'Enregistrer le brouillon',exact:true}).click();await completed(before);last=(await actions()).at(-1);assert.deepEqual(JSON.parse(last.selections),[]);assert.equal(JSON.parse(last.values).amount,500);
  await open('Q-WORKFLOW-DEMO','Vérifier et valider');assert.equal(await modal.locator('.ugc-action-totals').count(),0,'Validation must not show invented zero totals');assert.equal(await modal.getByRole('button',{name:'Valider',exact:true}).count(),0);assert.equal(await modal.getByRole('button',{name:'Demander validation',exact:true}).count(),1);before=await dashboards();await modal.getByRole('button',{name:'Demander validation',exact:true}).click();await completed(before);last=(await actions()).at(-1);assert.equal(last.intent,'workflow');assert.equal(last.workflow_action,'Demander validation');
  await page.setViewportSize({width:420,height:850});await open('SO-MODAL-DEMO','Enregistrer un règlement');
  assert(await modal.evaluate(element=>element.getBoundingClientRect().width<=window.innerWidth),'Mobile dialog fits viewport');
  assert(await modal.evaluate(element=>element.contains(document.activeElement)),'Focus stays in the modal');await page.keyboard.press('Escape');await modal.waitFor({state:'detached'});
  assert(await page.locator('.ugc-detail-actions').getByRole('button',{name:'Enregistrer un règlement',exact:true}).evaluate(element=>element===document.activeElement),'Escape restores focus to the action button');
  assert.equal(await page.evaluate(()=>routes.length),0,'Successful modal actions never redirect');assert.equal(externalRequests.length,0,'Synthetic test must make no network calls');assert.deepEqual(errors,[],'No browser runtime errors');
  await page.evaluate(()=>{cockpit.hide();cockpit.unmount();});
  console.log('Commercial action dialogs: partial quotation/order, parent services, independent partial BL, serials/warehouse/dimensions, mixed receipt, advance, inline retry/idempotency, native save/submit, explicit workflow, cockpit refresh, mobile and focus PASS. Synthetic data only.');
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
