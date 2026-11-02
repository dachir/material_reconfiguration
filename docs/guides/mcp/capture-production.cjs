/* Captures réelles de production. Toutes les écritures métier sont bloquées. */
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const {chromium}=require(process.env.UG_PLAYWRIGHT_MODULE||'/home/marsavco/frappe-bench/apps/crm/node_modules/playwright');
const cfg=JSON.parse(fs.readFileSync(process.env.UG_PRODUCTION_AUTH_FILE||'/tmp/ug-production-test/auth.json','utf8'));
const base=(cfg.base_url||cfg.url||'https://fimaci.f.frappe.cloud').replace(/\/$/,'');
const origin=new URL(base).origin,token=cfg.token||cfg.api_token||`${cfg.api_key}:${cfg.api_secret}`;
const reads=new Set(['frappe.desk.desk_page.getpage','frappe.desk.form.load.getdoctype',
 'frappe.desk.form.load.getdoc','frappe.desk.query_report.run','frappe.desk.query_report.get_report_doc','frappe.desk.query_report.get_script','frappe.desk.query_report.get_report_settings','mat_reco.material_reconfiguration.api.get_stock_for_mcp','mat_reco.material_reconfiguration.api.get_item_variants_for_mcp','mat_reco.material_reconfiguration.api.get_orders_by_source_item','mat_reco.material_reconfiguration.services.mcp_action_preview.load_mcp_effective_plan','frappe.client.get','frappe.client.get_list','frappe.client.get_value','frappe.client.validate_link',
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
  const before=await state();page=await context.newPage();page.setDefaultTimeout(25000);
  async function shot(file,selector,caption,unsaved=false){const filename=path.join(output,file+'.png');await page.waitForTimeout(400);if(selector){const target=page.locator(selector).first();if(file.includes('candidats')){await target.scrollIntoViewIfNeeded();const box=await target.boundingBox();await page.screenshot({path:filename,clip:{x:box.x,y:Math.max(0,box.y),width:box.width,height:Math.min(box.height,300)}});}else await target.screenshot({path:filename});}else await page.screenshot({path:filename,fullPage:false});manifest.screens.push({file:'images/'+file+'.png',source:page.url(),caption,unsaved,sha256:crypto.createHash('sha256').update(fs.readFileSync(filename)).digest('hex')});console.log('Capture '+file);}
  async function load(name){await page.goto(base+'/app/material-cutting-plan/'+name,{waitUntil:'domcontentloaded',timeout:60000});await page.waitForFunction(n=>window.cur_frm?.doc?.name===n,name);await page.waitForTimeout(1000);}
  await load('26MCP1000172');
  await shot('01-mcp-execute',null,'MCP existant 26MCP1000172, validé et exécuté, consulté sans modification.');
  await shot('02-identification','[data-fieldname="company"]:visible >> xpath=ancestor::div[contains(@class,"form-section")][1]','Identification réelle : société, dépôt source, matière, état et mode Planification.');
  await shot('03-commandes','[data-fieldname="selected_sales_orders"]:visible','Commande rattachée au plan existant.');
  await shot('04-regles','[data-fieldname="kerf_mm"]:visible >> xpath=ancestor::div[contains(@class,"form-section")][1]','Règles enregistrées de coupe : trait, algorithme, rotation et remise des déchets en stock.');
  await shot('05-candidats-enregistres','[data-fieldname="mcp_stock_candidate"]:visible','Extrait de candidats conservés dans le MCP exécuté ; liste historique, pas disponibilité actuelle.');
  await shot('06-pieces','[data-fieldname="simulation_lines"]:visible','Pièce réellement planifiée : 1 000 × 800 × 8 mm.');
  await shot('07-indicateurs','[data-fieldname="requested_piece_count"]:visible >> xpath=ancestor::div[contains(@class,"form-section")][1]','Quantités et surfaces enregistrées du plan existant.');
  await page.locator('.form-tabs .nav-link').filter({hasText:'Cutting Plan Preview'}).click();
  await page.locator('[data-fieldname="cutting_plan_preview"]:visible').waitFor();await page.waitForTimeout(800);
  await shot('08-plan','[data-fieldname="cutting_plan_preview"]:visible','Plan de découpe réel, conservé après exécution.');
  await shot('09-resume','[data-fieldname="plan_summary"]:visible','Résumé réel des pièces, chutes et surfaces du MCP exécuté.');
  await page.getByRole('button',{name:'Interface',exact:true}).click();
  await page.getByText('UX 2.0',{exact:true}).click();
  await page.locator('.modal:visible .mcpv-app').waitFor({timeout:45000});await page.waitForTimeout(600);
  await shot('10-atelier-consultation','.modal:visible .modal-dialog','Atelier UX 2.0 réel sur un document exécuté : consultation verrouillée.');
  await shot('11-navigation-plaques','.modal:visible .mcpv-nav','Navigation entre plaques et zoom dans l’atelier réel.');
  await shot('12-statut-verrouille','.modal:visible .mcpv-footer','Statut du document soumis : modifications terminées.');
  await page.getByRole('button',{name:'Agrandir ou réduire l’éditeur',exact:true}).click();
  await shot('13-atelier-agrandi','.modal:visible .modal-dialog','Consultation du plan réel dans l’atelier agrandi.');
  await page.getByRole('button',{name:'Fermer l’atelier',exact:true}).click();
  await page.goto(base+'/app/stock-entry/MAT-STE-2026-00180',{waitUntil:'domcontentloaded'});await page.waitForFunction(()=>window.cur_frm?.doc?.name==='MAT-STE-2026-00180');await page.waitForTimeout(700);
  await shot('14-repack',null,'Repack validé existant MAT-STE-2026-00180 lié au MCP 26MCP1000172.');
  await shot('15-mouvements','[data-fieldname="items"]:visible','Mouvements réels du Repack : consommation et production.');
  await page.evaluate(()=>frappe.new_doc('Material Cutting Plan'));
  await page.waitForFunction(()=>window.cur_frm?.doctype==='Material Cutting Plan'&&cur_frm.is_new());await page.waitForTimeout(500);
  await shot('16-nouveau-plan',null,'Vrai formulaire de création en production, laissé non enregistré. Aucun numéro MCP créé.',true);
  await page.evaluate(async()=>{await cur_frm.set_value('company','Univers Glass');await cur_frm.set_value('source_warehouse','Stores - UG');await cur_frm.set_value('source_item','VC8MMC');await cur_frm.set_value('mcp_mode','Planification');});
  await page.waitForTimeout(1000);
  await shot('17-mode-planification','[data-fieldname="company"]:visible >> xpath=ancestor::div[contains(@class,"form-section")][1]','Exemple de saisie non enregistré : Planification, matière VC8MMC et dépôt Stores - UG.',true);
  await page.getByRole('button',{name:'Outils',exact:true}).click();
  await shot('18-outils','.custom-actions:visible','Menu Outils réel pour sélectionner les commandes et charger les candidats. Aucun document enregistré.',true);
  await page.getByText('Get Stock',{exact:true}).click();
  await page.waitForFunction(()=>window.cur_frm?.doc?.mcp_stock_candidate?.length>0);await page.waitForTimeout(500);
  await shot('19-candidats-planification','[data-fieldname="mcp_stock_candidate"]:visible','Candidats actuellement disponibles chargés en mémoire ; aucun enregistrement ni mouvement.',true);
  await page.evaluate(()=>cur_frm.set_value('mcp_mode','Retour Terrain'));await page.waitForTimeout(700);
  await shot('20-mode-retour-terrain','[data-fieldname="company"]:visible >> xpath=ancestor::div[contains(@class,"form-section")][1]','Repérage du mode Retour Terrain dans un formulaire non enregistré ; sans plan initial, cet exemple n’est pas prêt à être traité.',true);
  await shot('21-candidats-retour-terrain','[data-fieldname="mcp_stock_candidate"]:visible','Repérage des colonnes : en Retour Terrain, l’entrée active est distincte de la qualification en Planification. Formulaire non enregistré.',true);
  await page.locator('.form-tabs .nav-link').filter({hasText:'Cutting Plan Preview'}).click();await page.waitForTimeout(400);
  await shot('22-incidents','[data-fieldname="material_plan_incidents"]:visible','Table d’incidents rendue visible en Retour Terrain. Aucun incident créé ; formulaire non enregistré.',true);
  const after=await state();manifest.checks={before,after,unchanged:JSON.stringify(before)===JSON.stringify(after),business_operations_executed:0};manifest.blocked_requests=[...blocked];if(!manifest.checks.unchanged)throw Error('Documents modifiés pendant les captures');fs.writeFileSync(path.join(__dirname,'captures.json'),JSON.stringify(manifest,null,2));console.log(JSON.stringify({captures:manifest.screens.length,unchanged:manifest.checks.unchanged}));
 }catch(e){if(page)await page.screenshot({path:'/tmp/ug-mcp-guide-debug.png',fullPage:true}).catch(()=>{});throw e;}finally{await browser.close();}
})().catch(e=>{console.error(e.name+': '+e.message.slice(0,450));process.exit(1)});
