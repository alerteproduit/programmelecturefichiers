"""Configuration helpers for the normalization pipeline."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Sequence

from ._compat import get_yaml
from . import utils


@dataclass
class ColumnSpec:
    """Specification of a normalized column."""

    name: str
    synonyms: Sequence[str] = ()
    dtype: str = "string"
    patterns: Sequence[str] = ()
    fuzzy_threshold: float | None = None

    def canonical_synonyms(self) -> List[str]:
        """Return canonicalized names for matching."""

        candidates: Iterable[str] = list(self.synonyms) + [self.name]
        return [utils.canonicalize(s) for s in candidates]

    def matches(self, column_name: str) -> bool:
        """Return ``True`` when the provided column should map to this spec."""

        canon = utils.canonicalize(column_name)
        if canon in self.canonical_synonyms():
            return True

        for pattern in self.patterns:
            if re.search(pattern, column_name, flags=re.IGNORECASE):
                return True

        if self.fuzzy_threshold:
            candidates: Iterable[str] = [self.name, *self.synonyms]
            for candidate in candidates:
                score = utils.fuzzy_ratio(column_name, candidate)
                if score >= self.fuzzy_threshold:
                    return True

        return False


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
        spec = self._index.get(key)
        if spec:
            return spec

        for candidate in self._columns:
            if candidate.matches(column_name):
                return candidate

        return None


def load_mapping(path: str | Path) -> ColumnMapping:
    """Load the column mapping from a YAML file."""

    yaml = get_yaml()
    with Path(path).open("r", encoding="utf-8") as fh:
        # ``safe_load`` rejects multi-document YAML streams. Some users may
        # duplicate mappings with ``---`` separators, so we fold any additional
        # documents into a single configuration by merging their ``columns``
        # entries. ``safe_load_all`` gracefully handles both single and
        # multi-document files.  When only one document exists the generator
        # yields a single item, keeping the common path efficient.
        documents = [doc for doc in yaml.safe_load_all(fh) if doc]

    if not documents:
        raise ValueError("Configuration file must contain a document with a 'columns' list")

    if len(documents) == 1:
        data = documents[0]
    else:
        data = {"columns": []}
        for doc in documents:
            if not isinstance(doc, dict):
                continue
            if "columns" in doc and isinstance(doc["columns"], list):
                data["columns"].extend(doc["columns"])

        if not data["columns"]:
            raise ValueError("Combined configuration must contain at least one 'columns' entry")

    if not data or "columns" not in data:
        raise ValueError("Configuration file must contain a 'columns' list")

    columns = []
    for raw_spec in data["columns"]:
        name = raw_spec.get("name")
        if not name:
            raise ValueError("Column specification missing 'name'")
        synonyms = raw_spec.get("synonyms", [])
        dtype = raw_spec.get("dtype", "string")
        patterns = raw_spec.get("patterns", [])
        fuzzy_threshold = raw_spec.get("fuzzy_threshold")
        columns.append(
            ColumnSpec(
                name=name,
                synonyms=synonyms,
                dtype=dtype,
                patterns=patterns,
                fuzzy_threshold=fuzzy_threshold,
            )
        )

    return ColumnMapping(columns)
