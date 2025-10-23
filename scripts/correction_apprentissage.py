import json
import os
import pandas as pd
from datetime import datetime

# === CONFIGURATION ===
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
LOGS_DIR = os.path.join(BASE_DIR, "logs")

FICHIER_CORRECTIONS = os.path.join(DATA_DIR, "corrections.json")
FICHIER_LEARNING = os.path.join(DATA_DIR, "learning.json")
FICHIER_SUGGESTIONS = os.path.join(LOGS_DIR, "suggestions_ia.csv")
FICHIER_LOG_CORRECTIONS = os.path.join(LOGS_DIR, "corrections_appliquees.csv")

# === Création des fichiers si absents ===
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(LOGS_DIR, exist_ok=True)

for file_path, default_content in [
    (FICHIER_CORRECTIONS, {}),
    (FICHIER_LEARNING, {}),
    (FICHIER_SUGGESTIONS, pd.DataFrame(columns=["produit_original", "suggestion_1"]))
]:
    if not os.path.exists(file_path):
        if file_path.endswith(".json"):
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(default_content, f, indent=4, ensure_ascii=False)
        else:
            default_content.to_csv(file_path, index=False)

# === Fonctions utilitaires ===
def charger_json(fichier):
    if os.path.exists(fichier):
        try:
            with open(fichier, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return {}
    return {}

def sauvegarder_json(fichier, data):
    with open(fichier, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

def charger_corrections():
    return charger_json(FICHIER_CORRECTIONS)

def sauvegarder_corrections(data):
    sauvegarder_json(FICHIER_CORRECTIONS, data)

def charger_learning():
    return charger_json(FICHIER_LEARNING)

def sauvegarder_learning(data):
    sauvegarder_json(FICHIER_LEARNING, data)

def charger_suggestions_ia():
    """
    Lit suggestions_ia.csv si présent → dict { produit_original: suggestion_1 }
    """
    if os.path.exists(FICHIER_SUGGESTIONS):
        try:
            df = pd.read_csv(FICHIER_SUGGESTIONS)
            return dict(zip(df["produit_original"].str.lower(), df["suggestion_1"]))
        except:
            return {}
    return {}

def log_correction(produit_original, produit_corrige, source):
    """Ajoute une ligne dans corrections_appliquees.csv"""
    header = ["Horodatage", "Produit_Original", "Produit_Corrige", "Source"]
    fichier_existe = os.path.exists(FICHIER_LOG_CORRECTIONS)
    with open(FICHIER_LOG_CORRECTIONS, "a", newline="", encoding="utf-8") as f:
        writer = pd.DataFrame(
            [[datetime.now().strftime("%Y-%m-%d %H:%M:%S"), produit_original, produit_corrige, source]],
            columns=header
        )
        writer.to_csv(f, header=not fichier_existe, index=False)

# === Application des corrections et apprentissage IA ===
def corriger_et_apprendre(data):
    """
    Applique corrections connues + suggestions IA validées sur rappels
    """
    corrections = charger_corrections()
    suggestions = charger_suggestions_ia()

    rappels = data.get("rappels", None)
    if rappels is not None and not rappels.empty:
        for i, row in rappels.iterrows():
            produit_original = row.get("produit", "").strip()
            prod_lower = produit_original.lower()

            # 1️⃣ Correction connue
            if prod_lower in corrections:
                correction = corrections[prod_lower]
                rappels.at[i, "produit"] = correction
                log_correction(produit_original, correction, "Correction manuelle")
                print(f"🔄 Correction appliquée : '{produit_original}' → '{correction}'")

            # 2️⃣ Suggestion IA validée
            elif prod_lower in suggestions:
                correction = suggestions[prod_lower]
                rappels.at[i, "produit"] = correction
                corrections[prod_lower] = correction  # Ajout pour usage futur
                log_correction(produit_original, correction, "Suggestion IA")
                print(f"🧠 Suggestion IA appliquée : '{produit_original}' → '{correction}'")

    data["rappels"] = rappels
    sauvegarder_corrections(corrections)
    return data

# === Apprentissage des erreurs ===
def analyser_erreurs_et_apprendre(data, resultats_matching):
    """
    Ajoute dans learning.json les produits sans correspondance
    """
    learning = charger_learning()
    learning.setdefault("produits_a_revoir", [])

    for resultat in resultats_matching:
        produit_rappel = resultat.get("produit", "").lower()
        clients = resultat.get("clients", [])
        if len(clients) == 0 and produit_rappel not in learning["produits_a_revoir"]:
            learning["produits_a_revoir"].append(produit_rappel)

    sauvegarder_learning(learning)
    return learning
