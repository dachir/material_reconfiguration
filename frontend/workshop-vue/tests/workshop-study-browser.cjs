/* Acceptance of the built bundle with synthetic documents, no ERPNext calls. */
const assert=require('node:assert/strict'),path=require('node:path');
const appRoot=path.resolve(__dirname,'../../..');
let chromium;
try{({chromium}=require('playwright'));}
catch{({chromium}=require(path.join(appRoot,'../crm/node_modules/playwright')));}

(async()=>{
 const browser=await chromium.launch({headless:true,args:['--no-sandbox']});
 try{
  const page=await browser.newPage({viewport:{width:1600,height:1050}}),errors=[];
  page.on('pageerror',error=>errors.push(error.message));
  await page.route('http://workshop.test/**',route=>route.fulfill({contentType:'text/html',
   body:'<!doctype html><html><body style="margin:0"><main id="app"></main></body></html>'}));
  await page.goto('http://workshop.test/');
  await page.addStyleTag({path:path.join(appRoot,'mat_reco/public/js/workshop_vue_dist/workshop.css')});
  await page.evaluate(()=>{
   const leaf={id:'CUT',sales_order:'SO-A',label:'Découpe de démonstration',item_type:'DECOUPE',
    required_qty:2,produced_qty:0,remaining_qty:2,fabricable_qty:0,manufacture_qty:2,
    state:'blocked',state_label:'À découper',children:[]};
   const order=(id,sheet)=>({id,sales_order:id,label:id,item_type:'ORDER',customer:'CLIENT',
    required_qty:2,produced_qty:0,remaining_qty:2,fabricable_qty:0,manufacture_qty:2,
    state:'blocked',state_label:'Fabrication requise',has_children:id==='SO-A',
    technical_studies:sheet?[{name:sheet,docstatus:1}]:[],children:id==='SO-A'?[leaf]:[]});
   window.payload={roots:[order('SO-A','FT-A'),order('SO-B','FT-B'),order('SO-HIDDEN',null)],
    errors:[],counters:{orders:3,works:1},primary_items:[],companies:[],chantiers:[],sections:[],
    dimension_fields:[],as_of:'2026-10-31 12:00:00',mcps:[]};
   window.routes=[];window.calls=[];
   window.frappe={router:{on(){}},realtime:{on(){},off(){}},get_route:()=>['workshop-cockpit'],
    set_route:(...args)=>window.routes.push(args),call:async options=>{
     window.calls.push(options.method);
     if(!options.method.endsWith('.get_dashboard'))throw new Error('Unexpected operation');
     return {message:JSON.parse(JSON.stringify(window.payload))};
    }};
  });
  await page.addScriptTag({path:path.join(appRoot,'mat_reco/public/js/workshop_vue_dist/workshop.js')});
  await page.evaluate(()=>{window.component=UniversWorkshop.mount(document.querySelector('#app'));component.show();});
  await page.locator('.ug-study-node').first().waitFor();
  assert.equal(await page.locator('.ug-study-node').count(),2);
  assert.equal(await page.locator('.ug-study-link').count(),2);
  assert.equal(await page.locator('.ug-node.order').count(),3);
  const study=page.getByRole('button',{name:'Ouvrir la fiche technique FT-A de SO-A',exact:true});
  await study.click();
  assert.deepEqual(await page.evaluate(()=>window.routes.at(-1)),['technical-study','FT-A']);
  await page.getByRole('button',{name:'Développer SO-A',exact:true}).click();
  assert.equal(await page.locator('.ug-study-node').count(),2);
  await page.locator('.ug-node:not(.order):not(.ug-study-node) .ug-node-body').first().click();
  await page.locator('.ug-study-links button').click();
  assert.deepEqual(await page.evaluate(()=>window.routes.at(-1)),['technical-study','FT-A']);
  await page.getByRole('button',{name:'☷ Vue liste',exact:true}).click();
  assert.equal(await page.locator('.ug-study-shortcut').count(),2);
  await page.locator('.ug-study-shortcut').last().click();
  assert.deepEqual(await page.evaluate(()=>window.routes.at(-1)),['technical-study','FT-B']);
  await page.getByRole('button',{name:'♧ Vue arbre',exact:true}).click();
  await page.getByRole('button',{name:'Réduire',exact:true}).click();
  assert.equal(await page.locator('.ug-study-node').count(),2);
  assert.equal(await page.locator('.ug-study-link').count(),2);
  await page.screenshot({path:'/tmp/ug-workshop-study-links.png',fullPage:true});
  await page.evaluate(()=>{component.hide();component.unmount();});
  assert.deepEqual(errors,[]);
  assert((await page.evaluate(()=>window.calls)).every(method=>method.endsWith('.get_dashboard')));
  console.log('PASS: FT links in collapsed/expanded graph, list and details; Vue routes; no manufacturing calls.');
 }finally{await browser.close();}
})().catch(error=>{console.error(error.name+': '+error.message);process.exit(1);});
