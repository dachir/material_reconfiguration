# Stock verre — Volumes & Chutes

Route Desk : `/app/glass-stock`. Page enregistrée sur `erpv15dev.marsavco.com`.
Référence : `../../docs/UG_Stock_Volumes_Chutes_Codex.zip` et sa maquette validée.
Page en lecture seule, sans sidebar, avec les ressources locales de l’archive.

## Construction et installation

Depuis la racine du bench :

```sh
npm --prefix apps/mat_reco/frontend/workshop-vue ci
npm --prefix apps/mat_reco/frontend/glass-stock run build
bench --site <site> migrate
bench --site <site> clear-cache
```

La construction utilise Vue et Vite déjà employés par le frontend atelier. Le bundle IIFE et sa CSS sont livrés dans `mat_reco/public/js/glass_stock_dist`. Le décor est dans `mat_reco/public/images/glass_stock`. Aucune migration de données ni nouveau champ. Le déploiement sur un autre site doit suivre la procédure habituelle de ce site ; seul le site dev a été synchronisé ici. Recharger les processus applicatifs selon la procédure habituelle pour la prise en compte des hooks Python.

## Données et règles

API : `mat_reco.material_reconfiguration.services.glass_stock` :
`get_stock_overview`, `get_stock_serials`, `get_warehouses`.

Le stock courant vient des `Serial No` Active ayant un warehouse courant, que la version installée d’ERPNext maintient à partir des mouvements soumis via `SerialBatchBundle`. Les séries consommées sont exclues, aucun plan ou mouvement draft n’est compté. Une série est dédupliquée par son identifiant.

La filiation suit exclusivement `Item.custom_parent_item` jusqu’au primaire le plus ancien accessible. Les articles PRIMAIRE et DECOUPE sont concernés ; les ouvrages et accessoires sont exclus. Un PRIMAIRE Full compte comme volume ; Partial ou un article DECOUPE, même Full, comme chute. Les cycles, liens manquants et statuts inconnus produisent un diagnostic ; aucune déduction par le nom. Corriger les liens dans les fiches article concernées après vérification métier, sans migration automatique. Les variantes primaires liées au même primaire racine partagent donc une famille.

Dimensions : champs `custom_dimension_*_mm` de Serial No. L’épaisseur absente apparaît `—`. Surface : `single_geometry.single_area`, rectangle moins découpe enregistrée dans `custom_removed_length_mm/custom_removed_width_mm`. Une géométrie invalide donne une surface inconnue, jamais le rectangle englobant. Les pièces restent comptées ; le diagnostic avertit que la surface totale est partielle. La somme utilise les valeurs non arrondies.

L’indicateur est volontairement nommé **Surface en stock** : stock physique, réservations non déduites. `surface_basis=physical`, `reserved_m2` et `available_m2` sont null ; aucun engagement sur le stock libre. Aucun chiffre de maquette n’est livré dans le produit.

## Accès et actualisation

Rôles de page : Stock User, Stock Manager, System Manager. Chaque API exige aussi la lecture de Item, Serial No, Warehouse et Stock Ledger Entry. Les requêtes `frappe.get_list` conservent les règles et User Permissions ; les entrepôts autorisés sont recoupés avec les séries et les articles autorisés. Un warehouse explicitement non autorisé est refusé. Pas de cache partagé entre utilisateurs.

L’insertion d’un Stock Ledger Entry publie `glass_stock_updated` après commit, sans données de stock dans le message. La page réinterroge les API après anti-rebond de 350 ms ; elle écoute aussi `workshop_updated`. Secours toutes les 60 secondes, bouton manuel et indication de connexion réelle. Écouteurs et minuteurs sont retirés lorsque la page est masquée. Les réponses obsolètes après changement de filtre sont ignorées.

Les familles sont chargées au récapitulatif. Les enfants sont chargés à l’expansion, par pages de 100 (maximum API 200), curseur lexical stable sur Serial No. Une fenêtre visible et une marge de 180 px limitent les lignes DOM, même après plusieurs pages. Le tableau défile horizontalement sur écran étroit. La pagination reflète le stock courant, pas un instantané immuable : un mouvement entre deux appels peut modifier le total ; actualiser resynchronise l’ensemble.

## Vérifications du 16 octobre 2026

```sh
env/bin/python -m unittest mat_reco.material_reconfiguration.tests.test_glass_stock -v
```

- 10 tests : déduplication, filiation, classification DECOUPE Full, Warehouse, recherche série, L, dimensions invalides/manquantes, somme non arrondie, pagination, contrôles de permissions, notification après commit et 10 000 séries simulées.
- Site dev, lecture seule : 135 volumes, 91 chutes, 226 pièces, 1 112,814716 m² et six familles lors de la vérification. Aucun diagnostic de géométrie/filiation pour ce périmètre ; chiffres variables avec les mouvements futurs.
- Échantillon de 13 séries confronté aux soldes des Serial and Batch Bundle soumis et non annulés : chaque solde est 1 dans le warehouse affiché. Invariants de totaux contrôlés pour les entrepôts occupés, refus effectif de Guest vérifié. Ce contrôle n’est pas un scénario de mutations couvrant à lui seul tous les transferts, annulations et recompositions.
- Récapitulatif réel mesuré à 1,65 s sur ce site. Objectif indicatif : moins de 2 s pour le calcul pur de 10 000 séries ; suite entière mesurée à environ 0,1 s. Pas de mesure SQL de bout en bout à 10 000 séries sur ce site : l’API lit l’ensemble autorisé et agrège en Python ; mesurer sur la volumétrie cible avant de garantir un SLA.
- Chromium : capture desktop du site réel, puis banc isolé de 10 000 séries synthétiques pour les filtres, recherche et rendu mobile. 22 lignes enfants DOM sur la fenêtre desktop ; aucune erreur JavaScript. Les captures isolées sont uniquement des données de test, hors produit.
- La poursuite du test navigateur authentifié a été empêchée par le contrôle automatique : création d’une session Administrator sans connexion normale refusée. Restent à vérifier avec une session autorisée : filtres de bout en bout dans le navigateur et réception Socket.IO après mouvement réel. Le rendu initial du site réel utilisait le secours périodique (Socket.IO déconnecté dans le navigateur de test).

Captures : `../../docs/glass_stock/desktop-site-dev.png`, `mobile-isolated.png`, `desktop-isolated.png`. Comparaison visuelle : disposition pleine largeur, bandeau vitres, trois KPI, table sombre, lignes de 30 px et sélection verte conformes à la structure de référence ; ajout explicite de la qualification du stock physique.

## Conservation de la consultation pendant les actualisations

Les actualisations manuelles, périodiques et temps réel conservent les familles ouvertes, toutes les pages enfants déjà chargées, la sélection et la position de défilement. Le tableau reste visible pendant la requête ; les données sont remplacées ensemble après le chargement des détails ouverts. Une famille ou une série disparue du résultat est retirée. Les changements explicites de recherche ou de Warehouse réinitialisent la consultation pour le nouveau filtre. En cas d’échec, le dernier résultat reste visible avec un message et son horodatage inchangé.

Test navigateur isolé (Playwright disponible dans `apps/crm/node_modules`) :

```sh
node apps/mat_reco/frontend/glass-stock/tests/refresh.cjs
```

Vérifié : trois sources d’actualisation, conservation de deux pages chargées, volet ouvert, sélection et défilement, mise à jour effective des surfaces, filtres et recherche, absence d’erreur JavaScript.

Le bundle courant est `glass-stock-r2.js`. Sa version est dans le nom de fichier : le chargeur `AssetManager.extn` de cette installation interprète incorrectement les URL contenant `?v=...` fournies directement à `frappe.require`. Le test navigateur utilise désormais le véritable `assets.js` de Frappe et le cycle de vie `glass_stock.js`, en plus des contrôles de conservation d’état, pour vérifier le montage et la disparition du masque de chargement.
