# Points à valider

## V01 — Ordre MCP / Repack

État : Ne pas déclarer une procédure officielle avant contrôle sur le site.

Responsable : Responsable atelier + stock

Validation : Valider les cas brouillon, MCP soumis et Repack partiel / complet.

## V02 — Rôles et droits

État : Les DocTypes mat_reco livrent System Manager ; les rôles opérateur sont une proposition.

Responsable : Administrateur / responsable

Validation : Confirmer droits de lecture, écriture, soumission et annulation.

## V03 — Chemin fournisseur

État : Purchase Order n’est pas requis dans toutes les réceptions.

Responsable : Achats / stock

Validation : Définir quand utiliser PO → PR et quand utiliser Material Receipt Plan.

## V04 — Double réception

État : Les deux circuits ne doivent pas compter deux fois les mêmes unités.

Responsable : Stock

Validation : Valider l’identification du justificatif et des séries par circuit.

## V05 — Chemins de facturation

État : Livraison → Facture est un parcours pédagogique, pas une obligation universelle.

Responsable : Commercial / facturation

Validation : Valider les chemins directs depuis SO et les règles Update Stock.

## V06 — Activation des scripts et fixtures

État : Les scripts du dépôt ne prouvent pas leur activation sur le site.

Responsable : Administrateur

Validation : Vérifier scripts Quotation, Purchase Receipt, dimensions, bundles et impressions.

## V07 — Champs de dimensions

État : Les noms et le report d’épaisseur doivent être contrôlés dans les métadonnées du site.

Responsable : Administrateur / stock

Validation : Confirmer Purchase Receipt, Serial No et lignes commerciales.

## V08 — Dialogue Repack SO

État : Une version est dans le script public, une autre dans les Client Scripts.

Responsable : Administrateur

Validation : Choisir Create Repack ou Generate Repack et éviter les doublons.

## V09 — Reconfiguration historique

État : Material Reconfiguration conserve un cycle spécifique et des effets sur séries.

Responsable : Responsable atelier / stock

Validation : Confirmer si ce circuit reste utilisé ; tester soumission et annulation isolément.

## V10 — Material Production Plan

État : Le contrôleur actuel est vide ; aucun flux automatisé démontré.

Responsable : Responsable produit

Validation : Exclure, utiliser manuellement ou développer avant de former.

## V11 — Politique déchets

État : Add Waiste to stock change les sorties attendues.

Responsable : Responsable stock

Validation : Définir la règle et les articles / entrepôts associés.

## V12 — Qualité et contraintes physiques

État : L’optimisation ne certifie pas toutes les contraintes machine ou de matériau.

Responsable : Responsable atelier

Validation : Valider kerf réel, sens matière, qualité et admissibilité des variantes.

## V13 — Coûts et mouvements réels

État : Le manuel décrit le code, pas une recette complète de valorisation soumise.

Responsable : Stock / comptabilité

Validation : Tester réception, Repack, répartition, arrondis et annulations sur jeu de recette.

## V14 — Captures en session ERPNext

État : Aucune capture en session métier authentifiée n’est revendiquée.

Responsable : Référent documentaire

Validation : Remplacer les vues reconstituées et confirmer l’apparence des hôtes de dialogue.

## V15 — Traçabilité de bout en bout

État : Des liens existent ; leur complétude sur chaque série doit être contrôlée.

Responsable : Stock / expédition

Validation : Valider matière racine, série parent, MCP, Stock Entry, SO et bundle livré.

## V16 — Recette exceptions

État : L’historique doit rester cohérent après casse successive ou production partielle.

Responsable : Atelier / stock

Validation : Tester unités manquantes, seconde casse, stock épuisé, conflit et verrou soumis.