from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_LOG_DIR = _PROJECT_ROOT / "web_flask" / "logs"
_EXECUTIONS_FILE = _LOG_DIR / "executions.jsonl"


def _ensure_log_dir() -> None:
    """Create the log directory expected by the workflow."""
    _LOG_DIR.mkdir(parents=True, exist_ok=True)


def log_exec(
    step: str,
    *,
    status: str = "ok",
    note: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    """Append a structured entry to ``web_flask/logs/executions.jsonl``.

    The legacy shell workflow expects this function to always succeed so the
    implementation deliberately catches no exception and only performs
    best‑effort serialisation.
    """

    _ensure_log_dir()
    record = {
        "timestamp": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "step": step,
        "status": status,
    }
    if note:
        record["note"] = note
    if extra:
        record.update(extra)

    with _EXECUTIONS_FILE.open("a", encoding="utf-8") as fh:
        json.dump(record, fh, ensure_ascii=False)
        fh.write("\n")


__all__ = ["log_exec"]
