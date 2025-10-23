"""Compatibilité descendante : alias vers le package `programmelecturefichiers`."""
from __future__ import annotations

from programmelecturefichiers import (  # noqa: F401
    NormalizationResult,
    UniversalNormalizer,
    WorkflowConfig,
    discover_config,
)

__all__ = [
    "WorkflowConfig",
    "discover_config",
    "UniversalNormalizer",
    "NormalizationResult",
]
