/* Actual production screens. Preparation only: execute_action is never allowed. */
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const {chromium}=require(process.env.UG_PLAYWRIGHT_MODULE||'/home/marsavco/frappe-bench/apps/crm/node_modules/playwright');
const cfg=JSON.parse(fs.readFileSync(process.env.UG_PRODUCTION_AUTH_FILE||'/tmp/ug-production-test/auth.json','utf8'));
const base=(cfg.base_url||cfg.url||'https://fimaci.f.frappe.cloud').replace(/\/$/,'');
const origin=new URL(base).origin,token=cfg.token||cfg.api_token||`${cfg.api_key}:${cfg.api_secret}`;
const api='mat_reco.material_reconfiguration.services.commercial_actions.';
const reads=new Set(['frappe.desk.desk_page.getpage','frappe.desk.form.load.getdoctype',
 'frappe.client.get','frappe.client.get_list','frappe.client.get_value','frappe.client.validate_link',
 'frappe.desk.search.search_link','frappe.desk.search.get_link_title',
 'frappe.desk.doctype.notification_log.notification_log.get_notification_logs']);
const output=path.join(__dirname,'images');fs.mkdirSync(output,{recursive:true});
const manifest={site:origin,captured_at:new Date().toISOString(),screens:[],checks:{}};
const blocked=new Set();let preparations=0;
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
    if(method===api+'prepare_action'){
     // Inspected server method: reads source, builds an unsaved document and rows.
     preparations++;await route.continue({headers});return;
    }
    if(!reads.has(method)){blocked.add(url.pathname);await route.abort();return;}
    for(const [key,value] of fields)url.searchParams.append(key,value);
    delete headers['content-type'];delete headers['content-length'];
    await route.continue({url:url.href,method:'GET',postData:undefined,headers});return;
   }
   if(url.pathname==='/api/method/'+api+'execute_action'){blocked.add(url.pathname);await route.abort();return;}
   await route.continue({headers});
  });
  async function state(){
   const result={};
   for(const dt of ['Chantier','Quotation','Sales Order','Bordereau Special','Reglement Special','Commercial Operation']){
    const args=new URLSearchParams({fields:JSON.stringify(['name','modified','docstatus']),limit_page_length:'500',order_by:'name'});
    const response=await context.request.get(base+'/api/resource/'+encodeURIComponent(dt)+'?'+args,
     {headers:{authorization:'token '+token}});
    if(!response.ok())throw new Error('Lecture de contrôle indisponible pour '+dt);
    const payload=await response.json();
    if(payload.data.length>=500)throw new Error('Périmètre de contrôle trop grand : '+dt);
    result[dt]={count:payload.data.length,sha256:crypto.createHash('sha256').update(JSON.stringify(payload.data)).digest('hex')};
   }
   return result;
  }
  const before=await state();
  page=await context.newPage();page.setDefaultTimeout(25000);
  await page.goto(base+'/app/commercial-cockpit',{waitUntil:'domcontentloaded',timeout:60000});
  await page.locator('.ug-commercial-cockpit').waitFor();
  async function settle(){
   await page.waitForFunction(()=>{
    const button=document.querySelector('button[aria-label="Rafraîchir les données"]');
    return button&&!button.disabled;
   },null,{timeout:45000});
   await page.waitForTimeout(400);
  }
  async function shot(file,selector,caption,unsaved=false){
   await page.waitForTimeout(300);const filename=path.join(output,file+'.png');
   if(selector)await page.locator(selector).first().screenshot({path:filename});
   else await page.screenshot({path:filename,fullPage:true});
   manifest.screens.push({file:'images/'+file+'.png',source:base+'/app/commercial-cockpit',caption,unsaved,
    sha256:crypto.createHash('sha256').update(fs.readFileSync(filename)).digest('hex')});
   console.log('Capture '+file);
  }
  async function client(name){
   await page.getByLabel('Client',{exact:true}).selectOption(name);await settle();
  }
  async function select(name){
   await page.getByRole('button',{name:'Sélectionner '+name,exact:true}).click();
   await page.locator('.ugc-details .ugc-action-loading').waitFor({state:'hidden'});
   await page.waitForTimeout(250);
  }
  async function action(label){
   await page.locator('.ugc-detail-actions').getByRole('button',{name:label,exact:true}).click();
   await page.locator('.ugc-action-modal[aria-busy="false"]').waitFor();
   if(await page.locator('.ugc-action-errors').count())throw new Error('Préparation refusée : '+await page.locator('.ugc-action-errors').innerText());
   await page.locator('.ugc-action-header h2').click();
  }
  async function close(){await page.getByRole('button',{name:'Fermer la fenêtre',exact:true}).click();}
  await settle();
  await shot('01-accueil',null,'Vue générale réelle du cockpit commercial.');
  await shot('02-filtres','.ugc-toolbar','Filtres, actualisation et impression.');
  await page.getByLabel('Période',{exact:true}).selectOption('all');await settle();
  await page.getByLabel('État des commandes',{exact:true}).selectOption('all');await settle();
  await client('CIA');
  await page.getByRole('button',{name:'Fermer les détails',exact:true}).click();
  await shot('03-clients','.ugc-clients','Liste réelle des clients et onglets Tous / À suivre.');
  await shot('04-parcours-client','.ug-commercial-cockpit','Parcours réel du client CIA avec commandes A et B.');
  await select('SAL-ORD-B-2026-00013');
  await shot('05-detail-commande-b','.ugc-details','Montants HT et suivi de livraison d’une commande B existante.');
  await select('SAL-ORD-2026-00049');
  await shot('06-detail-commande-a','.ugc-details','Montants TTC et suivi d’une commande A existante.');
  await page.getByRole('button',{name:'Liste',exact:true}).click();
  await shot('07-mode-liste','.ugc-list','Les mêmes documents dans l’affichage Liste.');
  await page.getByRole('button',{name:'Arbre',exact:true}).click();
  await client('AFRIBAT');await select('26CHANT1000078');await action('Créer un devis');
  await shot('08-preparer-devis','.ugc-action-modal','Fenêtre réelle de préparation d’un devis depuis un chantier validé.');
  await page.getByRole('button',{name:'Tout désélectionner',exact:true}).click();
  let first=page.locator('.ugc-action-table tbody tr').first();
  await first.locator('input[type="checkbox"]').first().check();
  const quantity=first.locator('.ugc-action-qty');
  const maximum=Number(await quantity.getAttribute('max'));
  await quantity.fill(String(maximum>1?Math.max(1,Math.floor(maximum/2)):maximum));
  await shot('09-selection-partielle','.ugc-action-line-section','Sélection partielle préparée dans la fenêtre, sans enregistrement.',true);
  await close();
  await client('CACI');await select('SAL-QTN-2026-00089');await action('Créer une commande');
  await page.locator('.ugc-action-modal [data-fieldname="order_type"] select').selectOption('B');
  await shot('10-preparer-commande','.ugc-action-modal','Choix du circuit B dans une préparation de commande non enregistrée.',true);
  await close();
  await client('WISSAM OBEID');await select('SAL-ORD-B-2026-00014');await action('Livrer');
  await shot('11-preparer-livraison','.ugc-action-modal','Choix des lignes, quantités et dépôt pour un bordereau spécial, sans validation.');
  await page.locator('.ugc-action-stock-row details').first().evaluate(node=>node.open=true);
  await shot('12-depot-series','.ugc-action-stock-row','Dépôt et séries d’une ligne : les séries doivent être disponibles pour livrer.');
  await close();
  await client('CIA');await select('SAL-ORD-B-2026-00013');await action('Enregistrer un règlement');
  await shot('13-preparer-reglement','.ugc-action-modal','Règlement et affectation aux bordereaux réellement disponibles de CIA.');
  await shot('14-affecter-reglement','.ugc-action-line-section','Table réelle d’affectation des montants aux bordereaux.');
  await close();
  await client('WISSAM OBEID');await select('SAL-ORD-B-2026-00014');await action('Enregistrer un règlement');
  await page.locator('.ugc-action-modal [data-fieldname="amount"] input').fill('10000');
  await page.locator('.ugc-action-modal [data-fieldname="reference"] input').fill('EXEMPLE NON ENREGISTRE');
  await page.locator('.ugc-action-header h2').click();
  await shot('15-avance','.ugc-action-modal','Exemple de saisie d’une avance sans BL disponible ; règlement non enregistré.',true);
  await close();
  await select('UG-BL-B-2026-00015');
  await shot('16-bordereau-brouillon','.ugc-details','Un bordereau existant en brouillon propose Modifier et Valider selon les droits.');
  await client('BORRO FRERES');await select('SAL-ORD-B-2026-00016');
  await shot('17-solde-zero','.ugc-details','Commande B réellement livrée et soldée HT, visible dans Tous les états.');
  await select('UG-REG-2026-00006');
  await shot('18-reglement-existant','.ugc-details','Règlement validé réel et documents associés.');
  await action('Affecter le règlement');
  await shot('19-reaffectation','.ugc-action-modal','Affectation d’un règlement validé : fenêtre ouverte sans modification enregistrée.');
  await close();
  await page.emulateMedia({media:'print'});
  await shot('20-impression','.ugc-print','Récapitulatif produit par le style d’impression réel du cockpit.');
  await page.emulateMedia({media:'screen'});
  const after=await state();
  manifest.checks={before,after,unchanged:JSON.stringify(before)===JSON.stringify(after),preparations,
   business_operations_executed:0,authentication_material_saved:false};
  manifest.blocked_requests=[...blocked];
  if(!manifest.checks.unchanged)throw new Error('Les documents ont changé pendant les captures ; contrôler les opérations concurrentes.');
  fs.writeFileSync(path.join(__dirname,'captures.json'),JSON.stringify(manifest,null,2)+'\n');
  console.log(JSON.stringify({captures:manifest.screens.length,unchanged:manifest.checks.unchanged,preparations}));
 }catch(error){
  console.log(JSON.stringify({blocked:[...blocked]}));
  if(page)await page.screenshot({path:'/tmp/ug-cockpit-guide-debug.png',fullPage:true}).catch(()=>{});
  throw error;
 }finally{await browser.close();}
})().catch(error=>{console.error(error.name+': '+error.message.slice(0,350));process.exit(1);});
