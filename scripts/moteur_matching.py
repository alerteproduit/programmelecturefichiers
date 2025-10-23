# === moteur_matching.py (robuste + règles apprises + filtre J jours) ===
# - Garde le rôle “diagnostic/bench” de l’étape 7
# - Filtre temporel sur les rappels
# - Applique des règles apprises (remap de libellés d’achats)
# - Matching prioritaire : Identifiant de fiche (alerte_id / identifiants proches)
# - Matching exact optionnel : EAN/GTIN si présent
# - Fallback IA via caches (rapide) ou encodage à la volée
# - Lookup téléphone : d’abord dans achats, sinon clients
# - URL de fiche fiable (colonne 'url' si dispo, sinon construite)
# - Logs détaillés (matching_ia.csv) et respect d’un historique (anti-doublons)

import os
import json
import re
from datetime import datetime, timedelta
from typing import Dict, List, Any, Tuple, Optional

import numpy as np
import pandas as pd
import torch
from sentence_transformers import SentenceTransformer, util

# ======= CONFIG =======
MODEL_NAME = "sentence-transformers/LaBSE"
IA_CACHE_DIR = "data/ia_cache"
HISTORIQUE_FILE = "web_flask/logs/historique_alertes.csv"
LOG_MATCHING = "web_flask/logs/matching_ia.csv"
REGLES_FILE = "config/regles_apprises.json"

SEUIL_SIMILARITE = float(os.getenv("MM_SEUIL_SIMILARITE", "0.75"))
FILTRAGE_JOURS = int(os.getenv("MM_FILTRAGE_JOURS", "7"))

# Active le match EAN exact si True
MATCH_EAN = os.getenv("MM_MATCH_EAN", "1") == "1"

# ======================

_model: Optional[SentenceTransformer] = None


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _only_digits(s: Any) -> str:
    return re.sub(r"\D", "", str(s or ""))


def _format_phone_fr(numero: str) -> str:
    """Normalise en E.164 FR (ex: 06.. -> +336..)."""
    n = re.sub(r"[^\d+]", "", str(numero or ""))
    if not n:
        return ""
    if n.startswith("00"):
        n = "+" + n[2:]
    elif n.startswith("+"):
        pass
    elif n.startswith("0"):
        n = "+33" + n[1:]
    else:
        if len(n) in (9, 10):
            n = "+33" + n[-9:]
        else:
            n = "+" + n
    return n


def _safe_read_csv(path: str) -> pd.DataFrame:
    return pd.read_csv(path, sep=None, engine="python", dtype=str).fillna("")


def _find_col(df: pd.DataFrame, candidates: List[str], default_first: bool = True) -> Optional[str]:
    lower = {c.lower(): c for c in df.columns}
    for c in candidates:
        if c in lower:
            return lower[c]
    return df.columns[0] if default_first and len(df.columns) else None


def _load_regles() -> Dict[str, str]:
    if os.path.exists(REGLES_FILE):
        try:
            with open(REGLES_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            return {str(k): str(v) for k, v in data.items()}
        except Exception:
            pass
    return {}


def _fiche_keys(row: pd.Series) -> List[str]:
    """Retourne des clés ‘fiche’ robustes (digits) à partir de colonnes usuelles."""
    out = []
    for k in ("alerte_id", "identifiant_de_la_fiche", "reference_fiche", "reference"):
        if k in row:
            d = _only_digits(row[k])
            if d:
                out.append(d)
    return out


def _build_fiche_index(rappels_df: pd.DataFrame) -> Dict[str, List[int]]:
    m: Dict[str, List[int]] = {}
    for i, row in rappels_df.iterrows():
        for key in _fiche_keys(row):
            m.setdefault(key, []).append(i)
    return m


def _extract_ean_series(df: pd.DataFrame) -> pd.Series:
    """Extraction EAN/GTIN : prend le premier bloc 8/12/13/14 chiffres par ligne."""
    if not MATCH_EAN:
        return pd.Series([""] * len(df))
    lower = {c.lower(): c for c in df.columns}
    ean_col = None
    for c in ("ean", "gtin", "codebarres", "code_barres", "code_barre", "barcode", "code"):
        if c in lower:
            ean_col = lower[c]
            break
    if ean_col is None:
        # heuristique : 8+ chiffres quelque part dans une colonne
        for c in df.columns:
            try:
                mx = df[c].astype(str).str.replace(r"\D", "", regex=True).str.len().max()
                if mx and mx >= 8:
                    ean_col = c
                    break
            except Exception:
                continue
    if ean_col is None:
        return pd.Series([""] * len(df))

    out = []
    for v in df[ean_col].astype(str):
        found = [x for x in re.findall(r"\d{8,14}", v) if len(x) in (8, 12, 13, 14)]
        out.append(found[0] if found else "")
    return pd.Series(out)


def _get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        print("⏳ Chargement du modèle IA…")
        _model = SentenceTransformer(MODEL_NAME)
        print("✅ Modèle chargé.")
    return _model


def _charger_cache_embeddings(prefix: str) -> Tuple[Optional[np.ndarray], Optional[np.ndarray]]:
    emb_file = os.path.join(IA_CACHE_DIR, f"{prefix}_embeddings.npy")
    txt_file = os.path.join(IA_CACHE_DIR, f"{prefix}_textes.npy")
    if os.path.exists(emb_file) and os.path.exists(txt_file):
        try:
            print(f"📦 Cache IA trouvé pour {prefix}.")
            return np.load(emb_file, mmap_mode="r"), np.load(txt_file, allow_pickle=True)
        except Exception:
            pass
    return None, None


def _lire_historique() -> pd.DataFrame:
    if os.path.exists(HISTORIQUE_FILE):
        try:
            return pd.read_csv(HISTORIQUE_FILE, dtype=str).fillna("")
        except Exception:
            pass
    return pd.DataFrame(columns=["Nom", "Prénom", "Produit"])


def _parse_date_any(s: str) -> Optional[pd.Timestamp]:
    for colfmt in [None, "%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"]:
        try:
            return pd.to_datetime(s, format=colfmt, errors="raise")
        except Exception:
            continue
    return None


def _filtrer_rappels_par_date(rappels_df: pd.DataFrame) -> pd.DataFrame:
    # Cherche une colonne date pertinente
    date_col = None
    for c in ("date_rappel", "date_de_rappel", "date_de_publication", "date_publication"):
        if c in rappels_df.columns:
            date_col = c
            break
    if date_col is None:
        return rappels_df  # on ne filtre pas si on ne sait pas
    # Parse
    dates = []
    for v in rappels_df[date_col].astype(str).values:
        ts = _parse_date_any(v)
        dates.append(ts)
    tmp = rappels_df.copy()
    tmp["_dt"] = dates
    tmp = tmp[~tmp["_dt"].isna()]
    if tmp.empty:
        return rappels_df
    limite = datetime.now() - timedelta(days=FILTRAGE_JOURS)
    out = tmp[tmp["_dt"] >= pd.Timestamp(limite)].drop(columns=["_dt"])
    return out


def _url_fiche(row: pd.Series) -> str:
    # Si la colonne url est fournie, on l’utilise
    if "url" in row and str(row["url"]).strip():
        return str(row["url"])
    # Sinon on fabrique à partir d’une clé fiche si possible
    keys = _fiche_keys(row)
    if keys:
        return f"https://rappel.conso.gouv.fr/fiche-rappel/{keys[0]}/Interne"
    # Dernier recours
    return "https://rappel.conso.gouv.fr"


def moteur_matching(rappels_df: pd.DataFrame, achats_df: pd.DataFrame, clients_df: pd.DataFrame) -> List[Dict[str, Any]]:
    """
    Retourne une liste de dicts {prenom, nom, telephone, produit, alerte_id, page}
    et trace matching_ia.csv. Ne modifie rien d’autre : étape 8 reste souveraine.
    """
    # 0) Filtre temporel + règles apprises
    regles_apprises = _load_regles()
    rappels_df = _filtrer_rappels_par_date(rappels_df)
    print(f"✅ {len(rappels_df)} rappels après filtre temporel (≤ {FILTRAGE_JOURS} jours).")

    historique = _lire_historique()
    print(f"ℹ️ Historique : {len(historique)} envois passés.")

    # Lookup téléphone “clients”
    clients_lookup: Dict[str, str] = {}
    if not clients_df.empty:
        lc = {c.lower(): c for c in clients_df.columns}
        idc = lc.get("id_client") or lc.get("client_id")
        telc = lc.get("telephone") or lc.get("tel") or lc.get("mobile") or lc.get("phone")
        if idc and telc:
            for cid, tel in clients_df[[idc, telc]].astype(str).values:
                fmt = _format_phone_fr(tel)
                if cid and fmt:
                    clients_lookup[str(cid)] = fmt

    # Préparation produits d’achats (règles apprises)
    prod_col = _find_col(achats_df, ["produit", "product", "libelle", "designation", "description"])
    achats_text = achats_df[prod_col].astype(str).tolist() if prod_col else [""] * len(achats_df)
    achats_text = [regles_apprises.get(x, x) for x in achats_text]

    # Index fiche + EAN
    fiche_index = _build_fiche_index(rappels_df)
    achats_ean = _extract_ean_series(achats_df)
    rappels_ean = _extract_ean_series(rappels_df)
    ean_to_idx: Dict[str, List[int]] = {}
    for i, e in enumerate(rappels_ean):
        if e:
            ean_to_idx.setdefault(e, []).append(i)

    logs: List[List[Any]] = []
    out: List[Dict[str, Any]] = []

    # === 1) Matching “exact” par identifiant de fiche (prioritaire) ===
    for i, achat in achats_df.iterrows():
        # clés fiche possibles côté achats (alerte_id / code / etc.)
        achat_keys = _fiche_keys(achat)
        if not achat_keys and "code" in achats_df.columns:
            c = _only_digits(achat.get("code", ""))
            if 3 <= len(c) <= 6:
                achat_keys = [c]

        if not achat_keys:
            continue

        for key in achat_keys:
            if key not in fiche_index:
                continue
            ridx = fiche_index[key][0]
            rapp = rappels_df.iloc[ridx]
            produit_rappel = str(
                rapp.get(
                    _find_col(rappels_df, ["titre", "libelle", "produit", "designation"]), ""
                )
            )
            # Téléphone: achats puis clients
            tel = ""
            for tk in ["telephone", "tel", "mobile", "phone", "gsm"]:
                if tk in achats_df.columns:
                    tel = str(achat.get(tk, "")) or ""
                    if tel:
                        break
            if not tel:
                cid = str(achat.get("id_client") or achat.get("client_id") or "")
                tel = clients_lookup.get(cid, "")
            tel = _format_phone_fr(tel) if tel else ""

            # Anti-doublon par historique (nom/prénom → optionnel si colonnes existent)
            nom = str(achat.get("nom", "")).strip()
            prenom = str(achat.get("prenom", "")).strip()
            statut = "Nouveau envoi"
            if nom and prenom and not historique.empty:
                if ((historique["Nom"] == nom) & (historique["Prénom"] == prenom) & (historique["Produit"] == produit_rappel)).any():
                    statut = "Ignoré (doublon)"

            logs.append([_now(), achats_text[i], produit_rappel, 1.0, rapp.get("date_rappel", ""), "Exact FICHE", statut])

            if statut == "Nouveau envoi":
                page = _url_fiche(rapp)
                out.append({
                    "prenom": prenom,
                    "nom": nom,
                    "telephone": tel,
                    "produit": produit_rappel,
                    "alerte_id": key,
                    "page": page
                })

    if out:
        _flush_logs(logs)
        print(f"✅ Matching exact (fiche) : {len(out)} alertes.")
        return out

    # === 2) Matching exact EAN (si activé) ===
    if MATCH_EAN:
        for i, achat in achats_df.iterrows():
            e = achats_ean.iloc[i] if i < len(achats_ean) else ""
            if not e or e not in ean_to_idx:
                continue
            ridx = ean_to_idx[e][0]
            rapp = rappels_df.iloc[ridx]
            produit_rappel = str(
                rapp.get(
                    _find_col(rappels_df, ["titre", "libelle", "produit", "designation"]), ""
                )
            )
            # téléphone
            tel = ""
            for tk in ["telephone", "tel", "mobile", "phone", "gsm"]:
                if tk in achats_df.columns:
                    tel = str(achat.get(tk, "")) or ""
                    if tel:
                        break
            if not tel:
                cid = str(achat.get("id_client") or achat.get("client_id") or "")
                tel = clients_lookup.get(cid, "")
            tel = _format_phone_fr(tel) if tel else ""

            nom = str(achat.get("nom", "")).strip()
            prenom = str(achat.get("prenom", "")).strip()
            statut = "Nouveau envoi"
            if nom and prenom and not historique.empty:
                if ((historique["Nom"] == nom) & (historique["Prénom"] == prenom) & (historique["Produit"] == produit_rappel)).any():
                    statut = "Ignoré (doublon)"

            logs.append([_now(), achats_text[i], produit_rappel, 1.0, rapp.get("date_rappel", ""), "Exact EAN", statut])

            if statut == "Nouveau envoi":
                page = _url_fiche(rapp)
                out.append({
                    "prenom": prenom,
                    "nom": nom,
                    "telephone": tel,
                    "produit": produit_rappel,
                    "alerte_id": _fiche_keys(rapp)[0] if _fiche_keys(rapp) else "",
                    "page": page
                })

    if out:
        _flush_logs(logs)
        print(f"✅ Matching exact (EAN) : {len(out)} alertes.")
        return out

    # === 3) Fallback IA (caches → rapide, sinon à la volée) ===
    print("🤖 Aucun match exact → Matching IA…")
    rappels_emb, rappels_txt = _charger_cache_embeddings("rappels")
    achats_emb, achats_txt = _charger_cache_embeddings("achats")

    # applique règles apprises côté achats_txt si cache
    if achats_txt is not None:
        achats_txt = np.array([regles_apprises.get(x, x) for x in achats_txt])

    if rappels_emb is not None and achats_emb is not None and rappels_txt is not None and achats_txt is not None:
        sim = util.cos_sim(torch.tensor(achats_emb), torch.tensor(rappels_emb)).cpu().numpy()
        for i in range(sim.shape[0]):
            for j in range(sim.shape[1]):
                score = float(sim[i, j])
                if score < SEUIL_SIMILARITE:
                    continue
                achat = achats_df.iloc[i]
                rapp = rappels_df.iloc[j]
                produit_rappel = str(rappels_txt[j])
                # téléphone
                tel = ""
                for tk in ["telephone", "tel", "mobile", "phone", "gsm"]:
                    if tk in achats_df.columns:
                        tel = str(achat.get(tk, "")) or ""
                        if tel:
                            break
                if not tel:
                    cid = str(achat.get("id_client") or achat.get("client_id") or "")
                    tel = clients_lookup.get(cid, "")
                tel = _format_phone_fr(tel) if tel else ""
                nom = str(achat.get("nom", "")).strip()
                prenom = str(achat.get("prenom", "")).strip()
                statut = "Nouveau envoi"
                if nom and prenom and not historique.empty:
                    if ((historique["Nom"] == nom) & (historique["Prénom"] == prenom) & (historique["Produit"] == produit_rappel)).any():
                        statut = "Ignoré (doublon)"
                logs.append([_now(), achats_txt[i], produit_rappel, round(score, 3), rapp.get("date_rappel", ""), "Cache IA", statut])
                if statut == "Nouveau envoi":
                    page = _url_fiche(rapp)
                    out.append({
                        "prenom": prenom, "nom": nom, "telephone": tel,
                        "produit": produit_rappel,
                        "alerte_id": (_fiche_keys(rapp)[0] if _fiche_keys(rapp) else ""),
                        "page": page
                    })
    else:
        # IA dynamique (plus lent)
        m = _get_model()
        rapp_labels_col = _find_col(rappels_df, ["titre", "libelle", "produit", "designation"])
        rapp_labels = rappels_df[rapp_labels_col].astype(str).tolist() if rapp_labels_col else [""] * len(rappels_df)
        for i, achat in achats_df.iterrows():
            achat_txt = achats_text[i] if i < len(achats_text) else str(achat.get(prod_col, ""))
            e1 = m.encode([achat_txt], convert_to_tensor=True)
            for j, rapp in rappels_df.iterrows():
                lab = rapp_labels[j]
                e2 = m.encode([lab], convert_to_tensor=True)
                score = float(util.cos_sim(e1, e2).cpu().numpy()[0, 0])
                if score < SEUIL_SIMILARITE:
                    continue
                # téléphone
                tel = ""
                for tk in ["telephone", "tel", "mobile", "phone", "gsm"]:
                    if tk in achats_df.columns:
                        tel = str(achat.get(tk, "")) or ""
                        if tel:
                            break
                if not tel:
                    cid = str(achat.get("id_client") or achat.get("client_id") or "")
                    tel = clients_lookup.get(cid, "")
                tel = _format_phone_fr(tel) if tel else ""
                nom = str(achat.get("nom", "")).strip()
                prenom = str(achat.get("prenom", "")).strip()
                statut = "Nouveau envoi"
                if nom and prenom and not historique.empty:
                    if ((historique["Nom"] == nom) & (historique["Prénom"] == prenom) & (historique["Produit"] == lab)).any():
                        statut = "Ignoré (doublon)"
                logs.append([_now(), achat_txt, lab, round(score, 3), rapp.get("date_rappel", ""), "IA dynamique", statut])
                if statut == "Nouveau envoi":
                    page = _url_fiche(rapp)
                    out.append({
                        "prenom": prenom, "nom": nom, "telephone": tel,
                        "produit": lab,
                        "alerte_id": (_fiche_keys(rapp)[0] if _fiche_keys(rapp) else ""),
                        "page": page
                    })

    _flush_logs(logs)
    print(f"✅ Matching IA terminé : {len(out)} alertes nouvelles détectées.")
    return out


def _flush_logs(rows: List[List[Any]]) -> None:
    if not rows:
        return
    os.makedirs(os.path.dirname(LOG_MATCHING), exist_ok=True)
    cols = ["Horodatage", "Produit_Achat", "Produit_Rappel", "Score", "Date_Rappel", "Source", "Statut"]
    df = pd.DataFrame(rows, columns=cols)
    if os.path.exists(LOG_MATCHING):
        df.to_csv(LOG_MATCHING, mode="a", index=False, header=False)
    else:
        df.to_csv(LOG_MATCHING, index=False)

