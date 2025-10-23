"""Helpers de compatibilité (dépendances optionnelles, TOML, etc.)."""

from __future__ import annotations

from importlib import import_module
from importlib.util import find_spec


def load_optional(module: str):
    """Retourne un module optionnel ou ``None`` s'il est introuvable."""
    return import_module(module) if find_spec(module) else None


if find_spec("tomllib") is not None:  # pragma: no cover - dépend du runtime
    import tomllib as _tomllib  # type: ignore[attr-defined]
elif find_spec("tomli") is not None:  # pragma: no cover - fallback Py<3.11
    import tomli as _tomllib  # type: ignore[import-not-found]
else:  # pragma: no cover - manque de dépendances
    _tomllib = None


def load_toml(data: bytes):
    """Charge un flux TOML en utilisant ``tomllib`` ou ``tomli`` si disponible."""
    if _tomllib is None:
        raise RuntimeError(
            "Aucun parser TOML disponible. Installez 'tomli' pour les runtimes < 3.11."
        )
    return _tomllib.loads(data)
