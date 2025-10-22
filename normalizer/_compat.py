"""Compatibility helpers for optional dependencies."""

from __future__ import annotations


def get_pandas():
    """Return the :mod:`pandas` module or raise a user-friendly error."""

    try:
        import pandas as pd  # type: ignore
    except ImportError as exc:  # pragma: no cover - runtime dependency
        raise ImportError(
            "Le module 'pandas' est requis. Installez les dépendances avec"
            " 'pip install -r requirements.txt'."
        ) from exc

    return pd


def get_yaml():
    """Return the :mod:`yaml` module or raise a user-friendly error."""

    try:
        import yaml  # type: ignore
    except ImportError as exc:  # pragma: no cover - runtime dependency
        raise ImportError(
            "Le module 'PyYAML' est requis. Installez les dépendances avec"
            " 'pip install -r requirements.txt'."
        ) from exc

    return yaml
