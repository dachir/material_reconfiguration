# Frontend complet MCP UX 2.0 — Vue 3 + Pinia

Ce ZIP contient le dossier `frontend/mcp-ux20-vue` complet, reconstruit à partir de la fondation Vue et du dernier correctif de raccordement. Aucun fichier Python ni module Frappe en dehors de frontend.

## Remplacement

Extraire le répertoire `frontend` à la racine de `apps/mat_reco/` (structure : `apps/mat_reco/frontend/mcp-ux20-vue/package.json`).

Depuis `~/frappe-bench/apps/mat_reco/frontend/mcp-ux20-vue` :

```bash
rm -rf node_modules
npm install
npm run build
```

Si Vite renvoie `Permission denied`, vérifier les droits du répertoire (éviter de recopier `node_modules` d'un autre OS).

Le `vite.config.js` pointe vers `apps/mat_reco/mat_reco/public/js/mcp_vue_dist`, conformément au lien des assets observé sur le serveur.

## Périmètre

Le ZIP contient seulement les sources frontend. Le chargement du bundle dans la modal Frappe dépend séparément des fichiers `mcp_ux20_modal.js` et `mcp_ux20.bundle.js` fournis auparavant. Les règles métier Python ne sont pas concernées.

## Vérification

Présence des fichiers et des imports locaux contrôlée. La compilation npm n'a pas pu être exécutée dans l'environnement de préparation car les dépendances npm ne sont pas accessibles hors ligne ; exécuter `npm install` et `npm run build` sur le serveur.
