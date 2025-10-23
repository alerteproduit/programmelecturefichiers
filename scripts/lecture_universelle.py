
# scripts/lecture_universelle.py
import re
import pandas as pd
from pathlib import Path
from typing import Optional, Dict, Tuple

# Dossiers
UPLOAD_DIR = Path("data/uploads")
ENTREE_DIR = Path("data/entree")
ENTREE_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# ----------------------------
# Utilitaires généraux
# ----------------------------
def _std(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(s).strip().lower()).strip("_")

def human_size(nbytes: int) -> str:
    try:
        n = float(nbytes)
    except Exception:
        return "?"
    for unit in ["B","KB","MB","GB","TB"]:
        if n < 1024.0:
            return f"{n:.2f} {unit}"
        n /= 1024.0
    return f"{n:.2f} PB"

def read_table_tolerant(path: Path) -> Optional[pd.DataFrame]:
    """CSV/XLS(X) tolérant : multiencoding + multiséparateurs."""
    ext = path.suffix.lower()
    if ext in [".xlsx", ".xls"]:
        try:
            # 👇 IMPORTANT: garder tout en str pour ne jamais perdre les 0 en tête (ex: téléphone)
            return pd.read_excel(path, dtype=str).fillna("")
        except Exception as e:
            print(f"⚠️ Erreur lecture Excel {path.name}: {e}")
            return None

    encodings = ["utf-8", "latin1", "cp1252"]
    seps = [None, ";", ",", "\t", "|"]
    for enc in encodings:
        for sep in seps:
            try:
                # 👇 IMPORTANT: dtype=str pour le sniff nrows et pour la lecture complète
                pd.read_csv(path, sep=sep, engine="python", on_bad_lines="skip", encoding=enc, nrows=200, dtype=str)
                return pd.read_csv(path, sep=sep, engine="python", on_bad_lines="skip", encoding=enc, dtype=str).fillna("")
            except Exception:
                continue
    print(f"⚠️ Erreur lecture CSV {path.name}: impossible de déterminer séparateur/encodage")
    return None

    print(f"⚠️ Erreur lecture CSV {path.name}: impossible de déterminer séparateur/encodage")
    return None

def clean_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = (
        df.columns.astype(str)
        .str.strip()
        .str.lower()
        .str.normalize("NFKD")
        .str.replace(r"[^a-z0-9_]", "_", regex=True)
        .str.replace(r"_+", "_", regex=True)
        .str.strip("_")
    )
    return df

# ---------------------------------
# Heuristiques de détection
# ---------------------------------
RAPPEL_CORE = {
    "identifiant_de_la_fiche","reference_fiche","rappelguid",
    "lien_vers_la_fiche_rappel","categorie_de_produit",
    "date_de_publication","date_de_rappel","gtin","ean","sujet","motif_du_rappel"
}
RAPPEL_HINTS = {"sous_categorie_de_produit","marque","denomination","risques_encourus"}

ACHAT_PROD = {"ean","gtin","code_ean","code_gtin","libelle","produit","designation","product","code"}
ACHAT_CLIENT = {"client","id_client","client_id","carte_fidelite","customer_id"}
ACHAT_TRANSAC = {"date_achat","transaction_date","ticket_id","magasin","enseigne","quantite","qte","achat_date","date"}

CLIENT_CONTACT = {"nom","prenom","email","telephone","tel","mobile"}

NAME_HINTS = {
    "rappels": ["rappel","rappels","rappelconso","dgccrf","fiche","alertes","recall"],
    "achats":  ["achat","achats","ticket","pos","sales","vente","ventes","panier"],
    "clients": ["client","clients","customer","loyal","fid","carte"],
}

def filename_score(path: Path, target: str) -> int:
    txt = f"{path.name} {path.parent}".lower()
    return sum(1 for kw in NAME_HINTS.get(target, []) if kw in txt)

def detect_type(df: pd.DataFrame, path: Path) -> Tuple[str, str]:
    cols = set(df.columns.map(_std))

    core_hit = len(cols & RAPPEL_CORE)
    hint_hit = len(cols & RAPPEL_HINTS)
    name_boost_r = filename_score(path, "rappels")
    is_rappels = core_hit >= 3 or (core_hit >= 2 and name_boost_r >= 1)

    prod_hit = len(cols & ACHAT_PROD) > 0
    client_hit = len(cols & ACHAT_CLIENT) > 0
    transac_hit = len(cols & ACHAT_TRANSAC) > 0
    name_boost_a = filename_score(path, "achats")
    is_achats = prod_hit and (client_hit or transac_hit)

    contact_hit = len(cols & CLIENT_CONTACT)
    name_boost_c = filename_score(path, "clients")
    is_clients = contact_hit >= 2

    if is_achats and is_clients and not is_rappels:
        return "mixte", f"MIXTE (achats+clients ; prod={prod_hit}, client={client_hit}, transac={transac_hit}, name+={name_boost_a}/{name_boost_c})"
    if is_achats and not is_rappels:
        return "achats", f"ACHATS (prod={prod_hit}, client={client_hit}, transac={transac_hit}, name+={name_boost_a})"
    if is_rappels and not is_achats:
        return "rappels", f"RAPPELS (core={core_hit}, hints={hint_hit}, name+={name_boost_r})"
    if is_achats and is_rappels:
        return "achats", f"ACHATS>RAPPELS (conflit résolu en achats ; core_rappels={core_hit}, prod={prod_hit}, transac={transac_hit})"
    if is_clients:
        return "clients", f"CLIENTS (contact_fields={contact_hit}, name+={name_boost_c})"
    return "inconnu", "INCONNU (aucun seuil atteint)"

# ---------------------------------------
# Sélection du meilleur fichier par type
# ---------------------------------------
def better(p_old: Optional[Path], p_new: Path) -> Path:
    if p_old is None:
        return p_new
    try:
        key = lambda p: (p.stat().st_size, p.stat().st_mtime)
        return max([p_old, p_new], key=key)
    except Exception:
        return p_old or p_new

# ---------------------------------------
# Standardisation & fusion clients↔achats
# ---------------------------------------
def standardize_achats(df: pd.DataFrame) -> pd.DataFrame:
    df = clean_columns(df)
    ren = {}
    cols = set(df.columns)

    # produit
    if "produit" not in cols:
        for c in ["product","libelle","designation","description"]:
            if c in df.columns:
                ren[c] = "produit"; break
    # code (EAN/GTIN…)
    if "code" not in cols:
        for c in ["ean","gtin","code_ean","code_gtin","barcode","code_barres","code_barre","codebarres"]:
            if c in df.columns:
                ren[c] = "code"; break
    # date d’achat
    if "achat_date" not in cols:
        for c in ["date_achat","date","transaction_date"]:
            if c in df.columns:
                ren[c] = "achat_date"; break

    if ren: df = df.rename(columns=ren)
    # garde les colonnes principales si elles existent
    keep = [c for c in ["client_id","telephone","enseigne","produit","code","achat_date","quantite"] if c in df.columns]
    if keep:
        df = df[keep]
    return df

def standardize_clients(df: pd.DataFrame) -> pd.DataFrame:
    df = clean_columns(df)
    # normalise téléphone
    ren = {}
    if "telephone" not in df.columns:
        for c in ["tel","mobile","phone","gsm"]:
            if c in df.columns: ren[c] = "telephone"; break
    if ren: df = df.rename(columns=ren)
    keep = [c for c in ["client_id","telephone","nom","prenom"] if c in df.columns]
    if keep: df = df[keep]
    return df

def merge_achats_clients(achats: pd.DataFrame, clients: pd.DataFrame) -> pd.DataFrame:
    if "client_id" in achats.columns and "client_id" in clients.columns:
        m = achats.merge(clients[["client_id","telephone"]].drop_duplicates(), on="client_id", how="left")
        # remet l’ordre standard (si présents)
        cols_order = [c for c in ["client_id","telephone","enseigne","produit","code","achat_date","quantite"] if c in m.columns]
        return m[cols_order]
    return achats

# --------------
# Script principal
# --------------
def lecture_universelle():
    data: Dict[str, Optional[pd.DataFrame]] = {"clients": None, "achats": None, "rappels": None}
    chosen_path: Dict[str, Optional[Path]] = {"clients": None, "achats": None, "rappels": None}
    reasons: Dict[str, Optional[str]] = {"clients": None, "achats": None, "rappels": None}

    print(f"🔍 Scan récursif du dossier {UPLOAD_DIR} ...")
    candidates = [p for p in UPLOAD_DIR.rglob("*") if p.is_file() and p.suffix.lower() in [".csv",".xlsx",".xls"]]
    if not candidates:
        print("ℹ️ Aucun fichier détecté.")
        return data

    for file in candidates:
        df = read_table_tolerant(file)
        if df is None or df.empty:
            print(f"⚠️ {file.name} ignoré (lecture impossible ou vide).")
            continue
        df = clean_columns(df)
        dtype, why = detect_type(df, file)

        if dtype == "mixte":
            # Duplique sur clients et achats
            for t, expl in (("clients","MIXTE (contact+prod)"), ("achats","MIXTE (prod+client/transaction)")):
                prev = chosen_path[t]
                best = better(prev, file)
                if best is file:
                    chosen_path[t] = file
                    data[t] = df
                    reasons[t] = expl
                print(f"✅ {file.name} → {t} ({human_size(file.stat().st_size)}) — {expl}")
            continue

        if dtype in data and dtype != "inconnu":
            prev = chosen_path[dtype]
            best = better(prev, file)
            if best is file:
                chosen_path[dtype] = file
                data[dtype] = df
                reasons[dtype] = why
            print(f"✅ {file.name} → {dtype} ({human_size(file.stat().st_size)}) — {why}")
        else:
            print(f"⚠️ {file.name} ignoré (type {dtype}).")

    # Résumé
    print("\n📦 Sélection finale :")
    for t in ["clients","achats","rappels"]:
        p = chosen_path[t]
        if p is None:
            print(f"  - {t:<7} : NONE")
        else:
            size = human_size(p.stat().st_size)
            print(f"  - {t:<7} : {p.name} ({size}) — {reasons.get(t)}")

    # ---------------------------
    # ✨ Écriture vers data/entree
    # ---------------------------
    # On standardise
    df_ach = standardize_achats(data["achats"]) if data["achats"] is not None else None
    df_cli = standardize_clients(data["clients"]) if data["clients"] is not None else None
    df_rap = data["rappels"]

    # Fusion achats+clients si possible
    if df_ach is not None and df_cli is not None:
        df_ach = merge_achats_clients(df_ach, df_cli)

    # Sauvegardes
    if df_ach is not None:
        out_a = ENTREE_DIR / "achats.csv"
        df_ach.to_csv(out_a, index=False)
        print(f"📝 Écrit: {out_a} ({len(df_ach)} lignes)")
    else:
        print("❌ Aucun ACHATS normalisé à écrire.")

    if df_cli is not None:
        out_c = ENTREE_DIR / "clients.csv"
        df_cli.to_csv(out_c, index=False)
        print(f"📝 Écrit: {out_c} ({len(df_cli)} lignes)")

    if df_rap is not None:
        out_r = ENTREE_DIR / "rappels.csv"
        df_rap.to_csv(out_r, index=False)
        print(f"📝 Écrit: {out_r} ({len(df_rap)} lignes)")

    return {"clients": df_cli, "achats": df_ach, "rappels": df_rap}

if __name__ == "__main__":
    res = lecture_universelle()
    for k, df in res.items():
        if df is not None:
            print(f"\n📂 {k.upper()} : {len(df)} lignes")
            print(df.head())
        else:
            print(f"❌ Aucun fichier {k} trouvé.")
