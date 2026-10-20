# MCP UX 2.0 — LOT 1 : audit et prévisualisation Python sans écriture

## Périmètre et résultat

Le lot 1 ajoute deux méthodes whitelisted en lecture de données : chargement du plan effectif et prévisualisation d’une intention. Il ne branche pas encore Vue, n’ajoute aucun incident enregistré et ne modifie aucun service de stock, contrôleur historique ou schéma de DocType. Les cinq actions passent par les fonctions Python existantes ; leurs résultats remplacent toute supposition géométrique côté client.

La référence de test réelle est `erpv15dev.marsavco.com`, MCP brouillon Retour Terrain `26MCP1001072`. Cette livraison ne constitue pas une validation en production et ne valide pas les lots 2 à 5.

## Matrice des fonctions auditées

Chemins depuis `apps/mat_reco/mat_reco/material_reconfiguration`.

| Service / fonction réelle | Signature / accès | Réutilisation / point manquant |
| --- | --- | --- |
| `services/mcp_incident_service.py` — `build_incident_map(doc)` | Interne, non whitelisted | Filtre `is_active`, applique les incidents en Retour Terrain uniquement, contrôle l’unicité Single. La table aplatie par identifiant ne constitue pas un journal d’opérations consécutives. |
| Même fichier — `apply_incidents_to_nodes(nodes, incident_map=None)` | Interne, sans persistance | Moteur des cinq actions utilisé par la prévisualisation. Move libère l’origine et découpe la destination ; Resize génère des zones détruites ; Merge consomme les zones et restitue `residual_rects`. Les protections Move/Merge seules sont insuffisantes contre des données client inventées : le nouvel adaptateur construit et valide les intentions avant ce moteur. |
| Même fichier — `resolve_mcp_effective_nodes(doc, tree)` | Interne, sans persistance | Autorité commune des résultats effectifs. Ne rejoue pas Move/Resize/Destroy/Merge sur un arbre `return_terrain_resolved`; réconcilie seulement les Single encore applicables. |
| `services/single_geometry.py` — `single_from_rectangles(children)`, `available_regions(length, width, removed_length=0, removed_width=0)` | Fonctions pures | Géométrie L exacte, deux zones libres dont au moins une chute, encoche supérieure gauche, dimensions retirées et surface exacte. Décomposition d’une seule plaque physique en régions virtuelles. Réutilisées sans changement. |
| `services/repack_draft_service.py` — `build_effective_nodes(doc)` | Interne | Charge le JSON effectif puis appelle le résolveur partagé. Le chargement de la nouvelle API emprunte exactement ce parcours. |
| Même fichier — `make_repack_draft(material_cutting_plan_name)` | Whitelisted existante | Retourne un Stock Entry Repack non soumis construit avec `build_effective_nodes`. Conserver ce bouton/service ; ne jamais l’appeler depuis une prévisualisation. Contrôle les sorties déjà générées. |
| `services/cutting_plan_service.py` — `generate_return_terrain_cutting_plan(*, plan_name, demands, bins, existing_tree, mcp_doc, kerf_mm=0.0, allow_rotation=True, packing_algorithm='maxrects', packing_heuristic='best_area_fit')` | Interne, calcul en mémoire | Utilise `base_tree`, applique les incidents, préserve les FG verrouillés, repacke les demandes dans les zones disponibles et produit un arbre résolu. Ce calcul dépasse l’application géométrique d’une intention. |
| `doctype/material_cutting_plan/material_cutting_plan.py` — `before_save()` | Hook de sauvegarde | Relit commandes et stock ; en Retour Terrain lance le générateur ci-dessus, écrit `effective_result_json` dans le document puis synchronise les plaques et résumés. La sauvegarde standard seule n’assure pas que le résultat soit identique à une simple application d’incident. |
| Même contrôleur — `_materialize_effective_plan(source_json_field='result_json')` | Interne | Applique les incidents et renseigne le JSON/table effectifs dans l’objet ; n’est pas utilisé comme API de preview et ne remplace pas `before_save`. |
| `doctype/material_cutting_plan/mcp_sheet_sync.py` — `sync_mcp_sheets(doc, source_json_field='result_json', child_table_field='mcp_sheets', overwrite=True)` | Interne | Reconstruit les lignes dans l’objet Document ; à réserver au parcours sauvegardé, pas à la prévisualisation. |
| `services/serial_creation_service.py` — `ensure_mcp_serials_and_bundles_for_stock_entry(doc)` et `_get_mcp_serial_dimension_map(mcp_name)` | Hooks / internes | Lit le résultat effectif ; normalise dimensions et encoche ; la création/mise à jour de Serial No appartient au parcours Stock Entry, exclu de la nouvelle API. |
| `utils/mcp_costing.py` — `_get_effective_children(mcp)`, `allocate_mcp_repack_costs_from_stock_entry(doc, mcp_name)` | Internes | Réutilise le même résolveur, calcule les surfaces nettes avec l’encoche pour les coûts. Ne pas dupliquer dans Vue. |
| `api.py` | API whitelisted existantes | Commandes, stock candidat, variantes, bundles ; aucune API existante ne prévisualise ces cinq intentions sans sauvegarde. |
| `ui/mcp_ux05_action_adapter.js` | Adaptateur JS pur | Construit les payloads Resize/Destroy/Merge/Single ; Merge calcule actuellement le rectangle/résidus côté client. À remplacer par le résultat serveur dans le lot 2. |
| `ui/mcp_ux06_move_adapter.js` | Adaptateur JS pur | Construit les Move avec `swap`/`swing` et exclusions ; les contrôles client ne remplacent pas les contrôles serveur. |
| `ui/mcp_ux07_frappe_bridge.js` | Bridge opt-in | Ajoute une ligne dans `frm.doc` puis `frm.save()`. Il refuse les autres modes et sources déjà incidentées ; ce n’est pas une prévisualisation en mémoire ni un enregistrement transactionnel de plusieurs intentions. |
| `frontend/mcp-ux20-vue/src/stores/cutting.js`, `src/lib/geometry.js`, `main.js`, `App.vue`, composants | Interface actuelle Vue / Pinia | Simulation JavaScript, callbacks de rendu, palette commune, verrouillage docstatus ; pas encore de client API métier. Aucun de ces fichiers n’est modifié par le lot 1. |
| `ui/mcp_ux20_modal.js`, `material_cutting_plan.js` | Pont / formulaire actuels | Montage et destruction Vue, chargement IIFE, simulation locale ; menu Opérations et Repack existants conservés. |

## Contrat API livré

Préfixe :

`mat_reco.material_reconfiguration.services.mcp_action_preview`

### `load_mcp_effective_plan(mcp_name)`

Recharge le MCP par `frappe.get_doc`, vérifie `read`, retourne `effective_tree`, `effective_nodes`, `summary`, `editable`, `document_version`, `warnings`, `errors`, `document_modified: false`. Un MCP Planification ou soumis est consultable, mais `editable` est faux. Un plan enregistré est requis.

### `preview_mcp_action(...)`

```javascript
frappe.call({
  method: 'mat_reco.material_reconfiguration.services.mcp_action_preview.preview_mcp_action',
  args: {
    mcp_name: '26MCP1001072',
    action: 'Resize',
    source_node_id: '<identifiant dans le résultat serveur>',
    target_node_ids: [],
    parameters: { length_mm: 1000, width_mm: 800 },
    pending_incidents: [],
    document_version: loaded.document_version
  }
});
```

`document_version` contient `modified` et une signature SHA-256 de l’état pertinent du document, JSON et incidents inclus. Il doit être repris intégralement du chargement. Toute différence retourne `valid: false`, `conflict: true` et une instruction de rechargement. Aucun état client n’est accepté comme base de géométrie.

Les éléments de `pending_incidents` peuvent être des intentions structurées ou les lignes canoniques renvoyées par une prévisualisation précédente. Ils sont reconstruits et revalidés dans l’ordre depuis le plan serveur. Maximum : 50 opérations, 8 régions sélectionnées pour Merge. Les sorties sont `valid`, `effective_tree`, `effective_nodes`, `incident` canonique, `pending_incidents` recalculés, `summary`, `warnings`, `errors`, `document_version`, `document_modified: false`.

Les échecs de permission remontent comme `frappe.PermissionError`, sans masquer un refus d’accès dans une réponse de succès. Toute intention nécessite `read`, `write`, Retour Terrain et `docstatus == 0`. La Planification ne peut pas silencieusement enregistrer des incidents que son moteur historique ignorerait.

## Validations et fidélité métier

- Aucune sauvegarde provisoire : seuls des dictionnaires copiés sont transformés.
- Le moteur d’incidents produit les nœuds effectifs ; le client ne fournit pas une surface ou un rectangle arbitraire à accepter.
- Move accepte une destination chute ou déchet encore physique, vérifie contenu réel, limites, absence de chevauchement et conservation des surfaces. `swap` désigne une destination de dimensions égales ; sinon `swing`.
- Merge vérifie la couverture disponible, conserve la première chute sélectionnée comme ancre (une source déchet peut alimenter la chute sélectionnée) et produit ses `residual_rects` en Python. Il peut consommer plusieurs régions et ne produit pas implicitement un L.
- Single appelle les fonctions existantes, conserve une seule sortie `__single` avec la surface nette et l’encoche ; le FG dans le coin absent reste intact.
- Resize conserve le traitement métier existant : le complément est détruit, il ne devient pas artificiellement une chute disponible comme dans la simulation JS précédente.
- Destroy conserve l’emprise physique et la traçabilité, mais la surface effective et `include_in_repack` deviennent nuls.
- Les anciennes zones retirées ne deviennent jamais disponibles ; leurs surfaces ne sont pas re-comptabilisées comme matière.
- Les bandes détruites générées par Resize héritaient du même identifiant que la source. L’adaptateur de preview leur donne des identifiants déterministes et conserve `__source_node_id`, sans toucher aux données enregistrées. Cela évite de redimensionner involontairement ces bandes lors d’une intention suivante.

## Tests exécutés

```sh
cd /home/marsavco/frappe-bench
./env/bin/python -m unittest mat_reco.material_reconfiguration.tests.test_mcp_action_preview -v
./env/bin/python -m py_compile apps/mat_reco/mat_reco/material_reconfiguration/services/mcp_action_preview.py
```

17 tests Python réussis, utilisant les vrais moteurs d’incident et Single ; persistance et permissions simulées dans les tests isolés. Couverture : cinq actions, Move intraplaque et interplaques, swap/swing, déchets disponibles, Merge partiel et multirégion, Single physique, redimensionnements consécutifs, erreurs de géométrie, conflit, permissions, refus après Submit, non-rejeu d’incidents déjà résolus et absence d’écriture partielle.

Sur `erpv15dev.marsavco.com`, exécution réelle de `load_mcp_effective_plan` et `preview_mcp_action` avec permissions Frappe :

- Chargement du MCP Retour Terrain `26MCP1001072`, 3 plaques : réussi.
- Destroy, Resize, Single et Move sur ses nœuds enregistrés : prévisualisations réussies.
- Merge : aucun couple compatible dans cet exemple ; couvert par les fixtures Python, non déclaré validé sur ce MCP réel.
- Espion SQL bloquant toute requête autre que SELECT/SHOW/DESCRIBE/EXPLAIN : 40 lectures, aucune écriture.
- Document complet avant/après identique ; nombres d’incidents, Stock Entry et Serial No identiques.
- Lecture par Guest refusée par la permission Frappe réelle.

La sauvegarde d’incidents, les créations de Serial No et la génération/soumission de Repack n’ont pas été exécutées dans ce lot, conformément à son périmètre sans écriture.

## Garde-fous avant les lots suivants

Le passage à l’enregistrement n’est pas encore validé. Le lot 1 expose volontairement cet avertissement au lieu de promettre que l’aperçu est enregistré :

1. Le journal d’intentions consécutives doit être raccordé à la sauvegarde. Aplatir toutes les lignes avec `build_incident_map` perd les opérations successives sur une même identité ; les identifiants générés d’une opération précédente doivent être résolus dans l’ordre.
2. Le contrôleur `before_save` recalcule Retour Terrain depuis commandes, bins et `base_tree`. Il faut établir et tester un contrat commun pour que preview, sauvegarde et Repack affichent/exportent le même arbre. L’API du lot 1 ne prétend pas reproduire ce repacking des demandes après chaque intention.
3. Le moteur historique Move traite une zone cible comme un rectangle. Une destination déjà en L est refusée explicitement par la nouvelle preview, même si un placement pourrait exister dans un de ses bras. Il faut adapter sa décomposition physique partagée avant d’annoncer ce cas pris en charge.
4. Les flags/identifiants hérités par certains nœuds générés doivent être normalisés et testés dans le parcours sauvegardé, et pas seulement pour la présentation du preview.
5. Lot 2 : ajouter le client Frappe, la gestion des réponses obsolètes et les trois états Pinia ; ne pas confondre preview et état sauvegardé.
6. Lot 3 : choisir un adaptateur transactionnel compatible avec le hook existant, détecter les conflits, revalider les intentions et empêcher les doublons. Aucun endpoint d’application n’est livré prématurément.
7. Lots 4–5 : rendre le champ preview non interactif selon la nouvelle consigne, conserver le menu historique, comparer les sorties Repack, Serial No, encoche et coûts sur le site de préproduction ; test de bout en bout requis.

## Fichiers et déploiement

Créés :

- `mat_reco/material_reconfiguration/services/mcp_action_preview.py`
- `mat_reco/material_reconfiguration/tests/test_mcp_action_preview.py`
- `docs/MCP_UX20_PYTHON_LOT1.md`

Aucun fichier existant ni frontend modifié dans ce lot. Aucune migration, aucune installation de dépendance et aucune compilation Vite nécessaires : le bundle Vue n’est pas raccordé à ces endpoints dans ce lot.

Pour déployer ce lot Python, transférer ces sources et redémarrer de manière contrôlée les processus Python qui chargent l’application. Aucun redémarrage de service ni déploiement production n’a été effectué ici. Le client pourra appeler les méthodes par leur chemin whitelisted après rechargement des processus.

Risques à surveiller : différences entre application d’incident et régénération Retour Terrain, historique d’identités clonées, journal d’incidents successifs, performances des fusions nombreuses. Les tailles d’intention sont bornées et les contrôles ne modifient pas les services historiques.
