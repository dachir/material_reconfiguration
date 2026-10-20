# UG - Stock de Vitres

Rapport standard Script Report du module Material Reconfiguration.

- Point d’entrée : bouton **Imprimer** du cockpit ; ouvre le rapport sans transmettre les filtres du cockpit.
- Filtres du rapport : Plaques / Chutes / Les deux ; article primaire ; société ; dépôt ; synthèse / détail par série.
- Source partagée avec Stock de Vitres : inventaire physique permissionné, séries actives en dépôt, filiation primaire résolue, séries consommées exclues.
- Synthèse par matière, article stocké, classification, dimensions, retrait et dépôt. Détail : une ligne par série.
- Les surfaces des chutes en L déduisent l’évidement ; les surfaces invalides restent inconnues, jamais remplacées par le rectangle extérieur.
- Impression A4 paysage, filtres et date d’édition, totaux des quantités et surfaces connues.

## Déploiement

Publier l’application mat_reco puis exécuter `bench --site <site> migrate` et recharger le navigateur. Les fichiers du rapport standard et du bouton sont dans l’application ; aucune fixture Report n’est requise.

Une première version personnalisée inline a été créée sur fimaci.f.frappe.cloud avant le choix d’un rapport standard. Elle reste utilisable à `/app/query-report/UG%20-%20Stock%20de%20Vitres`. Le rapport standard conserve le même nom : la synchronisation lors du migrate remplace sa définition personnalisée sans changer son URL. Le bouton du cockpit exige le déploiement du fichier workshop_cockpit.js. Ce déploiement de fichiers n’a pas été exécuté depuis cette session.

## Vérifications du 18 octobre 2026

- 15 tests unitaires stock et rapport réussis.
- Rapport standard importé et exécuté sur le site local erpv15dev.marsavco.com.
- Version inline exécutée en production pour chaque type de stock, le détail par série, un dépôt et un article.
- Totaux rapprochés à l’API officielle Stock de Vitres : 3 087 plaques, 15 chutes, 23 624,3532 m² à l’instant du contrôle.
- Rendu du rapport et impression du tableau contrôlés dans Chromium.

Les JSON et sources inline de ce dossier conservent la trace de la création initiale. La définition à maintenir est désormais celle de `mat_reco/material_reconfiguration/report/ug___stock_de_vitres/`.
