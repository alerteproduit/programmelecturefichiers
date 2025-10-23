#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Pré-calcul incrémental des embeddings pour les ACHATS.

- Lit data/entree/achats.csv
- Sélectionne le texte produit via colonnes candidates (produit/libelle/designation/description/nom/name/intitule)
- Clé de déduplication:
    * ean/gtin si dispo (prioritaire)
    * sinon texte produit normalisé (truncate 256)
- Cache dans data/ia_cache/ :
    - achats_keys.npy        (clé stable par produit)
    - achats_texts.npy       (texte produit utilisé)
    - achats_embeddings.npy  (embeddings float32)
- Ne réencode QUE les nouvelles clés ou celles dont le texte a changé
- Modèle rapide par défaut : paraphrase-multilingual-MiniLM-L12-v2
  (override via env: AP_EMB_MODEL="sentence-transformers/LaBSE")
- Compat Python 3.9
"""

import os
import sys
import time
from pathlib import Path
from typing import List, Tuple

import numpy as np
import pandas as pd
import torch
from sentence_transformers import SentenceTransformer

# --- chemins
BASE_DIR      = Path(__file__).resolve().parents[1]
ENTREE_CSV    = BASE_DIR / "data" / "entree" / "achats.csv"

IA_CACHE_DIR  = BASE_DIR / "data" / "ia_cache"
IA_CACHE_DIR.mkdir(parents=True, exist_ok=True)

KEYS_FILE     = IA_CACHE_DIR / "achats_keys.npy"        # NEW (clé stable)
TEXTS_FILE    = IA_CACHE_DIR / "achats_texts.npy"       # garde le nom original "textes" si tu préfères
EMBS_FILE     = IA_CACHE_DIR / "achats_embeddings.npy"  # idem

# --- modèle + device
DEVICE = (
    "cuda" if torch.cuda.is_available()
    else ("mps" if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available() else "cpu")
)
EMB_MODEL = os.getenv("AP_EMB_MODEL", "paraphrase-multilingual-MiniLM-L12-v2")  # plus rapide que LaBSE

def load_model() -> SentenceTransformer:
    print(f"⚙️  Modèle embeddings : {EMB_MODEL} (device={DEVICE})")
    return SentenceTransformer(EMB_MODEL, device=DEVICE)

# --- utils
CANDIDATE_TEXT_COLS = [
    "produit", "libelle", "designation", "description", "desc",
    "nom", "name", "intitule", "article", "libelle_produit"
]
CANDIDATE_KEY_COLS  = ["ean", "gtin", "code_ean", "code_gtin"]

def read_achats_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        print(f"❌ {path} introuvable.")
        sys.exit(1)
    # lecture tolérante (ton pipeline écrit en virgule ; d’autres sources en ';')
    try:
        df = pd.read_csv(path, engine="python", sep=None, dtype=str, on_bad_lines="skip")
    except Exception:
        df = pd.read_csv(path, engine="python", sep=",", dtype=str, on_bad_lines="skip")
    df = df.fillna("")
    return df

def pick_text_column(df: pd.DataFrame) -> str:
    cols = [c for c in CANDIDATE_TEXT_COLS if c in df.columns]
    if cols:
        return cols[0]
    # fallback: première colonne de type object non vide
    for c in df.columns:
        if df[c].dtype == object:
            return c
    # ultimement, la toute première
    return df.columns[0]

def normalize_text(s: str) -> str:
    t = str(s).strip()
    return t[:256]  # tronque pour accélérer un peu et éviter des très longues chaînes

def build_keys_and_texts(df: pd.DataFrame) -> Tuple[np.ndarray, np.ndarray]:
    text_col = pick_text_column(df)
    # clé = ean/gtin prioritaire
    key_col = None
    for c in CANDIDATE_KEY_COLS:
        if c in df.columns:
            key_col = c
            break

    if key_col:
        # On garde une ligne par clé, la plus récente (si date existe) ou la première
        dedup = df.copy()
        # tri par date si dispo pour garder la version la plus récente
        for dcol in ["date_achat", "transaction_date", "date"]:
            if dcol in dedup.columns:
                # on ne casse pas si parsing échoue
                try:
                    dedup["_dt_"] = pd.to_datetime(dedup[dcol], errors="coerce")
                    dedup = dedup.sort_values("_dt_", ascending=False).drop(columns=["_dt_"])
                except Exception:
                    pass
                break
        dedup = dedup.drop_duplicates(subset=[key_col], keep="first")
        keys  = dedup[key_col].astype(str).str.strip().to_numpy()
        texts = dedup[text_col].astype(str).map(normalize_text).to_numpy()
    else:
        # Pas d’EAN/GTIN : clé = texte normalisé
        texts_raw = df[text_col].astype(str).map(normalize_text)
        # dédup par texte
        dedup = texts_raw.drop_duplicates()
        keys  = dedup.to_numpy()
        texts = dedup.to_numpy()
    # filtre clés vides
    mask = (pd.Series(keys) != "")
    keys = keys[mask.to_numpy()]
    texts = texts[mask.to_numpy()]
    return keys.astype(object), texts.astype(object)

def load_cache() -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    if KEYS_FILE.exists() and TEXTS_FILE.exists() and EMBS_FILE.exists():
        try:
            keys = np.load(KEYS_FILE, allow_pickle=False)
            texts = np.load(TEXTS_FILE, allow_pickle=False)
            embs = np.load(EMBS_FILE, allow_pickle=False)
            if len(keys) == len(texts) == len(embs):
                print("✅ Cache IA achats trouvé → chargement.")
                return keys, texts, embs
        except Exception:
            pass
    print("ℹ️  Pas de cache achats valide → initialisation.")
    return np.array([], dtype=object), np.array([], dtype=object), np.zeros((0, 384), dtype=np.float32)

def save_cache(keys: np.ndarray, texts: np.ndarray, embs: np.ndarray) -> None:
    np.save(KEYS_FILE,  keys)
    np.save(TEXTS_FILE, texts)
    np.save(EMBS_FILE,  embs.astype(np.float32))

def encode_texts(model: SentenceTransformer, texts: List[str]) -> np.ndarray:
    if not texts:
        return np.zeros((0, model.get_sentence_embedding_dimension()), dtype=np.float32)
    bs = 128 if DEVICE in ("cuda", "mps") else 32
    with torch.no_grad():
        vec = model.encode(
            texts,
            convert_to_numpy=True,
            normalize_embeddings=False,   # laisse brut ; normalise au moment des similarités si besoin
            batch_size=bs,
            show_progress_bar=False,
            device=DEVICE
        )
    if vec.dtype != np.float32:
        vec = vec.astype(np.float32, copy=False)
    return vec

def main():
    t0 = time.time()

    df = read_achats_csv(ENTREE_CSV)
    keys_all, texts_all = build_keys_and_texts(df)

    # charge cache
    keys_cache, texts_cache, embs_cache = load_cache()
    dim_cache = embs_cache.shape[1] if embs_cache.size else None

    # modèle courant
    model = load_model()
    dim_model = model.get_sentence_embedding_dimension()

    # Si la dimension a changé (changement de modèle), on repars proprement
    if dim_cache is not None and dim_cache != dim_model:
        print(f"ℹ️  Dimension différente (cache={dim_cache}, modèle={dim_model}) → réinit cache achats.")
        keys_cache, texts_cache, embs_cache = np.array([], dtype=object), np.array([], dtype=object), np.zeros((0, dim_model), dtype=np.float32)

    # index rapide : clé -> index
    index_by_key = {k: i for i, k in enumerate(keys_cache.tolist())}

    # détecte nouvelles clés
    is_new = ~pd.Series(keys_all).isin(index_by_key.keys()).to_numpy()
    new_keys  = keys_all[is_new]
    new_texts = texts_all[is_new]

    # détecte modifs de texte pour clés existantes
    changed_idx = []
    changed_texts = []
    for k, t in zip(keys_all[~is_new], texts_all[~is_new]):
        i = index_by_key[k]
        if str(texts_cache[i]) != str(t):
            changed_idx.append(i)
            changed_texts.append(t)

    n_total   = len(keys_all)
    n_new     = len(new_keys)
    n_changed = len(changed_idx)
    print(f"📊 Produits uniques (clé) : {n_total} | nouveaux: {n_new} | modifiés: {n_changed}")

    # encodage uniquement des nécessaires
    to_encode = []
    if n_new:
        to_encode.extend(new_texts.tolist())
    if n_changed:
        to_encode.extend(changed_texts)

    if to_encode:
        print(f"⚡ Encodage de {len(to_encode)} éléments…")
        vecs = encode_texts(model, to_encode)

        off = 0
        if n_new:
            new_vecs = vecs[:n_new]
            keys_cache  = np.concatenate([keys_cache,  new_keys])  if keys_cache.size else new_keys
            texts_cache = np.concatenate([texts_cache, new_texts]) if texts_cache.size else new_texts
            embs_cache  = np.vstack([embs_cache, new_vecs])        if embs_cache.size else new_vecs
            off = n_new
        if n_changed:
            ch_vecs = vecs[off:off+n_changed]
            for j, i in enumerate(changed_idx):
                texts_cache[i] = changed_texts[j]
                embs_cache[i]  = ch_vecs[j]
    else:
        print("✅ Rien à encoder (cache achats à jour).")

    save_cache(keys_cache, texts_cache, embs_cache)
    dt = time.time() - t0
    print(f"✅ Cache achats mis à jour : {len(keys_cache)} items (dim={dim_model}) en {dt:.1f}s")
    print(f"   → {KEYS_FILE.name}, {TEXTS_FILE.name}, {EMBS_FILE.name}")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
    except SystemExit:
        raise
    except Exception as e:
        print("❌ Erreur pré-calcul embeddings achats :", e)
        sys.exit(1)

