# -*- coding: utf-8 -*-
"""
AlerteProduit — Pré-calcul incrémental des embeddings RappelConso

- Ne recalcule que les NOUVELLES fiches de rappel.
- Conserve un index (clé -> ligne) et l'embedding .npy associés.
- Si le modèle change (nom/dimension), on reconstruit proprement.

Usage:
    python -m scripts.precompute_rappel_embeddings
"""

import os
import json
import hashlib
from pathlib import Path
from typing import List, Tuple

import numpy as np
import pandas as pd
from sentence_transformers import SentenceTransformer

BASE_DIR = Path(__file__).resolve().parents[1]
LOGS_DIR = BASE_DIR / "logs"
DATA_DIR = BASE_DIR / "data"
CACHE_DIR = BASE_DIR / "data" / "ia_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

RAPPELS_CSV = LOGS_DIR / "rappels.csv"  # ta source actuelle
EMB_FILE   = CACHE_DIR / "rappels_embeddings.npy"
IDX_FILE   = CACHE_DIR / "rappels_index.csv"
META_FILE  = CACHE_DIR / "rappels_meta.json"

MODEL_NAME = os.getenv("AP_MODEL_NAME", "sentence-transformers/LaBSE")
BATCH_SIZE = int(os.getenv("AP_EMB_BATCH", "64"))

def _key(row: pd.Series) -> str:
    """
    Clé stable du rappel pour l'index:
    - Priorité à l'URL (unique chez RappelConso)
    - Sinon hash du couple (ean|libelle)
    """
    url = (row.get("url") or "").strip()
    if url:
        return url
    ean = (str(row.get("ean") or "")).strip()
    lib = (row.get("libelle") or "").strip()
    if ean or lib:
        raw = f"{ean}||{lib}"
        return "hash://" + hashlib.sha1(raw.encode("utf-8")).hexdigest()
    # Dernier filet: ligne entière
    return "hash://" + hashlib.sha1(str(tuple(row.fillna("").astype(str))).encode("utf-8")).hexdigest()

def _text(row: pd.Series) -> str:
    """Texte à encoder — simple et robuste."""
    parts = []
    for k in ("libelle", "marque", "categorie", "ean", "motif", "risques"):
        v = str(row.get(k) or "").strip()
        if v:
            parts.append(v)
    # Toujours joindre l'URL s'il y en a une (signal fort)
    u = (row.get("url") or "").strip()
    if u:
        parts.append(u)
    return " | ".join(parts) or u or "rappel"

def _load_existing() -> Tuple[pd.DataFrame, np.ndarray, dict]:
    if IDX_FILE.exists() and EMB_FILE.exists() and META_FILE.exists():
        idx = pd.read_csv(IDX_FILE, dtype=str).fillna("")
        emb = np.load(EMB_FILE)
        meta = json.loads(META_FILE.read_text(encoding="utf-8"))
        return idx, emb, meta
    return pd.DataFrame(columns=["key","text"]), np.empty((0, 768), dtype=np.float32), {}

def _need_rebuild(meta: dict, emb: np.ndarray, model: SentenceTransformer) -> bool:
    if not meta:
        return False
    if meta.get("model_name") != MODEL_NAME:
        return True
    if emb.size > 0 and emb.shape[1] != model.get_sentence_embedding_dimension():
        return True
    return False

def _encode_batches(model: SentenceTransformer, texts: List[str]) -> np.ndarray:
    out = []
    for i in range(0, len(texts), BATCH_SIZE):
        chunk = texts[i:i+BATCH_SIZE]
        vecs = model.encode(chunk, normalize_embeddings=True, show_progress_bar=False)
        out.append(np.asarray(vecs, dtype=np.float32))
    return np.vstack(out) if out else np.empty((0, model.get_sentence_embedding_dimension()), dtype=np.float32)

def main():
    if not RAPPELS_CSV.exists():
        print(f"❌ Source non trouvée: {RAPPELS_CSV}")
        return 1

    df = pd.read_csv(RAPPELS_CSV, dtype=str).fillna("")
    if df.empty:
        print("ℹ️ Aucun rappel en entrée.")
        return 0

    df["__key__"]  = df.apply(_key, axis=1)
    df["__text__"] = df.apply(_text, axis=1)

    model = SentenceTransformer(MODEL_NAME)

    idx, emb, meta = _load_existing()

    # Rebuild si modèle/dimension changée
    if _need_rebuild(meta, emb, model):
        print("♻️ Modèle/dimension modifiés → reconstruction complète du cache.")
        texts = df["__text__"].tolist()
        emb = _encode_batches(model, texts)
        idx = pd.DataFrame({"key": df["__key__"], "text": df["__text__"]})
    else:
        # Incrémental: on n'encode que les clés manquantes
        known = set(idx["key"].tolist())
        to_add = df[~df["__key__"].isin(known)].copy()
        if to_add.empty:
            print(f"✅ Cache à jour — total embeddings: {len(idx)}")
        else:
            print(f"➕ Nouveaux rappels: {len(to_add)} → encodage incrémental…")
            new_vecs = _encode_batches(model, to_add["__text__"].tolist())
            # Append
            if emb.size == 0:
                emb = new_vecs
            else:
                emb = np.vstack([emb, new_vecs])
            idx = pd.concat([idx, to_add.rename(columns={"__key__":"key","__text__":"text"})[["key","text"]]], ignore_index=True)

    # Persistance
    idx.to_csv(IDX_FILE, index=False)
    np.save(EMB_FILE, emb)
    META_FILE.write_text(json.dumps({
        "model_name": MODEL_NAME,
        "dim": int(model.get_sentence_embedding_dimension()),
        "total": int(len(idx)),
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"✅ Embeddings sauvegardés: {EMB_FILE.name} ({emb.shape[0]} x {emb.shape[1] if emb.size else 0})")
    print(f"✅ Index sauvegardé: {IDX_FILE.name} ({len(idx)} clés)")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
