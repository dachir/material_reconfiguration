# Manuel utilisateur mat_reco — version 0.1

Audience validée : opérateurs atelier et responsables de stock.

Le contenu couvre les DocTypes, services, hooks, fixtures et l’atelier Vue du
module. Les screenshots du composant Vue et du dialogue Repack sont réalisés
avec des données fictives. Les formulaires Receipt Plan, MCP, Issue Plan et
Repack sont des illustrations reconstituées et explicitement identifiées.
Aucun mouvement métier n’a été créé ou soumis pour ce manuel.

Les livrables sont dans `mat_reco/public/manuals/mat_reco-v0-1/` et servis par
`/assets/mat_reco/manuals/mat_reco-v0-1/`. Utiliser une nouvelle version du dossier
pour une diffusion corrigée. Le HTML et le PDF de lecture sont générés à partir
du même contenu que le Word ; le PDF est rendu par Chromium, pas par Word.

## Regénérer

Les dépendances de document sont temporaires : `python-docx`, Pillow, lxml.
`pypdf` et `pymupdf` permettent le contrôle de la version PDF. Ne pas les ajouter
aux dépendances métier de l’application.

1. `node docs/user_manual/capture_manual.cjs`
2. `env/bin/python apps/mat_reco/docs/user_manual/build_flowcharts.py`
3. `node docs/user_manual/render_flowcharts.cjs`
4. `PYTHONPATH=/tmp/mat_reco_manual_deps env/bin/python apps/mat_reco/docs/user_manual/build_manual.py`
5. `node docs/user_manual/render_manual.cjs`

Adapter les chemins absolus Playwright et les dépendances temporaires si
l’environnement change. Les scripts Node se lancent depuis le dossier de l’app ;
les commandes Python avec `env/bin/python` depuis le bench.

## Contrôles réalisés

- 29 chapitres ; 14 figures ; 2 flowcharts.
- DOCX : intégrité ZIP, parse des XML, 16 images embarquées, 29 signets uniques.
- PDF de lecture : 31 pages, aucun débordement sur une page supplémentaire,
  contrôle de la présence de chaque chapitre et inspection visuelle d’un
  échantillon de pages.
- Figures source vérifiées dans le navigateur, sans erreur JavaScript.
- Téléchargements servis sur le site de développement via HTTP, contrôle de
  taille et SHA-256 du DOCX téléchargé.

## Points à valider avec l’utilisateur

Le circuit de soumission MCP / Repack et les responsabilités ne sont pas
inventés comme des workflows actifs. Material Production Plan n’a pas
d’automatisation dans son contrôleur actuel. Les scripts et formats livrés
nécessitent une vérification de leur activation sur le site cible. Les captures
reconstituées pourront être remplacées par des captures de session ERPNext.
