const fs=require('node:fs'),path=require('node:path');
const {chromium}=require(process.env.UG_PLAYWRIGHT_MODULE||'/home/marsavco/frappe-bench/apps/crm/node_modules/playwright');
const dir=__dirname;
const captures=JSON.parse(fs.readFileSync(path.join(dir,'captures.json'),'utf8'));
const esc=s=>String(s).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;');
const figure=(file,caption,extra='')=>`<figure class="${extra}"><a href="images/${file}.png" target="_blank"><img src="images/${file}.png" alt="${esc(caption)}"/></a><figcaption>${caption}</figcaption></figure>`;
const note=(title,text)=>`<aside class="note"><strong>${title}</strong><p>${text}</p></aside>`;
const steps=rows=>'<ol>'+rows.map(row=>'<li>'+row+'</li>').join('')+'</ol>';
const table=(heads,rows)=>'<table><thead><tr>'+heads.map(head=>'<th>'+head+'</th>').join('')+'</tr></thead><tbody>'+rows.map(row=>'<tr>'+row.map(value=>'<td>'+value+'</td>').join('')+'</tr>').join('')+'</tbody></table>';
const chapters=[
 ['Repérer les zones de travail',`
 <p>Le chantier décrit le besoin commercial du client : les produits attendus, leurs dimensions, les prix et les prestations. La fiche technique définit ensuite la fabrication des découpes et ouvrages à produire.</p>
 ${figure('02-types','Les bulles permettent de filtrer les lignes par type. « Tous » affiche toutes les lignes.')}
 <div class="split compact"><div>${table(['Zone','Utilisation'],[
 ['En-tête','Client, responsable, devise, remise, modèle de taxes et dates.'],
 ['Types','Désignation et épaisseur communes ; unité de prix et prestations par défaut.'],
 ['Sections','Organisation du chantier : bâtiment, étage, façade, pièce…'],
 ['Grille','Une ligne par dimension ou besoin à chiffrer.'],
 ['Triangle vert','Afficher la section et les prestations de la ligne.'],
 ['Menu •••','Validation, devis, duplication, impression et autres actions autorisées.']])}</div>
 ${figure('03-sections','Sections réelles d’un chantier de production.','narrow')}</div>
 ${note('Type et section sont différents','Un même type peut être utilisé dans plusieurs sections. Une section peut contenir plusieurs types. Choisissez la section pour localiser l’ouvrage, et le type pour décrire ce que vous vendez.')}`],
 ['Créer ou retrouver un chantier',`
 ${steps(['Ouvrir <b>Univers Glass → Chantiers</b>. L’adresse directe est <span class="url">https://fimaci.f.frappe.cloud/app/chantiers</span>.',
 'Pour reprendre un dossier, rechercher son numéro ou sa désignation dans le champ <b>Chantier</b>, puis choisir le résultat.',
 'Pour créer un dossier, cliquer sur <b>+ Nouveau</b>. Renseigner la désignation, la société et le client ; préciser le responsable et les dates utiles.',
 'Choisir le modèle de taxes si nécessaire, puis <b>Enregistrer</b>. Le numéro de chantier est attribué automatiquement.'])}
 ${figure('09-nouveau-chantier','Formulaire ouvert sur le site de production ; aucune création n’a été exécutée.')}
 ${note('Le brouillon est l’espace de préparation','Compléter et enregistrer le chantier avant sa validation. Les modifications non enregistrées restent dans l’écran courant et peuvent être perdues en changeant de page.')}`],
 ['Compléter les informations commerciales',`
 <div class="two-figures">${figure('08a-identification','Identification du chantier et remise par défaut.')}${figure('08b-conditions','Devise, liste de prix, modèle de taxes et échéances.')}</div>
 ${table(['Champ','À renseigner ou vérifier'],[
 ['Client et nom','Vérifier le client concerné et utiliser un nom de chantier facilement identifiable.'],
 ['Responsable','Indiquer la personne chargée du suivi du dossier.'],
 ['Devise et liste de prix','Contrôler la devise et la base tarifaire avant de saisir les prix.'],
 ['Modèle de taxes','Sélectionner le modèle correspondant à la société et au dossier. Il est repris lors de la préparation du devis.'],
 ['Dates','Renseigner le début prévu et la fin de fabrication prévue.']])}
 ${note('Le total affiché sur Chantier est HT','La grille affiche le total hors taxes après remise. Contrôler les taxes et le total final dans le devis avant de le valider ou de l’imprimer.')}`],
 ['Définir un type d’ouvrage',`
 <p>Pour les ouvrages à fabriquer, commencer par créer le type : une désignation commerciale compréhensible par le client, une épaisseur et une unité de prix par défaut.</p>
 ${steps(['Cliquer sur <b>+ Type</b>.',
 'Saisir ou rechercher la <b>Désignation commerciale</b>. Le champ propose des désignations existantes tout en permettant une saisie libre.',
 'Renseigner une <b>épaisseur positive en millimètres</b>, puis choisir <b>PC</b> ou <b>M2</b>.',
 'Cliquer sur <b>Enregistrer</b> dans la fenêtre : le type est ajouté à la saisie en cours. Enregistrer ensuite le chantier pour le conserver.'])}
 ${figure('10-nouveau-type','Formulaire réel de production avec un exemple de saisie non enregistré.')}
 <p>La bulle du type sert de filtre. Ses petits boutons permettent de <b>modifier</b> le type, d’ouvrir ses <b>services et accessoires</b> ou de le <b>supprimer</b>. Un type utilisé par des lignes doit être réaffecté avant de pouvoir être supprimé.</p>
 ${note('Une description proposée, puis ajustable','La désignation du type est proposée sur les nouvelles lignes. Vous pouvez ensuite adapter la description d’une ligne sans changer la désignation commune.')}`],
 ['Saisir les lignes et choisir PC ou M2',`
 ${steps(['Sélectionner la bulle du type à utiliser, puis cliquer sur <b>+ Ajouter une ligne</b>.',
 'Vérifier la description proposée. Saisir la <b>longueur</b> et la <b>hauteur</b> en millimètres ; l’épaisseur provient du type.',
 'Saisir la quantité de pièces, l’unité de prix et le prix unitaire.',
 'Ajouter les autres dimensions comme des lignes distinctes. Le bouton de duplication d’une ligne permet de reprendre une saisie proche.'])}
 ${figure('11-saisie-ligne','Exemple saisi dans le vrai écran de production, sans enregistrement.')}
 ${table(['Unité de prix','Calcul du montant HT avant remise'],[
 ['PC','Quantité de pièces × prix unitaire.'],
 ['M2','Quantité de pièces × (longueur en mm × hauteur en mm ÷ 1 000 000) × prix au m².']])}
 ${note('Exemple M2','2 pièces de 1 500 × 1 000 mm représentent 3 m². À 95 000 par m², le montant HT avant remise est de 285 000. L’unité choisie sur le type est un défaut ; vérifiez celle de chaque ligne.')}
 ${figure('04-prix-m2','Lignes existantes facturées au m² sur le chantier VILLA II.','short')}`],
 ['Appliquer les services et accessoires du type',`
 <div class="split drawer"><div>
 <p>Les prestations communes évitent de ressaisir les mêmes services et accessoires pour chaque dimension.</p>
 ${steps(['Sur la bulle du type, cliquer sur l’icône <b>Services et accessoires</b>.',
 'Dans le volet de droite, rechercher et cocher les prestations utiles.',
 'Renseigner le prix unitaire par défaut et, selon la prestation, la quantité par pièce ou le coefficient.',
 'Cliquer sur <b>Appliquer au type</b>. Le volet se ferme ; les lignes de ce type héritent de ces prestations.',
 'Vérifier le résultat sur les lignes, puis <b>Enregistrer</b> le chantier.'])}
 ${note('Les dimensions de chaque ligne comptent','Une prestation au périmètre est calculée sur le périmètre de chaque ouvrage ; une prestation à la surface utilise sa surface. Les lignes ne reprennent donc pas forcément la même quantité de prestation.')}
 <p>Survolez la bulle du type pour consulter ses prestations communes et leurs valeurs par défaut.</p>
 </div>${figure('12a-prestation-type','Détail réel d’une prestation commune. Exemple non enregistré. <a href="images/12-prestations-type.png">Voir le volet complet.</a>','narrow')}</div>`],
 ['Consulter et ajuster une prestation de ligne',`
 ${figure('05-prestations-existantes','Le triangle de la ligne affiche sa section et ses prestations existantes.','short')}
 <div class="split drawer"><div>
 ${steps(['Cliquer sur le <b>triangle vert</b> d’une ligne pour voir les prestations qui lui sont rattachées.',
 'Pour un ajout ou un ajustement, ouvrir l’icône <b>Services / Accessoires</b> de la ligne.',
 'Dans <b>Compléments de ces lignes</b>, ajuster la quantité, le prix, la remise ou le montant lorsque nécessaire.',
 'Pour ajouter une prestation, la cocher dans le catalogue puis cliquer sur <b>Affecter à cet ouvrage</b>. Pour plusieurs lignes cochées, utiliser <b>Affecter aux ouvrages sélectionnés</b>.',
 'Le volet se ferme après l’affectation. <b>Enregistrer</b> le chantier pour conserver les modifications.'])}
 <p>Une prestation héritée du type est indiquée comme telle. Ses quantités et prix peuvent être ajustés pour une ligne ; les autres lignes conservent leurs propres valeurs.</p>
 </div>${figure('14a-ajuster-prestation','Champs réels d’ajustement d’une ligne. Exemple non enregistré. <a href="images/14-ajuster-prestation.png">Voir le volet complet.</a>','narrow')}</div>`],
 ['Organiser le chantier avec des sections',`
 <p>Les sections structurent le chantier et son impression : bâtiment, étage, façade ou pièce. Elles restent disponibles pendant la préparation du chantier, même après l’ajout des types et des lignes.</p>
 ${steps(['Cliquer sur <b>+ Section</b>. Saisir son nom et, si nécessaire, choisir une section parente.',
 'Pour ranger une ligne, utiliser son bouton <b>Affecter une section</b>. Les sections apparaissent alors à gauche avec une case de choix pour la ligne en cours.',
 'Choisir la section souhaitée puis terminer le choix. Enregistrer le chantier.',
 'Cliquer sur une section pour filtrer la grille ; <b>Tout le chantier</b> retire ce filtre. Le bouton « permet de replier le volet.'])}
 ${figure('16-nouvelle-section','Fenêtre réelle de création d’une section ; elle n’a pas été soumise.')}
 ${note('Réutiliser une structure','Le menu Gestion des sections permet de récupérer une arborescence depuis un modèle ou un autre chantier. Cette récupération ajoute les sections ; elle ne copie pas les lignes d’ouvrage. Les actions disponibles dépendent de vos droits.')}`],
 ['Traiter une vente directe',`
 <p>Une plaque entière, un accessoire ou un service vendu seul ne nécessite pas de type d’ouvrage ni de fiche technique. Il s’agit d’une vente directe.</p>
 ${steps(['Cliquer sur <b>Tous</b>, à côté des bulles de types.',
 'Cliquer sur <b>+ Ajouter une ligne</b> : la fenêtre de vente directe s’ouvre.',
 'Choisir l’article existant, saisir la quantité et le prix, et adapter la description si nécessaire.',
 'Enregistrer la fenêtre, puis le chantier.'])}
 ${figure('17-vente-directe','Fenêtre de vente directe réellement ouverte en production, sans création de ligne persistée.')}
 ${note('Chantier et commande mixtes','Un même dossier peut contenir des ventes directes et des ouvrages à fabriquer. La fiche technique concerne les découpes et ouvrages ; les plaques entières, accessoires et services restent dans le circuit commercial direct.')}`],
 ['Gérer les remises',`
 ${figure('08a-identification','Choix du mode et de la valeur de remise sous le responsable.')}
 ${table(['Mode','Comportement attendu'],[
 ['Pourcentage','La remise par défaut est proposée sur les lignes et les prestations. Les montants des lignes sont calculés après cette remise.'],
 ['Exception sur une ligne','Saisir la remise propre à cette ligne, par exemple 0 % lorsqu’elle est exclue de la remise générale.'],
 ['Montant','La remise porte globalement sur le total. Les pourcentages de remise des lignes ne s’appliquent pas en plus.']])}
 ${steps(['Choisir le mode de remise dans l’en-tête et saisir sa valeur.',
 'Vérifier les exceptions dans la colonne <b>Remise (%)</b> des lignes et dans les prestations.',
 'Contrôler le <b>Total HT après remise</b>, puis enregistrer le chantier.',
 'Vérifier les remises et les taxes dans le devis et son impression.'])}
 ${note('Ne pas confondre prix et remise','Le prix unitaire est le prix avant la remise de ligne. Une remise globale en montant est retranchée du total ; ne la saisir pas une seconde fois dans les prix unitaires.')}`],
 ['Enregistrer et valider le chantier',`
 <div class="split actions"><div>
 ${steps(['Contrôler le client, les types, les descriptions et les sections.',
 'Vérifier toutes les dimensions, quantités, unités PC/M2, prix et prestations. Contrôler le modèle de taxes et les remises.',
 'Cliquer sur <b>Enregistrer</b>. Attendre la fin de l’enregistrement.',
 'Dans le menu <b>•••</b>, choisir <b>Valider le commercial</b>, puis confirmer. Cette action nécessite le droit de validation.',
 'Le chantier validé peut servir à préparer le devis. Sa grille n’est plus modifiable comme un brouillon.'])}
 ${note('Point de départ du cockpit commercial','Le cockpit commercial commence aux chantiers validés, pour tous ses utilisateurs. Les brouillons se préparent dans l’écran Chantier ; ils ne sont pas à traiter par le responsable commercial dans le cockpit.')}
 <p>Le statut métier <b>Préparation</b> peut encore être affiché sur un chantier validé. Ne le confondez pas avec le badge <b>Brouillon commercial</b> : vérifiez la disponibilité des actions et le caractère modifiable de la grille.</p>
 </div>${figure('06-actions','Menu réel d’un chantier validé. Les actions dépendent de son état et de vos droits.','narrow')}</div>`],
 ['Préparer le devis puis la commande',`
 ${steps(['Dans le chantier validé, cocher les lignes à inclure au devis.',
 'Ajuster les quantités à deviser si vous ne traitez qu’une partie du besoin. Les quantités déjà reprises dans un devis actif sont prises en compte.',
 'Dans <b>•••</b>, choisir <b>Générer un devis</b>. Choisir s’il faut également le valider, puis lancer la génération.',
 'Contrôler le devis : descriptions, sections, dimensions, unités, services et accessoires, remises et taxes.',
 'Après acceptation client, préparer la commande depuis le devis ou le cockpit commercial. Choisir le circuit A ou B si cette option est autorisée.'])}
 ${figure('07-generation-devis','Fenêtre de génération réellement ouverte sur le chantier AFRIBAT ; aucune génération n’a été lancée.')}
 ${note('La fiche technique vient après la commande','La validation de la commande déclenche la préparation technique et les tâches associées lorsqu’il y a des découpes ou ouvrages à fabriquer. Le chantier commercial n’exige pas la fiche technique pour être validé ou pour préparer le devis.')}
 <p>Dans le cockpit atelier, seules les lignes de fabrication dont la fiche technique est validée sont proposées. Une vente directe n’a pas à passer par cette préparation technique.</p>`],
 ['Dupliquer, actualiser ou amender',`
 ${table(['Action','Utilisation'],[
 ['Dupliquer le chantier','Créer un nouveau brouillon à partir d’un chantier existant, puis adapter le client, les dimensions, les prix et les prestations. La copie reste dans la vue Chantier.'],
 ['Actualiser','Recharger les données enregistrées sur le serveur. En présence de modifications locales, confirmer leur abandon uniquement si vous ne voulez pas les conserver.'],
 ['Annuler puis amender','Sur un chantier validé admissible, annuler le document puis préparer sa révision en brouillon.'],
 ['Amender','Depuis un chantier déjà annulé, créer son amendement si vos droits le permettent.'],
 ['Imprimer A4','Ouvrir l’impression du chantier. L’impression du devis se fait sur le devis, avec son format de devis.']])}
 ${note('Une annulation peut être interdite','Un chantier déjà utilisé dans un devis, une commande ou un plan de découpe ne peut pas être annulé par cette action. Le bouton peut être désactivé pour cette raison.')}
 <h3>Travail à plusieurs</h3><p>Les bulles d’utilisateurs indiquent les personnes présentes. Si un avertissement signale que le chantier a changé, vos saisies ne sont pas automatiquement écrasées. Vérifiez les changements avec les personnes concernées, puis utilisez <b>Actualiser</b> pour recharger la version du serveur.</p>
 <h3>Avant de quitter l’écran</h3><p>Vérifier qu’aucun message <b>Modifications non enregistrées</b> ne subsiste. Les changements faits dans les fenêtres de types ou dans le volet des prestations doivent aussi être enregistrés sur le chantier.</p>
 <h3>Si une action est absente</h3><p>Vérifier l’état du dossier, les modifications en attente et les droits du compte. Un chantier validé propose moins d’actions de saisie qu’un brouillon. Demander au responsable habilité de valider lorsque cette action n’est pas autorisée.</p>`]
];
const cover=`<section class="page cover" id="couverture"><div class="eyebrow">UNIVERS GLASS · GUIDE UTILISATEUR</div><h1>Utiliser<br/>l’écran Chantier</h1><p class="lead">Préparer les besoins du client, organiser les ouvrages et établir le devis.</p>
 <div class="edition">Édition du 31 octobre 2026 · Captures du site de production</div>
 ${figure('01-vue-ensemble','Écran réel de production — chantier VITRE TRIPLEX.')}
 <div class="flow"><span>Chantier validé</span><b>→</b><span>Devis</span><b>→</b><span>Commande validée</span><b>→</b><span>FT si fabrication</span></div>
 <p>Pour les agents qui préparent les chantiers et les responsables qui les contrôlent et les valident.</p>
 <p class="small">Les captures proviennent de <b>fimaci.f.frappe.cloud</b>. Les exemples de saisie ont été préparés dans l’écran de production sans enregistrement. Aucun chantier, devis, commande ou mouvement de stock n’a été créé pour ce guide.</p></section>`;
const nav='<nav><strong>Guide Chantier</strong><a href="#couverture">Accueil</a>'+chapters.map(([title],i)=>`<a href="#chapitre-${i+1}">${i+1}. ${title}</a>`).join('')+'</nav>';
const html=`<!doctype html><html lang="fr"><head><meta charset="utf-8"/><title>Guide d’utilisation du chantier — Univers Glass</title><meta name="viewport" content="width=device-width,initial-scale=1"/><style>
 *{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:#eaf0f4;color:#183046;font:15px/1.55 Arial,sans-serif}main{max-width:900px;margin:30px auto;padding:0 20px}.page{background:white;padding:42px 46px;margin:0 0 24px;box-shadow:0 3px 20px #142b3b12;border-radius:5px}.eyebrow{font-size:10px;letter-spacing:1.8px;font-weight:700;color:#1982a5;margin-bottom:16px}h1{font-size:52px;line-height:1.08;letter-spacing:-1.5px;margin:16px 0;color:#082c46}h2{font-size:28px;line-height:1.16;margin:0 0 18px;color:#082c46}h3{font-size:17px;margin:20px 0 6px}p{margin:0 0 13px}.lead{font-size:21px;line-height:1.4;max-width:580px}.edition{font-size:12px;color:#526c7f;margin:20px 0}.small,figcaption{font-size:10px;color:#526c7f}.small{margin-top:22px}figure{margin:17px 0}figure img{display:block;width:100%;height:auto;max-height:350px;object-fit:contain;object-position:top;border:1px solid #d4e0e8;background:#f8fbfd}figure a{display:block}figcaption{line-height:1.4;margin-top:6px}.short img{max-height:190px}.narrow img{max-height:620px}.note{padding:12px 16px;border-left:4px solid #2495b7;background:#eff8fb;margin:17px 0}.note strong{color:#0c526e}.note p{margin:5px 0 0;font-size:12px}.split{display:grid;grid-template-columns:1.45fr 1fr;gap:20px;align-items:start}.split.compact{grid-template-columns:2.2fr .8fr}.split.actions{grid-template-columns:1.5fr .8fr}.split.drawer{grid-template-columns:1.35fr .85fr}.split figure{margin:0}.split.drawer .narrow img{max-height:650px}.two-figures{display:grid;grid-template-columns:1fr 1fr;gap:16px}.two-figures figure{margin-top:4px}table{width:100%;border-collapse:collapse;font-size:12px;margin:14px 0}th{text-align:left;background:#eaf2f7;color:#123e59}th,td{padding:9px;border:1px solid #d8e3eb;vertical-align:top}td:first-child{font-weight:600;width:28%}ol{padding-left:22px;margin:13px 0}li{padding-left:3px;margin:0 0 9px}.url{font-size:11px;overflow-wrap:anywhere}.flow{display:flex;align-items:center;justify-content:space-between;gap:6px;margin:25px 0}.flow span{background:#edf6fb;color:#14516f;border:1px solid #cee3ed;padding:8px;font-size:11px;border-radius:4px}.flow b{color:#42a1be}nav{position:fixed;left:16px;top:24px;width:195px;font-size:12px}nav strong{display:block;color:#0c3b55;margin-bottom:12px}nav a{display:block;color:#35566a;text-decoration:none;margin-bottom:8px}nav a:hover{text-decoration:underline}@media(min-width:1250px){main{margin-left:230px}}@media(max-width:1249px){nav{position:static;width:auto;padding:20px;display:flex;flex-wrap:wrap;gap:8px}nav a{background:#fff;padding:6px;border-radius:4px}nav strong{width:100%}}@media(max-width:650px){main{padding:0 8px}.page{padding:24px 18px}.split,.two-figures{display:block}figure{margin:18px 0}.flow{flex-wrap:wrap}h1{font-size:38px}}
 @page{size:A4;margin:16mm 16mm 19mm}@media print{html{scroll-behavior:auto}body{background:white;width:178mm;font-size:10.5pt;line-height:1.48}nav{display:none}main{max-width:none;margin:0;padding:0}.page{padding:0;margin:0;border:0;border-radius:0;box-shadow:none;break-after:page;break-inside:avoid}.page:last-child{break-after:auto}.eyebrow{margin-bottom:12px}h2{font-size:25px;margin-bottom:14px}h1{font-size:50px}.lead{font-size:19px}figure{break-inside:avoid;margin:14px 0}figure img{max-height:300px}figure.short img{max-height:160px}.narrow img{max-height:580px}.split.drawer .narrow img{max-height:580px}.cover figure img{max-height:320px}.note{padding:10px 13px;margin:13px 0}.note p{font-size:10px}.two-figures{gap:12px}table{font-size:10px}th,td{padding:7px}li{margin-bottom:8px}figcaption{font-size:9px}.small{font-size:9px}.split{gap:16px}a{color:inherit;text-decoration:none}}
 @media print{#chapitre-2 figure img{max-height:500px}#chapitre-3 .two-figures{display:block}#chapitre-3 .two-figures img{max-height:200px}#chapitre-9 figure img{max-height:360px}}
 </style></head><body>${nav}<main>${cover}${chapters.map(([title,body],i)=>`<section class="page" id="chapitre-${i+1}"><div class="eyebrow">CHANTIER · ${String(i+1).padStart(2,'0')}</div><h2>${title}</h2>${body}</section>`).join('')}</main></body></html>`;
fs.writeFileSync(path.join(dir,'Guide-utilisation-Chantier.html'),html);
(async()=>{
 const browser=await chromium.launch({headless:true,args:['--no-sandbox']});
 try{
  const page=await browser.newPage({viewport:{width:1000,height:1300}});
  await page.goto('file://'+path.join(dir,'Guide-utilisation-Chantier.html'),{waitUntil:'load'});
  await page.emulateMedia({media:'print'});
  const issues=await page.evaluate(()=>({missingImages:[...document.images].filter(image=>!image.complete||!image.naturalWidth).map(image=>image.getAttribute('src')),
   pages:[...document.querySelectorAll('.page')].map((node,index)=>({index,title:node.querySelector('h1,h2').innerText,height:Math.ceil(node.getBoundingClientRect().height)}))}));
  if(issues.missingImages.length)throw new Error('Images manquantes : '+issues.missingImages.join(', '));
  await page.pdf({path:path.join(dir,'Guide-utilisation-Chantier.pdf'),format:'A4',printBackground:true,preferCSSPageSize:true,
   displayHeaderFooter:true,headerTemplate:'<div></div>',footerTemplate:'<div style="font:9px Arial;color:#506b7e;width:100%;padding:0 60px;display:flex;justify-content:space-between"><span>Univers Glass · Utilisation du chantier · 31/10/2026</span><span><span class="pageNumber"></span> / <span class="totalPages"></span></span></div>'});
  fs.writeFileSync(path.join(dir,'controle-mise-en-page.json'),JSON.stringify({captured_at:captures.captured_at,chapters:chapters.length,expected_pdf_pages:chapters.length+1,...issues},null,2)+'\n');
  console.log(JSON.stringify(issues));
 }finally{await browser.close();}
})().catch(error=>{console.error(error.message);process.exit(1);});
