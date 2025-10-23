"""Compatibilité descendante : alias vers le package ``programmelecturefichiers``."""
from __future__ import annotations

from programmelecturefichiers import WorkflowConfig, discover_config
from programmelecturefichiers.normalizer import NormalizationResult, UniversalNormalizer

__all__ = [
    "WorkflowConfig",
    "discover_config",
    "UniversalNormalizer",
    "NormalizationResult",
]
