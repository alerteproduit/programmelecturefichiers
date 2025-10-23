# programmelecturefichiers

Ce dépôt regroupe le workflow d'alertes produits et la brique de lecture
universelle utilisée à l'étape 5.

## Lecture universelle

Le module `programmelecturefichiers` expose :

- un cœur métier (`normalizer.UniversalNormalizer`) capable de scanner le
  dossier `data/uploads`, détecter les fichiers achats/clients/rappels et
  écrire leurs versions normalisées dans `data/entree` ;
- une CLI (`python -m programmelecturefichiers.cli`) permettant soit d'afficher
  la configuration détectée (`config`), soit de lancer la normalisation
  (`normalize`).

Pour conserver la compatibilité avec les anciens scripts, un alias `normalizer`
a été conservé. Vous pouvez donc indifféremment utiliser :

```bash
python -m programmelecturefichiers.cli normalize --json
# ou
python -m normalizer.cli normalize --json
```

### Pourquoi cette organisation ?

- **Séparation claire des responsabilités** : la logique de normalisation vit
  désormais dans un paquet dédié (`programmelecturefichiers`). Les scripts du
  workflow se contentent d'importer et d'utiliser cette brique commune, ce qui
  simplifie la maintenance.
- **Compatibilité garantie** : le sous-paquet `normalizer` ré-exporte les mêmes
  fonctions/classes. Les commandes historiques (`python -m normalizer.cli`)
  continuent donc de fonctionner tout en profitant du nouveau moteur.
- **Performance et résilience** : `UniversalNormalizer` essaie plusieurs
  combinaisons de formats (CSV/Excel, encodages, séparateurs), normalise les
  colonnes et évite de retraiter les fichiers déjà gérés par l'étape de
  dispatch. Les sorties sont directement utilisables par les étapes IA, SMS et
  archivage.

### Comment s'articulent les modules ?

1. Les scripts du workflow sont lancés via `workflow_alerteproduit.command`.
2. L'étape 5 invoque `python -m normalizer.cli normalize ...`, qui redirige vers
   `programmelecturefichiers.cli`.
3. La CLI résout la configuration projet, instancie `UniversalNormalizer` et
   écrit les fichiers normalisés dans `data/entree`.
4. Les étapes suivantes (matching, alertes, SMS, archivage, apprentissage)
   consomment ces sorties sans adaptation supplémentaire.

## Workflow

Le lanceur `workflow_alerteproduit.command` orchestre les scripts présents dans
`scripts/`. Ceux-ci sont exécutés via `python -m scripts.<module>` (collecte
SFTP, dispatch, normalisation universelle, matching IA, envoi des SMS,
archivage, apprentissage, etc.).
