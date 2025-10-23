"""Toolkit de lecture et de normalisation des fichiers achats/clients/rappels."""
from __future__ import annotations

from pathlib import Path

from .config import WorkflowConfig, discover_config
from .normalizer import NormalizationResult, UniversalNormalizer

__all__ = [
    "WorkflowConfig",
    "discover_config",
    "UniversalNormalizer",
    "NormalizationResult",
]

__version__ = "0.1.0"

PACKAGE_ROOT = Path(__file__).resolve().parent
