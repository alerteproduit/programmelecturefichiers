#!/bin/bash
# === Workflow AlerteProduit (Étapes 1 & 2 + dispatcher) ===
# - Log ping garanti (executions.jsonl)
# - Collecte SFTP -> Rangement par enseigne -> MAJ RappelConso -> Dispatcher -> Normalisation
# - Exécution des scripts en mode module (fiable)
set -uo pipefail

# 0) Contexte projet
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DEFAULT_PROJ="$HOME/Desktop/AlerteProduit/alerteproduit_intelligent"
if [ -d "$DEFAULT_PROJ" ]; then
  PROJ="$DEFAULT_PROJ"
else
  PROJ="$SCRIPT_DIR"
  echo "ℹ️  Utilisation du dépôt courant comme racine du projet: $PROJ"
fi
cd "$PROJ" || { echo "❌ Projet introuvable: $PROJ"; exit 1; }

# 1) Batch + logs (Étape 1)
export BATCH_ID="$(date +'%Y%m%d-%H%M%S')-$$"
mkdir -p web_flask/logs
echo "🆔 Batch: $BATCH_ID"

# 2) Assurer le paquet Python 'scripts'
[ -d scripts ] || mkdir -p scripts
[ -f scripts/__init__.py ] || touch scripts/__init__.py

# 3) Choisir le bon Python (venv si présent, sinon système)
if [ -x "$PWD/venv310/bin/python" ]; then
  PYBIN="$PWD/venv310/bin/python"
elif [ -x "$PWD/venv/bin/python" ]; then
  PYBIN="$PWD/venv/bin/python"
else
  PYBIN="$(which python3)"
  echo "⚠️  VENV introuvable, usage de: $PYBIN"
fi

# 4) Rendre le paquet 'scripts' visible + config env
export PYTHONPATH="$PWD"

# 👉 Source officielle RappelConso (Excel complet).
#    Tu peux changer cette URL si tu as ton propre miroir.
export RAPPELS_SOURCE_URL="https://rappel.conso.gouv.fr/uc/api/excel"

# (Optionnel) Ajuster le seuil IA sans toucher au code
# export AP_SEUIL_IA="0.58"

# 5) Ping log garanti (ÉTAPE 1)
"$PYBIN" - <<'PY'
from scripts.log_utils import log_exec
log_exec("ping", note="etape1_ok")
print("✅ Log ping écrit.")
PY

# 6) Helper: exécuter un module seulement si le fichier existe
runmod() {
  local mod="$1"
  local file="scripts/${mod//./\/}.py"
  shift || true
  if [ -f "$file" ]; then
    "$PYBIN" -m "scripts.$mod" "$@"
  else
    echo "⚠️  Script manquant: $file — SKIP"
    return 0
  fi
}

# ----------------- PIPELINE ORDONNÉ -----------------

echo "🚀 [1/10] Collecte SFTP (enseignes)..."
runmod auto_collecte_ia || echo "⚠️  Étape 1: continuité malgré erreur"

echo "🚀 [2/10] Rangement par enseigne..."
runmod ranger_par_enseigne || echo "⚠️  Étape 2: continuité malgré erreur"

# ⬇️ On met à jour RappelConso AVANT le dispatch
echo "🚀 [3/10] Mise à jour des rappels officiels (RappelConso)..."
echo "   ↪️ RAPPELS_SOURCE_URL=$RAPPELS_SOURCE_URL"
runmod alerte_auto_rappels || echo "⚠️  Étape 3: continuité malgré erreur"

echo "🚀 [4/10] Dispatcher vers data/entree..."
runmod dispatcher_simple || echo "⚠️  Dispatcher: continuité malgré erreur"

echo "🚀 [5/10] Normalisation des fichiers (lecture universelle)..."
runmod lecture_universelle || echo "⚠️  Étape 5: continuité malgré erreur"

echo "🚀 [6/10] Pré-calcul embeddings IA..."
if [ -f "data/ia_cache/achats_embeddings.npy" ] && [ -f "data/ia_cache/rappels_embeddings.npy" ]; then
  echo "✅ Cache IA détecté → Skip recalcul."
else
  runmod precompute_achats_embeddings
  runmod precompute_rappel_embeddings
fi

echo "🚀 [7/10] Matching IA (exact/EAN/NLP)..."
runmod moteur_matching || echo "⚠️  Étape 7: continuité malgré erreur"

echo "🚀 [8/10] Construction des alertes..."
runmod traitement_alerte_final || echo "⚠️  Étape 8: continuité malgré erreur"

echo "🚀 [9/10] Envoi des SMS (Brevo)..."
runmod envoyer_sms || echo "⚠️  Étape 9: continuité malgré erreur"

echo "🚀 [10/10] Archivage + apprentissage (IA)..."
runmod archiver_fichiers
runmod correction_apprentissage
runmod ia_suggestions

echo "🧮 Consolidation des KPIs pour le dashboard..."
"$PYBIN" -m scripts.kpis_consolidate || echo "⚠️ Consolidation: continuité malgré erreur"

echo "🎉 Workflow terminé (tolérance aux erreurs activée)."
