"""Utility functions used by the normalization pipeline."""

from __future__ import annotations

import logging
import re
from difflib import SequenceMatcher
import unicodedata
from typing import Iterable, TYPE_CHECKING

from ._compat import get_pandas

if TYPE_CHECKING:  # pragma: no cover - typing aid
    import pandas as pd

LOGGER = logging.getLogger("normalizer")


def canonicalize(value: str) -> str:
    """Return a canonical representation of a column name.

    The canonical form removes diacritics, whitespace and punctuation so that
    columns such as ``"Nom du client"`` and ``"nom_client"`` map to the same key.
    """

    normalized = unicodedata.normalize("NFKD", value)
    normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    normalized = normalized.lower()
    normalized = re.sub(r"[^a-z0-9]+", "", normalized)
    return normalized


def fuzzy_ratio(left: str, right: str) -> float:
    """Return a similarity score between two strings in the range [0, 100]."""

    if not left or not right:
        return 0.0

    matcher = SequenceMatcher(None, left.lower(), right.lower())
    return matcher.ratio() * 100


def coerce_dtype(series: "pd.Series", dtype: str) -> "pd.Series":
    """Attempt to coerce a pandas Series to the requested dtype."""

    pd = get_pandas()
    dtype = (dtype or "string").lower()

    if dtype in {"string", "str", "text"}:
        return series.astype("string")
    if dtype in {"int", "integer"}:
        return pd.to_numeric(series, errors="coerce").astype("Int64")
    if dtype in {"float", "double", "number"}:
        return pd.to_numeric(series, errors="coerce")
    if dtype in {"bool", "boolean"}:
        return series.astype("boolean")
    if dtype in {"date", "datetime"}:
        return pd.to_datetime(series, errors="coerce")

    LOGGER.warning("Unknown dtype '%s', leaving column unchanged", dtype)
    return series


def iter_files(root: str, extensions: Iterable[str]) -> Iterable[str]:
    """Yield files from ``root`` that match the provided extensions."""

    from pathlib import Path

    allowed = {ext.lower() for ext in extensions}
    for path in Path(root).iterdir():
        if path.is_file() and path.suffix.lower() in allowed:
            yield str(path)
