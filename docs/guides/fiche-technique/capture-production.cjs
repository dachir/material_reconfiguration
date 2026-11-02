/* Captures réelles de production. Toutes les écritures métier sont bloquées. */
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const {chromium}=require(process.env.UG_PLAYWRIGHT_MODULE||'/home/marsavco/frappe-bench/apps/crm/node_modules/playwright');
const cfg=JSON.parse(fs.readFileSync(process.env.UG_PRODUCTION_AUTH_FILE||'/tmp/ug-production-test/auth.json','utf8'));
const base=(cfg.base_url||cfg.url||'https://fimaci.f.frappe.cloud').replace(/\/$/,'');
const origin=new URL(base).origin,token=cfg.token||cfg.api_token||`${cfg.api_key}:${cfg.api_secret}`;
const reads=new Set(['frappe.desk.desk_page.getpage','frappe.desk.form.load.getdoctype',
 'frappe.client.get','frappe.client.get_list','frappe.client.get_value','frappe.client.validate_link',
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
   for(const dt of ['Chantier Technical Study','Chantier','Sales Order','Item','Stock Entry']){
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
  const draft='eqt5ui8inr';
  await page.goto(base+'/app/technical-study/'+draft,{waitUntil:'domcontentloaded',timeout:60000});
  await page.locator('.ug-tech .work-entry').first().waitFor();
  await page.waitForTimeout(800);
  async function shot(file,selector,caption,unsaved=false){
   const filename=path.join(output,file+'.png');await page.waitForTimeout(300);
   if(selector)await page.locator(selector).first().screenshot({path:filename});else await page.screenshot({path:filename,fullPage:true});
   manifest.screens.push({file:'images/'+file+'.png',source:page.url(),caption,unsaved,sha256:crypto.createHash('sha256').update(fs.readFileSync(filename)).digest('hex')});console.log('Capture '+file);
  }
  await shot('01-vue-ensemble',null,'Fiche technique réelle en brouillon de la commande SAL-ORD-2026-00052.');
  await shot('02-commandes-actions','.ug-tech header','Sélecteur de fiche et actions disponibles sur un brouillon.');
  await shot('03-indicateurs','.ug-tech .cards','Indicateurs réels : types, pièces, nouveaux articles et éléments à compléter.');
  await shot('04-types','.ug-tech .works','Types de la commande et quantités de pièces liées.');
  await shot('05-definition-existante','.ug-tech .definition','Découpe existante avec sa matière primaire et contrôle d’épaisseur.');
  await shot('06-article-existant','.ug-tech .inspector','Un article existant conserve sa définition et ses champs protégés.');
  await page.locator('.node-select').nth(1).click();
  await shot('07-format-plaque','.ug-tech .inspector','Format nominal de la plaque primaire, distinct des dimensions à découper.');
  await page.locator('.node-select').first().click();
  await page.getByRole('button',{name:'Rechercher un Item existant',exact:true}).click();
  await page.locator('.modal:visible').waitFor();
  await shot('08-rechercher-article','.modal:visible .modal-dialog','Recherche d’un article existant du type sélectionné ; aucun choix enregistré.');
  await page.keyboard.press('Escape');
  await page.locator('.work-entry>input').nth(0).check();
  await page.locator('.work-entry>input').nth(2).check();
  await shot('09-selection-commune','.ug-tech .works','Deux types de 6 mm cochés pour une définition commune ; aucun enregistrement.',true);
  await shot('10-appliquer-definition','.batch-definition','Action de partage de la composition entre les types cochés.');
  await page.getByRole('button',{name:/Appliquer cette définition aux/}).click();
  await shot('11-definition-appliquee','.batch-notice','Confirmation locale : la composition a été recopiée sans enregistrement serveur.',true);
  // Reload discards the browser-only definition copy.
  await page.reload({waitUntil:'domcontentloaded'});await page.locator('.ug-tech .work-entry').first().waitFor();
  await page.locator('.work-entry>button').nth(1).click();
  await shot('12-nouvel-article','.ug-tech .inspector','Champs à compléter pour un nouvel article : code, désignation, unité, groupe et dépôt.');
  await page.getByRole('button',{name:/Ajouter un composant à/}).first().click();
  await page.locator('.modal:visible').waitFor();
  await shot('13-ajouter-composant','.modal:visible .modal-dialog','Fenêtre réelle d’ajout d’un ouvrage, d’une découpe ou d’un ESPACE.');
  const opts=await page.locator('.modal:visible [data-fieldname="kind"] option').evaluateAll(nodes=>nodes.map(n=>({value:n.value,label:n.textContent})));console.log(JSON.stringify(opts));await page.locator('.modal:visible [data-fieldname="kind"] select').selectOption(opts.find(o=>/ESPACE|AIR/i.test(o.value+' '+o.label)).value);
  await page.locator('.modal:visible [data-fieldname="air_thickness"] input').fill('2');
  await shot('14-espace','.modal:visible .modal-dialog','Exemple non soumis d’ESPACE de 2 mm : aucune matière stockée n’est consommée par ce composant.',true);
  await page.keyboard.press('Escape');
  await page.getByRole('button',{name:'Reprendre toute la composition',exact:true}).click();
  await page.locator('.modal:visible').waitFor();
  await shot('15-reprendre-composition','.modal:visible .modal-dialog','La reprise de composition demande confirmation ; cette confirmation n’a pas été donnée.');
  await page.keyboard.press('Escape');
  await page.goto(base+'/app/technical-study/1sqkkdug0f',{waitUntil:'domcontentloaded'});await page.locator('.ug-tech .work-entry').first().waitFor();
  await page.getByRole('button',{name:/Ajouter un composant à/}).first().click();await page.locator('.modal:visible').waitFor();
  await page.locator('.modal:visible [data-fieldname="kind"] select').selectOption('DECOUPE');
  await page.locator('.modal:visible [data-fieldname="item"] input').fill('DVC6MMC');
  await page.locator('.modal:visible [data-fieldname="qty"] input').fill('1');
  await page.locator('.modal:visible .modal-footer .btn-primary').click();
  await page.locator('.modal:visible').waitFor({state:'hidden'});
  await shot('16-epaisseur-incoherente','.thickness-check','Exemple local : une seule découpe de 6 mm ne correspond pas au type de 12 mm.',true);
  await page.locator('.ug-tech .inspector label').filter({hasText:'Quantité par parent'}).locator('input').fill('2');
  await shot('17-epaisseur-coherente','.ug-tech .definition','Exemple local : deux découpes de 6 mm donnent une épaisseur cohérente de 12 mm. Rien n’est enregistré.',true);
  await page.goto(base+'/app/technical-study/3pb5gpdipi',{waitUntil:'domcontentloaded'});await page.locator('.ug-tech .work-entry').first().waitFor();
  await shot('18-fiche-validee',null,'Fiche réellement validée : ouvrage de 16 mm composé de deux découpes de 8 mm.');
  await shot('19-composition-validee','.ug-tech .definition','Composition validée réelle ; la fiche est consultable sans modification.');
  await shot('20-actions-fiche-validee','.ug-tech header','Actions de consultation, impression, actualisation et annulation selon les droits.');
  const after=await state();manifest.checks={before,after,unchanged:JSON.stringify(before)===JSON.stringify(after),business_operations_executed:0};
  manifest.blocked_requests=[...blocked];
  if(!manifest.checks.unchanged)throw new Error('Des documents ont changé pendant la capture.');
  fs.writeFileSync(path.join(__dirname,'captures.json'),JSON.stringify(manifest,null,2));
  console.log(JSON.stringify({captures:manifest.screens.length,unchanged:manifest.checks.unchanged}));
 }catch(error){if(page)await page.screenshot({path:'/tmp/ug-ft-debug.png',fullPage:true}).catch(()=>{});throw error;}finally{await browser.close();}
})().catch(e=>{console.error(e.name+': '+e.message.slice(0,400));process.exit(1)});
