# Correction du bouton Appliquer et des dimensions retirées Single

Le bouton ne transmettait que l’arbre SVG à `frm.__mcp_ux20_visual`. Aucune opération n’était gardée comme intention métier et aucune ligne de `material_plan_incidents` n’était créée. Un dessin en L n’avait donc aucune incidence sur les résultats enregistrés ni le Repack.

Le DocType enfant réel est `Material Plan Incidents`. Il ne possède pas de colonnes `removed_length_mm` / `removed_width_mm`. Comme dans le formulaire historique, une ligne `Single` contient :

- `plan_node_id` : première région ; `source_serial_no` : plaque physique.
- `incident_action = Single` ; `affected_node_ids_json` : les deux régions.
- `group_area_mm2`, `new_area_mm2` : surface nette ; `new_length_mm`, `new_width_mm` : dimensions extérieures.
- `target_x_mm`, `target_y_mm` : position extérieure.
- `include_in_repack = 1`, `is_active = 1`.
- `remarks` : JSON avec `removed_length_mm` et `removed_width_mm`.

Python reporte ensuite l’encoche dans le nœud effectif `geometry_type = single`. Les services Repack et Serial No existants utilisent ces propriétés ; aucun changement de schéma n’est nécessaire.

## Parcours corrigé

Sur un MCP enregistré, Retour Terrain, non soumis et avec permission d’écriture :

1. L’éditeur charge le résultat et sa version depuis Python.
2. Chaque action est prévisualisée par `preview_mcp_action`; le résultat Python fait autorité. Une réponse annulée/obsolète est ignorée.
3. Confirmer ajoute la ligne canonique aux incidents en attente dans Pinia. Annuler/Rétablir conserve aussi ce journal ; un passage de l’aperçu à la modal le transfère.
4. Appliquer appelle `prepare_mcp_incidents`. Cette méthode recharge le MCP, vérifie permissions/version, reconstruit les lignes et exécute `before_save` sur une copie en mémoire. Elle refuse un batch que le recalcul historique ne pourrait pas restituer.
5. Le bridge remplit `frm.add_child('material_plan_incidents')`, rafraîchit la table et appelle **une seule sauvegarde standard `frm.save()`** pour le batch.
6. Les résultats effectifs sont rechargés depuis Python, le journal est vidé et le statut devient `Enregistré`. Le panneau d’une chute Single affiche aussi ses dimensions retirées.
7. L’édition reste possible jusqu’au Submit. Les couleurs utilisent le même canevas.

Les autres modifications du formulaire doivent être enregistrées avant Appliquer : elles ne sont pas sauvegardées silencieusement avec le batch. La sauvegarde standard Frappe conserve ses contrôles de permission, de version et sa transaction. En cas d’échec, les lignes ajoutées sont retirées de la copie client et les intentions restent disponibles. Si la sauvegarde réussit mais le rechargement échoue, le message indique explicitement que les incidents sont enregistrés et qu’il faut recharger ; la table n’est pas faussement restaurée à son ancien état.

Les règles de Planification, les handlers métiers, le générateur Retour Terrain et le processus Repack ne sont pas réécrits. Certaines chaînes opérant sur des nœuds générés nécessitent d’appliquer une opération puis recharger avant la suivante : le précontrôle les refuse au lieu d’enregistrer des incidents perdus. Move vers une destination déjà en L reste refusé par le service de preview.

## Vérifications exécutées

- 19 tests Python réussis : cinq actions, prévisualisations consécutives, permissions, conflits, précontrôle de sauvegarde, payload Single et refus d’un résultat ignoré par le parcours historique.
- 23 tests Vue/Pinia/client Frappe réussis : géométrie existante, résultat Python, journal canonique, annulation des réponses obsolètes et erreurs métier.
- Compilation Vite IIFE/CSS réussie.
- Chromium : ancien parcours visuel, couleurs avant/après, verrouillage Submit et nouveau parcours de sauvegarde. Le nouveau test vérifie Single → confirmation → transfert vers modal → sauvegarde refusée/restauration → double clic → une seule ligne enregistrée → rechargement effectif → affichage des dimensions retirées. Les transports Frappe sont simulés dans ces tests navigateur.
- Site réel **erpv15dev.marsavco.com**, MCP `26MCP1001072` : précontrôle Single avec encoche **1500 × 1000 mm**, sauvegarde réelle, relecture de la ligne et des propriétés de l’encoche dans le résultat effectif, vérification du même résultat par `build_effective_nodes` utilisé pour Repack. Test dans une transaction annulée ensuite ; le document original est restauré. Aucun Stock Entry ni Serial No n’a été généré pendant ce test.
- Syntaxe JS et `git diff --check` réussis.

Pas de recette navigateur authentifiée sur le site réel ; pas de génération/soumission de Repack complète dans cette correction.

## Fichiers de cette correction

Modifiés (depuis `apps/mat_reco`) :

- `mat_reco/material_reconfiguration/services/mcp_action_preview.py`
- `mat_reco/material_reconfiguration/tests/test_mcp_action_preview.py`
- `frontend/mcp-ux20-vue/src/main.js`
- `frontend/mcp-ux20-vue/src/App.vue`
- `frontend/mcp-ux20-vue/src/stores/cutting.js`
- `frontend/mcp-ux20-vue/src/lib/geometry.js`
- `frontend/mcp-ux20-vue/src/lib/preview.js`
- `frontend/mcp-ux20-vue/src/components/SelectionPanel.vue`
- `frontend/mcp-ux20-vue/src/components/PreviewFooter.vue`
- `mat_reco/material_reconfiguration/doctype/material_cutting_plan/ui/mcp_ux20_modal.js`
- `mat_reco/material_reconfiguration/doctype/material_cutting_plan/material_cutting_plan.js` : version des assets.
- `mat_reco/public/js/mcp_ux20.bundle.js`
- `frontend/mcp-ux20-vue/README.md`
- Assets compilés `mat_reco/public/js/mcp_vue_dist/mcp_vue.iife.js` et `mat-reco-mcp-ux20-vue.css`.

Créés :

- `frontend/mcp-ux20-vue/src/services/frappeClient.js`
- `frontend/mcp-ux20-vue/tests/server.test.mjs`
- `frontend/mcp-ux20-vue/tests/save-incidents.cjs`
- `docs/MCP_UX20_APPLY_INCIDENTS.md`

## Rejouer les tests

```sh
cd /home/marsavco/frappe-bench
./env/bin/python -m unittest mat_reco.material_reconfiguration.tests.test_mcp_action_preview -v
npm --prefix apps/mat_reco/frontend/mcp-ux20-vue run build
npm --prefix apps/mat_reco/frontend/mcp-ux20-vue test
```

Le test navigateur de sauvegarde attend une fixture produite par les vrais moteurs Python (ne pas copier un résultat de simulation JS) :

```sh
./env/bin/python - <<'PY'
import json
from mat_reco.material_reconfiguration.tests.test_mcp_action_preview import fixture, action
from mat_reco.material_reconfiguration.services.mcp_action_preview import preview_intentions
nodes, incidents = preview_intentions(fixture(), [action('Single', 'left', ['red'])])
with open('/tmp/mcp-single-save-fixture.json', 'w') as f:
    json.dump({'tree': {'nodes': fixture()}, 'saved': {'nodes': nodes, 'return_terrain_resolved': True}, 'incidents': incidents}, f)
PY
PLAYWRIGHT_MODULE=/home/marsavco/frappe-bench/apps/crm/node_modules/playwright node apps/mat_reco/frontend/mcp-ux20-vue/tests/save-incidents.cjs
```

Aucune migration ni dépendance supplémentaire. La version de cache des bundles est `20261013_10`.


## Correction complémentaire : identifiants RTL / base historique

Le MCP `26MCP1001072` montre des régions `VVC0001-07::RTL1` et `RTL2`, alors que `before_save` applique les incidents à `base_tree`, qui les nomme `L1` et `L2`. La prévalidation ajoutait bien une ligne en mémoire, mais ses identifiants ne correspondaient à aucun nœud de la base : le générateur l’ignorait.

`prepare_mcp_incidents` parcourt maintenant toutes les lignes du batch et traduit leurs identifiants vers la base historique par une correspondance physique unique (plaque, type libre, position, dimensions et encoche). Il conserve cette correspondance dans `remarks.ux20_node_aliases`. Les dimensions retirées de Single et les `residual_rects` de Merge sont préservés. Une correspondance ambiguë ou une géométrie différente est refusée ; le JSON final n’est pas utilisé pour inventer une action.

Vérification réelle de la fusion de la capture : source `RTL2`, cible `RTL1`, ligne enregistrée avec `plan_node_id=L2`, `affected_node_ids_json=[L2,L1]`. Résultat : chute 3500 × 1600 et reste 500 × 1000. La sauvegarde, la relecture et une deuxième sauvegarde conservent cette géométrie. Transaction de test annulée, MCP initial restauré. Deux tests supplémentaires couvrent la traduction de toutes les lignes, la conservation des dimensions Single et le refus d’un rapprochement géométrique incorrect.
