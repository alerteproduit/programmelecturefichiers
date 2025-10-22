# Programme de normalisation des fichiers

Ce projet fournit un outil Python permettant de normaliser automatiquement des
fichiers tabulaires hétérogènes (CSV, XLSX, TSV…). L'objectif est de regrouper
les intitulés de colonnes variés sous un schéma unique afin d'alimenter le reste
du workflow sans erreur de structure.

## Installation

1. Créez un environnement virtuel Python 3.10+.
2. Installez les dépendances :
   ```bash
   pip install -r requirements.txt
   ```

## Configuration du mapping

Le fichier [`config/column_mappings.yaml`](config/column_mappings.yaml) décrit
les colonnes attendues ainsi que les différentes façons de les reconnaître.
Pour chaque entrée vous pouvez :

- Déclarer autant de synonymes que nécessaire (`synonyms`).
- Ajouter des expressions régulières (`patterns`) capables de repérer de
  nouveaux intitulés inattendus.
- Activer un rapprochement approximatif (`fuzzy_threshold`) pour tolérer des
  fautes de frappe ou des variations légères (valeur entre 0 et 100).
- Spécifier un `dtype` (`string`, `float`, `int`, `date`, `bool`).

Grâce à ces options, un fichier Excel ou CSV avec des noms de colonnes encore
jamais vus mais proches des synonymes déclarés sera rattaché automatiquement à
la bonne colonne normalisée.

## Utilisation

1. Déposez vos fichiers sources dans un dossier, par exemple `data/raw/`.
2. Exécutez la commande suivante pour normaliser tous les fichiers pris en
   charge et générer des fichiers CSV normalisés dans `data/normalized/` :
   ```bash
   python -m normalizer.cli normalize data data/normalized --config config/column_mappings.yaml
   ```

   Options supplémentaires :
   - `--encoding` pour forcer un encodage particulier lors de la lecture des
     fichiers CSV (ex. `latin-1`).
   - `--output-format` pour choisir le format de sortie (`csv` ou `xlsx`).
   - `--verbose` pour afficher des informations détaillées.

Les colonnes connues sont normalisées (noms cohérents, types convertis) et les
colonnes non reconnues sont conservées telles quelles en fin de fichier.
Si plusieurs colonnes d'origine correspondent à la même colonne cible, celle
contenant le plus de valeurs renseignées est choisie automatiquement.

## Exemple

Un fichier CSV d'exemple est fourni dans le dossier `data/`. Vous pouvez tester
la commande suivante :
```bash
python -m normalizer.cli normalize data data/normalized --config config/column_mappings.yaml
```

Les fichiers normalisés se trouveront dans `data/normalized/`.
