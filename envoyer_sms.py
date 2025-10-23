#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import os
import re
from typing import Optional, Dict, Any

from dotenv import load_dotenv
import requests

# 👇 Logger commun Étape 1 (fallback si non présent)
try:
    from scripts.log_utils import log_exec  # type: ignore
except Exception:
    def log_exec(etape: str, statut: str, **kv: Any) -> None:
        # Fallback minimal: imprime sur la sortie standard
        print(f"[log_exec] etape={etape} statut={statut} data={kv}")

load_dotenv()

# 📁 Chemins
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
FICHIER_MESSAGES = os.path.join(DATA_DIR, "messages_personnalises.json")

# 🔑 Clé API Brevo (mettre BREVO_API_KEY=xxxxx dans .env)
BREVO_API_KEY = os.getenv("BREVO_API_KEY")

BREVO_URL = "https://api.brevo.com/v3/transactionalSMS/sms"
SENDER = "AlerteProd"  # 11 chars max conseillé chez Brevo

def _normaliser_numero(numero: str) -> str:
    """Transforme 06.. en +33..., enlève espaces/points etc."""
    n = re.sub(r"[^\d+]", "", str(numero))
    if n.startswith("00"):  # 0033... -> +33...
        n = "+" + n[2:]
    elif n.startswith("0"):  # 06... -> +33 6...
        n = "+33" + n[1:]
    elif not n.startswith("+"):
        n = "+" + n
    return n

def _charger_messages() -> Dict[str, str]:
    try:
        with open(FICHIER_MESSAGES, "r", encoding="utf-8") as f:
            data = json.load(f)
        # on force dict[str,str]
        return {str(k): str(v) for k, v in data.items()}
    except Exception as e:
        print("❌ Erreur chargement messages_personnalises.json :", e)
        return {}

def _construire_message(messages: Dict[str, str], url: str, produit: Optional[str], enseigne: str) -> str:
    modele = messages.get(enseigne, messages.get("default", "Rappel produit : {produit}. Infos : {url}"))
    texte_sms = modele.format(produit=(produit or "produit concerné"), url=url)
    # Brevo recommande des SMS courts ; on coupe gentiment si > ~180
    if len(texte_sms) > 180:
        texte_sms = texte_sms[:177] + "..."
    return texte_sms

# 📡 Fonction d’envoi de SMS via Brevo (avec log Étape 1)
def envoyer_sms(numero: str, url: str, produit: Optional[str] = None, enseigne: str = "") -> bool:
    """
    Envoie un SMS personnalisé en fonction de l’enseigne.
    Log un enregistrement dans web_flask/logs/executions.jsonl :
      { etape: 'sms', statut: 'ok'|'error', enseigne, last4, url }
    """
    last4 = str(numero)[-4:]

    if not BREVO_API_KEY:
        err = "BREVO_API_KEY manquante (dotenv / variables d’environnement)."
        print("❌", err)
        log_exec("sms", "error", enseigne=enseigne, last4=last4, url=url, err=err)
        return False

    messages = _charger_messages()
    texte_sms = _construire_message(messages, url, produit, enseigne)
    numero_fmt = _normaliser_numero(numero)

    payload = {
        "sender": SENDER,
        "recipient": numero_fmt,
        "content": texte_sms,
        "type": "transactional",
    }
    headers = {
        "accept": "application/json",
        "api-key": BREVO_API_KEY,
        "content-type": "application/json",
    }

    try:
        resp = requests.post(BREVO_URL, json=payload, headers=headers, timeout=15)
        # Brevo renvoie 201 en succès ; on gère toutes les 2xx
        if not (200 <= resp.status_code < 300):
            raise RuntimeError(f"Brevo HTTP {resp.status_code} — {resp.text}")

        provider_id: Optional[str] = None
        try:
            j = resp.json()
            provider_id = j.get("messageId") or j.get("message") or None
        except Exception:
            pass

        print(f"✅ SMS envoyé à {numero_fmt} → {url}")
        log_exec("sms", "ok", enseigne=enseigne, last4=last4, url=url, provider_id=provider_id)
        return True

    except Exception as e:
        print(f"❌ Erreur SMS vers {numero_fmt} → {e}")
        log_exec("sms", "error", enseigne=enseigne, last4=last4, url=url, err=str(e))
        return False



if __name__ == "__main__":
    # Envoi batch depuis logs/alertes_a_envoyer.csv
    import os, sys, csv
    from pathlib import Path
    from dotenv import load_dotenv

    # Racine du projet
    base = Path(__file__).resolve().parents[1]

    # Charger .env à la racine
    try:
        load_dotenv(dotenv_path=str(base / ".env"))
    except Exception:
        pass

    csv_path = base / "logs" / "alertes_a_envoyer.csv"
    if not csv_path.exists():
        print(f"⚠️ Fichier introuvable: {csv_path}")
        sys.exit(0)

    # Lire les lignes
    with open(csv_path, newline="", encoding="utf-8") as f:
        rdr = csv.DictReader(f)
        rows = list(rdr)

    if not rows:
        print("ℹ️ CSV vide — aucun SMS à envoyer.")
        sys.exit(0)

    # Importer la fonction d'envoi
    from scripts.envoyer_sms import envoyer_sms

    ok = err = 0
    for r in rows:
        tel = (r.get("telephone") or "").strip()
        url = (r.get("url") or "").strip()
        produit = (r.get("produit") or "").strip()
        enseigne = (r.get("enseigne") or "Carrefour").strip()
        if not tel or not url:
            print(f"⏭️  Ligne ignorée (tel/url manquants) → {r}")
            continue
        if envoyer_sms(numero=tel, url=url, produit=produit, enseigne=enseigne):
            ok += 1
        else:
            err += 1

    print(f"📤 Envoi SMS terminé: {ok} succès / {err} échecs")
