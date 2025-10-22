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
les colonnes attendues ainsi que leurs synonymes possibles.
Adaptez la clé `columns` à vos propres données. Chaque colonne peut également
spécifier un `dtype` (`string`, `float`, `int`, `date`, `bool`).

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

## Exemple

Un fichier CSV d'exemple est fourni dans le dossier `data/`. Vous pouvez tester
la commande suivante :
```bash
python -m normalizer.cli normalize data data/normalized --config config/column_mappings.yaml
```

Les fichiers normalisés se trouveront dans `data/normalized/`.
