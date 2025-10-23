"""Toolkit de lecture et de normalisation des fichiers achats/clients/rappels."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .config import WorkflowConfig, discover_config

__all__ = [
    "WorkflowConfig",
    "discover_config",
    "UniversalNormalizer",
    "NormalizationResult",
]

__version__ = "0.1.0"

PACKAGE_ROOT = Path(__file__).resolve().parent


def __getattr__(name: str) -> Any:  # pragma: no cover - accès dynamique simple
    if name in {"UniversalNormalizer", "NormalizationResult"}:
        from .normalizer import NormalizationResult, UniversalNormalizer

        return {  # type: ignore[return-value]
            "UniversalNormalizer": UniversalNormalizer,
            "NormalizationResult": NormalizationResult,
        }[name]
    raise AttributeError(name)
