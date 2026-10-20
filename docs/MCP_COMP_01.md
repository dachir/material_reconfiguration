# COMP-01 — Audit et besoins résiduels

Cette note décrit le lot initial. La livraison des lots suivants et leur état de validation sont détaillés dans [MCP_COMPENSATION.md](MCP_COMPENSATION.md).

## Livraison

Service : `mat_reco/material_reconfiguration/services/mcp_compensation_service.py`.
Tests : `mat_reco/material_reconfiguration/tests/test_mcp_compensation_service.py`.
API en lecture seule :
`mat_reco.material_reconfiguration.services.mcp_compensation_service.get_compensation_requirements(material_cutting_plan_name)`.
Elle exige les permissions read/write, un brouillon Retour Terrain et un résultat existant.
Aucune écriture, aucune recherche de stock, aucune migration de schéma.

## Audit du code présent

- `order_explosion_service.build_unit_cutting_demands` produit les identifiants commerciaux
  `SO::ligne::article::unité`, les dimensions, l'article et les références de commande.
  Le service réutilise cette explosion pour calculer les besoins actuels.
- `cutting_plan_service.generate_cutting_plan` crée des finished_good avec `is_real=False`.
  Leur simple présence ne constitue donc pas une preuve de production.
- `generate_return_terrain_cutting_plan` existe déjà. Il verrouille les finished_good,
  considère leur piece_uid comme couvert, puis place les besoins restants dans
  leftover/waste et nouvelles entrées. Les remplacements portent `::RT…` dans leur id.
  Ce moteur ne constitue pas encore le parcours de compensation demandé : sauvegarde
  et recalcul sont liés, waste est accepté, aucune priorité stricte par origine.
- `MaterialCuttingPlan.before_save` appelle ce moteur en Retour Terrain et conserve
  result_json comme simulation ; effective_result_json devient la base vivante.
  Une future application de compensation devra maîtriser ce hook pour éviter un
  second recalcul automatique. Le présent lot ne modifie pas ce fonctionnement.
- `mcp_incident_service.resolve_mcp_effective_nodes` conserve les résultats résolus
  et réconcilie les Single encore en attente ; il ne rejoue pas les autres actions.
  Le calcul des besoins vérifie donc aussi les Destroy actifs par identifiant
  d'opération, notamment sur un résultat déjà résolu.
- `repack_draft_service.build_effective_nodes` fournit le résultat effectif utilisé
  par le Repack. `_target_serial_name` utilise id, puis piece_uid. Les sorties sont
  regroupées par article/dimensions et portent les Serial No déterministes.
  `_extract_serial_nos_from_stock_entry_detail` réutilise les mécanismes réels de
  lecture des Serial No, dont les bundles. Seuls les Repack soumis liés au MCP sont
  des preuves pour COMP-01 ; brouillons et annulés sont exclus.
- `MaterialCuttingPlan.before_submit` est actuellement vide. La couverture des
  besoins ne bloque pas encore la soumission du MCP.
- `Material Plan Incidents` contient les cinq actions existantes, leurs références
  géométriques et is_active. Aucun événement Compensation dédié n'existe.
- Single conserve une boîte englobante avec dimensions retirées. COMP-02 devra
  réutiliser `single_geometry.available_regions`, jamais la boîte seule.

## Contrat des états

piece_uid = besoin commercial unitaire ; id = opération physique et Serial No
sortant. Un remplacement historique est identifié par id différent du piece_uid.
`broken_pieces` conserve les opérations cassées individuellement ; un besoin
commercial ne peut figurer qu'une fois dans `compensation_requirements`.

- produced : une opération conforme apparaît dans un Repack soumis.
- planned : une opération initiale conforme est planifiée, réalisation non prouvée.
- replacement_planned : un remplacement conforme réserve ce besoin.
- missing : aucune opération conforme vivante ne couvre le besoin.

`to_compensate` exclut les réservations planifiées pour éviter les doublons.
`remaining_to_produce` inclut toutes les unités sans preuve Repack.
`produced` est une preuve comptable et non un indicateur de terrain avant Repack.
Une casse portant sur une sortie déjà soumise déclenche un avertissement : aucune
correction du stock ni altération du Repack n'est effectuée.
Les dimensions effectives et l'article doivent correspondre au besoin ; les
bandes détruites générées par Resize ne comptent pas comme des pièces cassées.
Les identités commerciales ou physiques dupliquées sont rejetées ; plusieurs
opérations vivantes pour un même besoin sont signalées et ne doublent pas le total.

## Validation

Depuis la racine du bench :

```sh
env/bin/python -m unittest mat_reco.material_reconfiguration.tests.test_mcp_compensation_service mat_reco.material_reconfiguration.tests.test_mcp_action_preview
```

33 tests réussis : 12 nouveaux tests de besoins et 21 tests des actions existantes.
Cas couverts : cinq besoins dont une casse, plan sans réalisation prouvée,
remplacement réservé, nouvelle casse, identifiant de reçu, Destroy actif/inactif,
Resize, besoins partiels/non planifiés, relecture immuable, doublons, couverture
multiple et permissions/absence de sauvegarde.

```sh
cd apps/mat_reco/frontend/mcp-ux20-vue
npm run build
```

Compilation réussie, 27 modules. Aucun composant Vue changé dans ce lot.
Pas de test sur une base métier ni de Repack réel exécuté.

## Déploiement et limites

Déployer les sources Python par le circuit habituel du projet et redémarrer les
workers web via l'exploitation. Aucun migrate requis pour ce lot. La compilation
Vue a été vérifiée ; aucune publication ni modification des données de site.

Le module complet n'est pas encore livré : COMP-02 (géométrie/prévisualisation),
COMP-03 (priorités stock/interface conforme à la maquette) et COMP-04
(persistance atomique, soumission et Repack) restent à développer et tester.
Les scénarios A à I complets ne peuvent pas encore être déclarés validés.
L'identification historique par id != piece_uid ne remplace pas le futur contrat
persistant de liens casse/besoin/remplacement. Les opérations sans référence
commerciale sont signalées et ne sont pas affectées arbitrairement à une commande.
Les besoins sont issus des commandes actuelles, pas d'un instantané historique
immuable ; les modifications commerciales ultérieures doivent être versionnées
lors de la conception de COMP-04.
