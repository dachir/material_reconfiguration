# Exécution automatique du Repack à la validation du MCP

Lors de la validation native d’un Material Cutting Plan, le hook Python `on_submit` appelle `mcp_repack.execute_on_submit` dans la même transaction. Un Repack brouillon lié est soumis ; sinon le générateur existant prépare un Repack qui est inséré puis soumis avec les droits de l’opérateur. Aucun `ignore_permissions`, commit indépendant ni job différé n’est ajouté.

Les dimensions comptables sont reprises du plan, du brouillon existant ou des commandes liées, puis des valeurs par défaut société par le résolveur existant. Des commandes dont les dimensions comptables sont incompatibles sont bloquées. Les dimensions d’inventaire des séries consommées sont reprises de leur dernier mouvement entrant par ERPNext, sans attribuer arbitrairement une qualité aux sorties. Les lignes regroupant des séries aux dimensions de stock différentes doivent être séparées dans le brouillon.

Les validations de compensation, de disponibilité, de géométrie, de valorisation, de quantités, de numéros de série et de bundles restent actives. Le paramètre de mise en stock des déchets est repris du plan pour le nouveau Repack. Si un contrôle échoue, la requête de soumission échoue et Frappe annule la transaction complète, y compris le changement de docstatus du MCP. Plusieurs brouillons liés sont refusés plutôt que d’en choisir un arbitrairement.

Une exécution déjà complète est reconnue par les séries produites et consommées, pour éviter une seconde consommation. Un brouillon partiel ne peut pas marquer tout le plan comme exécuté. Après succès, `status` vaut `Executed` et `created_stock_entries_json` contient les Stock Entries validées. Le formulaire propose « Repack lié » après validation ; la préparation manuelle d’un brouillon reste disponible avant validation. Aucun ancien plan n’a été exécuté rétroactivement par un script.

## Fichiers

- `mat_reco/material_reconfiguration/doctype/material_cutting_plan/material_cutting_plan.py` : ajout limité du hook `on_submit`.
- `mat_reco/material_reconfiguration/services/mcp_repack.py` : exécution transactionnelle et traçabilité.
- `mat_reco/material_reconfiguration/doctype/material_cutting_plan/material_cutting_plan.js` : accès aux Repack liés après soumission.
- `mat_reco/material_reconfiguration/tests/test_mcp_auto_repack.py` : couverture ciblée, mocks et mouvements natifs avec rollback.

## Vérifications

40 tests réussis sur le site de développement :

- `bench --site erpv15dev.marsavco.com run-tests --app mat_reco --module mat_reco.material_reconfiguration.tests.test_mcp_auto_repack --skip-test-records` : 10 tests (nouveau Repack, brouillon existant, doublons, couverture complète, permissions, conflits comptables, exécution native de la plaque/découpe/chute et rollback sur erreur de Stock Entry).
- Même commande avec `test_mcp_zero_costing` : 8 tests.
- Même commande avec `test_mcp_leftover_status` : 7 tests.
- Même commande avec `test_mcp_compensation_persistence` : 15 tests.

Syntaxe JavaScript et Python, et `git diff --check` vérifiés. Cache du site actualisé et workers web rechargés gracieusement. Les transactions de recette ont été annulées : aucun stock commercial existant n’a été exécuté pour la vérification.
