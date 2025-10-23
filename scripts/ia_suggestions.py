"""Lightweight placeholder for IA suggestion harvesting.

The historical workflow expects a module named ``scripts.ia_suggestions`` to
run near the end of the pipeline.  The real implementation was not delivered
with the repository, so this module focuses on two goals:

* avoid a crash when the workflow reaches this step;
* leave a concise trace explaining that no advanced IA feedback is available
  yet.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = PROJECT_ROOT / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
TRACE_FILE = LOG_DIR / "ia_suggestions.json"


def collect_stub_feedback() -> Dict[str, Any]:
    """Return a small payload stating that the step ran successfully."""

    return {
        "timestamp": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "status": "noop",
        "message": (
            "Aucune suggestion IA supplémentaire n'a été générée car le module "
            "complet n'est pas encore implémenté."
        ),
    }


def main() -> None:
    payload = collect_stub_feedback()
    TRACE_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"ℹ️  Suggestions IA factices enregistrées dans {TRACE_FILE.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
