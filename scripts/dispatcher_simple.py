#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Dispatcher simple :
- Cherche dans data/uploads (et sous-dossiers) les fichiers achats / clients / rappels
- Sélectionne le "meilleur" (taille + mtime) par catégorie
- Convertit proprement en CSV dans data/entree :
    - achats  -> entree/achats.csv
    - clients -> entree/clients.csv
    - rappels -> entree/rappels_raw.csv  (on NE touche PAS au rappels.csv normalisé)
- Loggue les fichiers traités du jour dans web_flask/logs/fichiers_recus.csv
  (colonnes : Horodatage, Nom_fichier, Type_fichier, enseigne)
"""

import csv
import datetime
import os
import re
import sys
from pathlib import Path
from typing import Optional, List

import pandas as pd

# --- Bases ----------------------------------------------------
BASE = Path(__file__).resolve().parents[1]
SRC  = BASE / "data" / "uploads"
DEST = BASE / "data" / "entree"
DEST.mkdir(parents=True, exist_ok=True)

# --- LOG des fichiers reçus ----------------------------------
LOGS_DIR = Path(os.environ.get("AP_LOGS_DIR", BASE / "web_flask" / "logs"))
LOGS_DIR.mkdir(parents=True, exist_ok=True)
RECUS_CSV = LOGS_DIR / "fichiers_recus.csv"

# Enseignes connues (complète si besoin)
KNOWN_ENSEIGNES = {
    "carrefour", "leclerc", "intermarche", "auchan", "lidl",
    "monoprix", "casino", "u", "systeme_u", "cora", "aldi"
}

def human_size(nbytes: int) -> str:
    try:
        n = float(nbytes)
    except Exception:
        return "?"
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if n < 1024.0:
            return f"{n:.2f} {unit}"
        n /= 1024.0
    return f"{n:.2f} PB"

def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")

# --- Heuristiques de schémas ---------------------------------
RAPPEL_KEYS = {
    "reference_fiche", "n_de_version", "identifiant_de_la_fiche",
    "lien_vers_la_fiche_rappel", "titre_de_la_fiche", "rappelguid",
    "categorie_de_produit", "sous_categorie_de_produit", "gtin"
}
ACHAT_HINTS = {
    "id_client", "client", "customer_id", "carte_fidelite", "ticket_id",
    "date_achat", "transaction_date", "produit", "libelle", "ean", "gtin", "magasin"
}
CLIENT_HINTS = {
    "id_client", "client_id", "email", "telephone", "tel", "mobile", "prenom", "nom"
}

def read_head(path: Path) -> List[str]:
    try:
        df = pd.read_csv(path, nrows=3, engine="python", sep=None, on_bad_lines="skip")
        return [_norm(c) for c in df.columns.tolist()]
    except Exception:
        try:
            df = pd.read_csv(path, nrows=3, engine="python", sep=";")
            return [_norm(c) for c in df.columns.tolist()]
        except Exception:
            return []

def schema_class(path: Path) -> Optional[str]:
    if path.suffix.lower() not in {".csv", ".xlsx", ".xls"}:
        return None
    if path.suffix.lower() == ".csv":
        cols = read_head(path)
    else:
        try:
            df = pd.read_excel(path, nrows=3)
            cols = [_norm(c) for c in df.columns.tolist()]
        except Exception:
            cols = []
    colset = set(cols)
    if len(colset & RAPPEL_KEYS) >= 3:
        return "rappels"
    if len(colset & ACHAT_HINTS) >= 2 and "identifiant_de_la_fiche" not in colset:
        return "achats"
    if len(colset & CLIENT_HINTS) >= 2:
        return "clients"
    return None

# --- Heuristiques sur le nom/chemin --------------------------
KEYS = {
    "achats":  ["achat", "achats", "vente", "ventes", "ticket", "pos", "receip", "sales"],
    "clients": ["client", "clients", "customer", "loyal", "fid", "carte"],
    "rappels": ["rappel", "rappels", "recall", "rappelconso", "dgccrf", "fiche", "alertes"],
}
def norm_text(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", s.lower())

def path_class(path: Path) -> Optional[str]:
    text = norm_text(path.name + " " + str(path.parent))
    tokens = set(text.split())
    for t, kws in KEYS.items():
        for k in kws:
            if k in tokens or k in text:
                return t
    return None

def pick_best(files: List[Path]) -> Optional[Path]:
    if not files:
        return None
    return max(files, key=lambda p: (p.stat().st_size, p.stat().st_mtime))

# --- IO sûres ------------------------------------------------
def read_csv_safely(path: Path) -> pd.DataFrame:
    encodings = ["utf-8", "latin1", "cp1252"]
    seps = [None, ";", "\t", "|", ","]
    for enc in encodings:
        for sep in seps:
            try:
                pd.read_csv(path, sep=sep, engine="python", on_bad_lines="skip", encoding=enc, nrows=200)
                return pd.read_csv(path, sep=sep, engine="python", on_bad_lines="skip", encoding=enc)
            except Exception:
                continue
    return pd.DataFrame()

def to_csv_clean(src: Path, dest_csv: Path) -> bool:
    try:
        dest_csv.parent.mkdir(parents=True, exist_ok=True)
        if src.suffix.lower() == ".csv":
            df = read_csv_safely(src)
        else:
            df = pd.read_excel(src)
        if df.empty and src.stat().st_size > 0:
            return False
        df.to_csv(dest_csv, index=False)
        return True
    except Exception:
        return False

def best_existing(paths: List[Path]) -> Optional[Path]:
    paths = [p for p in paths if p and p.exists()]
    if not paths:
        return None
    return max(paths, key=lambda p: (p.stat().st_size, p.stat().st_mtime))

# --- Déduction de l’enseigne --------------------------------
def extract_enseigne_from_path(p: Path) -> str:
    """Déduit l'enseigne depuis le chemin (uploads/<enseigne>/YYYY-MM-DD/…) ou via mot-clé."""
    parts = [s.lower() for s in p.parts]
    for s in parts:
        if s in KNOWN_ENSEIGNES:
            return s
    # fallback : premier sous-dossier sous uploads
    try:
        rel = p.relative_to(SRC)
        cand = rel.parts[0].lower()
        if cand in KNOWN_ENSEIGNES:
            return cand
    except Exception:
        pass
    # dernier fallback : heuristique sur le nom de fichier
    name = p.name.lower().replace("é", "e")
    for ens in KNOWN_ENSEIGNES:
        if ens in name:
            return ens
    return "autre"

def log_file_received(path: Path, type_fichier: str):
    """
    Append dans fichiers_recus.csv : Horodatage, Nom_fichier, Type_fichier, enseigne
    - on N'ENREGISTRE PAS rappels.csv (ce n’est pas un fichier enseigne)
    - horodatage = local
    """
    if path.name.lower() == "rappels.csv":
        return
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    row = [ts, path.name, type_fichier, extract_enseigne_from_path(path)]
    write_header = not RECUS_CSV.exists()
    with open(RECUS_CSV, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if write_header:
            w.writerow(["Horodatage", "Nom_fichier", "Type_fichier", "enseigne"])
        w.writerow(row)

# --- Main ----------------------------------------------------
def main():
    uploads = SRC
    entree  = DEST

    print("📦 Dispatcher (schéma d'abord)")
    print(f"  {uploads}  →  {entree}\n")

    # (A) Fichiers candidats depuis uploads
    candidates = [
        p for p in uploads.rglob("*")
        if p.is_file() and p.suffix.lower() in {".csv", ".xlsx", ".xls"}
    ]

    buckets = {"achats": [], "clients": [], "rappels": []}
    for p in candidates:
        t = schema_class(p) or path_class(p)
        if t:
            buckets.setdefault(t, []).append(p)

    # (B) Sélection meilleur par type
    selected = {t: pick_best(lst) for t, lst in buckets.items()}

    # (C) Écriture :
    #  - achats  → entree/achats.csv
    #  - clients → entree/clients.csv
    #  - rappels → entree/rappels_raw.csv (jamais rappels.csv ici)
    results = {}
    for t in ["achats", "clients", "rappels"]:
        src = selected.get(t)
        if not src:
            results[t] = "NONE"
            continue

        if t == "rappels":
            dest_csv = entree / "rappels_raw.csv"
        else:
            dest_csv = entree / f"{t}.csv"

        # revalide par schéma (sécurité)
        t_schema = schema_class(src) or t
        if t in {"achats", "clients"} and t_schema != t:
            results[t] = f"SKIP (schéma={t_schema}) from {src.name}"
            continue

        ok = to_csv_clean(src, dest_csv)
        src_size  = human_size(src.stat().st_size)
        dest_size = human_size(dest_csv.stat().st_size) if dest_csv.exists() else "0 B"
        if ok:
            results[t] = f"OK -> {dest_csv.name} (from {src.name}, {src_size} → {dest_size})"
            # LOG fichiers reçus uniquement pour achats/clients
            if t in {"achats", "clients"}:
                log_file_received(src, t)
        else:
            results[t] = f"FAIL write {dest_csv.name} (from {src.name}, {src_size})"

    for t in ["achats", "clients", "rappels"]:
        print(f"  - {t:<8} : {results.get(t)}")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"❌ Dispatcher erreur : {e}", file=sys.stderr)
        sys.exit(1)
