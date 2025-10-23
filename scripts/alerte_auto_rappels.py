#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# scripts/alerte_auto_rappels.py
# - Télécharge CSV + RSS RappelConso
# - Normalise en 5 colonnes (produit, secteur, date, url, source) avec dates UTC→Europe/Paris
# - Écrit logs/rappels.csv et data/entree/rappels.csv
# - NEW: crée/rafraîchit un lien symbolique BASE/rappels.csv → data/entree/rappels.csv
#         (fallback en copie si symlink impossible) pour compatibilité avec l’étape 8.

import os
import sys
import shutil
from pathlib import Path
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo

import requests
import pandas as pd
import xml.etree.ElementTree as ET

# -- Chemins projet
BASE = Path(__file__).resolve().parents[1]
LOGS = BASE / "logs"
ENTREE = BASE / "data" / "entree"
LOGS.mkdir(parents=True, exist_ok=True)
ENTREE.mkdir(parents=True, exist_ok=True)

MASTER = LOGS / "rappels.csv"               # historique normalisé
ENTREE_CSV = ENTREE / "rappels.csv"         # normalisé (5 colonnes)
ROOT_SYMLINK = BASE / "rappels.csv"         # compat pour scripts qui lisent BASE/rappels.csv
HTML_OUT = BASE / "web_flask" / "rappels_detectes.html"
HTML_OUT.parent.mkdir(parents=True, exist_ok=True)

# -- Timezones
PARIS_TZ = ZoneInfo("Europe/Paris")

def to_paris_series(series_like) -> pd.Series:
    s = pd.to_datetime(series_like, errors="coerce", utc=True)
    return s.dt.tz_convert(PARIS_TZ).dt.tz_localize(None)

def to_paris_dt(dt: datetime) -> datetime:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(PARIS_TZ).replace(tzinfo=None)

# -- URLs sources
CSV_URL = "https://data.economie.gouv.fr/api/explore/v2.1/catalog/datasets/rappelconso0/exports/csv?lang=fr&timezone=Europe%2FBerlin&use_labels=true&delimiter=%3B"
# Alternative long terme :
# CSV_URL = "https://data.economie.gouv.fr/api/explore/v2.1/catalog/datasets/rappelconso-v2-gtin-espaces/exports/csv?limit=-1&timezone=Europe/Paris&use_labels=true"
RSS_URL = "https://rappel.conso.gouv.fr/rss"

def download_text(url: str, timeout=60) -> str:
    r = requests.get(url, timeout=timeout)
    r.raise_for_status()
    r.encoding = r.encoding or "utf-8"
    return r.text

def read_csv_tolerant(path_or_text) -> pd.DataFrame:
    try:
        if isinstance(path_or_text, str) and "\n" in path_or_text:
            from io import StringIO
            buf = StringIO(path_or_text)
            return pd.read_csv(buf, engine="python", sep=None, on_bad_lines="skip", dtype=str)
        return pd.read_csv(path_or_text, engine="python", sep=None, on_bad_lines="skip", dtype=str)
    except Exception:
        try:
            if isinstance(path_or_text, str) and "\n" in path_or_text:
                from io import StringIO
                buf = StringIO(path_or_text)
                return pd.read_csv(buf, engine="python", sep=";", on_bad_lines="skip", dtype=str)
            return pd.read_csv(path_or_text, engine="python", sep=";", on_bad_lines="skip", dtype=str)
        except Exception:
            try:
                if isinstance(path_or_text, str) and "\n" in path_or_text:
                    from io import StringIO
                    buf = StringIO(path_or_text)
                    return pd.read_csv(buf, engine="python", sep=",", on_bad_lines="skip", dtype=str)
                return pd.read_csv(path_or_text, engine="python", sep=",", on_bad_lines="skip", dtype=str)
            except Exception:
                return pd.DataFrame()

def normalize_rappels_csv(df: pd.DataFrame) -> pd.DataFrame:
    """Uniformise → produit/secteur/date/url/source (date en heure de Paris, naïf)."""
    if df.empty:
        return df
    cols = {c.strip(): c for c in df.columns}
    def pick(*names):
        for n in names:
            if n in cols: return cols[n]
        return None

    col_prod = pick("Titre de la fiche", "titre_de_la_fiche", "Titre", "titre")
    col_cat  = pick("Catégorie de produit", "categorie_de_produit")
    col_date = pick("Date de publication", "date_de_publication", "Date", "date")
    col_url  = pick("Lien vers la fiche rappel", "lien_vers_la_fiche_rappel", "URL", "url")

    out = pd.DataFrame()
    out["produit"] = df[col_prod] if col_prod else ""
    out["secteur"] = df[col_cat] if col_cat else ""
    out["date"]    = df[col_date] if col_date else ""
    out["url"]     = df[col_url] if col_url else ""
    out["source"]  = "CSV"

    out["date"] = to_paris_series(out["date"])
    out = out.dropna(subset=["date"])
    return out

def load_rss(url: str) -> pd.DataFrame:
    try:
        r = requests.get(url, timeout=30)
        r.raise_for_status()
        root = ET.fromstring(r.content)
    except Exception:
        return pd.DataFrame(columns=["produit","secteur","date","url","source"])

    items = []
    for item in root.findall(".//item"):
        titre = (item.findtext("title", "") or "").strip()
        lien  = (item.findtext("link", "") or "").strip()
        pub   = item.findtext("pubDate", "") or ""
        dt = None
        try:
            dt = parsedate_to_datetime(pub)
        except Exception:
            try:
                dt = datetime.strptime(pub, "%a, %d %b %Y %H:%M:%S %Z")
            except Exception:
                dt = None
        if dt is None:
            continue
        dt_paris = to_paris_dt(dt)
        items.append({
            "produit": titre,
            "secteur": "",
            "date": dt_paris,
            "url": lien,
            "source": "RSS"
        })
    return pd.DataFrame(items)

def write_master_and_entry(df: pd.DataFrame):
    df_all = df.copy()
    df_all.to_csv(MASTER, index=False)
    df_all.to_csv(ENTREE_CSV, index=False)

def make_root_symlink_to_entry():
    """Assure la compat : BASE/rappels.csv → data/entree/rappels.csv (normalisé)."""
    try:
        if ROOT_SYMLINK.is_symlink() or ROOT_SYMLINK.exists():
            ROOT_SYMLINK.unlink()
        # symlink relatif pour rester portable
        rel_target = ENTREE_CSV.relative_to(BASE)
        ROOT_SYMLINK.symlink_to(rel_target)
        how = "symlink"
    except Exception:
        # Certains FS interdisent les symlinks → on copie
        shutil.copy2(ENTREE_CSV, ROOT_SYMLINK)
        how = "copy"
    return how

def build_html(df: pd.DataFrame, out_path: Path):
    df = df.sort_values("date", ascending=False)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("""<!DOCTYPE html>
<html lang='fr'>
<head>
<meta charset='UTF-8'>
<title>Rappels consommateurs détectés</title>
<style>
html, body { margin:0; padding:0; font-family:Arial, sans-serif; background:#f6f7fb; }
.container { background:white; color:#111; max-width:1000px; margin:40px auto; padding:30px; border-radius:10px; box-shadow:0 10px 30px rgba(0,0,0,.06); }
h1 { text-align:center; color:#002147; margin:0 0 10px; }
#count { text-align:center; font-weight:bold; margin:10px 0 20px; }
table { width:100%; border-collapse:collapse; margin-top:10px; }
th, td { border-bottom:1px solid #eee; padding:10px; text-align:left; }
th { background-color:#002147; color:white; cursor:pointer; }
td a { color:#a60000; text-decoration:none; }
.filters { display:flex; gap:12px; justify-content:center; align-items:center; flex-wrap:wrap; margin-bottom: 16px; }
.refresh { text-align:center; margin-bottom: 12px; }
.refresh button { padding:10px 20px; border-radius:6px; background-color:#a60000; color:white; border:none; cursor:pointer; }
</style>
</head>
<body>
<div class="container">
<h1>Rappels consommateurs détectés</h1>
<div class="refresh"><button onclick="location.reload()">🔄 Actualiser les données</button></div>
<div id="count">0 rappels affichés</div>
<div class="filters">
<label for="categorieFilter">Catégorie :</label>
<select id="categorieFilter" onchange="filtrer()">
<option value="">-- Toutes --</option>
<option value="Alimentation">Alimentation</option>
<option value="Automobiles et moyens de déplacement">Automobiles et moyens de déplacement</option>
<option value="Bébés-Enfants (hors alimentaire)">Bébés-Enfants (hors alimentaire)</option>
<option value="Hygiène-Beauté">Hygiène-Beauté</option>
<option value="Vêtements, Mode, EPI">Vêtements, Mode, EPI</option>
<option value="Sports-loisirs">Sports-loisirs</option>
<option value="Maison-Habitat">Maison-Habitat</option>
<option value="Appareils électriques, Outils">Appareils électriques, Outils</option>
<option value="Équipements de communication">Équipements de communication</option>
<option value="Autres">Autres</option>
</select>
<label for="dateFilter">Date après :</label>
<input type="date" id="dateFilter" onchange="filtrer()">
</div>
<table id="rappelsTable">
<thead><tr>
<th>Produit</th>
<th>Secteur</th>
<th onclick="sortTable(2)">Date ⬍</th>
<th>Source</th>
<th>Lien</th>
</tr></thead>
<tbody>
""")
        for _, row in df.iterrows():
            produit = (str(row.get("produit","")).replace("&","&amp;").replace("<","&lt;"))
            secteur = str(row.get("secteur","") or "-")
            date_dt = row.get("date")
            if isinstance(date_dt, str):
                try:
                    date_dt = datetime.fromisoformat(date_dt)
                except Exception:
                    date_dt = None
            date_aff = date_dt.strftime("%d/%m/%Y") if isinstance(date_dt, datetime) else ""
            url = str(row.get("url",""))
            source = str(row.get("source",""))
            f.write(f"<tr><td>{produit}</td><td>{secteur}</td><td>{date_aff}</td><td>{source}</td><td><a href='{url}' target='_blank'>Voir</a></td></tr>\n")
        f.write("""
</tbody></table>
</div>
<script>
function sortTable(n){
  const table=document.getElementById("rappelsTable");
  let switching=true, dir="asc", switchcount=0;
  while(switching){
    switching=false;
    const rows=table.rows;
    for(let i=1;i<rows.length-1;i++){
      let shouldSwitch=false;
      const x=rows[i].getElementsByTagName("TD")[n];
      const y=rows[i+1].getElementsByTagName("TD")[n];
      const dx=new Date(x.innerHTML.split('/').reverse().join('-'));
      const dy=new Date(y.innerHTML.split('/').reverse().join('-'));
      if((dir==="asc" && dx>dy) || (dir==="desc" && dx<dy)){
        rows[i].parentNode.insertBefore(rows[i+1], rows[i]); switching=true; switchcount++;
      }
    }
    if(switchcount===0 && dir==="asc"){ dir="desc"; switching=true; }
  }
  filtrer();
}
function filtrer(){
  const cat=document.getElementById("categorieFilter").value;
  const dateLim=document.getElementById("dateFilter").value;
  const rows=document.querySelectorAll("#rappelsTable tbody tr");
  let count=0;
  rows.forEach(r=>{
    const secteur=r.children[1].textContent.trim();
    const dateTexte=r.children[2].textContent.trim();
    const [jj,mm,aa]=dateTexte.split("/");
    const dateLigne=`${aa}-${mm}-${jj}`;
    let visible=true;
    if(cat && secteur!==cat) visible=false;
    if(dateLim && dateLigne<dateLim) visible=false;
    r.style.display=visible?"":"none";
    if(visible) count++;
  });
  document.getElementById("count").innerText=`${count} rappels affichés`;
}
document.addEventListener("DOMContentLoaded", filtrer);
</script>
</body></html>""")

def main():
    # 1) CSV
    print("📥 Téléchargement du fichier CSV…")
    try:
        csv_text = download_text(CSV_URL, timeout=60)
        df_csv_raw = read_csv_tolerant(csv_text)
        df_csv = normalize_rappels_csv(df_csv_raw)
        print(f"✅ CSV chargé: {len(df_csv)} lignes utiles")
    except Exception as e:
        print("⚠️ Échec CSV :", e)
        df_csv = pd.DataFrame(columns=["produit","secteur","date","url","source"])

    # 2) RSS
    print("📥 Lecture du flux RSS…")
    try:
        df_rss = load_rss(RSS_URL)
        print(f"✅ RSS chargé: {len(df_rss)} éléments")
    except Exception as e:
        print("⚠️ Échec RSS :", e)
        df_rss = pd.DataFrame(columns=["produit","secteur","date","url","source"])

    # 3) Fusion + dédup
    df_all = pd.concat([df_csv, df_rss], ignore_index=True)
    df_all = df_all.drop_duplicates(subset=["url"], keep="first")
    df_all = df_all.dropna(subset=["date"]).sort_values("date", ascending=False)

    # 4) Écritures + symlink racine
    write_master_and_entry(df_all)
    how = make_root_symlink_to_entry()

    size_mb = MASTER.stat().st_size / (1024*1024)
    print(f"✅ Rappels mis à jour → {MASTER} ({size_mb:.2f} MB) — {len(df_all)} lignes")
    print(f"↪️ Copie pipeline → {ENTREE_CSV}")
    print(f"🔗 Racine → {ROOT_SYMLINK} → {ENTREE_CSV.name} [{how}]")
    print(f"📝 HTML → {HTML_OUT}")
    build_html(df_all, HTML_OUT)

if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:
        print("❌ Erreur alerte_auto_rappels:", e)
        sys.exit(1)
