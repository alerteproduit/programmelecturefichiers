"""Cœur métier : lecture tolérante des fichiers uploads et normalisation."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, Optional, Tuple

import pandas as pd

from .config import WorkflowConfig

__all__ = ["NormalizationResult", "UniversalNormalizer"]


@dataclass
class NormalizationResult:
    clients: Optional[pd.DataFrame] = None
    achats: Optional[pd.DataFrame] = None
    rappels: Optional[pd.DataFrame] = None
    selected_files: Dict[str, Optional[Path]] = field(default_factory=dict)
    reasons: Dict[str, Optional[str]] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Optional[pd.DataFrame]]:
        return {"clients": self.clients, "achats": self.achats, "rappels": self.rappels}


class UniversalNormalizer:
    """Implémente la logique de ``scripts/lecture_universelle.py`` sous forme réutilisable."""

    SUPPORTED_SUFFIXES = {".csv", ".xlsx", ".xls"}

    RAPPEL_CORE = {
        "identifiant_de_la_fiche",
        "reference_fiche",
        "rappelguid",
        "lien_vers_la_fiche_rappel",
        "categorie_de_produit",
        "date_de_publication",
        "date_de_rappel",
        "gtin",
        "ean",
        "sujet",
        "motif_du_rappel",
    }
    RAPPEL_HINTS = {"sous_categorie_de_produit", "marque", "denomination", "risques_encourus"}

    ACHAT_PROD = {"ean", "gtin", "code_ean", "code_gtin", "libelle", "produit", "designation", "product", "code"}
    ACHAT_CLIENT = {"client", "id_client", "client_id", "carte_fidelite", "customer_id"}
    ACHAT_TRANSAC = {
        "date_achat",
        "transaction_date",
        "ticket_id",
        "magasin",
        "enseigne",
        "quantite",
        "qte",
        "achat_date",
        "date",
    }

    CLIENT_CONTACT = {"nom", "prenom", "email", "telephone", "tel", "mobile"}

    NAME_HINTS = {
        "rappels": ["rappel", "rappels", "rappelconso", "dgccrf", "fiche", "alertes", "recall"],
        "achats": ["achat", "achats", "ticket", "pos", "sales", "vente", "ventes", "panier"],
        "clients": ["client", "clients", "customer", "loyal", "fid", "carte"],
    }

    def __init__(self, config: WorkflowConfig):
        self.config = config
        self.config.ensure_directories()

    # ----------------------------
    # Utilitaires généraux
    # ----------------------------
    @staticmethod
    def _std(s: str) -> str:
        return re.sub(r"[^a-z0-9]+", "_", str(s).strip().lower()).strip("_")

    @staticmethod
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

    def read_table_tolerant(self, path: Path) -> Optional[pd.DataFrame]:
        ext = path.suffix.lower()
        if ext in {".xlsx", ".xls"}:
            try:
                return pd.read_excel(path, dtype=str).fillna("")
            except Exception as exc:
                print(f"⚠️ Erreur lecture Excel {path.name}: {exc}")
                return None

        encodings = ["utf-8", "latin1", "cp1252"]
        seps = [None, ";", ",", "\t", "|"]
        for enc in encodings:
            for sep in seps:
                try:
                    pd.read_csv(
                        path,
                        sep=sep,
                        engine="python",
                        on_bad_lines="skip",
                        encoding=enc,
                        nrows=200,
                        dtype=str,
                    )
                    return pd.read_csv(
                        path,
                        sep=sep,
                        engine="python",
                        on_bad_lines="skip",
                        encoding=enc,
                        dtype=str,
                    ).fillna("")
                except Exception:
                    continue
        print(f"⚠️ Erreur lecture CSV {path.name}: impossible de déterminer séparateur/encodage")
        return None

    @staticmethod
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

    def filename_score(self, path: Path, target: str) -> int:
        txt = f"{path.name} {path.parent}".lower()
        return sum(1 for kw in self.NAME_HINTS.get(target, []) if kw in txt)

    def detect_type(self, df: pd.DataFrame, path: Path) -> Tuple[str, str]:
        cols = set(df.columns.map(self._std))

        core_hit = len(cols & self.RAPPEL_CORE)
        hint_hit = len(cols & self.RAPPEL_HINTS)
        name_boost_r = self.filename_score(path, "rappels")
        is_rappels = core_hit >= 3 or (core_hit >= 2 and name_boost_r >= 1)

        prod_hit = len(cols & self.ACHAT_PROD) > 0
        client_hit = len(cols & self.ACHAT_CLIENT) > 0
        transac_hit = len(cols & self.ACHAT_TRANSAC) > 0
        name_boost_a = self.filename_score(path, "achats")
        is_achats = prod_hit and (client_hit or transac_hit)

        contact_hit = len(cols & self.CLIENT_CONTACT)
        name_boost_c = self.filename_score(path, "clients")
        is_clients = contact_hit >= 2

        if is_achats and is_clients and not is_rappels:
            return "mixte", (
                "MIXTE (achats+clients ; "
                f"prod={prod_hit}, client={client_hit}, transac={transac_hit}, "
                f"name+={name_boost_a}/{name_boost_c})"
            )
        if is_achats and not is_rappels:
            return "achats", (
                "ACHATS (prod={prod_hit}, client={client_hit}, "
                f"transac={transac_hit}, name+={name_boost_a})"
            )
        if is_rappels and not is_achats:
            return "rappels", f"RAPPELS (core={core_hit}, hints={hint_hit}, name+={name_boost_r})"
        if is_achats and is_rappels:
            return "achats", (
                "ACHATS>RAPPELS (conflit résolu en achats ; "
                f"core_rappels={core_hit}, prod={prod_hit}, transac={transac_hit})"
            )
        if is_clients:
            return "clients", f"CLIENTS (contact_fields={contact_hit}, name+={name_boost_c})"
        return "inconnu", "INCONNU (aucun seuil atteint)"

    @staticmethod
    def _better(p_old: Optional[Path], p_new: Path) -> Path:
        if p_old is None:
            return p_new
        try:
            key = lambda p: (p.stat().st_size, p.stat().st_mtime)
            return max([p_old, p_new], key=key)
        except Exception:
            return p_old or p_new

    @staticmethod
    def standardize_achats(df: Optional[pd.DataFrame]) -> Optional[pd.DataFrame]:
        if df is None:
            return None
        df = UniversalNormalizer.clean_columns(df)
        ren: Dict[str, str] = {}
        cols = set(df.columns)
        if "produit" not in cols:
            for c in ["product", "libelle", "designation", "description"]:
                if c in df.columns:
                    ren[c] = "produit"
                    break
        if "code" not in cols:
            for c in ["ean", "gtin", "code_ean", "code_gtin", "barcode", "code_barres", "code_barre", "codebarres"]:
                if c in df.columns:
                    ren[c] = "code"
                    break
        if "achat_date" not in cols:
            for c in ["date_achat", "date", "transaction_date"]:
                if c in df.columns:
                    ren[c] = "achat_date"
                    break
        if ren:
            df = df.rename(columns=ren)
        keep = [
            c
            for c in ["client_id", "telephone", "enseigne", "produit", "code", "achat_date", "quantite"]
            if c in df.columns
        ]
        if keep:
            df = df[keep]
        return df

    @staticmethod
    def standardize_clients(df: Optional[pd.DataFrame]) -> Optional[pd.DataFrame]:
        if df is None:
            return None
        df = UniversalNormalizer.clean_columns(df)
        ren: Dict[str, str] = {}
        if "telephone" not in df.columns:
            for c in ["tel", "mobile", "phone", "gsm"]:
                if c in df.columns:
                    ren[c] = "telephone"
                    break
        if ren:
            df = df.rename(columns=ren)
        keep = [c for c in ["client_id", "telephone", "nom", "prenom"] if c in df.columns]
        if keep:
            df = df[keep]
        return df

    @staticmethod
    def merge_achats_clients(achats: pd.DataFrame, clients: pd.DataFrame) -> pd.DataFrame:
        if "client_id" in achats.columns and "client_id" in clients.columns:
            merged = achats.merge(
                clients[["client_id", "telephone"]].drop_duplicates(),
                on="client_id",
                how="left",
            )
            cols_order = [
                c
                for c in [
                    "client_id",
                    "telephone",
                    "enseigne",
                    "produit",
                    "code",
                    "achat_date",
                    "quantite",
                ]
                if c in merged.columns
            ]
            return merged[cols_order]
        return achats

    def _candidates(self) -> Iterable[Path]:
        for path in self.config.uploads_dir.rglob("*"):
            if path.is_file() and path.suffix.lower() in self.SUPPORTED_SUFFIXES:
                yield path

    def run(self) -> NormalizationResult:
        result = NormalizationResult(
            selected_files={"clients": None, "achats": None, "rappels": None},
            reasons={"clients": None, "achats": None, "rappels": None},
        )

        print(f"🔍 Scan récursif du dossier {self.config.uploads_dir} ...")
        candidates = list(self._candidates())
        if not candidates:
            print("ℹ️ Aucun fichier détecté.")
            return result

        dataframes: Dict[str, Optional[pd.DataFrame]] = {"clients": None, "achats": None, "rappels": None}

        for file in candidates:
            df = self.read_table_tolerant(file)
            if df is None or df.empty:
                print(f"⚠️ {file.name} ignoré (lecture impossible ou vide).")
                continue
            df = self.clean_columns(df)
            dtype, why = self.detect_type(df, file)

            if dtype == "mixte":
                for target, expl in (("clients", "MIXTE (contact+prod)"), ("achats", "MIXTE (prod+client/transaction)")):
                    prev = result.selected_files[target]
                    best = self._better(prev, file)
                    if best is file:
                        result.selected_files[target] = file
                        dataframes[target] = df
                        result.reasons[target] = expl
                    print(
                        f"✅ {file.name} → {target} ({self.human_size(file.stat().st_size)}) — {expl}"
                    )
                continue

            if dtype in dataframes and dtype != "inconnu":
                prev = result.selected_files[dtype]
                best = self._better(prev, file)
                if best is file:
                    result.selected_files[dtype] = file
                    dataframes[dtype] = df
                    result.reasons[dtype] = why
                print(
                    f"✅ {file.name} → {dtype} ({self.human_size(file.stat().st_size)}) — {why}"
                )
            else:
                print(f"⚠️ {file.name} ignoré (type {dtype}).")

        print("\n📦 Sélection finale :")
        for dtype in ["clients", "achats", "rappels"]:
            path = result.selected_files[dtype]
            if path is None:
                print(f"  - {dtype:<7} : NONE")
            else:
                size = self.human_size(path.stat().st_size)
                print(f"  - {dtype:<7} : {path.name} ({size}) — {result.reasons.get(dtype)}")

        df_ach = self.standardize_achats(dataframes["achats"])
        df_cli = self.standardize_clients(dataframes["clients"])
        df_rap = dataframes["rappels"]

        if df_ach is not None and df_cli is not None:
            df_ach = self.merge_achats_clients(df_ach, df_cli)

        result.achats = df_ach
        result.clients = df_cli
        result.rappels = df_rap

        if df_ach is not None:
            out_a = self.config.entree_dir / "achats.csv"
            df_ach.to_csv(out_a, index=False)
            print(f"📝 Écrit: {out_a} ({len(df_ach)} lignes)")
        else:
            print("❌ Aucun ACHATS normalisé à écrire.")

        if df_cli is not None:
            out_c = self.config.entree_dir / "clients.csv"
            df_cli.to_csv(out_c, index=False)
            print(f"📝 Écrit: {out_c} ({len(df_cli)} lignes)")

        if df_rap is not None:
            out_r = self.config.entree_dir / "rappels.csv"
            df_rap.to_csv(out_r, index=False)
            print(f"📝 Écrit: {out_r} ({len(df_rap)} lignes)")
            self.config.apply_symlink(out_r)

        return result
