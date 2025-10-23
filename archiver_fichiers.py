import os, shutil
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = (BASE_DIR / "../data").resolve()
ARCHIVE_DIR = (BASE_DIR / "../data/archives").resolve()

LOG_DIRS = [
    (BASE_DIR / "../web_flask/logs").resolve(),
    (BASE_DIR / "../logs").resolve(),  # certains modules écrivent ici
]

LOG_FILES = [
    "fichiers_recus.csv",
    "kpis_rappels.csv",
    "historique_alertes.csv",
    "clics_clients.csv",
    "overview_daily.csv",
    "rappels_detectes.csv",
]

def safe_copytree(src: Path, dst: Path):
    if src.exists():
        shutil.copytree(src, dst, dirs_exist_ok=True)

def safe_copy(src: Path, dst_dir: Path, copied):
    if src.exists() and src.is_file():
        dst_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst_dir / src.name)
        copied.append(str(src))
        return True
    return False

def archiver_fichiers():
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    archive_path = ARCHIVE_DIR / f"archive_{ts}"
    archive_path.mkdir(parents=True, exist_ok=True)

    print(f"📦 Archivage en cours vers {archive_path}...")

    # 1) Dossiers de data
    for d in ["entree", "ia_cache"]:
        src = DATA_DIR / d
        dst = archive_path / d
        if src.exists():
            safe_copytree(src, dst)
            print(f"✅ Dossier archivé : {d}")
        else:
            print(f"ℹ️ Dossier manquant : {d}")

    # 2) Logs CSV (depuis web_flask/logs et logs)
    copied = []
    missing = []
    for name in LOG_FILES:
        found = False
        for logdir in LOG_DIRS:
            if safe_copy(logdir / name, archive_path, copied):
                print(f"✅ Log archivé : {name}  (depuis {logdir})")
                found = True
                break
        if not found:
            missing.append(name)

    if missing:
        print("⚠️ Logs absents (non trouvés dans web_flask/logs ni logs) :", ", ".join(missing))

    print(f"✅ Archivage terminé : {archive_path}")
    if copied:
        print("Résumé copiés:")
        for c in copied:
            print("  •", c)

if __name__ == "__main__":
    archiver_fichiers()
