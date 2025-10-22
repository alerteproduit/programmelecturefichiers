"""File loading helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ._compat import get_pandas

SUPPORTED_EXTENSIONS = {".csv", ".tsv", ".txt", ".xls", ".xlsx"}


def load_table(path: str | Path, *, encoding: str | None = None):
    """Load a tabular file into a :class:`~pandas.DataFrame`."""

    pd = get_pandas()
    path = Path(path)
    ext = path.suffix.lower()

    if ext not in SUPPORTED_EXTENSIONS:
        raise ValueError(f"Unsupported file extension: {ext}")

    read_kwargs: dict[str, Any] = {}
    if encoding:
        read_kwargs["encoding"] = encoding

    if ext in {".csv", ".txt"}:
        return pd.read_csv(path, sep=None, engine="python", **read_kwargs)
    if ext == ".tsv":
        return pd.read_csv(path, sep="\t", **read_kwargs)

    return pd.read_excel(path, **read_kwargs)
