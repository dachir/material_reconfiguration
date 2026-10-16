from pathlib import Path
from html import escape
from blueprint import *
COLORS={'blue':('#eaf3ff','#246fa9'),'green':('#eaf7f0','#248767'),'orange':('#fff3d9','#c38a26'),'red':('#fff0ef','#b94646'),'violet':('#f1edfa','#7355aa'),'gray':('#eff3f7','#455b6d')}
class Graph:
 def __init__(self,w,h,title,subtitle):
  self.w,self.h=w,h;self.items=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}"><defs><marker id="arr" markerWidth="10" markerHeight="10" refX="8" refY="4" orient="auto"><path d="M0 0L8 4L0 8" fill="none" stroke="#5b7083" stroke-width="1.5"/></marker></defs><rect width="100%" height="100%" fill="white"/>'];self.text(w/2,42,[title],28,True);self.text(w/2,75,[subtitle],17)
 def text(self,x,y,lines,size=20,bold=False,color='#193b55'):
  if isinstance(lines,str):lines=[lines]
  self.items.append(f'<text text-anchor="middle" font-family="Arial,sans-serif" fill="{color}" font-weight="{700 if bold else 400}" font-size="{size}" x="{x}" y="{y}">'+''.join(f'<tspan x="{x}" dy="{0 if i==0 else size*1.3}">{escape(l)}</tspan>' for i,l in enumerate(lines))+'</text>')
 def frame(self,x,y,w,h,title,color):
  fill,stroke=COLORS[color];self.items.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="18" fill="{fill}" stroke="{stroke}" stroke-width="1"/>');self.text(x+w/2,y+32,[title],21,True,stroke)
 def box(self,x,y,w,h,lines,color='blue',diamond=False):
  fill,stroke=COLORS[color]
  if diamond:self.items.append(f'<path d="M{x+w/2} {y}L{x+w} {y+h/2}L{x+w/2} {y+h}L{x} {y+h/2}Z" fill="{fill}" stroke="{stroke}" stroke-width="2"/>')
  else:self.items.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="12" fill="{fill}" stroke="{stroke}" stroke-width="2"/>')
  size=min(20,(w-30)/max(map(len,lines))/.55);size=min(size,18) if diamond else size
  self.text(x+w/2,y+h/2-(len(lines)-1)*size*.65+size*.34,lines,size,True)
 def arrow(self,points,label=None,lx=0,ly=0,dashed=False):
  self.items.append('<polyline points="'+' '.join(f'{x},{y}' for x,y in points)+'" fill="none" stroke="#5b7083" stroke-width="2" marker-end="url(#arr)"'+(' stroke-dasharray="6 5"' if dashed else '')+'/>')
  if label:self.text(lx,ly,[label],16,True)
 def foot(self,lines):self.text(self.w/2,self.h-50,lines,16)
 def save(self,name,folder='06_FLOWCHARTS'):
  p=KIT/folder/(name+'.svg');p.parent.mkdir(parents=True,exist_ok=True);p.write_text('\n'.join(self.items)+ '</svg>')
# G01 — three converging flows, not three isolated chapters.
g=Graph(1540,1180,'G01 · Carte globale des trois flux','La matière vient du Fournisseur ; le besoin vient du Client ; l’Atelier les rapproche.')
g.frame(30,110,440,425,'FLUX 1 · FOURNISSEUR','green');g.frame(1070,110,440,960,'FLUX 2 · CLIENT','violet');g.frame(550,570,440,500,'FLUX 3 · ATELIER / STOCK','blue')
for x,y,w,h,lines,c in [(80,175,340,75,['Commande fournisseur','si le circuit achat le prévoit'],'green'),(80,295,340,75,['Réception et séries','Purchase Receipt ou Receipt Plan'],'green'),(80,415,340,75,['Matière contrôlée','Disponible dans le dépôt'],'green'),(1120,175,340,75,['Devis','Dimensions + services'],'violet'),(1120,295,340,75,['Commande client','Besoin confirmé'],'violet'),(1120,415,340,75,['Besoin dimensionné','Passage C07 → A01'],'violet'),(600,635,340,70,['MCP + Planification','Matière et commandes'],'blue'),(600,750,340,70,['Retour Terrain','Incidents + compensation'],'blue'),(600,865,340,70,['Repack de découpe','Pièces et chutes en stock'],'green'),(600,980,340,65,['Recomposition si nécessaire','Repack distinct pour l’ouvrage'],'green'),(1120,865,340,70,['Produits disponibles','Retour S14 → C08 / C09'],'green'),(1120,980,150,65,['Livraison'],'violet'),(1310,980,150,65,['Facture'],'violet')]:g.box(x,y,w,h,lines,c)
for x in [250,1290]:g.arrow([(x,250),(x,295)]);g.arrow([(x,370),(x,415)])
g.arrow([(420,452),(500,452),(500,670),(600,670)],'Matière',493,560);g.arrow([(1120,452),(1030,452),(1030,670),(940,670)],'Besoin',1031,560)
for y in [705,820,935]:g.arrow([(770,y),(770,y+45)])
g.arrow([(940,900),(1120,900)],'Pièces',1030,885);g.arrow([(940,1012),(1030,1012),(1030,925),(1120,925)],'Ouvrage',1024,999)
g.arrow([(1290,935),(1195,980)]);g.arrow([(1270,1012),(1310,1012)])
g.foot(['Parcours pédagogique : Commande → Atelier → Livraison → Facture. Variantes ERPNext à confirmer sur site.']);g.save('G01_carte_globale_3_flux','00_CARTE_GLOBALE')
# G02 — suppliers: alternate receipt routes, no duplicate stock receipt.
g=Graph(1240,1280,'G02 · Flux Fournisseur','F01 à F09 · Choisir le circuit avant de constater l’entrée de stock.')
g.box(430,130,380,75,['F01 · Besoin matière','Article, dimensions, quantité'],'blue');g.box(430,250,380,110,['Circuit d’approvisionnement ?'],'orange',True);g.arrow([(620,205),(620,250)])
g.box(90,420,430,80,['F02 · Purchase Order','Circuit fournisseur standard ERPNext'],'green');g.arrow([(430,305),(305,305),(305,420)],'Achat fournisseur',297,385)
g.box(90,555,430,80,['F03 / F04 · Purchase Receipt','Contrôle physique + séries / bundles'],'green');g.arrow([(305,500),(305,555)])
g.box(720,420,430,80,['F05 · Material Receipt Plan','Réception dimensionnée hors ce chemin PO'],'blue');g.arrow([(810,305),(935,305),(935,420)],'Autre circuit autorisé',938,385)
g.box(720,555,430,80,['Soumettre le Receipt Plan','Crée et soumet Material Receipt'],'green');g.arrow([(935,500),(935,555)])
g.box(425,740,390,90,['F07 / F08 · Contrôler les séries','Dimensions, épaisseur, qualité'],'orange');g.arrow([(305,635),(305,710),(620,710),(620,740)]);g.arrow([(935,635),(935,710),(620,710)])
g.box(425,895,390,90,['F09 · Dépôt et disponibilité','Matière admissible au MCP'],'green');g.arrow([(620,830),(620,895)])
g.box(425,1050,390,75,['Passage vers A04 / A05','Charger et qualifier la matière'],'blue');g.arrow([(620,985),(620,1050)])
g.foot(['F06 : ne pas recevoir deux fois les mêmes unités par les deux chemins.','Purchase Order n’est pas imposé par mat_reco à toute réception.']);g.save('G02_flux_fournisseur')
# G03 — client: join atelier, invoice alternatives shown but not prescribed.
g=Graph(1240,1420,'G03 · Flux Client','C01 à C13 · Le besoin part à l’atelier ; seuls les produits disponibles reviennent vers la livraison.')
seq=[(130,['C01 / C02 · Demande → Devis'],'violet'),(260,['C03 / C04 · Dimensions','Services et accessoires'],'blue'),(390,['C05 / C06 · Articles / composants','Commande client confirmée'],'violet'),(540,['C07 → A01 · Besoin dimensionné','Traiter dans le Flux 3'],'blue'),(740,['S14 → C08 / C09','Pièces / ouvrages disponibles'],'green'),(920,['C10 / C11 · Delivery Note','Séries et dimensions livrées'],'violet'),(1100,['C12 / C13 · Sales Invoice','Références, quantités, valeurs'],'violet')]
for y,lines,c in seq:g.box(390,y,460,85,lines,c)
for i in range(len(seq)-1):g.arrow([(620,seq[i][0]+85),(620,seq[i+1][0])])
g.box(35,540,280,110,['Atelier :','MCP → Repack découpe','→ Recomposition si requise'],'blue');g.arrow([(390,580),(315,580)]);g.arrow([(175,650),(175,780),(390,780)])
g.box(905,1075,290,135,['Autres chemins de facture','possibles dans ERPNext','À confirmer sur le site'],'orange');g.arrow([(850,432),(1050,432),(1050,1075)],dashed=True)
g.foot(['La séquence Livraison → Facture est le parcours pédagogique retenu, pas une obligation universelle.','Éviter de constater deux fois la même sortie avec Delivery Note et une facture Update Stock.']);g.save('G03_flux_client')
# G04 — detailed atelier sequence, actions grouped, 28 codes visible.
g=Graph(1440,1600,'G04 · Flux Atelier / MCP / Repack','A01 à A28, puis S01 à S14 · Le plan effectif conserve le lien aux besoins client.')
for y,lines,c in [(130,['A01–A06 · Préparer et charger','Besoins, commandes, matière, paramètres'],'blue'),(275,['A07 / A08 · Plan initial','Lire les pièces, chutes et déchets'],'blue'),(420,['A09–A11 · Retour Terrain / UX 2.0','Sélectionner et choisir une action'],'blue'),(610,['A18 · Confirmer puis appliquer','Enregistrer les incidents'],'blue'),(800,['A19 · Besoin non couvert ?'],'orange'),(990,['A26 · Plan effectif contrôlé','Pièces conformes + remplacements'],'green'),(1145,['A28 · Préparer la clôture MCP','Ordre de soumission à valider'],'orange'),(1300,['S01–S09 · Repack de découpe','Contrôler puis soumettre le stock'],'green'),(1450,['S10–S14 · Recomposition si requise','Retour au Flux Client : C08 / C09'],'green')]:g.box(460,y,520,90,lines,c,diamond=y==800)
for y1,y2 in [(220,275),(365,420),(510,610),(700,800),(890,990),(1080,1145),(1235,1300),(1390,1450)]:g.arrow([(720,y1),(720,y2)])
g.box(40,420,330,200,['A12 · Déplacer','A13 · Tourner à 90°','A14 · Redimensionner','A15 · Détruire','A16 · Fusionner','A17 · Chute en L'],'blue');g.arrow([(460,465),(370,465)]);g.arrow([(205,620),(205,655),(460,655)])
g.box(1080,765,320,175,['A20–A24 · Compenser','Chute MCP → chute stock','→ plaque entière','Calculer puis valider'],'blue');g.arrow([(980,845),(1080,845)],'Oui',1033,830);g.arrow([(1240,940),(1240,1035),(980,1035)])
g.text(745,943,['Non'],17,True)
g.box(40,840,330,115,['A25 · Casse successive','Nouvelle opération + bilan','Production soumise figée'],'red');g.arrow([(1080,875),(1030,875),(1030,720),(205,720),(205,840)],dashed=True)
g.box(40,1080,330,125,['A27 · Réinitialiser','Confirmation obligatoire','Plan initial restauré'],'orange');g.arrow([(460,1035),(405,1035),(405,1142),(370,1142)],dashed=True);g.arrow([(40,1142),(20,1142),(20,250),(460,250),(460,320)],dashed=True)
g.save('G04_flux_atelier_stock')
# G05 — button workflow + automatic priority cascade / remaining coverage.
g=Graph(1320,1370,'G05 · Compensation : du besoin au résultat','A19 à A25 · Rotation permise en Retour Terrain, indépendamment de la Planification.')
g.box(430,120,460,80,['Ouvrir Compenser','Lire les besoins et les sources'],'blue');g.box(430,250,460,80,['Choisir Automatique ou Manuel','Manuel : sources et justification'],'blue');g.arrow([(660,200),(660,250)])
g.box(430,380,460,80,['Cliquer Calculer','Début du calcul automatique'],'blue');g.arrow([(660,330),(660,380)])
for y,lines in [(545,['1 · Affecter les chutes du MCP']),(680,['2 · Chutes du stock pour le reste']),(815,['3 · Plaques entières pour le reste'])]:g.box(430,y,460,75,lines,'gray')
for a,b in [(460,545),(620,680),(755,815)]:g.arrow([(660,a),(660,b)])
g.box(430,955,460,90,['Contrôler la proposition','Pièces remplacées + besoins restants'],'orange');g.arrow([(660,890),(660,955)])
g.box(430,1130,460,80,['Valider la compensation','Sauvegarde confirmée → atelier'],'green');g.arrow([(660,1045),(660,1130)])
g.box(950,955,320,90,['Annuler la proposition','Retour sans application'],'gray');g.arrow([(890,1000),(950,1000)],dashed=True)
g.box(45,955,320,130,['Besoin restant non couvert','Actualiser / approvisionner','Ne pas forcer la clôture'],'red');g.arrow([(430,1000),(365,1000)]);g.arrow([(205,955),(205,420),(430,420)],'Recalculer',222,565,dashed=True)
g.foot(['Le calcul n’est pas une validation. Une compensation validée ne soumet ni le MCP ni un Repack.']);g.save('G05_compensation')
# G06 — documents, split stock movements and return to client.
g=Graph(1440,1180,'G06 · Relations MCP / Repack / Client','Deux Repack distincts peuvent se succéder : découper la matière, puis recomposer l’ouvrage.')
g.box(30,140,370,100,['Sales Order / ligne dimensionnée','Quantité et structure d’ouvrage'],'violet');g.box(1040,140,370,100,['Serial No matière / dépôt','Matière disponible'],'green')
g.box(500,330,440,105,['Material Cutting Plan','Plan initial → plan effectif'],'blue');g.arrow([(215,240),(215,380),(500,380)]);g.arrow([(1225,240),(1225,380),(940,380)])
g.box(500,530,440,105,['Stock Entry · Repack découpe','Entrées matière → pièces / chutes'],'green');g.arrow([(720,435),(720,530)])
g.box(500,730,440,105,['Stock Entry · Repack recomposition','Pièces disponibles → ouvrage'],'green');g.arrow([(720,635),(720,730)],'Si nécessaire',813,690)
g.box(500,930,440,105,['Delivery Note → Sales Invoice','Produits disponibles, séries et références'],'violet');g.arrow([(720,835),(720,930)])
g.arrow([(940,582),(1010,582),(1010,980),(940,980)],'Découpe livrée directement',1190,775)
g.box(30,730,370,115,['Material Reconfiguration','Circuit historique distinct','S12 · À confirmer avant usage'],'gray');g.arrow([(400,780),(500,780)],dashed=True)
g.foot(['Le nom du document Stock Entry ne rend pas les deux transformations équivalentes.','L’ordre de soumission MCP / Repack est une décision encore ouverte.']);g.save('G06_relations_documents')
# G07 — no deletion of submitted output, repeated breaks remain recorded.
g=Graph(1280,1380,'G07 · Décision en cas de casse','A15 / A19 / A24 / A25 · Déclarer, enregistrer, recontrôler, remplacer.')
for y,lines,c in [(130,['Pièce inutilisable / cassée ?'],'orange'),(300,['Oui · Détruire la pièce','Confirmer puis appliquer les incidents'],'red'),(490,['Relire le besoin client','Ne pas compter la pièce détruite'],'blue'),(675,['Besoin déjà couvert ?'],'orange'),(930,['Compenser le besoin restant','Calculer / contrôler / valider'],'blue'),(1130,['Contrôler le plan effectif','Puis traiter le Repack approprié'],'green')]:g.box(420,y,440,90,lines,c,diamond=y in [130,675])
for a,b in [(220,300),(390,490),(580,675),(765,930),(1020,1130)]:g.arrow([(640,a),(640,b)])
g.text(668,832,['Non'],17,True);g.arrow([(860,720),(940,720),(940,1175),(860,1175)],'Oui',968,703)
g.box(30,930,300,140,['Casse d’un remplacement','Créer un nouvel incident','Conserver l’historique'],'orange');g.arrow([(420,975),(330,975)],dashed=True);g.arrow([(180,930),(180,350),(420,350)],dashed=True)
g.box(930,300,300,140,['Déjà produit en Repack soumis ?','Production / consommation figées','Responsable stock à solliciter'],'red');g.arrow([(860,345),(930,345)],dashed=True)
g.foot(['Une casse successive n’est ni une deuxième demande client ni une suppression des événements antérieurs.']);g.save('G07_decision_casse')
# Navigation strip for each business chapter; current phase and code marked explicitly.
def stage_index(code):
 n=int(code[1:]);group=code[0]
 if group=='F':return 0 if n==1 else 1 if n==2 else 2 if n<=6 else 3 if n<=8 else 4
 if group=='C':return 0 if n==1 else 1 if n<=5 else 2 if n==6 else 3 if n<=9 else 4 if n<=11 else 5
 if group=='A':return 0 if n==1 else 1 if n<=8 else 2 if n<=18 else 3 if n<=25 else 4
 return 0 if n==1 else 1 if n<=9 else 2 if n<=12 else 3
for code in all_codes():
 stages=STAGES[code[0]];cur=stage_index(code);w=1440;h=160
 parts=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}"><rect width="100%" height="100%" fill="white"/>']
 step=(w-60)/len(stages)
 for i,label in enumerate(stages):
  x=30+i*step;fill='#246fa9' if i==cur else '#eff3f7';text='white' if i==cur else '#526375'
  parts.append(f'<rect x="{x}" y="34" width="{step-20}" height="62" rx="9" fill="{fill}"/><text text-anchor="middle" x="{x+(step-20)/2}" y="74" font-family="Arial" font-size="20" fill="{text}">{escape(label)}</text>')
  if i<len(stages)-1:parts.append(f'<path d="M{x+step-17} 65l9 0m-4-4l4 4l-4 4" stroke="#526375" fill="none" stroke-width="2"/>')
  if i==cur:parts.append(f'<text x="{x+(step-20)/2}" y="128" text-anchor="middle" font-family="Arial" font-size="19" font-weight="bold" fill="#246fa9">VOUS ÊTES ICI · {code}</text>')
 parts.append('</svg>');(KIT/'06_FLOWCHARTS'/f'position_{code}.svg').write_text(''.join(parts))
# Functional vector icons: reusable, not decorative photographs.
icons={'objectif':'<circle cx="32" cy="32" r="21"/><circle cx="32" cy="32" r="11"/><path d="M32 18v28M18 32h28"/>','pourquoi':'<path d="M23 21q0-13 14-10q14 4 0 16q-5 4-5 10"/><circle cx="32" cy="47" r="1.5"/>','entrees':'<path d="M10 35v17h44V35H40l-3 6H27l-3-6zM32 7v25m-7-8l7 8l7-8"/>','action':'<path d="M17 8v44l11-14l12 16l8-6l-12-15l16-4z"/>','controle':'<path d="M32 7L10 16v18q4 17 22 24q18-7 22-24V16zM21 31l8 8l15-18"/>','resultat':'<circle cx="32" cy="32" r="24"/><path d="M18 32l9 10l21-24"/>','suivante':'<path d="M8 32h45M37 15l17 17l-17 17"/>','attention':'<path d="M32 8L6 54h52zM32 24v15"/><circle cx="32" cy="46" r="1"/>','astuce':'<path d="M24 46h16m-16 7h16M22 42q-22-33 10-34q32 1 10 34z"/>','role':'<circle cx="32" cy="18" r="11"/><path d="M10 56q0-30 22-25q22-5 22 25z"/>','document':'<path d="M15 6h25l11 11v41H15zM40 6v13h11M23 29h20M23 38h20M23 47h13"/>','position':'<path d="M32 58q-38-40 0-52q38 12 0 52z"/><circle cx="32" cy="24" r="8"/>','blocage':'<path d="M20 5h24l15 15v24L44 59H20L5 44V20zM21 21l22 22M43 21L21 43"/>'}
for name,shape in icons.items():
 col='#c38a26' if name in ['attention','controle'] else '#248767' if name=='resultat' else '#7355aa' if name in ['role','document','position'] else '#b94646' if name=='blocage' else '#246fa9'
 svg=f'<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" viewBox="0 0 64 64"><g fill="none" stroke="{col}" stroke-width="3.4" stroke-linejoin="round" stroke-linecap="round">{shape}</g></svg>'
 (KIT/'07_ICONES'/(name+'.svg')).write_text(svg)
print('Phase 2 : 7 grands graphes, 64 repères de position et 13 icônes SVG.')
