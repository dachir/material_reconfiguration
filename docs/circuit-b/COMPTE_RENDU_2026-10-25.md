# Circuit B — bordereaux, règlements et situation client

Implémentation dans `mat_reco`, réalisée en développement le 25 octobre 2026. Aucun traitement métier n’a été exécuté en production pour cette mission.

## 1. Audit de l’existant

- `services/order_b.py` : rôle `UG COMMANDES B`, restrictions de lecture B, interdiction des Delivery Notes, Sales Invoices et écritures clients faisant référence à une commande B. Un même Customer peut avoir des commandes A et B.
- `services/sales_order_types.py` : séries A et B indépendantes ; série A conservée.
- `services/order_technical.py` et les services atelier : FT, fabrication et traçabilité préexistantes conservées.
- `services/order_b_stock.py` : sortie native **Stock Entry / Material Issue**, idempotence par clé et empreinte, contrôle des quantités, des dépôts, des réservations et des séries. Les ouvrages/découpes doivent provenir de leur ligne de commande ; la FT doit être validée avant leur sortie.
- `services/order_b_export.py` : export commercial Sage traçable et verrouillage des sorties exportées, conservés.
- `report/suivi_commandes_b/`, `public/js/order_b_actions.js` : consultation et actions sur le formulaire Sales Order natif, réutilisées.
- `printing.py` : impressions A4 génériques des documents enregistrés, réutilisées.
- Le cockpit Vue reste chargé de la fabrication. Aucun second moteur de fabrication, de stock ou de comptabilité n’a été créé et aucun changement Vue supplémentaire n’est nécessaire pour les nouveaux formulaires natifs.

## 2. Documents et relations

Les identifiants techniques des DocTypes sont sans accent ; leurs libellés français sont fournis par la traduction.

| DocType | Usage |
| --- | --- |
| `Bordereau Special` | Commande B validée, société/client/devise, date, dépôt, montants et sortie native associée. Plusieurs BL par commande. |
| `Bordereau Special Item` | Référence exacte de la ligne source, désignation, quantités commandées/déjà livrées/restantes/à livrer, unité, dépôt, dimensions, séries, lot, prix et montant. |
| `Reglement Special` | Encaissement B autonome : société/client/devise, date, référence, mode et montant ; commande facultative. |
| `Reglement Special Allocation` | Affectation d’une partie du règlement à un BL validé. Plusieurs BL et plusieurs règlements sont possibles. |
| `Solde Initial Client B` | Reprise historique signée : positive pour un débiteur, négative pour un créditeur ; référence de reprise unique et justification obligatoires. |

Les trois documents principaux sont submittables, avec `docstatus` 0/1/2 et historique Frappe. Les permissions réutilisent le rôle B et les User Permissions natives. Les droits natifs Stock Entry de création/validation/annulation restent nécessaires pour les opérations physiques. Le rôle de consultation du cockpit ne donne pas accès aux règlements ni au rapport financier.

## 3. Bordereau et stock

- Création depuis **Sales Order B → Create → Bordereau Spécial**. Les lignes restantes sont proposées ; l’opérateur ajuste les quantités, retire les lignes non livrées et renseigne les séries/dépôts nécessaires. Les références techniques sont masquées sur le formulaire et ne sont pas saisies manuellement.
- Le bouton **Recharger les articles** recharge le reste à livrer, après confirmation de la perte des choix locaux. Le bouton **Dimensions de stock** réutilise les dimensions comptables existantes (ex. Branch).
- Les prix HT proviennent des lignes nettes de la commande. Les taxes et remises globales déjà présentes sont réparties proportionnellement via le rapport `grand_total / net_total`. Les arrondis cumulés et une base non arrondie garantissent la concordance finale, y compris en CFA.
- Seuls les articles physiques déclenchent le mécanisme existant `order_b_stock.create_issue`. Un BL de services peut être validé sans Stock Entry.
- Un lien `Stock Entry.custom_ug_special_delivery` et une clé idempotente identifient la sortie. Les anciens mouvements B sont inclus dans les quantités déjà sorties ; ils ne sont pas comptés deux fois lorsqu’ils sont rattachés à un BL.
- **Create → Reprendre une sortie B existante** et l’API `make_from_issue` préparent un BL à partir d’une sortie validée sans nouvelle sortie. La date, les quantités, séries et dépôts sont contrôlés/repris. Une sortie ne peut avoir qu’un BL actif. Les reprises ambiguës d’une même ligne répartie sur plusieurs dépôts/lots sont refusées.
- Annuler le BL annule sa sortie native dans la même transaction, en conservant les contrôles ERPNext. Une sortie liée ne peut pas être annulée directement. Les autres liens ERPNext ne sont pas ignorés : seule la référence au BL en cours d’annulation est exclue du contrôle de retour de lien.
- Un BL avec des affectations actives ne peut être annulé : retirer les affectations ou annuler les règlements concernés d’abord. Les restrictions Sage existantes restent applicables.

## 4. Règlements, avances et absence de double comptage

- Le montant, le client, la devise, la date, la référence et la commande du règlement sont immuables après validation.
- Les affectations peuvent être modifiées après validation avec **Update**, selon les règles Frappe `allow_on_submit`, avec contrôles serveur et historique.
- Chaque affectation doit viser un BL validé du même client, de la même société et de la même devise. Les doublons et dépassements de solde sont bloqués. La somme des affectations ne peut dépasser l’encaissement.
- Un règlement avec commande ne peut couvrir que ses BL. Pour couvrir plusieurs commandes B du client, laisser la commande vide.
- Un montant reçu non affecté reste au compte client B : il peut constituer une avance ou réduire une dette historique reprise en ouverture, sans BL détaillé. Affecter ce montant ultérieurement ne crée aucun nouvel encaissement.
- **Le rapport client crédite l’en-tête du règlement une seule fois**, jamais chaque ligne d’affectation. L’annulation du règlement retire son crédit et libère ses affectations.
- Avec un filtre de commande, un règlement dédié à cette commande compte en totalité, avances comprises. Un règlement multi-commandes compte pour la seule part affectée à cette commande ; son avance sans commande reste au niveau client. Il ne faut donc pas additionner les soldes des commandes pour reconstituer un compte client comportant une reprise ou une avance globale non répartie.

## 5. Soldes d’ouverture et étanchéité A/B

Le solde d’ouverture concerne **exclusivement l’historique B**, même si le Customer a aussi des commandes A. Il ne provient pas du solde comptable standard du Customer.

- La date de reprise représente le début de journée. Le montant reprend seulement l’historique antérieur.
- Une référence de migration unique évite le réimport du même solde. Les reprises actives d’un compte client/devise ne peuvent se recouvrir ; une reprise globale et des reprises par commande du même compte ne peuvent coexister.
- La reprise est refusée si des mouvements B antérieurs sont déjà enregistrés et seraient ajoutés une seconde fois. Après reprise, les mouvements antérieurs à sa date sont bloqués. Il faut choisir entre reprise d’un solde et reprise détaillée des mêmes mouvements historiques.
- Une reprise avec des mouvements actifs ne peut être annulée isolément.
- **Les Sales Invoices, Payment Entries, Journal Entries, Delivery Notes et GL Entries du circuit A ne sont jamais interrogés pour calculer le solde B.** Une commande A ne peut être source d’un BL/règlement B. Les affectations ne peuvent viser que des Bordereaux Spéciaux B.

## 6. Rapport et consultation

Script Report standard : **Situation des comptes clients B**.

Filtres : société, période, client, commande B et devise. Les résultats sont regroupés par société/client/devise, avec solde initial, opérations au débit/crédit, solde progressif et solde final. Les périodes sans mouvement restent consultables. Les devises et sociétés ne sont jamais additionnées entre elles.

`Solde final = Solde initial + BL validés − Règlements validés`.

Les références sont des Dynamic Links vers les documents d’origine. Le rapport conserve les exports Excel/CSV et l’impression PDF natifs, avec une présentation d’impression dédiée.

Sur la commande B :

- **Create → Bordereau Spécial / Règlement Spécial / Reprendre une sortie B existante** ;
- **Livraisons et règlements B** : détail par article des quantités livrées/restantes, BL et sorties liés, montants/affectations/soldes, règlements et avances ;
- **Situation client B** : consultation du compte B global du client, pas du compte A ;
- `Suivi commandes B` : colonnes BL validés, montants BL, règlements, solde des BL et solde de commande.

Les impressions des documents réutilisent `Mat Reco A4`, avec liens d’origine et montants CFA sans décimales.

## 7. Transactions et incidence comptable

Les opérations d’écriture sont sérialisées par un verrou de société, puis par les verrous natifs de commande/stock et les lectures courantes des livraisons/affectations. Les modifications concurrentes sont vérifiées à nouveau sous verrou. Aucune validation métier ne fait de `commit` explicite : document, sortie, séries et annulation partagent la transaction de la requête Frappe.

Aucune Sales Invoice, Payment Entry, Journal Entry ou écriture client n’est générée par le sous-circuit financier B.

**Le stock conserve sa comptabilité native.** À coût non nul et avec inventaire permanent, le Material Issue peut générer des GL Entries de stock/charge. La recette vérifie notamment une sortie de 3 unités à coût 12 : débit et crédit de stock/charge de 36, sans partie Customer. Une sortie sérialisée à coût nul et son annulation sont également testées. Le code ne force aucun coût à zéro et ne supprime aucune écriture de valorisation.

## 8. Fichiers de cette évolution

Nouveaux fichiers :

- `material_reconfiguration/doctype/{bordereau_special,bordereau_special_item,reglement_special,reglement_special_allocation,solde_initial_client_b}/` : JSON Frappe et contrôleurs Python.
- `material_reconfiguration/services/special_b.py` : règles, verrouillage, API, reprises et consultation.
- `material_reconfiguration/report/situation_des_comptes_clients_b/` : définition, Python, filtres JS et impression HTML.
- `public/js/special_b_forms.js` : formulaires Frappe natifs.
- `material_reconfiguration/tests/test_special_b.py` : recette transactionnelle.
- `translations/fr.csv` : libellés des nouveaux documents.

Fichiers existants complétés :

- `hooks.py` : migration, permissions et scripts des nouveaux documents ;
- `services/order_b_stock.py` : lien BL, date de sortie, garde d’annulation et lectures verrouillées ;
- `report/suivi_commandes_b/suivi_commandes_b.py` : suivi financier/livraison ;
- `public/js/order_b_actions.js` : actions de commande et consultation ;
- `printing.py` : réutilisation A4, liens et présentation des documents B ;
- `workspace/univers_glass/univers_glass.json` : raccourci vers la situation B.

Les modifications antérieures du chantier, du cockpit et des print formats présentes dans l’espace de travail ont été conservées ; elles ne constituent pas une reconstruction de l’application.

## 9. Migration et mise en service

1. Déployer le code de `mat_reco`, puis exécuter `bench --site <site> migrate` et recharger les processus/cache selon le déploiement habituel.
2. La migration synchronise les cinq DocTypes, le rapport, les formats A4, les index et le lien Stock Entry → Bordereau Spécial. Le hook `special_b.install` est idempotent.
3. Vérifier les utilisateurs autorisés : rôle B, accès aux sociétés/clients et permissions Stock Entry pour les opérateurs physiques.
4. Préparer le périmètre **B uniquement** des soldes historiques ; importer/valider les ouvertures avant les nouveaux mouvements. Ne pas réintroduire les BL/règlements inclus dans ces ouvertures.
5. Les anciens mouvements de stock et exports Sage ne sont ni supprimés ni automatiquement transformés en mouvements financiers B. Toute reprise explicite doit être contrôlée.

Installation réalisée en développement par le même installateur. La production n’a pas été migrée pendant cette mission.

## 10. Recette

Voir `recette-2026-10-25.json` pour le résultat final automatisé.

Scénarios couverts : livraison totale ; livraisons multiples ; livraison partielle de plusieurs articles et services ; article sérialisé ; annulation BL + Stock Entry ; plusieurs règlements d’un BL ; règlement multi-BL/multi-commandes ; avance et affectation après validation ; annulation règlement ; client mixte A/B ; période sans mouvement ; ouvertures débitrices/créditrices ; doublons de reprise/règlement ; dépassements ; accès ; devises ; arrondis et taxes ; CFA ; reprise d’une sortie existante ; Excel et PDF natifs.

Les tests de sorties B préexistants sont rejoués : valorisation réelle/nulle, séries produites pour la bonne commande, réservations, idempotence, export Sage et limites comptables A/B.

Une recette navigateur ouvre les formulaires BL/règlement depuis une commande B et le rapport avec ses filtres, sans enregistrer de document métier. Les tests serveur utilisent des savepoints et sont annulés après chaque scénario : aucun stock ni solde client de recette n’est laissé dans la base.
