# Écran Chantier — livraison du 17 octobre 2026

## Correspondance avec le dépôt

- Page Desk : `mat_reco/material_reconfiguration/page/chantiers/chantiers.js`, montage `mountChantiers` de `frontend/workshop-vue/src/main.js`.
- Écran réel : `frontend/workshop-vue/src/Chantiers.vue` ; catalogue/drawer : `CommercialExtrasPanel.vue`.
- Lecture : `chantier_service.get_dossier` fournit le Chantier, ses sections, droits, étude, devis et usages.
- Ouvrages : table `Chantier.lines` / `Chantier Line` ; identité `line_id`, repère `repere`, désignation, `proposed_item`, `section`, dimensions mm structurées, quantité, UOM, prix et confirmation.
- Prestations : `Chantier.commercial_extras` / `Chantier Commercial Extra` ; rattachement par `parent_line_id` ; catalogue et `preview_batch` de `chantier_extras`.
- Sauvegarde : `technical_study_service.save_commercial` ; droits write, brouillon, contrôle modified, validation des lignes et prestations par `doc.save()`. En-tête ajouté à la même transaction avec liste stricte de champs autorisés.
- Préparation/validation technique, validation commerciale, génération devis et confirmation commande : API existantes conservées et accessibles via le menu complémentaire. Fabrication accessible via Atelier.

## Comportement livré

En-tête deux colonnes, sections repliables, recherche d’ouvrages, saisie directement en cellules, contrôles Link natifs Frappe, dimensions structurées, duplication/suppression, chevrons indépendants, grille à défilement conditionnel et en-tête fixe. Le drawer est dans la page et réduit la grille. Chaque icône cible la sélection complète, même masquée, ou seulement la ligne cliquée en l’absence de sélection. La sélection des ouvrages reste intacte après affectation. Les choix de prestations restent présents pendant le filtrage. Le serveur calcule les quantités et exclut les paires ouvrage/article déjà affectées. Les ajouts restent non sauvegardés jusqu’à Enregistrer. Avant une prévisualisation, les éditions existantes sont sauvegardées par le mécanisme déjà utilisé par le projet.

Le pied présente le total HT de tous les ouvrages et prestations, sans dépendre du filtre. Les taxes et montants définitifs restent ceux du devis ERPNext.

## Champs absents et limites

Le DocType ne possède pas Adresse/Lieu, Contact, ni Date livraison cible. Aucun champ n’a été ajouté : l’écran affiche Responsable, Début prévu et Fin de fabrication prévue avec leurs vrais libellés. Le statut reste en lecture seule et piloté par les workflows existants. Le prix reste modifiable uniquement dans un brouillon avec droit write, comme dans l’ancienne interface.

Les captures utilisent un dossier de recette intercepté dans le navigateur : aucune donnée commerciale factice n’est enregistrée. La persistance est vérifiée séparément par les tests serveur avec rollback. La recette ne constitue pas une mesure de performance à 500 lignes ni une validation visuelle exhaustive sur mobile.

## Vérifications

- `npm test --prefix apps/mat_reco/frontend/workshop-vue` : 17 tests réussis.
- `npm run build --prefix apps/mat_reco/frontend/workshop-vue` : réussi ; assets Frappe régénérés.
- `bench --site erpv15dev.marsavco.com run-tests --app mat_reco --module mat_reco.material_reconfiguration.tests.test_technical_study_service --skip-test-records` : 36 tests réussis ; couvre notamment réaffectation sans doublons, calculs propres à chaque ouvrage, sauvegarde/rechargement et collision modified.
- `WORKSHOP_PLAYWRIGHT_MODULE=/home/marsavco/frappe-bench/apps/crm/node_modules/playwright node apps/mat_reco/frontend/workshop-vue/tests/chantier-browser.cjs` : réussi dans le Desk Frappe réel. Nécessite une session locale dans `/tmp/workshop-browser-session.json` (ou `WORKSHOP_SESSION_FILE`). Couvre sélection A+B puis clic C avec B masqué, conservation des choix filtrés, affectation, détail, fermeture, repli, cible unique sans sélection, ajout dans la section active et édition de quantité. Aucune erreur JavaScript.
- `git diff --check` : réussi.

## Fichiers modifiés ou ajoutés

- `frontend/workshop-vue/src/Chantiers.vue`
- `frontend/workshop-vue/src/CommercialExtrasPanel.vue`
- `frontend/workshop-vue/src/FrappeCell.vue`
- `frontend/workshop-vue/src/chantier-selection.js`
- `frontend/workshop-vue/tests/chantier-selection.test.mjs`
- `frontend/workshop-vue/tests/chantier-browser.cjs`
- `mat_reco/material_reconfiguration/services/technical_study_service.py`
- `mat_reco/material_reconfiguration/tests/test_technical_study_service.py`
- `mat_reco/public/js/workshop_vue_dist/workshop.js`
- `mat_reco/public/js/workshop_vue_dist/workshop.css`
- `docs/chantier-v1/RECETTE.md`
- `docs/chantier-v1/desktop.png`
- `docs/chantier-v1/sections-repliees.png`
- `docs/chantier-v1/saisie.png`

L’archive source `docs/UG_Chantier_Codex_v1.zip`, déjà présente, n’a pas été modifiée.

## Ajustements après retour utilisateur

- Article : un seul champ texte libre avec autocomplétion des désignations existantes via `designation_suggestions` ; les références historiques restent conservées dans les données.
- Suppression : icône SVG de corbeille, rouge, avec le libellé accessible existant.
- Drawer : colonne droite de hauteur `100dvh`, alignée au haut de l’écran ; l’en-tête et la grille se rétrécissent ensemble. Liste défilante et pied accessibles.
- Build et 17 tests frontend réussis. Recette navigateur complétée : champ article unique, choix au clavier d’une suggestion, texte libre conservé après flou, corbeille SVG, drawer de 1 000 px sur viewport de 1 000 px, en-tête réduit et largeur restaurée à la fermeture.
- Fichier complémentaire modifié : `frontend/workshop-vue/src/FrappeCell.vue`. Captures actualisées.

## Complétion automatique et affectation de section

La première suggestion commençant par le texte saisi complète automatiquement le champ et sélectionne la fin ajoutée, sans empêcher de saisir une désignation libre. Tab accepte la suggestion active ; les suggestions s’affichent sur une largeur de 150 % du champ en dehors de la zone de défilement du tableau. Réponses périmées ignorées et requêtes temporisées.

La colonne Section affiche uniquement le libellé. Un bouton icône de dossier ouvre le volet Services / Accessoires où la section peut être affectée aux ouvrages ciblés (sélection cochée complète ou ligne cliquée). « Sans section » permet le retrait. Les changements sont enregistrés avec les ouvrages par l’API existante.

Build, 17 tests frontend et recette navigateur réussis : complétion automatique sans Entrée, largeur de 150 %, texte libre préservé après flou, absence de champ de section dans la grille et déplacement d’un ouvrage dans une autre section depuis le volet. Capture complémentaire : `sections-affectation.png`.

## Section dans les détails uniquement

La colonne Section a été retirée. Sa largeur est transférée à Article (minimum 380 px). Le libellé de section apparaît dans la sous-ligne avec les services et accessoires uniquement quand le triangle vert est ouvert. L’affectation par le volet reste disponible. Build et recette navigateur réussis, avec vérification de l’absence de colonne Section et de l’apparition/disparition de l’information à chaque clic sur le triangle. Captures actualisées.

## Simplification du prix et quantité élargie

Case « Confirmé » retirée de la grille, sans changement des règles serveur. Champ Quantité élargi de 65 à 100 px ; colonne Prix unitaire resserrée. Build et recette navigateur réussis ; captures actualisées.

## Choix de section dans le panneau gauche

Le bouton « Affecter une section » d’un ouvrage active désormais le panneau Sections : les compteurs deviennent des cases à cocher, avec la section de cette ligne précochée. Le panneau indique le repère de la ligne concernée. Une seule section est affectée à la fois ; « Sans section » permet de retirer l’affectation. Le bouton de fermeture du mode ou un nouveau clic sur la même icône restaure les compteurs et le filtrage habituel. La section concerne uniquement la ligne dont l’icône a été activée ; l’affectation groupée des prestations conserve son fonctionnement. L’ancien sélecteur de section dans le drawer est supprimé. Enregistrer sauvegarde l’affectation avec le document.

Build, 17 tests frontend et recette navigateur réussis : section précochée, compteurs masqués, changement de section exclusif, compteurs restaurés en sortie et déplacement de la bonne ligne. Capture : `section-checkboxes.png`.

## Sections conservées au devis, exclues des commandes

Règle clarifiée par le demandeur : la section appartient au chantier et au devis, mais ne doit pas être transmise à la commande. Le transfert natif Quotation → Sales Order efface maintenant `custom_chantier_section` sur toutes les lignes. La validation des commandes nettoie aussi les valeurs d’anciens brouillons ; les prestations ne recopient plus la section. Les contrôles d’article, unité, dimensions, repère et empreinte technique restent actifs. Aucun document commercial existant n’a été modifié par un script de réparation.

Le blocage initial a été reproduit sans écriture sur SAL-QTN-2026-00025 : le devis contenait une chaîne vide pour la section et le mapper produisait `None`. La comparaison de sections n’a plus lieu pour la commande selon la règle clarifiée.

Validation : 15 tests de ChantierServiceTests et 38 tests de test_technical_study_service réussis, dont transfert/enregistrement natif sans section et conservation de la section sur le devis pour les ouvrages et prestations. Le test historique NativeChantierTests testé en complément échoue avant la conversion en commande sur une fixture d’épaisseur incohérente (10 mm saisis, composition de 20 mm) ; ce problème de fixture n’a pas été modifié. Syntaxe Python et diff vérifiés. Rechargement gracieux des workers web effectué.

## Commandes créées depuis ERPNext

Diagnostic : SAL-ORD-2026-00033 est bien liée au chantier 26CHANT1000004 et au devis SAL-QTN-2026-00025, avec docstatus 0 (brouillon). L’API ne retournait auparavant que les commandes validées pour les calculs de production et l’écran ne présentait pas de liste de commandes.

`get_dossier` expose désormais `sales_orders`, filtrées par les permissions de lecture, indépendamment de l’accès au stock. Les brouillons, commandes validées et annulées sont affichés dans une ligne compacte de liens avec statut et montant. Les calculs de fabrication restent limités aux commandes validées. Les commandes enregistrées via ERPNext publient l’événement existant `workshop_updated` sur on_update ; le chantier ouvert se recharge à sa réception, sauf en présence d’éditions non enregistrées. Le retour sur la page et l’actualisation périodique restent disponibles.

Build, 39 tests serveur, 17 tests frontend et recette navigateur réussis. Nouveau test serveur : création native depuis le devis, visibilité du brouillon dans le dossier sans quantité de fabrication, lecture par un rôle sans accès stock, puis prise en compte après validation. Nouveau scénario navigateur : numéro/statut visibles et actualisation du statut sur réception de l’événement ERPNext. Cache du site rafraîchi et workers web rechargés gracieusement. Aucun statut de commande ni document métier existant n’a été modifié.

Fichiers complémentaires modifiés : `mat_reco/hooks.py`, `mat_reco/material_reconfiguration/services/chantier_service.py`, `mat_reco/material_reconfiguration/tests/test_technical_study_service.py`, `frontend/workshop-vue/src/Chantiers.vue`, `frontend/workshop-vue/tests/chantier-browser.cjs`, assets JS/CSS générés et captures.

## Étude technique — définition commune à plusieurs ouvrages

Chaque ouvrage du volet gauche dispose d’une case indépendante du bouton qui affiche sa définition. « Tout sélectionner » permet de cocher tous les ouvrages. Le panneau central identifie l’ouvrage source et propose « Appliquer cette définition aux N ouvrages cochés ». Le demandeur a confirmé que seules la composition et l’épaisseur sont copiées : longueurs, hauteurs, quantités commerciales et repères sont conservés pour chaque ouvrage. La définition peut provenir d’un ouvrage non coché. Les compositions sont copiées profondément pour rester indépendantes après l’affectation. Les modifications restent locales jusqu’à Enregistrer. La sélection est conservée après sauvegarde/rechargement de la même étude, remise à zéro lors du changement d’étude, et les commandes de copie sont masquées en lecture seule ou après validation.

Validation : build réussi, 20 tests frontend réussis et 40 tests serveur de test_technical_study_service réussis. Nouveau test serveur : sauvegarde puis validation de deux lignes de dimensions différentes partageant la même définition, réutilisation d’un seul article final, conservation des dimensions dans les snapshots et des quantités commerciales, absence de stock créé. Recette navigateur : cases indépendantes de l’ouvrage actif, source non cochée, application multiple, dimensions/quantités propres, compositions indépendantes, sauvegarde/rechargement, sélection conservée, sélection globale et lecture seule.

Commande navigateur : `WORKSHOP_PLAYWRIGHT_MODULE=/home/marsavco/frappe-bench/apps/crm/node_modules/playwright node apps/mat_reco/frontend/workshop-vue/tests/technical-batch-browser.cjs`. Les données de capture sont des fixtures navigateur sans écriture métier. Capture : `technical-batch.png`.

Fichiers de cette évolution : `frontend/workshop-vue/src/TechnicalStudy.vue`, `frontend/workshop-vue/src/technical-batch.js`, `frontend/workshop-vue/tests/technical-batch.test.mjs`, `frontend/workshop-vue/tests/technical-batch-browser.cjs`, `mat_reco/material_reconfiguration/tests/test_technical_study_service.py`, assets `workshop.js` et `workshop.css`, ce compte rendu et la capture. Aucune API métier ni règle de validation n’a été changée.

## Étude technique — présentation compacte

Suppression des paragraphes pédagogiques génériques (exemple double vitrage, explication du bouton +, article existant et création des Items), du bandeau de rappel, du pied explicatif et de la décoration de verre. Les erreurs métier et le contrôle d’épaisseur restent visibles. Le rappel d’application groupée est ramené à la source et aux champs copiés. Les notes techniques restent éditables.

Les espacements des champs, panneaux, cartes d’ouvrages et composants ont été réduits. La marge héritée de 48 px et le padding vertical hérité de 12 px des cartes sont explicitement neutralisés. Hauteur mesurée dans le navigateur : environ 41 px par carte de composant, contre 65 px avant neutralisation, avec une indentation d’arbre conservée. Build et recette navigateur d’affectation groupée/sauvegarde réussis. Capture `technical-batch.png` actualisée. Aucune modification de règles métier.

## Chantier réintégré à la page ERPNext standard

À la demande de l’utilisateur, suppression des règles globales de plein écran qui cachaient la navbar et le titre ERPNext, forçaient la pleine largeur et remplaçaient le fond de page. Chantier reste monté dans le `page.main` standard existant. Le composant conserve son thème interne et ses fonctionnalités. Le volet Services / Accessoires se limite à la hauteur disponible sous les barres ERPNext.

Build et recette navigateur réussis : navbar et titre de page visibles, composant encastré dans le conteneur ERPNext, volet fonctionnel et contrôles d’affectation conservés. Captures actualisées.

## Fiche technique dans le cadre ERPNext

L’écran technique est réintégré au conteneur ERPNext standard : les règles globales de plein écran sont supprimées et la page ne masque plus la navbar ni le titre ERPNext. La présentation compacte et la copie groupée restent actives. Le titre visible devient « Fiche technique », avec les actions et confirmations correspondantes, le raccourci Univers Glass, les liens depuis Chantier, les champs liés des devis/commandes et le titre du rapport A4. Les noms internes `Chantier Technical Study` et `technical-study` sont conservés.

Les libellés ERPNext ont été actualisés de façon ciblée : Page, libellé du champ de Chantier, Custom Fields de devis/commande et raccourci du Workspace. Les autres paramètres du Workspace et les données commerciales ont été conservés. Cache actualisé et workers web rechargés pour le titre d’impression.

Validation : build réussi, recette navigateur de sélection/copie/sauvegarde réussie avec vérification de la navbar, du titre Fiche technique et du conteneur standard, quatre tests d’impression A4 réussis. Capture `technical-batch.png` actualisée.

## En-tête épuré et statut dans ERPNext

Suppression des textes barrés dans le panneau sombre : marque/préparation technique, titre Fiche technique répété, nom/référence de chantier et libellé visible du sélecteur. Le sélecteur conserve son nom accessible. Les actions restent disponibles. Le statut est remonté au titre de page ERPNext dans la partie blanche via `page.set_indicator` ; il suit le chargement, la sauvegarde et les changements de docstatus de la fiche.

Build et recette navigateur réussis, avec vérification des indicateurs Brouillon et Validée dans le titre ERPNext, de l’absence de titre répété et des fonctionnalités d’affectation groupée/sauvegarde. Capture complémentaire : `fiche-technique-status.png`. Le navigateur de recette a utilisé `TMPDIR=/dev/shm` après un manque d’espace temporaire sur le disque système ; aucune donnée existante n’a été supprimée.

## Alignement de la barre de commandes

Sélecteur de fiche et bouton Document ERPNext déplacés à gauche de la même rangée que les actions de droite. L’alignement vertical est vérifié dans le navigateur (centres identiques), avec retour à la ligne sur les petits écrans. Build et recette d’interaction réussis. Captures actualisées.
