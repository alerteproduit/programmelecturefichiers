# -*- coding: utf-8 -*-
"""
Étape 8 – Construction des alertes (version robuste + caches + MiniLM)

Priorité de match : FICHE (ID 4–6 chiffres) → EAN (8/12/13/14) → IA.
- Téléphone récupéré où qu’il soit (achats ou clients) + format E.164 FR
- Libellés robustes (produit/product/libelle/designation/description)
- Mapping 'fiche → index' tolérant (colonnes, URL, et scan global du tableau)
- Multi-encodages CSV tolérants
- Caches d’embeddings utilisés si présents
"""

import os, sys, time, re
import numpy as np
import pandas as pd
from pathlib import Path

# ========= CONFIG =========
BASE_DIR   = Path(__file__).resolve().parent.parent
ENTREE_DIR = BASE_DIR / "data" / "entree"
CACHE_DIR  = BASE_DIR / "data" / "ia_cache"
LOGS_DIR   = BASE_DIR / "logs"

ACHATS_CSV    = ENTREE_DIR / "achats.csv"
RAPPELS_CSV   = BASE_DIR   / "rappels.csv"  # symlink créé à l'étape 3
OUT_CANDIDATS = LOGS_DIR   / "alertes_a_envoyer.csv"

MODEL_NAME      = os.environ.get("AP_EMB_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
TOPK            = int(os.environ.get("AP_TOPK", "5"))
MATCH_THRESHOLD = float(os.environ.get("AP_MATCH_THRESHOLD", "0.82"))
USE_FAISS       = os.environ.get("AP_USE_FAISS", "1") == "1"

# ==========================

def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")

def safe_read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"{path} introuvable.")
    return pd.read_csv(path, sep=None, engine="python", dtype=str).fillna("")

def _snake_cols(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = (
        df.columns.astype(str)
        .str.strip()
        .str.lower()
        .str.normalize("NFKD")
        .str.replace(r"[^a-z0-9]+", "_", regex=True)
        .str.replace(r"_+", "_", regex=True)
        .str.strip("_")
    )
    return df

def _format_phone_fr(numero: str) -> str:
    n = re.sub(r"[^\d+]", "", str(numero or ""))
    if not n: return ""
    if n.startswith("00"): n = "+" + n[2:]
    elif n.startswith("+"): pass
    elif n.startswith("0"): n = "+33" + n[1:]
    else:
        if len(n) in (9, 10): n = "+33" + n[-9:]
        else: n = "+" + n
    return n

def only_digits(s: str) -> str:
    return "".join(ch for ch in (s or "") if ch.isdigit())

# ---------- EAN ----------
def extract_ean_series(df: pd.DataFrame) -> pd.Series:
    """EAN/GTIN uniquement longueurs valides 8/12/13/14."""
    candidates = [c for c in df.columns if c in {
        "ean","gtin","codebarres","code_barres","code_barre","barcode","code"
    }]
    if not candidates:
        for c in df.columns:
            try:
                if df[c].astype(str).str.replace(r"\D","",regex=True).str.len().max() >= 8:
                    candidates = [c]; break
            except Exception:
                continue
    if not candidates:
        return pd.Series([""]*len(df))

    col = candidates[0]
    out = []
    for v in df[col].astype(str):
        found = [x for x in re.findall(r"\d{8,14}", v) if len(x) in (8,12,13,14)]
        out.append(found[0] if found else "")
    return pd.Series(out)

# ---------- Fiche RappelConso ----------
def build_ficheid_map(rappels_df: pd.DataFrame) -> dict:
    """
    Construit un mapping { '20002' : [row_idx, ...], ... }.
    Sources :
      1) Colonnes explicites (après normalisation) :
         identifiant_de_la_fiche, reference_fiche, reference, id_fiche, identifiant_fiche
      2) Colonne url/lien : extrait /fiche-rappel/<id>/
      3) Scan global de toutes les cellules : motifs A?\d{4,6}
    """
    m = {}

    # 1) Colonnes dédiées
    col_candidates = [c for c in (
        "identifiant_de_la_fiche","reference_fiche","reference",
        "id_fiche","identifiant_fiche"
    ) if c in rappels_df.columns]
    for c in col_candidates:
        for i, val in enumerate(rappels_df[c].astype(str)):
            k = only_digits(val)
            if 4 <= len(k) <= 6:
                m.setdefault(k, []).append(i)

    # 2) URL / lien
    for c in ("url","lien","lien_vers_la_fiche_rappel"):
        if c in rappels_df.columns:
            for i, val in enumerate(rappels_df[c].astype(str)):
                m2 = re.search(r"/fiche-rappel/(\d{4,6})", val)
                if m2:
                    k = m2.group(1)
                    m.setdefault(k, []).append(i)

    # 3) Scan global (dernière chance)
    sample = rappels_df.astype(str).fillna("").values
    for i, row in enumerate(sample):
        joined = " ".join(row)
        for k in re.findall(r"\bA?(\d{4,6})\b", joined):
            m.setdefault(k, []).append(i)

    # dédoublonne les indices
    for k in list(m.keys()):
        m[k] = sorted(set(m[k]))
    return m

def _rappel_url(idx: int, rappels_df: pd.DataFrame) -> str:
    for c in ("url","lien","lien_vers_la_fiche_rappel"):
        if c in rappels_df.columns:
            val = str(rappels_df.iloc[idx].get(c, "") or "").strip()
            if val: return val
    # reconstruit depuis identifiant si possible
    for c in ("identifiant_de_la_fiche","reference_fiche","reference","id_fiche","identifiant_fiche"):
        if c in rappels_df.columns:
            fid = only_digits(rappels_df.iloc[idx].get(c, ""))
            if 4 <= len(fid) <= 6:
                return f"https://rappel.conso.gouv.fr/fiche-rappel/{fid}/Interne"
    return ""

# ---------- Embeddings utils ----------
def load_cache_pair(prefix: str):
    t_path = CACHE_DIR / f"{prefix}_textes.npy"
    e_path = CACHE_DIR / f"{prefix}_embeddings.npy"
    if not t_path.exists() or not e_path.exists():
        return None, None
    textes = np.load(t_path, allow_pickle=True)
    embs   = np.load(e_path, mmap_mode="r")
    return textes, embs

def ensure_minilm():
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer(MODEL_NAME)

def l2_normalize(mat: np.ndarray) -> np.ndarray:
    return mat / (np.linalg.norm(mat, axis=1, keepdims=True) + 1e-12)

def cosine_topk(query_vecs: np.ndarray, index_vecs: np.ndarray, k: int = 5):
    if index_vecs.shape[0] == 0:
        return np.zeros((query_vecs.shape[0], 0)), np.zeros((query_vecs.shape[0], 0), dtype=int)
    sims = np.dot(query_vecs, index_vecs.T)
    k_eff = min(k, max(1, sims.shape[1]))
    idx = np.argpartition(-sims, kth=k_eff-1, axis=1)[:, :k_eff]
    row = np.arange(sims.shape[0])[:, None]
    order = np.argsort(-sims[row, idx], axis=1)
    top_idx = idx[row, order]
    top_scores = sims[row, top_idx]
    return top_scores, top_idx

def try_build_faiss(index_vecs: np.ndarray):
    try:
        import faiss
    except Exception:
        return None, None
    d = index_vecs.shape[1]
    index = faiss.IndexFlatIP(d)
    index.add(index_vecs.astype(np.float32))
    return index, "faiss"

# ==========================

def _pick_col(df: pd.DataFrame, candidates) -> str:
    for c in candidates:
        if c in df.columns:
            return c
    return df.columns[0]

def main():
    print(f"=== LANCEMENT ÉTAPE 8 [{_now()}] ===")
    print(f"📁 achats : {ACHATS_CSV}")
    print(f"📁 rappels: {RAPPELS_CSV}")

    # 1) Chargement + normalisation colonnes
    achats_df  = _snake_cols(safe_read_csv(ACHATS_CSV))
    rappels_df = _snake_cols(safe_read_csv(RAPPELS_CSV))

    # 1.a) Mapping fiche → index (très tolérant)
    ficheid_to_idx = build_ficheid_map(rappels_df)
    print(f"🔗 mapping fiches construit: {len(ficheid_to_idx)} clés")

    # 1.b) Libellé produit côté achats
    produit_col = _pick_col(achats_df, ["produit","product","libelle","designation","description"])

    # 1.c) Lookup téléphone depuis clients.csv
    clients_lookup = {}
    cpath = ENTREE_DIR / "clients.csv"
    if cpath.exists():
        try:
            cdf = _snake_cols(safe_read_csv(cpath))
            if "client_id" in cdf.columns:
                telc = next((c for c in ("telephone","tel","mobile","phone","gsm") if c in cdf.columns), None)
                if telc:
                    for cid, tel in cdf[["client_id", telc]].astype(str).values:
                        fmt = _format_phone_fr(tel)
                        if cid and fmt:
                            clients_lookup[str(cid)] = fmt
            print(f"📞 clients_lookup: {len(clients_lookup)} entrées")
        except Exception as e:
            print("⚠️ fallback téléphone impossible:", e)

    # 2) Exact-match EAN
    achats_ean  = extract_ean_series(achats_df)
    rappels_ean = extract_ean_series(rappels_df)
    ean_to_idx = {}
    for i, e in enumerate(rappels_ean):
        if e:
            ean_to_idx.setdefault(e, []).append(i)

    # 3) Caches embeddings
    achats_textes, achats_embs   = load_cache_pair("achats")
    rappels_textes, rappels_embs = load_cache_pair("rappels")

    encoder = None
    if achats_embs is None or achats_textes is None:
        print("⚠️  Cache achats manquant → encodage MiniLM.")
        encoder = ensure_minilm()
        achats_textes = achats_df[produit_col].astype(str).values
        achats_embs   = encoder.encode(achats_textes, batch_size=256, show_progress_bar=False)

    if rappels_embs is None or rappels_textes is None:
        print("⚠️  Cache rappels manquant → encodage MiniLM.")
        encoder = encoder or ensure_minilm()
        rapp_label_col = _pick_col(rappels_df, ["titre","title","libelle","designation","produit"])
        rappels_textes = rappels_df[rapp_label_col].astype(str).values
        rappels_embs   = encoder.encode(rappels_textes, batch_size=512, show_progress_bar=False)

    # 4) Normalisation L2
    A = l2_normalize(np.asarray(achats_embs))
    R = l2_normalize(np.asarray(rappels_embs))

    # 5) Index (FAISS ou numpy)
    faiss_index, backend = (None, "numpy")
    if USE_FAISS:
        faiss_index, backend = try_build_faiss(R)
        if faiss_index is None: backend = "numpy"
    print(f"⚙️  Backend matching : {backend}")

    # 6) Boucle achats
    alertes = []
    n = len(achats_df)
    for i in range(n):
        row = achats_df.iloc[i]
        prod_txt  = str(row.get(produit_col, ""))
        client_id = str(row.get("client_id", ""))
        # Téléphone : achats → clients.csv
        tel = ""
        for tk in ("telephone","tel","mobile","phone","gsm"):
            if tk in achats_df.columns:
                tel = str(row.get(tk, "") or "")
                if tel: break
        if not tel and client_id:
            tel = clients_lookup.get(client_id, "")
        tel = _format_phone_fr(tel) if tel else ""

        # --- 6.1 Match FICHE (code 4–6 chiffres, ex: 20002) ---
        raw_code = str(row.get("code", "") or "")
        m_code = re.search(r"A?(\d{4,6})", raw_code)
        fiche_code = m_code.group(1) if m_code else ""
        if fiche_code and fiche_code in ficheid_to_idx:
            ridx = ficheid_to_idx[fiche_code][0]
            rappel_texte = str(rappels_textes[ridx]) if 0 <= ridx < len(rappels_textes) else ""
            if not rappel_texte:
                fb = [c for c in ("titre","libelle","produit","designation") if c in rappels_df.columns]
                rappel_texte = str(rappels_df.iloc[ridx][fb[0]]) if fb else f"Fiche {fiche_code}"
            alertes.append({
                "client_id": client_id,
                "telephone": tel,
                "produit":   prod_txt,
                "match_type": "FICHE",
                "rappel_idx": ridx,
                "rappel_texte": rappel_texte,
                "url": _rappel_url(ridx, rappels_df),
                "score": 1.0
            })
            print(f"🔎 [{i+1}/{n}] MATCH FICHE → {prod_txt} (ID={fiche_code})")
            continue

        # --- 6.2 Match EAN exact ---
        ean = achats_ean.iloc[i] if i < len(achats_ean) else ""
        if ean and ean in ean_to_idx:
            ridx = ean_to_idx[ean][0]
            rappel_texte = str(rappels_textes[ridx]) if 0 <= ridx < len(rappels_textes) else ""
            if not rappel_texte:
                fb = [c for c in ("titre","title","libelle","designation","produit") if c in rappels_df.columns]
                rappel_texte = str(rappels_df.iloc[ridx][fb[0]]) if fb else "EAN trouvé (libellé indisponible)"
            alertes.append({
                "client_id": client_id,
                "telephone": tel,
                "produit":   prod_txt,
                "match_type": "EAN",
                "rappel_idx": ridx,
                "rappel_texte": rappel_texte,
                "url": _rappel_url(ridx, rappels_df),
                "score": 1.0
            })
            print(f"🔍 [{i+1}/{n}] EXACT EAN → {prod_txt} (GTIN={ean})")
            continue

        # --- 6.3 Match IA ---
        q = A[i:i+1, :]
        if faiss_index is not None:
            D, I = faiss_index.search(q.astype(np.float32), TOPK)
            scores = D[0] if D.size else np.array([])
            idxs   = I[0] if I.size else np.array([], dtype=int)
        else:
            scores, idxs = cosine_topk(q, R, TOPK)
            scores = scores.ravel() if isinstance(scores, np.ndarray) else np.asarray(scores).ravel()
            idxs   = idxs.ravel()   if isinstance(idxs,   np.ndarray) else np.asarray(idxs).ravel()

        if scores.size == 0 or idxs.size == 0:
            print("ℹ️ Aucun score renvoyé — aucune alerte à construire (0 match).")
            continue

        top_score = float(scores[0]); top_idx = int(idxs[0])
        if top_score >= MATCH_THRESHOLD:
            alertes.append({
                "client_id": client_id,
                "telephone": tel,
                "produit":   prod_txt,
                "match_type": "IA",
                "rappel_idx": top_idx,
                "rappel_texte": str(rappels_textes[top_idx]),
                "url": _rappel_url(top_idx, rappels_df),
                "score": top_score
            })
            print(f"✅ [{i+1}/{n}] IA OK ({top_score:.3f}) → {prod_txt}")
        else:
            print(f"❌ [{i+1}/{n}] IA score trop bas ({top_score:.3f}) → {prod_txt}")

    # 7) Sauvegarde
    os.makedirs(OUT_CANDIDATS.parent, exist_ok=True)
    if not alertes:
        print("ℹ️  Aucune alerte nouvelle à envoyer (liste vide).")
        pd.DataFrame(columns=[
            "client_id","telephone","produit","match_type","rappel_idx","rappel_texte","url","score"
        ]).to_csv(OUT_CANDIDATS, index=False)
        print(f"📝 CSV vide écrit: {OUT_CANDIDATS}")
        print("=== FIN ÉTAPE 8 ===")
        return

    df_alertes = pd.DataFrame(alertes)

    # Enrichissement (on garde 'url' déjà calculée)
    join_cols = [c for c in (
        "lien","reference","date_publication","categorie","marque","lot","risque","titre","libelle"
    ) if c in rappels_df.columns]
    if join_cols:
        add = rappels_df.iloc[df_alertes["rappel_idx"].astype(int)][join_cols].reset_index(drop=True)
        df_alertes = pd.concat([df_alertes.reset_index(drop=True), add], axis=1)

    df_alertes.to_csv(OUT_CANDIDATS, index=False)
    print(f"📝 Alertes candidates → {OUT_CANDIDATS}  ({len(df_alertes)} lignes)")
    print("=== FIN ÉTAPE 8 ===")

# ==== MAIN ====
if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback; traceback.print_exc()
        sys.exit(1)

