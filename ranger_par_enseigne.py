import os, re, json, shutil
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
SRC_DIR = BASE / "data" / "uploads"          # source "en vrac" (ou ton dossier actuel)
DEST_DIR = BASE / "data" / "uploads"         # même racine, on reclasse dans sous-dossiers
CONF = BASE / "config" / "enseignes.json"

def load_mapping():
    if not CONF.exists():
        return {"autre": []}
    with open(CONF, "r", encoding="utf-8") as f:
        raw = json.load(f)
    # compile regex par enseigne
    compiled = []
    for enseigne, keys in raw.items():
        if not keys: 
            compiled.append((enseigne, None))
            continue
        pat = r"|".join([re.escape(k) for k in keys if k.strip()])
        compiled.append((enseigne, re.compile(pat, re.I)))
    return compiled

def guess_enseigne(name: str, mapping):
    for ens, rx in mapping:
        if rx and rx.search(name):
            return ens
    return "autre"

def main():
    mapping = load_mapping()
    today = datetime.utcnow().strftime("%Y-%m-%d")

    # fichiers à plat dans data/uploads (sans sous-dossiers d’enseigne)
    for p in list(SRC_DIR.glob("*")):
        if p.is_dir():
            # on ignore déjà les sous-dossiers qui seraient des enseignes
            continue
        if not p.name.lower().endswith((".csv", ".xlsx", ".zip")):
            continue

        ens = guess_enseigne(p.name.lower(), mapping)
        dest = DEST_DIR / ens / today
        dest.mkdir(parents=True, exist_ok=True)
        target = dest / p.name

        # si un fichier de même nom existe, suffixe horodaté
        if target.exists():
            stem, suf = os.path.splitext(p.name)
            target = dest / f"{stem}_{datetime.utcnow().strftime('%H%M%S')}{suf}"

        shutil.move(str(p), str(target))
        print(f"↪️  {p.name} ➜ {ens}/{today}/")

if __name__ == "__main__":
    main()
