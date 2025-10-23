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

### Pré-requis Python (macOS / Python 3.9)

Les bibliothèques IA récentes ciblent Python ≥ 3.10 et NumPy 2.x. Si vous
restez sur Python 3.9 (configuration historique du workflow), il faut figer les
versions compatibles avant de lancer le pipeline :

```bash
pip install -r requirements-workflow.txt
```

Ce fichier impose notamment `numpy<2` (pour éviter l'erreur *"A module that was
compiled using NumPy 1.x cannot be run in NumPy 2.0.2"*), `transformers<4.38`
(dernier release compatible Python 3.9) et une version de `torch` cohérente.

### Erreurs fréquentes et correctifs

| Symptôme observé pendant le workflow | Solution recommandée |
| --- | --- |
| `ModuleNotFoundError: No module named 'normalizer'` à l'étape 5 | Mettre à jour le dépôt (alias `normalizer` fourni) ou lancer `python -m programmelecturefichiers.cli ...`. |
| `ImportError: cannot import name 'NormalizationResult'` | Le paquet a été partiellement chargé. Relancer le workflow après mise à jour : les imports sont désormais paresseux et compatibles avec l'alias `normalizer`. |
| `A module that was compiled using NumPy 1.x cannot be run in NumPy 2.0.2` | Installer les dépendances via `pip install -r requirements-workflow.txt` (pins `numpy<2`). |
| `TypeError: unsupported operand type(s) for |: 'type' and 'NoneType'` dans `transformers` | Même correctif que ci-dessus : la version épinglée (<4.38) conserve une syntaxe compatible Python 3.9. |
| `FileNotFoundError: .../data/entree/achats.csv introuvable` à l'étape 8 | Vérifier que des fichiers achats/clients sont présents dans `data/uploads/<enseigne>/` avant le lancement. Sans matière, les étapes 4-5 ne produisent aucun CSV. |
| `BREVO_API_KEY manquante` à l'étape 9 | Définir la clé API Brevo dans `config/.env` ou dans l'environnement (`export BREVO_API_KEY=...`). |
