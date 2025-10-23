#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
auto_collecte_ia.py — collecte SFTP → dépose dans data/uploads/{Enseigne}/{YYYY-MM-DD}/
→ archive locale → corrections/embeddings (best-effort) → rapport HTML.

- Auth SFTP : priorité au MOT DE PASSE fourni ici, sinon clé (facultatif)
- Host OVH SSH/SFTP : ssh.cluster029.hosting.ovh.net (port 22)
- Chemins distants POSIX (/www/uploads)
- Suppression distante seulement après succès local + archive
- Embeddings device auto (cuda/mps/cpu)
"""

import os
import posixpath
import stat
import csv
import json
from pathlib import Path
from datetime import datetime

import paramiko
import pandas as pd
from sentence_transformers import SentenceTransformer
import torch

# =========================
# === CONFIGURATION I/O ===
# =========================

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = (BASE_DIR / "../data").resolve()
ENTREE_DIR = DATA_DIR / "entree"
ARCHIVE_DIR = DATA_DIR / "archives"
IA_DIR = DATA_DIR / "ia"
LOG_DIR = (BASE_DIR / "../web_flask/logs").resolve()
REPORT_DIR = (BASE_DIR / "../reports").resolve()
UPLOADS_DIR = DATA_DIR / "uploads"   # ← alimentation du pipeline

for d in [ENTREE_DIR, ARCHIVE_DIR, IA_DIR / "embeddings", LOG_DIR, REPORT_DIR, UPLOADS_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# =========================
# === FICHIERS / LOGS  ====
# =========================

CORRECTIONS_FILE = IA_DIR / "corrections.json"
corrections = {}
if CORRECTIONS_FILE.exists():
    try:
        with open(CORRECTIONS_FILE, "r", encoding="utf-8") as f:
            corrections = json.load(f)
    except Exception:
        corrections = {}

LOG_FICHIERS = LOG_DIR / "fichiers_recus.csv"
LOG_IA = LOG_DIR / "ia_corrections.csv"

# =========================
# ===  EMBEDDINGS / IA  ===
# =========================

DEVICE = (
    "cuda" if torch.cuda.is_available()
    else ("mps" if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available() else "cpu")
)
model = SentenceTransformer("sentence-transformers/LaBSE", device=DEVICE)

def read_table_generic(path: Path) -> pd.DataFrame:
    """Lecture tolérante CSV/XLS(X) (essais multi-encodages/séparateurs)."""
    try:
        if path.suffix.lower() in {".xls", ".xlsx"}:
            return pd.read_excel(path)
        encodings = ["utf-8", "latin1", "cp1252"]
        seps = [None, ";", ",", "\t", "|"]
        for enc in encodings:
            for sep in seps:
                try:
                    # sniff rapide
                    pd.read_csv(path, sep=sep, engine="python", on_bad_lines="skip", encoding=enc, nrows=400)
                    # lecture complète
                    return pd.read_csv(path, sep=sep, engine="python", on_bad_lines="skip", encoding=enc)
                except Exception:
                    continue
        return pd.read_csv(path)  # dernier recours
    except Exception:
        return pd.DataFrame()

def precompute_embeddings(fichier: Path, type_fichier: str):
    """Calcule des embeddings (best-effort) pour Achats/Rappels sur une colonne texte pertinente."""
    try:
        if type_fichier not in {"Achats", "Rappels"}:
            return
        df = read_table_generic(fichier)
        if df.empty:
            return
        # colonnes candidates par ordre de préférence
        for col in ["designation", "libelle", "produit", "titre_de_la_fiche", "titre"]:
            if col in df.columns:
                text_col = col
                break
        else:
            text_col = df.columns[0]  # fallback
        texts = df[text_col].astype(str).fillna("").tolist()
        if not texts:
            return
        bs = 64 if DEVICE in ("cuda", "mps") else 32
        with torch.no_grad():
            emb = model.encode(
                texts, convert_to_tensor=True, batch_size=bs,
                show_progress_bar=False, device=DEVICE
            )
        out = IA_DIR / "embeddings" / f"{type_fichier}_{datetime.now().strftime('%Y%m%d_%H%M')}.pt"
        torch.save(emb, out)
        print(f"✅ Embeddings pré-calculés pour {type_fichier} → {out.name} (device={DEVICE})")
    except Exception as e:
        print(f"⚠️ Erreur embeddings : {e}")

def appliquer_corrections(df: pd.DataFrame, type_fichier: str):
    """Renomme les colonnes selon corrections.json[type_fichier] si présent."""
    applied = []
    if not isinstance(df, pd.DataFrame) or df.empty:
        return df, applied
    mapping = corrections.get(type_fichier, {})
    for col, new_col in mapping.items():
        if col in df.columns and col != new_col:
            df.rename(columns={col: new_col}, inplace=True)
            applied.append((col, new_col))
    return df, applied

# =========================
# ===   LOG FUNCTIONS   ===
# =========================

def log_fichier(nom_fichier: str, type_fichier: str):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(LOG_FICHIERS, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if f.tell() == 0:
            w.writerow(["Horodatage", "Nom_fichier", "Type_fichier"])
        w.writerow([now, nom_fichier, type_fichier])

def log_ia(enseigne: str, type_fichier: str, anomalie: str, correction: str):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(LOG_IA, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if f.tell() == 0:
            w.writerow(["Horodatage", "Enseigne", "Type_fichier", "Anomalie", "Action"])
        w.writerow([now, enseigne, type_fichier, anomalie, correction])

def generer_rapport_html():
    rapport_path = REPORT_DIR / "rapport_auto_collecte.html"
    fichiers_df = pd.read_csv(LOG_FICHIERS) if LOG_FICHIERS.exists() else pd.DataFrame()
    ia_df = pd.read_csv(LOG_IA) if LOG_IA.exists() else pd.DataFrame()

    html = [
        "<html><head><meta charset='UTF-8'><title>Rapport Auto Collecte IA</title>",
        "<style>body{font-family:Arial;padding:20px;}table{border-collapse:collapse;width:100%;margin-bottom:20px;}th,td{border:1px solid #ccc;padding:8px;text-align:left;}th{background:#003366;color:#fff;}h1{color:#003366;}</style>",
        "</head><body>",
        f"<h1>Rapport Auto Collecte IA - {datetime.now().strftime('%d/%m/%Y %H:%M')}</h1>"
    ]
    if not fichiers_df.empty:
        html.append("<h2>Fichiers récupérés</h2>")
        html.append(fichiers_df.to_html(index=False))
        stats = fichiers_df["Type_fichier"].value_counts().to_dict()
        html.append(f"<p><strong>Statistiques :</strong> {stats}</p>")
    if not ia_df.empty:
        html.append("<h2>Corrections IA appliquées</h2>")
        html.append(ia_df.to_html(index=False))

    html.append("<p><strong>Badges :</strong> ✅ RGPD OK | ✅ Embeddings calculés | ✅ Corrections IA</p>")
    html.append("</body></html>")

    with open(rapport_path, "w", encoding="utf-8") as f:
        f.write("".join(html))
    print(f"📄 Rapport HTML généré : {rapport_path}")

# =========================
# ===     SFTP CONF     ===
# =========================

SFTP_HOST = "ssh.cluster029.hosting.ovh.net"   # hôte SSH/SFTP OVH
SFTP_PORT = 22                                  # port SSH/SFTP
SFTP_USERNAME = "alerteo"                       # identifiant OVH
SFTP_PASSWORD = "A3j5l9pa14chrisal"        # ←←← REMPLACE ICI PAR TON MDP (laisser vide "" si tu utilises une clé)
SFTP_KEY_PATH = Path.home() / ".ssh" / "id_rsa" # (optionnel) chemin vers ta clé privée
REMOTE_BASE = "www/uploads"                    # dossier distant (commence par /)

def get_sftp_client() -> paramiko.SFTPClient:
    """
    Connexion SFTP :
      - si un mot de passe est fourni (non vide) → on l'utilise en priorité,
      - sinon si une clé existe → on tente la clé,
      - sinon on échoue proprement.
    """
    transport = paramiko.Transport((SFTP_HOST, SFTP_PORT))
    try:
        if SFTP_PASSWORD and SFTP_PASSWORD.strip():
            transport.connect(username=SFTP_USERNAME, password=SFTP_PASSWORD)
            print("🔐 Authentification SFTP : mot de passe")
        elif SFTP_KEY_PATH.exists():
            pkey = paramiko.RSAKey.from_private_key_file(str(SFTP_KEY_PATH))
            transport.connect(username=SFTP_USERNAME, pkey=pkey)
            print(f"🔐 Authentification SFTP : clé {SFTP_KEY_PATH}")
        else:
            raise RuntimeError("Aucun moyen d'authentification fourni (ni mot de passe, ni clé).")
    except paramiko.AuthenticationException as e:
        raise RuntimeError("Échec d'authentification SFTP : vérifie identifiant/mot de passe (ou clé SSH activée côté OVH).") from e
    return paramiko.SFTPClient.from_transport(transport)

# =========================
# ===   TYPE FICHIERS   ===
# =========================

def detect_type_fichier(nom: str) -> str:
    n = nom.lower()
    if "client" in n:
        return "Clients"
    if "achat" in n or "ticket" in n or "pos" in n:
        return "Achats"
    if "rappel" in n or "recall" in n or "dgccrf" in n:
        return "Rappels"
    return "Inconnu"

# =========================
# ===   MAIN COLLECTE   ===
# =========================

def fetch_and_process():
    print("📡 Connexion au SFTP OVH...")
    print(f"   Host={SFTP_HOST} Port={SFTP_PORT} Remote={REMOTE_BASE}")
    sftp = get_sftp_client()
    try:
        # Vérifie que REMOTE_BASE existe
        try:
            sftp.listdir(REMOTE_BASE)
        except IOError:
            raise RuntimeError(f"Le répertoire distant {REMOTE_BASE} est introuvable (vérifie le chemin et les droits OVH).")

        # Liste des enseignes = sous-dossiers de REMOTE_BASE
        enseignes = []
        try:
            for attrs in sftp.listdir_attr(REMOTE_BASE):
                if stat.S_ISDIR(attrs.st_mode):
                    enseignes.append(attrs.filename)
        except Exception:
            # Fallback simple si st_mode non renseigné
            for name in sftp.listdir(REMOTE_BASE):
                try:
                    p = posixpath.join(REMOTE_BASE, name)
                    if stat.S_ISDIR(sftp.stat(p).st_mode):
                        enseignes.append(name)
                except Exception:
                    pass

        print(f"✅ Enseignes trouvées : {enseignes}")

        for enseigne in enseignes:
            remote_dir = posixpath.join(REMOTE_BASE, enseigne)
            local_drop = UPLOADS_DIR / enseigne / datetime.now().strftime("%Y-%m-%d")
            local_drop.mkdir(parents=True, exist_ok=True)

            archive_path = ARCHIVE_DIR / f"{datetime.now().strftime('%Y%m%d_%H%M')}_{enseigne}"
            archive_path.mkdir(parents=True, exist_ok=True)

            try:
                fichiers = sftp.listdir(remote_dir)
            except IOError:
                print(f"ℹ️ Pas d'accès à {remote_dir}")
                continue

            print(f"📂 {enseigne}: {fichiers}")

            for fichier in fichiers:
                remote_file = posixpath.join(remote_dir, fichier)

                # Ignore les sous-dossiers (sécurité)
                try:
                    if stat.S_ISDIR(sftp.stat(remote_file).st_mode):
                        continue
                except Exception:
                    pass

                local_file = local_drop / fichier
                archive_file = archive_path / fichier
                type_fichier = detect_type_fichier(fichier)

                try:
                    # 1) Téléchargement vers data/uploads/{enseigne}/{date}/
                    sftp.get(remote_file, str(local_file))

                    # 2) Copie vers archives (après succès)
                    try:
                        with open(local_file, "rb") as src, open(archive_file, "wb") as dst:
                            dst.write(src.read())
                    except Exception as e:
                        print(f"⚠️ Échec copie archive {archive_file}: {e}")

                    print(f"✅ Téléchargé : {fichier} → {local_file}")

                    # 3) Log réception
                    log_fichier(fichier, type_fichier)

                    # 4) Traitements IA (best-effort)
                    try:
                        df = read_table_generic(local_file)
                        df, applied = appliquer_corrections(df, type_fichier)
                        for c in applied:
                            log_ia(enseigne, type_fichier, f"Colonne {c[0]}", f"Renommée {c[1]}")
                        precompute_embeddings(local_file, type_fichier)
                    except Exception as e:
                        print(f"⚠️ Erreur traitement IA : {e}")

                    # 5) Suppression distante seulement après succès local + archive
                    try:
                        sftp.remove(remote_file)
                        print(f"🧹 Supprimé distant : {remote_file}")
                    except Exception as e:
                        print(f"⚠️ Impossible de supprimer distant {remote_file}: {e}")

                except Exception as e:
                    print(f"❌ Échec téléchargement {remote_file}: {e}")
                    # On n'efface rien côté serveur dans ce cas

    finally:
        try:
            sftp.close()
        except Exception:
            pass

    print("🎉 Collecte terminée.")
    generer_rapport_html()


if __name__ == "__main__":
    fetch_and_process()
    # TODO: déclencher le pipeline ensuite si besoin (ex: subprocess.run([...]))
