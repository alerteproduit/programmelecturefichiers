"""Utility script producing lightweight KPIs for the workflow dashboard."""
from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Dict

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = PROJECT_ROOT / "web_flask" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
DATA_DIR = PROJECT_ROOT / "data"

OUTPUT_FILE = LOG_DIR / "kpis.json"


def _count_csv_rows(path: Path) -> int:
    if not path.exists():
        return 0
    try:
        with path.open("r", encoding="utf-8") as fh:
            reader = csv.reader(fh)
            next(reader, None)  # Skip header
            return sum(1 for _ in reader)
    except Exception:
        return 0


def compute_kpis() -> Dict[str, int]:
    fichiers_recus = LOG_DIR / "fichiers_recus.csv"
    alertes = PROJECT_ROOT / "logs" / "alertes_a_envoyer.csv"
    archives_dir = DATA_DIR / "archives"

    archives_count = 0
    if archives_dir.exists():
        archives_count = sum(1 for item in archives_dir.iterdir() if item.is_dir())

    return {
        "timestamp": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "fichiers_recus": _count_csv_rows(fichiers_recus),
        "alertes_a_envoyer": _count_csv_rows(alertes),
        "archives": archives_count,
    }


def main() -> None:
    payload = compute_kpis()
    OUTPUT_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"📊 KPIs consolidés dans {OUTPUT_FILE.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
