from pathlib import Path
from html import escape
ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'mat_reco/public/manuals/mat_reco-v0-1'
class Chart:
 def __init__(self,w,h,title,subtitle):
  self.w,self.h=w,h;self.parts=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}"><defs><marker id="arrow" markerWidth="10" markerHeight="10" refX="8" refY="4" orient="auto"><path d="M0 0L8 4L0 8" fill="none" stroke="#496883" stroke-width="2"/></marker></defs><rect width="100%" height="100%" fill="#fff"/>'];self.text(w/2,38,[title],25,bold=True);self.text(w/2,70,[subtitle],16)
 def text(self,x,y,lines,size=18,bold=False,color='#15364f'):
  lines=[lines] if isinstance(lines,str) else lines
  self.parts.append(f'<text x="{x}" y="{y}" font-family="Arial,sans-serif" font-size="{size}" font-weight="{700 if bold else 400}" fill="{color}" text-anchor="middle">'+''.join(f'<tspan x="{x}" dy="{0 if i==0 else size*1.32}">{escape(l)}</tspan>' for i,l in enumerate(lines))+'</text>')
 def box(self,x,y,w,h,lines,kind='atelier'):
  colors={'atelier':('#eaf3ff','#2c78c6'),'stock':('#eaf7f0','#3b9470'),'decision':('#fff4d9','#c79830'),'danger':('#fff0ef','#c96c61'),'note':('#fff4d9','#c79830')};fill,stroke=colors[kind]
  if kind=='decision':self.parts.append(f'<path d="M{x+w/2},{y} L{x+w},{y+h/2} L{x+w/2},{y+h} L{x},{y+h/2}Z" fill="{fill}" stroke="{stroke}" stroke-width="2"/>')
  else:self.parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="12" fill="{fill}" stroke="{stroke}" stroke-width="2"/>')
  self.text(x+w/2,y+h/2-(len(lines)-1)*12+6,lines,18,bold=True)
 def arrow(self,points,label=None,lx=None,ly=None,dashed=False):
  self.parts.append('<polyline points="'+' '.join(f'{x},{y}' for x,y in points)+'" fill="none" stroke="#496883" stroke-width="2.1" marker-end="url(#arrow)"'+(' stroke-dasharray="6 5"' if dashed else '')+'/>')
  if label:self.text(lx,ly,[label],16,bold=True)
 def save(self,name):
  self.parts.append('</svg>');(OUT/(name+'.svg')).write_text('\n'.join(self.parts))
c=Chart(1040,1360,'Circuit mat_reco · proposition à valider','Opérateurs atelier et responsables de stock — version 0.1 / 14 octobre 2026')
c.box(365,115,350,70,['Devis / commande client','Dimensions et quantité'])
c.box(30,115,275,70,['Recevoir la matière','Receipt Plan ou','Purchase Receipt'],'stock')
c.box(30,230,275,75,['Stock disponible contrôlé','Séries, dimensions, lieu'],'stock');c.arrow([(167,185),(167,230)])
c.box(365,230,350,75,['Planification MCP','Commandes + matière qualifiée']);c.arrow([(540,185),(540,230)]);c.arrow([(305,268),(365,268)])
c.box(365,350,350,75,['Découpe / Retour Terrain','Saisir les incidents constatés']);c.arrow([(540,305),(540,350)])
c.box(385,465,310,120,['Besoin non couvert','ou pièce cassée ?'],'decision');c.arrow([(540,425),(540,465)])
c.box(30,465,285,115,['Compenser','Calculer puis valider','Rotation à 90° autorisée']);c.arrow([(385,525),(315,525)],'Oui',350,508)
c.arrow([(167,465),(167,445),(760,445),(760,525),(695,525)],'Recontrôler la couverture',450,438)
c.box(365,635,350,75,['Plan effectif enregistré','Pièces requises couvertes']);c.arrow([(540,585),(540,635)],'Non',570,614)
c.box(365,750,350,75,['Créer le brouillon Repack','Depuis le MCP']);c.arrow([(540,710),(540,750)])
c.box(365,865,350,75,['Contrôler les entrées / sorties','Séries, quantités, dimensions'],'stock');c.arrow([(540,825),(540,865)])
c.box(365,980,350,75,['Soumettre le Repack','Mouvement réel de stock'],'stock');c.arrow([(540,940),(540,980)])
c.box(365,1095,350,75,['Tracer les séries produites','Livraison / facture si applicable'],'stock');c.arrow([(540,1055),(540,1095)])
c.box(775,635,235,120,['Soumission du MCP :','circuit interne','à valider'],'note');c.arrow([(715,672),(775,672)],dashed=True)
c.box(30,635,285,120,['Réinitialiser + confirmer','Supprime les incidents','Restaure la Planification'],'danger');c.arrow([(365,672),(315,672)],dashed=True);c.arrow([(30,710),(15,710),(15,320),(365,320),(365,268)],dashed=True)
c.text(520,1230,['Bleu : préparation / atelier    Vert : stock    Jaune : décision / validation'],17)
c.text(520,1270,['Réinitialisation bloquée après un Repack soumis lié aux découpes.'],16)
c.text(520,1300,['Le flux représente le parcours métier proposé ; il ne vaut pas validation de procédure.'],15)
c.save('Flowchart-mat_reco-v0-1')
c=Chart(1040,1190,'Compensation des découpes · décisions','Après les incidents du Retour Terrain, avant finalisation du MCP')
c.box(355,115,330,75,['Ouvrir Compenser','Lire les besoins à remplacer']);c.box(380,235,280,110,['Chute interne','compatible ?'],'decision');c.arrow([(520,190),(520,235)])
c.box(65,253,265,75,['Chute du MCP','Priorité automatique 1']);c.arrow([(380,290),(330,290)],'Oui',355,275)
c.box(380,405,280,110,['Chute du stock','compatible ?'],'decision');c.arrow([(520,345),(520,405)],'Non',550,382)
c.box(65,423,265,75,['Chute du stock','Priorité automatique 2']);c.arrow([(380,460),(330,460)],'Oui',355,445)
c.box(380,575,280,110,['Plaque entière','compatible ?'],'decision');c.arrow([(520,515),(520,575)],'Non',550,552)
c.box(65,593,265,75,['Plaque entière','Priorité automatique 3']);c.arrow([(380,630),(330,630)],'Oui',355,615)
c.box(710,593,270,75,['Besoin restant :','Actualiser le stock','ou approvisionner'],'danger');c.arrow([(660,630),(710,630)],'Non',685,615)
for y in [290,460,630]:c.arrow([(65,y),(35,y),(35,752),(355,752)])
c.box(355,715,330,75,['Calculer la proposition','Contrôler matière et couverture']);c.box(355,850,330,75,['Valider la compensation','Confirmation serveur']);c.arrow([(520,790),(520,850)])
c.box(735,715,270,75,['Annuler la proposition','Sans application']);c.arrow([(685,752),(735,752)],dashed=True)
c.box(735,850,270,75,['Retour à l’atelier','Plan précédent']);c.arrow([(870,790),(870,850)])
c.box(355,985,330,75,['Retour à l’atelier','Plan effectif enregistré']);c.arrow([(520,925),(520,985)])
c.text(520,1110,['La rotation à 90° est toujours permise en Retour Terrain, même sans la case de Planification.'],16)
c.text(520,1144,['En mode Manuel : choisir les sources ; justifier un contournement des priorités.'],16)
c.save('Flowchart-compensation-v0-1')
print('Generated two editable SVG flowcharts.')
