# Compensation des découpes — COMP-01 à COMP-04

## État de la livraison

Le code des quatre lots est intégré à MCP UX 2.0. Il reste à valider une véritable
sauvegarde transactionnelle sur le site de développement avant de considérer la
recette complète comme terminée. Aucune donnée métier n'a été sauvegardée ou
soumise pendant cette livraison ; aucun service de production n'a été redémarré.

## COMP-01 — Besoins résiduels

Le service central distingue le besoin commercial `piece_uid`, l'opération
physique `id` et le reçu d'une production dans un Repack soumis. Une opération
planifiée réserve un besoin sans constituer une preuve de réalisation. Plusieurs
casses successives restent plusieurs événements pour un seul besoin résiduel.
Les dimensions effectives, l'article et l'épaisseur sont contrôlés.
Les bandes détruites par Resize ne sont pas des pièces unitaires cassées.

Fichiers :

- `mat_reco/material_reconfiguration/services/mcp_compensation_service.py`
- `mat_reco/material_reconfiguration/tests/test_mcp_compensation_service.py`
- `docs/MCP_COMP_01.md` (audit initial, antérieur aux lots suivants)

13 tests de réconciliation et permissions passent. Les anciens 21 tests Python
Move, Merge, Single, Resize et Destroy passent également.

## COMP-02 — Géométrie interne

Le complément utilise `_run_rectpack_plan`, `_compute_free_rectangles`,
`_classify_free_region`, `single_geometry.available_regions` et le validateur
physique existant. Aucun moteur de packing parallèle n'est créé.
Les régions originales restent en coordonnées absolues. Seules les chutes
`leftover` non déjà sorties en Repack sont exploitables. Ni `waste`, ni les
empreintes détruites, ni une encoche retirée ne sont réutilisées.
Les pièces existantes restent identiques dans la proposition.

Les dimensions sont converties en millièmes de millimètre avant l'adaptateur
rectpack entier : les besoins sont arrondis vers le haut, les régions vers le
bas. Le trait de coupe est réservé entre les nouvelles pièces et les bandes
correspondantes sont des régions détruites exclues du Repack.
Un Single utilisé est décomposé en régions physiques ; un bras non utilisé reste
une région disponible, pas un deuxième Serial No.

Fichiers nouveaux :

- `mat_reco/material_reconfiguration/services/mcp_compensation_geometry.py`
- `mat_reco/material_reconfiguration/tests/test_mcp_compensation_geometry.py`

11 tests passent : faisabilité dimensionnelle, rotation, décimales, kerf,
collisions, conservation des surfaces, immutabilité, compensation partielle,
chutes soumises et encoche Single. Ce lot a été validé avant l'ajout du stock.

## COMP-03 — Stock et Vue

Le service réutilise `stock_candidate_service.get_available_cutting_bins`.
Il contrôle la société, le dépôt, l'article admissible et ses variantes, le statut
Active du Serial No, les engagements dans d'autres MCP et l'épaisseur physique.
Les Serial No historiques sans épaisseur utilisent `Item.custom_thickness_mm`,
champ vérifié sur le site de développement. Une épaisseur inconnue reste exclue.
Les matières incompatibles sont signalées et leur sélection est désactivée.

Les priorités sont strictes : interne, chute stock, plaque entière. À même
priorité, le choix couvre le plus d'unités avec une source puis limite le résidu.
Cette heuristique favorise une matière couvrant tous les besoins plutôt que
plusieurs petites matières ; elle ne garantit pas un optimum combinatoire.
Une matière sélectionnée mais inutilisée n'entre jamais dans le résultat.
Un choix qui écarte une source prioritaire exige une justification.

Sur demande de l'utilisateur, la compensation reprend désormais le même écran
noir que l'atelier : `EditorHeader`, `SheetNavigator`, `CuttingCanvas`, la grille
et `PreviewFooter` restent montés. Le bouton **Compenser** est groupé avec
**Réinitialiser** sur la même ligne. La compensation change les données affichées
et remplace seulement le contenu du panneau d'information droit par les besoins,
les matières disponibles et le résultat. Les instructions numérotées, les grandes
cartes et la page blanche séparée ont été retirées.

Une seule plaque s'affiche à gauche, y compris les nouvelles plaques stock
proposées, avec la navigation et le zoom existants. Les remplacements proposés
sont verts dans le canvas d'origine. Les découpes ordinaires sont désactivées
pendant cette prévisualisation. Les chiffres viennent de Python, sans déclarer
une pièce réalisée parce qu'elle ne porte pas d'incident.

Le bouton est disponible en Retour Terrain modifiable, avec un plan enregistré
et sans incident local non sauvegardé. Le mode manuel choisit les sources ; les
positions restent calculées par Python. Modifier les sources invalide la
proposition. Le stock reste dans la zone d'information à droite.

**Annuler** supprime la proposition et ramène à l'atelier sans sauvegarde.
**Valider la compensation** attend la confirmation serveur puis revient à
l'atelier avec le résultat enregistré. La plaque initiale, le zoom et l'état du
panneau sont restaurés. Le rafraîchissement Frappe garde la même modal ouverte.
Un conflit conserve le mode compensation, recharge les besoins et invalide la
proposition précédente.

Nouveaux fichiers :

- `frontend/mcp-ux20-vue/src/components/CompensationPanel.vue`
- `frontend/mcp-ux20-vue/tests/compensation.test.mjs`
- `frontend/mcp-ux20-vue/tests/compensation-browser.cjs`
- `frontend/mcp-ux20-vue/tests/fixtures/compensation.json` (données synthétiques)
- `mat_reco/material_reconfiguration/tests/test_mcp_compensation_priority.py`

Fichiers modifiés :

- `frontend/mcp-ux20-vue/src/stores/cutting.js`
- `frontend/mcp-ux20-vue/src/services/frappeClient.js`
- `frontend/mcp-ux20-vue/src/App.vue`
- `frontend/mcp-ux20-vue/src/components/EditorHeader.vue`
- `frontend/mcp-ux20-vue/src/components/SheetNavigator.vue`
- `frontend/mcp-ux20-vue/src/components/CuttingCanvas.vue`
- `frontend/mcp-ux20-vue/src/components/PreviewFooter.vue`
- `frontend/mcp-ux20-vue/src/main.js`
- `mat_reco/material_reconfiguration/doctype/material_cutting_plan/ui/mcp_ux20_modal.js`
- `mat_reco/material_reconfiguration/doctype/material_cutting_plan/material_cutting_plan.js`
- `mat_reco/public/js/mcp_ux20.bundle.js` (module modal synchronisé)
- `mat_reco/public/js/mcp_vue_dist/mcp_vue.iife.js`
- `mat_reco/public/js/mcp_vue_dist/mat-reco-mcp-ux20-vue.css`

11 tests Python de priorité passent. Les 33 tests Node passent, dont 10 nouveaux
pour Pinia/API. Le test Playwright de compensation passe sur le bundle réellement
monté par le chargeur Frappe : besoins, calcul, conflit, application confirmée,
rechargement du formulaire, absence de double application, navigation par plaque,
retour à l’atelier après annulation/validation et absence de débordement mobile.
Il utilise des réponses API isolées calculées sur une fixture Python.
Le test navigateur existant de sauvegarde Single passe également.

## COMP-04 — Persistance, soumission et Repack

La confirmation prend un identifiant de proposition et une version signée du
MCP. Le serveur recalcule la proposition, verrouille le MCP et les Serial No
réellement utilisés, contrôle le stock par des lectures sous verrou, puis
revalide avant d'appeler une unique sauvegarde Frappe. Une erreur revient au
savepoint de la transaction. Aucun commit explicite ni Stock Entry.submit
n'est ajouté.

Les placements reçoivent des identifiants stables `CP-…`. Le résultat contient
`compensation_events` avec besoin, casse(s), remplacement, géométrie, matière,
MCP, opérateur, date, options et version de référence. Les régions résiduelles
reçoivent également des identifiants stables. Les dates commerciales sont
sérialisées correctement.

Aucun nouveau DocType ni champ n'est nécessaire : le journal est enregistré dans
le champ métier existant `effective_result_json` ; les matières supplémentaires
utilisées sont des lignes du `MCP Stock Candidate` existant ; la table
`Effective MCP Sheet` est synchronisée pour le circuit Repack et sa traçabilité.
Il ne s'agit pas d'un JSON temporaire Vue : la sauvegarde est celle du document
Frappe, avec les validations et les child tables existantes.

Après la première compensation, le hook utilise le plan enregistré en base comme
référence. Il interdit la réécriture du journal et la modification des incidents
historiques, applique seulement les nouveaux incidents, conserve les opérations
soumises et ne lance plus de recalcul global. Le résultat de simulation original
reste conservé. Les paramètres physiques historiques ne peuvent plus changer.

Le changement nécessaire dans `before_save` est explicite : en Retour Terrain,
la sauvegarde d'un incident ne fabrique plus automatiquement les remplacements.
Le moteur historique reçoit `plan_missing_pieces=False` ; il applique toujours
les cinq actions et leurs règles géométriques. Le remplacement passe désormais
par calcul puis confirmation. La planification initiale garde son chemin existant
et les autres appelants du moteur gardent son comportement par défaut.
Sans ce changement, une simple sauvegarde de Destroy aurait déjà créé un
remplacement et court-circuité le module demandé.

La soumission d'un MCP Retour Terrain bloque les besoins sans placement conforme
et les incohérences de couverture. Aucune règle de clôture partielle n'est créée.
Un placement planifié ne devient pas pour autant une production prouvée : le
Repack reste son circuit comptable de confirmation.

Pour les MCP compensés, le Repack ignore les entrées déjà consommées et les
sorties déjà produites dans un Repack soumis. Les matières inutilisées ne sont
pas ajoutées. Les fonctions historiques d'articles, dépôts, dimensions, surfaces,
bundles et valorisation sont conservées. Aucun Serial No sortant ni mouvement de
stock n'est créé pendant la prévisualisation ou l'application de la compensation.

Fichiers modifiés :

- `mat_reco/material_reconfiguration/services/mcp_compensation_service.py`
- `mat_reco/material_reconfiguration/services/cutting_plan_service.py`
- `mat_reco/material_reconfiguration/services/repack_draft_service.py`
- `mat_reco/material_reconfiguration/doctype/material_cutting_plan/material_cutting_plan.py`

Fichier nouveau :

- `mat_reco/material_reconfiguration/tests/test_mcp_compensation_persistence.py`

15 tests passent : conservation après relecture, nouvelle casse du remplacement,
immutabilité des opérations soumises, journal serveur, sauvegarde unique,
rollback, conflit MCP/stock, historique compatible, couverture à la soumission,
Repack sans doublons, dates et épaisseurs historiques.

## API

Préfixe : `mat_reco.material_reconfiguration.services.mcp_compensation_service`.

| Méthode | Usage | Écriture |
| --- | --- | --- |
| `get_compensation_requirements(material_cutting_plan_name)` | Besoins unitaires et état des opérations | Non |
| `load_compensation(mcp_name)` | Besoins, plan, sources et version | Non |
| `preview_compensation(mcp_name, strategy, selected_sources, override_reason)` | Proposition Python et bilan résiduel | Non |
| `apply_compensation(mcp_name, proposal_id, document_version, strategy, selected_sources, override_reason)` | Revalidation et sauvegarde du MCP | Oui, transactionnelle |

L'API d'application accepte des intentions et une signature, jamais un plan
Vue arbitraire à sauvegarder. `strategy` vaut `automatic` ou `manual`.

## Vérifications exécutées

Depuis `/home/marsavco/frappe-bench` :

```sh
env/bin/python -m unittest discover -s apps/mat_reco/mat_reco/material_reconfiguration/tests -p 'test_mcp*.py'
npm --prefix apps/mat_reco/frontend/mcp-ux20-vue test
npm --prefix apps/mat_reco/frontend/mcp-ux20-vue run build
PLAYWRIGHT_MODULE=/home/marsavco/frappe-bench/apps/crm/node_modules/playwright node apps/mat_reco/frontend/mcp-ux20-vue/tests/compensation-browser.cjs
```

Résultats : **71 tests Python**, **33 tests Node**, test Playwright compensation et
régression navigateur Single réussis. Build Vite réussi, 31 modules.
`compileall`, vérification syntaxique JS et `git diff --check` passent.

Le site `erpv15dev.marsavco.com` a été vérifié en lecture seule : application
installée, API accessible, métadonnées des trois DocTypes et sources réelles.
Un contrôle supplémentaire utilise les données et métadonnées réelles mais
interdit `save`, `insert`, `set_value` et toute requête SQL autre qu'une lecture.
En mémoire, il valide Destroy, besoin résiduel, remplacement interne sans matière
supplémentaire, sérialisation du journal et construction des lignes Repack
contenant le remplacement. Les données enregistrées restent identiques.

## Recette et limites restantes

| Scénario | Validation obtenue |
| --- | --- |
| A — Chute interne suffisante | Tests géométriques et contrôle réel en mémoire, zéro matière supplémentaire |
| B — Chute stock | Test de priorité, une matière supplémentaire |
| C — Plaque entière | Test du dernier recours |
| D — Partielle | Besoins résiduels conservés ; contrôle de soumission testé |
| E — Nouvelle casse | Un besoin, plusieurs opérations cassées, nouvelle identité de remplacement |
| F — Chute en L | Tests interne, stock, sélection manuelle et encoche interdite |
| G — Repack | Constructeurs de lignes testés, contrôle réel sans écriture ; coûts finaux non validés par un Stock Entry réel |
| H — Rechargement | Journal et coordonnées préservés dans les tests isolés ; sauvegarde DB réelle en attente |
| I — Conflit | Version/stock/rollback testés ; conflit et rechargement testés dans le navigateur |

La revue automatique a refusé le test qui aurait sauvegardé et appliqué une
compensation à un MCP de développement existant comme Administrator, malgré un
rollback prévu, en raison du risque de mutation persistante de données métier.
Ce test n'a pas été exécuté ni contourné. Une autorisation utilisateur explicite
est nécessaire pour cette recette en base. Les doubles transactions concurrentes
réelles, le redémarrage serveur et les coûts finaux ERPNext restent aussi hors des
vérifications exécutées. La recette complète ne doit pas être annoncée acquise.

## Compilation et déploiement

Aucune migration de schéma ni nouvelle dépendance n'est introduite. Déployer les
sources Python, les sources Vue, le script DocType et le bundle modal synchronisé
ensemble. La version de cache est `20261014_move_cursor_1`.

Le bundle Vue se compile avec `npm --prefix … run build` ci-dessus. Les assets
actifs sont sous `apps/mat_reco/mat_reco/public/js/`, accessibles par le lien
`sites/assets/mat_reco`. Le répertoire homonyme `apps/mat_reco/public/` n'est pas
la cible de ce lien et n'est pas le livrable actif.

Si `mcp_ux20_modal.js` est modifié à nouveau, synchroniser son bloc après le
marqueur `/* UX 2.0 modal integration */` dans `mcp_ux20.bundle.js` avant diffusion.
Redémarrer ensuite les workers web par le circuit d'exploitation habituel et
rafraîchir les caches du site cible. Ces actions n'ont pas été exécutées ici.
Aucune compensation ne soumet automatiquement le MCP ou un Stock Entry.
