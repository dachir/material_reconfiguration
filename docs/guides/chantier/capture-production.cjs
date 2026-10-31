/* Real production screenshots. Authentication stays outside the repository.
 * Only navigation and explicit read APIs are permitted; no business POST runs.
 */
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const {chromium}=require(process.env.UG_PLAYWRIGHT_MODULE||'/home/marsavco/frappe-bench/apps/crm/node_modules/playwright');
const cfg=JSON.parse(fs.readFileSync(process.env.UG_PRODUCTION_AUTH_FILE||'/tmp/ug-production-test/auth.json','utf8'));
const base=(cfg.base_url||cfg.url||'https://fimaci.f.frappe.cloud').replace(/\/$/,'');
const origin=new URL(base).origin,token=cfg.token||cfg.api_token||`${cfg.api_key}:${cfg.api_secret}`;
const output=path.join(__dirname,'images');fs.mkdirSync(output,{recursive:true});
const readMethods=new Set([
 'mat_reco.material_reconfiguration.services.chantier_service.get_dossier',
 'mat_reco.material_reconfiguration.services.chantier_extras.catalogue',
 'mat_reco.material_reconfiguration.services.technical_study_service.designation_autocomplete',
 'frappe.client.get','frappe.client.get_list','frappe.client.validate_link',
 'frappe.desk.form.load.getdoctype','frappe.desk.desk_page.getpage',
 'frappe.desk.search.search_link','frappe.desk.search.get_link_title','frappe.desk.form.load.get_user_info_for_viewers',
 'frappe.desk.doctype.notification_log.notification_log.get_notification_logs'
]);
const manifest={site:origin,captured_at:new Date().toISOString(),screens:[],blocked_requests:[],checks:{}};
const blocked=new Set();
(async()=>{
 const browser=await chromium.launch({headless:true,args:['--no-sandbox']});
 let context;
 try{
  context=await browser.newContext({viewport:{width:1800,height:1100},deviceScaleFactor:1.5});
  await context.route('**/*',async route=>{
   const request=route.request(),url=new URL(request.url());
   if(url.origin!==origin){await route.abort();return;}
   if(url.pathname.startsWith('/socket.io/')){await route.abort();return;}
   const headers={...request.headers(),authorization:'token '+token};
   if(!['GET','HEAD'].includes(request.method())){
    const fields=new URLSearchParams(request.postData()||'');
    const method=url.pathname.startsWith('/api/method/')?decodeURIComponent(url.pathname.slice(12)):fields.get('cmd');
    if(!readMethods.has(method)){blocked.add(url.pathname);await route.abort();return;}
    for(const [key,value] of fields)url.searchParams.append(key,value);
    delete headers['content-type'];delete headers['content-length'];
    await route.continue({url:url.href,method:'GET',postData:undefined,headers});return;
   }
   await route.continue({headers});
  });
  async function documentState(){
   const response=await context.request.get(base+'/api/resource/Chantier/26CHANT1000080',
    {headers:{authorization:'token '+token}});
   if(!response.ok())throw new Error('Impossible de vérifier le brouillon source.');
   const {data}=await response.json();
   return {modified:data.modified,docstatus:data.docstatus,lines:data.lines.length,types:data.work_types.length,extras:data.commercial_extras.length};
  }
  const before=await documentState();
  async function chantier(name){
   console.log('Ouverture '+name);
   const page=await context.newPage();page.setDefaultTimeout(25000);
   await page.goto(base+'/app/chantiers/'+name,{waitUntil:'domcontentloaded',timeout:60000});
   await page.locator('.header-fields').waitFor();
   await page.waitForFunction(()=>[...document.querySelectorAll('.ug-chantiers header button')]
    .some(button=>button.title==='Recharger le chantier depuis le serveur'&&!button.disabled),null,{timeout:45000});
   await page.waitForTimeout(800);
   return page;
  }
  async function shot(page,file,selector=null,caption='',unsaved=false){
   await page.waitForTimeout(350);
   const filePath=path.join(output,file+'.png');
   if(selector)await page.locator(selector==='.modal.show'?'.modal.show .modal-dialog':selector).screenshot({path:filePath});
   else await page.screenshot({path:filePath,fullPage:true});
   manifest.screens.push({file:'images/'+file+'.png',source:new URL(page.url()).origin+new URL(page.url()).pathname,
    caption,unsaved,sha256:crypto.createHash('sha256').update(fs.readFileSync(filePath)).digest('hex')});
   console.log('Capture '+file);
  }
  const complex=await chantier('26CHANT1000087');
  await shot(complex,'01-vue-ensemble',null,'Chantier existant validé : vue générale.');
  await shot(complex,'02-types','.work-types-panel','Plusieurs types d’ouvrage dans un même chantier.');
  await shot(complex,'03-sections','.sections','Sections et nombres de lignes associés.');
  const sqm=await chantier('26CHANT1000085');
  await shot(sqm,'04-prix-m2','.macro','Dimensions en millimètres et unité de prix M2 sur un chantier existant.');
  const accessory=await chantier('26CHANT1000078');
  await accessory.getByRole('button',{name:'Prestations de OUV-002',exact:true}).click();
  await shot(accessory,'05-prestations-existantes','.macro','Prestation associée à une ligne existante, affichée avec le triangle.');
  await accessory.locator('summary[aria-label="Autres actions"]').click();
  await shot(accessory,'06-actions','.more-actions','Menu des actions du chantier validé.');
  await accessory.getByRole('button',{name:'Générer un devis',exact:true}).click();
  await accessory.locator('.modal.show').waitFor();
  if(await accessory.locator('.modal.show').count()){
   await shot(accessory,'07-generation-devis','.modal.show','Fenêtre réelle de génération du devis, sans exécuter la génération.');
   await accessory.locator('.modal.show .btn-modal-close').click();
  }
  const draft=await chantier('26CHANT1000080');
  await shot(draft,'08-entete','.header-fields','En-tête du brouillon existant : client, remises, devise et taxes.');
  await shot(draft,'08a-identification','.header-fields section:first-child','Client, nom du chantier, responsable et remise.');
  await shot(draft,'08b-conditions','.header-fields section:last-child','Devise, liste de prix, modèle de taxes et dates.');
  await draft.getByRole('button',{name:'+ Nouveau',exact:true}).click();
  await shot(draft,'09-nouveau-chantier','.modal.show','Formulaire réel de création ; aucun chantier n’a été enregistré.');
  await draft.locator('.modal.show .btn-modal-close').click();
  await draft.getByRole('button',{name:'+ Type',exact:true}).click();
  let modal=draft.locator('.modal.show');
  await modal.locator('[data-fieldname="designation"] input').fill('VITRE CLAIRE TREMPEE 10MM');
  await modal.locator('[data-fieldname="thickness_mm"] input').fill('10');
  await modal.locator('[data-fieldname="pricing_unit"] select').selectOption('M2');
  await shot(draft,'10-nouveau-type','.modal.show','Exemple de saisie dans le formulaire de production, non enregistré.',true);
  await modal.getByRole('button',{name:'Enregistrer',exact:true}).click();
  await draft.getByRole('button',{name:'+ Ajouter une ligne',exact:true}).click();
  let row=draft.locator('.macro tbody tr').first();
  await row.getByRole('spinbutton',{name:'length_mm',exact:true}).fill('1500');
  await row.getByRole('spinbutton',{name:'width_mm',exact:true}).fill('1000');
  await row.getByRole('spinbutton',{name:'Quantité',exact:true}).fill('2');
  await row.getByRole('spinbutton',{name:'Prix unitaire',exact:true}).fill('95000');
  await shot(draft,'11-saisie-ligne','.macro','Exemple réel de saisie non enregistrée : 2 pièces de 1 500 × 1 000 mm, prix M2.',true);
  await draft.getByRole('button',{name:'Services et accessoires du type VITRE CLAIRE TREMPEE 10MM',exact:true}).click();
  await draft.locator('.catalogue-item').first().waitFor();
  await draft.getByLabel('Type de complément',{exact:true}).selectOption('SERVICE');
  let catalogue=draft.locator('.catalogue-item').filter({hasText:/RABOTAGE/i}).first();
  if(!await catalogue.count())catalogue=draft.locator('.catalogue-item').first();
  await catalogue.locator('input[type="checkbox"]').first().check();
  const price=catalogue.locator('.item-settings input[type="number"]').last();
  if(await price.count())await price.fill('1500');
  await shot(draft,'12-prestations-type','.extras-panel','Catalogue réel et valeurs par défaut du type, dans une saisie non enregistrée.',true);
  await shot(draft,'12a-prestation-type','.catalogue-item.picked','Détail de la prestation commune sélectionnée ; saisie non enregistrée.',true);
  await draft.getByRole('button',{name:'Appliquer au type',exact:true}).click();
  await draft.getByRole('button',{name:'Prestations de OUV-001',exact:true}).click();
  await shot(draft,'13-heritage-type','.macro','Prestation héritée du type : calcul affiché sur la ligne, non enregistré.',true);
  await draft.getByRole('button',{name:'Affecter des services et accessoires',exact:true}).first().click();
  await draft.locator('.assigned-extras').waitFor();
  await shot(draft,'14-ajuster-prestation','.extras-panel','Quantité, prix, remise et montant ajustables pour la ligne ; aucune affectation envoyée.',true);
  await shot(draft,'14a-ajuster-prestation','.assigned-extras article:first-of-type','Détail des quantités, prix et remise d’une prestation de ligne ; saisie non enregistrée.',true);
  await draft.getByRole('button',{name:'Fermer les prestations',exact:true}).click();
  await draft.getByRole('button',{name:'Affecter une section',exact:true}).first().click();
  await shot(draft,'15-affecter-section','.sections','Sélecteur de section de la ligne en cours ; brouillon sans section.',true);
  await draft.getByRole('button',{name:'Terminer le choix de section',exact:true}).click();
  await draft.getByRole('button',{name:'+ Section',exact:true}).click();
  await shot(draft,'16-nouvelle-section','.modal.show','Formulaire réel de section, non soumis.');
  await draft.locator('.modal.show .btn-modal-close').click();
  const direct=await chantier('26CHANT1000080');
  await direct.getByRole('button',{name:'+ Ajouter une ligne',exact:true}).click();
  await shot(direct,'17-vente-directe','.modal.show','Formulaire de vente directe : plaque entière, accessoire ou service.');
  await direct.locator('.modal.show .btn-modal-close').click();
  manifest.blocked_requests=[...blocked];
  const after=await documentState();
  manifest.checks={source_draft:'26CHANT1000080',before,after,unchanged:JSON.stringify(before)===JSON.stringify(after),
   business_writes_executed:0,authentication_material_saved:false};
  if(!manifest.checks.unchanged)throw new Error('Le brouillon source a changé pendant la capture. Vérifier avant livraison.');
  fs.writeFileSync(path.join(__dirname,'captures.json'),JSON.stringify(manifest,null,2)+'\n');
  console.log(JSON.stringify({captures:manifest.screens.length,unchanged:manifest.checks.unchanged,blocked:manifest.blocked_requests}));
 }catch(error){
  console.log(JSON.stringify({blocked:[...blocked]}));
  if(context)for(const [index,page] of context.pages().entries()){
   console.log(JSON.stringify({page:index,path:new URL(page.url()).pathname,alerts:await page.locator('[role="alert"],.msgprint').allTextContents(),
    activeModals:await page.locator('.modal.show').count()}));
   await page.screenshot({path:'/tmp/ug-guide-debug-'+index+'.png',fullPage:true}).catch(()=>{});
  }
  throw error;
 }finally{await browser.close();}
})().catch(error=>{console.error(error.name+': '+error.message.slice(0,350));process.exit(1);});
