# MCP UX 2.0 — Vue 3 + Pinia

L’éditeur est intégré au bouton **Interface → UX 2.0**. Le champ du formulaire utilise aussi Vue dès le chargement du plan. La modal ouvre un store Pinia par instance, se démonte à sa fermeture et propose un agrandissement. Le canevas SVG conserve les proportions et les coordonnées originales. Une palette commune conserve les produits finis bleus, les pertes roses hachurées, les chutes grises hachurées et les chutes en L vertes hachurées avant et après application. Chaque canevas possède des identifiants de motifs SVG uniques. Le panneau affiche la sélection ou l’opération en cours ; le menu flottant propose uniquement les actions applicables. Les opérations sont guidées par trois étapes, avec une explication lorsqu’aucune cible ne convient. Les modes Avant / Après / Superposer comparent le résultat proposé à la géométrie initiale ; les pointillés orange montrent l’emprise initiale, les contours violets les régions modifiées. Le centrage sur la sélection agrandit la pièce sans modifier ses coordonnées. Pendant une opération, les détails de la source sont repliables et les boutons Annuler / Confirmer restent hors de la zone défilante du panneau. Sur écran réduit, le panneau se place sous le canevas et peut être masqué.

Depuis `apps/mat_reco/frontend/mcp-ux20-vue` :

```sh
npm install
npm run build
npm test
```

Le build IIFE produit `mat_reco/public/js/mcp_vue_dist/mcp_vue.iife.js` et `mat-reco-mcp-ux20-vue.css`, sans CDN ni variable globale Node `process`.

## API

```js
const instance = window.MatRecoMCPVue.mount(container, {
  tree,
  context: { reference: 'MCP-001', material: 'Verre clair' },
  onApplyPreview: simulationTree => { /* arbre complet confirmé */ },
  onReset: () => {},
  onToggleExpand: () => {}
});
instance.unmount();
const preview = window.MatRecoMCPVue.renderPreview(previewContainer, tree, {
  readonly: false, // éditeur pour un document brouillon
  onApplyPreview: simulationTree => {}
});
preview.unmount();
```

`onApplyPreview` reçoit l’arbre et un second argument `{pendingIncidents, documentVersion}`. Le bridge réel utilise maintenant Python pour prévisualiser, préparer les lignes de `Material Plan Incidents`, les ajouter à la table du formulaire puis appeler `frm.save()`. Il recharge ensuite le résultat effectif produit par Python. Les dimensions retirées de Single sont enregistrées dans `remarks` et reportées dans le nœud effectif. Les incidents restent modifiables en Retour Terrain jusqu’au Submit.

Les simulations JS restent disponibles pour les tests autonomes et le mode de compatibilité sans API. Elles ne constituent pas une validation métier. Les champs JSON effectifs ne sont pas écrits directement par Vue et aucun Stock Entry/Serial No n’est créé par une action graphique.

Voir [le correctif Appliquer et les résultats de tests](../../docs/MCP_UX20_APPLY_INCIDENTS.md) pour le contrat de sauvegarde, les fichiers et les limites de recette.

## Géométrie prise en charge

- Move : placement sans rotation dans un rectangle disponible, soustraction réelle de la destination et création de régions libres à l’origine. Navigation interplaques pendant le choix de cible.
- Merge : deux chutes/déchets dont l’union est exactement rectangulaire, sans recouvrement. La première chute sélectionnée est la source qui s’étend et conserve ses identifiants (`id`, `node_id`), son libellé et ses métadonnées. Si la seconde chute ou le déchet adjacent dépasse la source, seule sa bande alignée est récupérée ; son reste est conservé avec son type initial. Une extension partielle dépend donc de l’ordre de sélection : la source ne change jamais implicitement entre deux chutes. Pour un déchet sélectionné avant une chute, la chute existante reçoit la matière récupérée comme auparavant. Deux déchets fusionnés restent un déchet rouge.
- Single : deux chutes dont l’union forme un L avec une encoche supérieure gauche. Les régions visuelles et les encoches historiques ne sont jamais représentées comme de la matière disponible.
- Resize : réduction positive d’un produit fini ou d’un déchet rectangulaire. Les régions résiduelles d’un déchet restent rouges ; aucune chute n’est créée artificiellement. L’agrandissement et le redimensionnement des régions avec encoche sont refusés.
- Destroy : produit fini ou déchet, avec conservation de l’emprise comme zone détruite et indisponible, après confirmation locale.

Les formes non prises en charge sont refusées avec « Aperçu non disponible » ; aucune validation Python n’est revendiquée. Les simulations demandent des coordonnées millimétriques et des identifiants uniques dans le JSON. Le repli classique est conservé si Vue ne démarre pas ; ses opérations refusent de produire un résultat lorsque le moteur fiable est inaccessible.

## Vérifications exécutées le 13 octobre 2026

- `npm install` : réussi, audit sans vulnérabilité.
- `npm run build` : réussi, assets IIFE et CSS aux chemins attendus.
- `npm test` : 23 tests réussis (conservation de surface, absence de recouvrement, réduction, destruction, fusion, L historique, transitions Pinia, historique avec embranchement, comparaison sans mutation, opérations sur déchets, fusion partielle chute/déchet, identité de la chute source et conservation des restes de la chute cible).
- Syntaxe JS du pont et du bundle : vérifiée avec `node --check`.
- Chromium / Playwright : cinq actions, choix de cible, annulation, confirmation, réinitialisation, application au rendu éditable jusqu’au Submit, navigation, zoom, encoche historique, bornes du menu et absence de débordement à 1280/800/480 px, montage/démontage et deux ouvertures/fermetures via une API Dialog Frappe simulée. Vérification supplémentaire des boutons et raccourcis Annuler/Rétablir, de la comparaison Avant/Après/Superposer, du centrage, de l’absence de cible, de la réouverture automatique du panneau et de la fraîcheur de l’aperçu. Déchets rouges : menu Merge/Resize/Destroy, fusion partielle dans les deux ordres, dimensions résultantes, annulation/rétablissement et préservation du reste rouge. Fusion chute/chute : extension partielle, maintien de l’identifiant initial et refus d’inverser implicitement la source. Le test dédié `preview-lifecycle.cjs` vérifie la palette dès l’initialisation du formulaire, l’édition après application et refresh brouillon, la reprise du dernier état et le verrouillage au Submit avec opération en attente. Aucune erreur JavaScript ; JSON et documents métier inchangés.
- Captures de contrôle : `/tmp/mcp-ux20-editor.png`, `/tmp/mcp-ux20-comparison.png` , `/tmp/mcp-ux20-waste-merge.png` et `/tmp/mcp-ux20-leftover-merge.png`.

Pour rejouer le test navigateur avec une installation Playwright existante :

```sh
PLAYWRIGHT_MODULE=/chemin/vers/node_modules/playwright node tests/browser.cjs
PLAYWRIGHT_MODULE=/chemin/vers/node_modules/playwright node tests/preview-lifecycle.cjs
```

La recette sur un document réel dans une session ERPNext authentifiée reste à faire. Les tests Dialog utilisent une API simulée, sans accès aux données métier du site.

## Fichiers de cette intervention

Modifiés dans ce frontend :

- `src/main.js`
- `src/App.vue`
- `src/components/CuttingCanvas.vue`
- `src/stores/cutting.js`
- `src/lib/geometry.js`
- `README.md`

Créés :

- `src/components/EditorHeader.vue`
- `src/components/SheetNavigator.vue`
- `src/components/ContextMenu.vue`
- `src/components/SelectionPanel.vue`
- `src/components/ActionPreview.vue`
- `src/components/PreviewFooter.vue`
- `src/lib/preview.js`
- `src/lib/palette.js`
- `src/styles/editor.css`
- `tests/geometry.test.mjs`
- `tests/browser.cjs`
- `tests/preview-lifecycle.cjs`

Modifiés dans l’application (chemins depuis `apps/mat_reco`) :

- `mat_reco/material_reconfiguration/doctype/material_cutting_plan/ui/mcp_ux20_modal.js`
- `mat_reco/material_reconfiguration/doctype/material_cutting_plan/material_cutting_plan.js` : chargement partagé du bundle, initialisation du rendu Vue, verrouillage local après Submit ; changements et handlers métier préexistants conservés.
- `mat_reco/public/js/mcp_ux20.bundle.js` : portion modal synchronisée avec sa source, repli conservé.

Assets recompilés :

- `mat_reco/public/js/mcp_vue_dist/mcp_vue.iife.js`
- `mat_reco/public/js/mcp_vue_dist/mat-reco-mcp-ux20-vue.css`

Les sources Vue et plusieurs fichiers UX étaient déjà non suivis par Git au début de cette intervention. Aucun service Python modifié.
