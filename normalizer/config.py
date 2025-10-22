"""Configuration helpers for the normalization pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Sequence

from ._compat import get_yaml
from . import utils


@dataclass
class ColumnSpec:
    """Specification of a normalized column."""

    name: str
    synonyms: Sequence[str]
    dtype: str = "string"

    def canonical_synonyms(self) -> List[str]:
        """Return canonicalized names for matching."""

        candidates: Iterable[str] = list(self.synonyms) + [self.name]
        return [utils.canonicalize(s) for s in candidates]


class ColumnMapping:
    """Represents the mapping configuration."""

    def __init__(self, columns: Sequence[ColumnSpec]):
        if not columns:
            raise ValueError("Column mapping requires at least one column specification")
        self._columns = list(columns)
        self._index: Dict[str, ColumnSpec] = {}
        for spec in self._columns:
            for synonym in spec.canonical_synonyms():
                self._index[synonym] = spec

    @property
    def columns(self) -> Sequence[ColumnSpec]:
        return list(self._columns)

    def match(self, column_name: str) -> ColumnSpec | None:
        """Return the spec matching the provided raw column name."""

        key = utils.canonicalize(column_name)
        return self._index.get(key)


def load_mapping(path: str | Path) -> ColumnMapping:
    """Load the column mapping from a YAML file."""

    yaml = get_yaml()
    with Path(path).open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)

    if not data or "columns" not in data:
        raise ValueError("Configuration file must contain a 'columns' list")

    columns = []
    for raw_spec in data["columns"]:
        name = raw_spec.get("name")
        if not name:
            raise ValueError("Column specification missing 'name'")
        synonyms = raw_spec.get("synonyms", [])
        dtype = raw_spec.get("dtype", "string")
        columns.append(ColumnSpec(name=name, synonyms=synonyms, dtype=dtype))

    return ColumnMapping(columns)
