from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'mat_reco/public/manuals/mat_reco-v0-2'
KIT=OUT/'MANUEL_GLOBAL_MAT_RECO'
GROUPS={'F':('Flux 1 · Fournisseur','01_FOURNISSEUR','#248767'),'C':('Flux 2 · Client','02_CLIENT','#7355aa'),'A':('Flux 3 · Atelier','03_ATELIER_MCP','#246fa9'),'S':('Flux 3 · Stock / Recomposition','04_REPACK_RECOMPOSITION','#248767'),'E':('Exceptions','05_EXCEPTIONS','#b94646')}
TITLES={
'F':['Identifier le besoin d’approvisionnement','Créer une commande fournisseur','Préparer la réception physique','Réceptionner avec Purchase Receipt','Réceptionner via Material Receipt Plan','Comprendre les deux circuits de réception','Contrôler les Serial No générés','Contrôler dimensions, épaisseur et qualité','Vérifier le dépôt et la disponibilité'],
'C':['Comprendre la demande client','Créer un devis','Saisir dimensions et quantités','Ajouter services et accessoires','Définir les articles DECOUPE et OUVRAGE','Transformer le devis en Sales Order','Transmettre les besoins à l’atelier','Suivre l’état de fabrication','Vérifier les produits finis disponibles','Préparer et soumettre Delivery Note','Contrôler les Serial No et les dimensions livrées','Créer Sales Invoice','Contrôler facture, quantités et références'],
'A':['Comprendre les besoins issus des commandes','Créer Material Cutting Plan','Charger les commandes client','Charger les matières disponibles','Qualifier les plaques','Paramétrer la découpe','Générer et lire le plan initial','Comprendre produits finis, chutes et déchets','Passer en Retour Terrain','Ouvrir Atelier UX 2.0','Sélectionner une pièce et utiliser le menu contextuel','Déplacer une pièce','Tourner une pièce à 90°','Redimensionner','Détruire une pièce cassée','Fusionner deux zones','Créer une Chute en L','Prévisualiser, confirmer et appliquer','Identifier les besoins manquants','Ouvrir la compensation','Réutiliser une chute du MCP','Utiliser une chute du stock','Ajouter une plaque entière','Calculer et valider la compensation','Gérer les casses successives','Contrôler le plan effectif','Réinitialiser en sécurité','Préparer la clôture et la soumission MCP'],
'S':['Comprendre le rôle du Repack','Créer Draft Repack depuis MCP','Contrôler les matières consommées','Contrôler les pièces produites','Contrôler les chutes générées','Comprendre les déchets','Contrôler les surfaces','Contrôler les coûts et valeurs','Soumettre Stock Entry Repack','Recomposition depuis une Sales Order','Contrôler les composants d’un OUVRAGE','Comprendre Material Reconfiguration historique','Suivre les nouveaux Serial No','Mettre les produits à disposition du Flux Client'],
'E':['Commande introuvable','Matière insuffisante','Dimensions incompatibles','Pièce cassée','Compensation impossible','Chute en L non exploitable','Conflit entre deux utilisateurs','Serial No indisponible','Repack refusé','Différence de surface ou de valeur','Annulation et réinitialisation','Document déjà soumis']}
INTRO=[('00','Bienvenue dans mat_reco : objectifs et fonctionnement'),('01','Carte globale des trois flux'),('02','Les documents ERPNext et leurs relations'),('03','Rôles et responsabilités'),('04','Comment lire les graphes, captures et repères visuels'),('05','Cas pratique fil rouge : de la commande à la facture')]
STAGES={'F':['Besoin','Commande','Réception','Séries','Stock'], 'C':['Demande','Devis','Commande','Atelier','Livraison','Facture'], 'A':['Besoins','Planification','Retour Terrain','Compensation','Plan effectif'], 'S':['Plan effectif','Repack découpe','Recomposition','Produits disponibles']}
SOURCE_MAP={
'F02':['erpnext/buying/doctype/purchase_order/purchase_order.js','erpnext/buying/doctype/purchase_order/purchase_order.json'],
'F04':['erpnext/stock/doctype/purchase_receipt/purchase_receipt.js','mat_reco/fixtures/server_script.json','mat_reco/fixtures/client_script.json'],
'F05':['mat_reco/material_reconfiguration/doctype/material_receipt_plan/material_receipt_plan.py'],
'C02':['erpnext/selling/doctype/quotation/quotation.js','mat_reco/fixtures/server_script.json'],
'C04':['mat_reco/fixtures/client_script.json'],
'C06':['erpnext/selling/doctype/quotation/quotation.js','erpnext/selling/doctype/sales_order/sales_order.js'],
'C10':['erpnext/selling/doctype/sales_order/sales_order.js','erpnext/stock/doctype/delivery_note/delivery_note.js'],
'C11':['mat_reco/public/js/dimension_from_serial.js','mat_reco/fixtures/client_script.json'],
'C12':['erpnext/stock/doctype/delivery_note/delivery_note.py','erpnext/accounts/doctype/sales_invoice/sales_invoice.js'],
'A':['mat_reco/material_reconfiguration/doctype/material_cutting_plan/material_cutting_plan.py','mat_reco/material_reconfiguration/doctype/material_cutting_plan/material_cutting_plan.js','frontend/mcp-ux20-vue/src/stores/cutting.js'],
'S':['mat_reco/material_reconfiguration/services/repack_draft_service.py','mat_reco/stock_hooks.py'],
'S10':['mat_reco/material_reconfiguration/services/repack_from_sales_order_service.py','mat_reco/public/js/stock_entry_repack_from_so.js'],
'S12':['mat_reco/material_reconfiguration/doctype/material_reconfiguration/material_reconfiguration.py']}
EXCEPTIONS={
'E01':('C07, A03','Matière source, hiérarchie d’article, commande et périmètre sélectionné.','Vérifier la Sales Order et recharger Select Orders for Source Item.','A03'),
'E02':('F01, A04, A19','Quantité physique et séries admissibles ; épaisseur et entrepôt.','Actualiser le stock ; qualifier une matière adaptée ou faire approvisionner.','F01 / A04'),
'E03':('C03, A12–A17','Les deux dimensions, l’épaisseur, l’espace utile et l’encoche.','Essayer la rotation autorisée ; sinon choisir une autre source, sans modifier la commande sans accord.','A13 / A22'),
'E04':('A15, A25','Pièce réellement cassée et identité de la commande.','Détruire, confirmer et appliquer ; relire les besoins et compenser.','A19'),
'E05':('A20–A24','Sources internes, chutes stock, plaques, avertissements et besoins restants.','Actualiser puis recalculer ; approvisionner si aucune matière compatible ne couvre le besoin.','A22 / F01'),
'E06':('A17, S05','Encoche supérieure gauche, contiguïté et matière retirée.','Choisir une autre zone libre ; ne pas compter le grand rectangle comme surface utile.','A12 / A17'),
'E07':('A18, A24, A27','Le message de conflit et la version courante du document.','Conserver la référence du travail ; recharger, vérifier l’état puis refaire l’action sur la nouvelle version.','A18 / A24'),
'E08':('F09, S03, C11','Entrepôt, état, mouvement soumis et bundle de la série.','Actualiser les séries ; choisir seulement une unité réellement disponible.','S03 / C09'),
'E09':('S02–S09','Doublons, entrées/sorties, quantités, limites MCP, bundles, valeur.','Corriger le contrôle signalé sur le brouillon ; ne pas soumettre un deuxième Repack pour les mêmes séries.','S03'),
'E10':('S07, S08','Unités mm / m², encoche, déchets, coûts d’entrée et arrondis.','Comparer tout le plan effectif au Repack ; faire contrôler la valorisation par le responsable stock.','S07'),
'E11':('A18, A24, A27','Portée exacte : action, proposition, historique ou plan entier.','Annuler localement pour abandonner ; Réinitialiser exige confirmation et absence de Repack soumis lié.','A27'),
'E12':('A28, S09','Statut du document et liens de stock déjà soumis.','Consulter sans modifier. Toute annulation / amendement relève du responsable et du circuit ERPNext approuvé.','03 / E11')}

def all_codes():
 return [f'{g}{i:02d}' for g in ['F','C','A','S'] for i in range(1,len(TITLES[g])+1)]
def title(code):return TITLES[code[0]][int(code[1:])-1]
