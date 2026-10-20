### Material Reconfiguration

This app purpose is to help splitting an item into chunck

### Installation

You can install this app using the [bench](https://github.com/frappe/bench) CLI:

```bash
cd $PATH_TO_YOUR_BENCH
bench get-app $URL_OF_THIS_REPO --branch develop
bench install-app mat_reco
```

### Contributing

This app uses `pre-commit` for code formatting and linting. Please [install pre-commit](https://pre-commit.com/#installation) and enable it for this repository:

```bash
cd apps/mat_reco
pre-commit install
```

Pre-commit is configured to use the following tools for checking and formatting your code:

- ruff
- eslint
- prettier
- pyupgrade

### CI

This app can use GitHub Actions for CI. The following workflows are configured:

- CI: Installs this app and runs unit tests on every push to `develop` branch.
- Linters: Runs [Frappe Semgrep Rules](https://github.com/frappe/semgrep-rules) and [pip-audit](https://pypi.org/project/pip-audit/) on every pull request.


### License

mit
# material_reconfiguration

### Documents imprimables A4

Les formats `Mat Reco A4 - <DocType>` couvrent les chantiers, sections,
modèles de sections, études techniques, plans de découpe/production/réception/sortie,
reconfigurations, fabrications/refabrications, devis, commandes, mouvements de stock,
contrôles qualité et fiches de série. Ils sont installés automatiquement après
installation ou migration. Pour une installation ciblée sur un site existant :

```sh
bench --site <site> execute mat_reco.printing.install_print_formats
bench --site <site> clear-cache
```

Dans Vue, utiliser « Imprimer A4 » ; depuis un formulaire ERPNext, sélectionner
le format dans l’aperçu d’impression. Les modifications doivent être enregistrées
avant impression. Dans l’éditeur de découpe, le bouton imprime explicitement le
plan enregistré, et non la simulation locale. Le plan effectif enregistré prévaut
sur la planification initiale ; les encoches des chutes en L sont conservées.
Les schémas sont sans échelle. Les documents longs occupent plusieurs pages A4.

Les droits de lecture, d’impression et les restrictions de champs Frappe restent
appliqués. L’installation ne modifie ni les rôles ni les formats par défaut.
La vue stock verre permet d’imprimer la fiche de la série sélectionnée ; elle ne
crée pas de nouveau document de stock.

Validation : `python -m unittest mat_reco.material_reconfiguration.tests.test_a4_printing`,
puis `npm test` et `npm run build` dans les frontends atelier et découpe,
et `npm run build` dans le frontend stock verre.
