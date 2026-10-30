/* Browser acceptance of the built bundle, using synthetic documents only.
 * Run after npm run build: node tests/commercial-browser.cjs
 * No ERPNext session, credentials, database writes or production calls.
 */
const assert = require('node:assert/strict');
const path = require('node:path');
const fs = require('node:fs');
const appRoot = path.resolve(__dirname, '../../..');
let chromium;
try { ({chromium} = require('playwright')); }
catch { ({chromium} = require(path.join(appRoot, '../crm/node_modules/playwright'))); }

const DT = {project:'Chantier',quotation:'Quotation',order:'Sales Order',study:'Chantier Technical Study',delivery:'Bordereau Special',payment:'Reglement Special',invoice:'Sales Invoice',native_delivery:'Delivery Note',native_payment:'Payment Entry'};
const identity = (kind,name) => `${DT[kind]}::${name}`;
const document = (kind,name,extra={}) => ({id:identity(kind,name),doctype:DT[kind],kind,name,title:name,customer:'CLIENT-DEMO',currency:'XOF',docstatus:1,status:'Validé',date:'2026-10-30',...extra});
const relation = (source,target,kind='source',amount) => ({source:source.id,target:target.id,kind,...(amount===undefined?{}:{amount,currency:'XOF'})});
function fixture() {
 const chantier=document('project','CH-DEMO-047',{title:'CH-DEMO-047',subtitle:'Résidence Les Palmiers'});
 const qa=document('quotation','DEV-DEMO-069',{amount:354000,basis:'TTC',status:'Accepted'});
 const qb=document('quotation','DEV-DEMO-070',{amount:200000,basis:'HT',status:'Accepted'});
 const pending=document('quotation','DEV-DEMO-071',{amount:150000,basis:'TTC',status:'Open',docstatus:0});
 const a=document('order','SO-DEMO-A',{order_type:'A',amount:354000,basis:'TTC',subtitle:'Client Démonstration',metrics:{ordered_qty:6,delivered_qty:4,remaining_qty:2,remaining_all_qty:2,can_deliver:true,order_amount:354000,delivery_amount:236000,received:100000,balance:121000,delivery_balance:136000}});
 const b=document('order','SO-DEMO-B',{order_type:'B',amount:200000,basis:'HT',subtitle:'Client Démonstration',metrics:{ordered_qty:5,delivered_qty:3,remaining_qty:2,remaining_all_qty:2,can_deliver:true,order_amount:200000,delivery_amount:120000,received:80000,balance:40000,delivery_balance:40000}});
 const fa=document('study','FT-DEMO-A',{sales_order:a.name,subtitle:'Validée'});
 const fb=document('study','FT-DEMO-B',{sales_order:b.name,subtitle:'Validée'});
 const da=document('delivery','BL-DEMO-021',{sales_order:a.name,order_type:'A',basis:'TTC',amount:118000,metrics:{balance:18000}});
 const da2=document('delivery','BL-DEMO-022',{sales_order:a.name,order_type:'A',basis:'TTC',amount:118000,metrics:{balance:118000}});
 const db=document('delivery','BL-DEMO-023',{sales_order:b.name,order_type:'B',basis:'HT',amount:120000,metrics:{balance:40000}});
 const mixed=document('payment','REG-DEMO-MIXTE',{order_type:'Mixte',amount:180000,basis:'',metrics:{amount_a:100000,amount_b:80000,unallocated_amount:0}});
 const invoice=document('invoice','INV-DEMO-1',{amount:118000,basis:'TTC'});
 const documents=[chantier,qa,qb,pending,a,b,fa,fb,da,da2,db,mixed,invoice];
 const edges=[relation(chantier,qa),relation(chantier,qb),relation(chantier,pending),relation(qa,a),relation(qb,b),relation(a,fa,'technical'),relation(b,fb,'technical'),relation(a,da),relation(a,da2),relation(b,db),relation(da,mixed,'allocation',100000),relation(db,mixed,'allocation',80000)];
 const details=Object.fromEntries(documents.map(doc=>[doc.id,{...doc,linked_documents:[],tasks:[]}]));
 details[a.id].linked_documents=[fa,invoice].map(doc=>({...doc,label:doc.kind==='study'?'Fiche technique':'Facture'}));
 details[a.id].tasks=[{name:'TODO-DEMO',status:'Open',description:'Livrer les 2 pièces restantes'}];
 return {capabilities:{...Object.fromEntries(['orders','quotations','projects','studies','deliveries','payments','invoices','native_deliveries','native_payments'].map(key=>['can_read_'+key,true])),can_create_delivery:true,can_create_payment:true,can_create_customer:true,can_open_workshop:true},clients:[{customer:'CLIENT-DEMO',label:'Client Démonstration',orders:2,remaining_qty:4,balances_a:[{company:'Société Démo',currency:'XOF',amount:136000}],balances_b:[{company:'Société Démo',currency:'XOF',amount:40000}]}],kpis:{orders:2,remaining_qty:4,balances_a:[{company:'Société Démo',currency:'XOF',amount:136000}],balances_b:[{company:'Société Démo',currency:'XOF',amount:40000}]},documents,edges,details,orders:[a,b],currencies:['XOF'],companies:[{name:'Société Démo',default_currency:'XOF'}],warnings:[],truncated:false,as_of:'2026-10-30 12:00:00'};
}

(async()=>{
 const browser=await chromium.launch({headless:true,args:['--no-sandbox']});
 try {
  const page=await browser.newPage({viewport:{width:1672,height:1000}}),errors=[];
  page.on('pageerror',error=>errors.push(error.message));
  await page.route('http://commercial.test/**',route=>route.fulfill({contentType:'text/html',body:'<!doctype html><html lang="fr"><head><meta charset="utf-8"></head><body style="margin:0;background:#fff"><header style="height:62px;padding:15px 20px;box-sizing:border-box;font:24px Arial;color:#102230">Cockpit commercial</header><main id="app" style="margin:0 6px"></main></body></html>'}));
  await page.goto('http://commercial.test/');
  await page.addStyleTag({path:path.join(appRoot,'mat_reco/public/js/workshop_vue_dist/workshop.css')});
  await page.evaluate(payload=>{
   window.testPayload=payload;window.requests=[];window.routes=[];window.printed=0;window.denyAccess=false;
   window.print=()=>window.printed++;
   window.frappe={router:{on(){}},datetime:{get_today:()=> '2026-10-30'},get_route:()=>['commercial-cockpit'],set_route:(...route)=>window.routes.push(route),new_doc:doctype=>window.routes.push(['New',doctype]),
    model:{can_create:()=>true,with_doctype:async()=>{},sync:doc=>[doc]},
    call:async options=>{
     window.requests.push(options);
     if(options.method.endsWith('.get_dashboard')){
      if(window.denyAccess)throw {status:403,message:'Accès refusé aux documents spéciaux.'};
      const result=JSON.parse(JSON.stringify(window.testPayload));
      const filters=JSON.parse(options.args.filters);result.filters=filters;
      if(!filters.customer){result.documents=[];result.edges=[];result.details={};}
      return {message:result};
     }
     if(options.method.endsWith('.get_actions'))return {message:options.args.source_doctype==='Sales Order'?[
      ...(testPayload.capabilities.can_create_delivery?[{action:'delivery',label:'Livrer'}]:[]),
      ...(testPayload.capabilities.can_create_payment?[{action:'payment',label:'Enregistrer un règlement'}]:[])
     ]:[]};
     throw new Error('Unexpected API call: '+options.method);
    }};
  },fixture());
  await page.addScriptTag({path:path.join(appRoot,'mat_reco/public/js/workshop_vue_dist/workshop.js')});
  await page.evaluate(()=>{window.component=UniversWorkshop.mountCommercialCockpit(document.querySelector('#app'));component.show();});
  await page.getByText('Sélectionner un client',{exact:true}).waitFor();
  await page.locator('.ugc-client').first().click();
  await page.locator('.ugc-node.order').first().waitFor();
  assert.equal(await page.locator('.ugc-node.payment').count(),1,'The mixed receipt must appear once');
  assert.equal(await page.locator('.ugc-allocation-link').count(),5,'Both allocation links must remain visible');
  assert.match(await page.locator('.ugc-zoom').innerText(),/65 %/);
  assert(!await page.locator('.ugc-node.payment').innerText().then(text=>text.includes('TTC')),'A receipt has no tax basis');
  await page.getByRole('button',{name:'Sélectionner SO-DEMO-B',exact:true}).click();
  assert.match(await page.locator('.ugc-details').innerText(),/Total commande HT/);
  await page.getByRole('button',{name:'Sélectionner SO-DEMO-A',exact:true}).click();
  assert.match(await page.locator('.ugc-details').innerText(),/136\s*000/);
  assert(!/121\s*000/.test(await page.locator('.ugc-details').innerText()),'The BL balance must not be confused with an advance-adjusted account balance');
  await page.getByRole('button',{name:'Ouvrir la commande',exact:true}).click();
  assert.deepEqual(await page.evaluate(()=>window.routes.at(-1)),['Form','Sales Order','SO-DEMO-A']);
  await page.getByRole('button',{name:'Ouvrir FT-DEMO-A',exact:true}).click();
  assert.deepEqual(await page.evaluate(()=>window.routes.at(-1)),['technical-study','FT-DEMO-A']);
  await page.getByRole('button',{name:'Liste',exact:true}).click();
  assert.equal(await page.locator('.ugc-list-row').count(),10);
  await page.getByRole('button',{name:'Arbre',exact:true}).click();
  await page.getByRole('button',{name:'Augmenter le zoom',exact:true}).click();
  assert.match(await page.locator('.ugc-zoom').innerText(),/75 %/);
  await page.getByRole('button',{name:'Réduire le zoom',exact:true}).click();
  await page.getByRole('button',{name:'Imprimer le récapitulatif',exact:true}).click();
  assert.equal(await page.evaluate(()=>window.printed),1);
  await page.emulateMedia({media:'print'});
  assert(await page.locator('.ugc-print').isVisible());
  assert(!await page.locator('.ugc-screen').isVisible());
  await page.emulateMedia({media:'screen'});
  const out=process.env.UG_COMMERCIAL_SCREENSHOT;
  if(out){fs.mkdirSync(path.dirname(out),{recursive:true});await page.screenshot({path:out,fullPage:true});}
  await page.setViewportSize({width:600,height:900});
  assert(await page.locator('.ug-commercial-cockpit').evaluate(element=>element.scrollWidth<=element.clientWidth+1),'The mobile cockpit must not overflow');
  await page.setViewportSize({width:1672,height:1000});
  await page.evaluate(()=>{testPayload.capabilities.can_create_delivery=false;testPayload.capabilities.can_create_payment=false;});
  await page.getByRole('button',{name:'Rafraîchir les données',exact:true}).click();
  await page.waitForFunction(()=>!document.querySelector('.ugc-toolbar button[disabled]'));
  await page.waitForFunction(()=>!document.querySelector('.ugc-detail-actions .ugc-action-loading'));
  assert.equal(await page.locator('.ugc-detail-actions .ugc-primary').count(),0);
  assert.equal(await page.locator('.ugc-detail-actions').getByRole('button',{name:'Enregistrer un règlement',exact:true}).count(),0);
  await page.evaluate(()=>window.denyAccess=true);
  await page.getByRole('button',{name:'Rafraîchir les données',exact:true}).click();
  await page.getByRole('alert').waitFor();
  assert.equal(await page.locator('.ugc-node').count(),0,'Revoked access must clear the visible documents');
  assert.equal(errors.length,0,errors.join('\n'));
  await page.evaluate(()=>{component.hide();component.unmount();});
  console.log('Cockpit commercial: graph, mixed allocations, document routes, list, zoom, print, mobile and revoked permissions OK. Synthetic data only.');
 } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
