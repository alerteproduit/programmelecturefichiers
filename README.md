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

## Workflow

Le lanceur `workflow_alerteproduit.command` orchestre les scripts présents dans
`scripts/`. Ceux-ci sont exécutés via `python -m scripts.<module>` (collecte
SFTP, dispatch, normalisation universelle, matching IA, envoi des SMS,
archivage, apprentissage, etc.).
