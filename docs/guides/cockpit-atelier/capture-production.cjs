/* Captures réelles de production. Toutes les écritures métier sont bloquées. */
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const {chromium}=require(process.env.UG_PLAYWRIGHT_MODULE||'/home/marsavco/frappe-bench/apps/crm/node_modules/playwright');
const cfg=JSON.parse(fs.readFileSync(process.env.UG_PRODUCTION_AUTH_FILE||'/tmp/ug-production-test/auth.json','utf8'));
const base=(cfg.base_url||cfg.url||'https://fimaci.f.frappe.cloud').replace(/\/$/,'');
const origin=new URL(base).origin,token=cfg.token||cfg.api_token||`${cfg.api_key}:${cfg.api_secret}`;
const reads=new Set(['frappe.desk.desk_page.getpage','frappe.desk.form.load.getdoctype',
 'frappe.desk.form.load.getdoc','frappe.desk.query_report.run','frappe.desk.query_report.get_report_doc','frappe.desk.query_report.get_script','frappe.desk.query_report.get_report_settings','frappe.client.get','frappe.client.get_list','frappe.client.get_value','frappe.client.validate_link',
 'frappe.desk.search.search_link','frappe.desk.search.get_link_title',
 'frappe.desk.doctype.notification_log.notification_log.get_notification_logs']);
const output=path.join(__dirname,'images');fs.mkdirSync(output,{recursive:true});
const manifest={site:origin,captured_at:new Date().toISOString(),screens:[],checks:{}};
const blocked=new Set();
(async()=>{
 const browser=await chromium.launch({headless:true,args:['--no-sandbox']});let context,page;
 try{
  context=await browser.newContext({viewport:{width:1800,height:1100},deviceScaleFactor:1.5});
  await context.route('**/*',async route=>{
   const request=route.request(),url=new URL(request.url());
   if(url.origin!==origin||url.pathname.startsWith('/socket.io/')){await route.abort();return;}
   const headers={...request.headers(),authorization:'token '+token};
   if(!['GET','HEAD'].includes(request.method())){
    const fields=new URLSearchParams(request.postData()||'');
    const method=url.pathname.startsWith('/api/method/')?decodeURIComponent(url.pathname.slice(12)):fields.get('cmd');
    if(!reads.has(method)){blocked.add(url.pathname);await route.abort();return;}
    for(const [key,value] of fields)url.searchParams.append(key,value);
    delete headers['content-type'];delete headers['content-length'];
    await route.continue({url:url.href,method:'GET',postData:undefined,headers});return;
   }
   await route.continue({headers});
  });
  async function state(){
   const result={};
   for(const dt of ['Chantier Technical Study','Sales Order','Material Cutting Plan','Stock Entry','Workshop Operation']){
    const args=new URLSearchParams({fields:JSON.stringify(['name','modified','docstatus']),limit_page_length:'2000',order_by:'name'});
    const response=await context.request.get(base+'/api/resource/'+encodeURIComponent(dt)+'?'+args,
     {headers:{authorization:'token '+token}});
    if(!response.ok())throw new Error('Lecture de contrôle indisponible pour '+dt);
    const payload=await response.json();
    if(payload.data.length>=2000)throw new Error('Périmètre de contrôle trop grand : '+dt);
    result[dt]={count:payload.data.length,sha256:crypto.createHash('sha256').update(JSON.stringify(payload.data)).digest('hex')};
   }
   return result;
  }
  const before=await state();
  page=await context.newPage();page.setDefaultTimeout(25000);
  await page.goto(base+'/app/workshop-cockpit',{waitUntil:'domcontentloaded',timeout:60000});
  await page.locator('.ug-workshop').waitFor();
  await page.waitForFunction(()=>{const el=document.querySelector('.ug-graph-panel');return el&&el.getAttribute('aria-busy')==='false';},null,{timeout:60000});
  async function shot(file,selector,caption,unsaved=false){const filename=path.join(output,file+'.png');await page.waitForTimeout(350);if(selector&&['09-tableau-stock','10-stock-chutes'].includes(file)){const target=page.locator(selector).first();await target.scrollIntoViewIfNeeded();const box=await target.boundingBox();await page.screenshot({path:filename,clip:{x:box.x,y:Math.max(0,box.y),width:box.width,height:Math.min(box.height,file==='09-tableau-stock'?280:500)}});}else if(selector)await page.locator(selector).first().screenshot({path:filename});else await page.screenshot({path:filename,fullPage:false});manifest.screens.push({file:'images/'+file+'.png',source:page.url(),caption,unsaved,sha256:crypto.createHash('sha256').update(fs.readFileSync(filename)).digest('hex')});console.log('Capture '+file);}
  await shot('01-vue-ensemble',null,'Vue réelle du cockpit atelier sur le site de production.');
  await shot('02-filtres','.ug-filters','Filtres de fabrication et accès au rapport de stock.');
  await shot('03-indicateurs','.ug-cards','Indicateurs du cockpit au moment de la capture : aucune fabrication en attente.');
  await shot('04-navigation','.ug-panel-heading','Zoom initial de 65 %, développement et repli des branches.');
  await shot('05-legende','.ug-legend','Légende réelle des états de fabrication.');
  await page.getByRole('button',{name:/Vue liste/}).click();
  await page.waitForFunction(()=>document.querySelector('.ug-graph-panel')?.getAttribute('aria-busy')==='false');
  await shot('06-vue-liste','.ug-list-wrap','Colonnes réelles de la vue Liste ; aucun besoin en attente à cette date.');
  await page.getByRole('button',{name:'Imprimer le stock de plaques et chutes',exact:true}).click();
  await page.waitForURL('**/query-report/**');
  await page.waitForFunction(()=>window.frappe?.query_report?.report_name==='UG - Stock de Vitres'&&!!document.querySelector('.datatable'),null,{timeout:60000});
  await page.waitForTimeout(700);
  await shot('07-rapport-stock',null,'Rapport réel UG - Stock de Vitres ouvert depuis le bouton d’impression du cockpit.');
  await shot('08-filtres-stock','.page-form:visible','Filtres directement sur le rapport : plaques, chutes ou les deux, matière, société, dépôt et présentation.');
  await shot('09-tableau-stock','.datatable','Extrait des premières lignes du stock réel affiché en synthèse.');
  // Change only report filters; no stock operation is triggered.
  await page.evaluate(()=>frappe.query_report.set_filter_value('stock_type','Chutes'));
  await page.waitForTimeout(1800);
  await shot('10-stock-chutes','.layout-main-section:visible','Extrait du rapport réel filtré sur les chutes ; ce filtre ne modifie pas le stock.');
  await page.goto(base+'/app/material-cutting-plan/26MCP1000172',{waitUntil:'domcontentloaded'});
  await page.waitForFunction(()=>window.cur_frm?.doc?.name==='26MCP1000172');await page.waitForTimeout(1500);
  await shot('11-mcp-execute',null,'MCP existant 26MCP1000172 validé et exécuté ; aucune action de production lancée.');
  await shot('12-source-mcp','[data-fieldname="company"] >> xpath=ancestor::div[contains(@class,"form-section")][1]','Société, dépôt source, matière et état Executed du MCP existant.');
  await shot('13-commandes-mcp','[data-fieldname="selected_sales_orders"]','Commande affectée au MCP existant. Un plan peut regrouper plusieurs commandes de même matière.');
  await shot('14-pieces-planifiees','[data-fieldname="simulation_lines"]','Une pièce de 1 000 × 800 × 8 mm effectivement planifiée dans ce MCP.');
  await page.locator('.form-tabs .nav-link').filter({hasText:'Cutting Plan Preview'}).click();
  await page.locator('[data-fieldname="cutting_plan_preview"]:visible').waitFor();
  await page.waitForTimeout(800);
  await shot('15-plan-decoupe','[data-fieldname="cutting_plan_preview"]:visible','Aperçu réel du plan de découpe exécuté, consulté sans modification.');
  if(await page.locator('[data-fieldname="plan_summary"]:visible').count())await shot('16-resume-plan','[data-fieldname="plan_summary"]:visible','Résumé réel du plan exécuté : pièces, surfaces et chutes.');
  await page.goto(base+'/app/stock-entry/MAT-STE-2026-00180',{waitUntil:'domcontentloaded'});
  await page.waitForFunction(()=>window.cur_frm?.doc?.name==='MAT-STE-2026-00180');await page.waitForTimeout(900);
  await shot('17-repack-lie',null,'Repack réel validé MAT-STE-2026-00180 lié au MCP 26MCP1000172.');
  await shot('18-mouvements-repack','[data-fieldname="items"]:visible','Lignes réelles du mouvement de stock : matière consommée et sorties produites.');
  const after=await state();manifest.checks={before,after,unchanged:JSON.stringify(before)===JSON.stringify(after),business_operations_executed:0};manifest.blocked_requests=[...blocked];if(!manifest.checks.unchanged)throw Error('Documents modifiés pendant la capture');fs.writeFileSync(path.join(__dirname,'captures.json'),JSON.stringify(manifest,null,2));console.log(JSON.stringify({captures:manifest.screens.length,unchanged:manifest.checks.unchanged}));
 }catch(e){if(page)await page.screenshot({path:'/tmp/ug-atelier-guide-debug.png',fullPage:true}).catch(()=>{});throw e;}finally{await browser.close();}
})().catch(e=>{console.error(e.name+': '+e.message.slice(0,450));process.exit(1)});
