"""Configuration helpers for the normalization pipeline."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence

from ._compat import get_yaml
from . import utils

LOGGER = logging.getLogger(__name__)


@dataclass
class ColumnSpec:
    """Specification of a normalized column."""

    name: str
    synonyms: list[str] = field(default_factory=list)
    dtype: str = "string"
    patterns: list[str] = field(default_factory=list)
    fuzzy_threshold: float | None = None
    extras: dict[str, Any] = field(default_factory=dict)

    def canonical_synonyms(self) -> List[str]:
        """Return canonicalized names for matching."""

        candidates: Iterable[str] = [*self.synonyms, self.name]
        return [utils.canonicalize(s) for s in candidates]

    def add_synonym(self, value: str) -> bool:
        """Record a new synonym for this column if it is unknown."""

        canon = utils.canonicalize(value)
        if canon in self.canonical_synonyms():
            return False

        self.synonyms.append(value)
        self.synonyms = utils.unique_preserving_order(self.synonyms)
        return True

    def to_dict(self) -> dict[str, Any]:
        """Serialize the specification back to a dictionary."""

        data: dict[str, Any] = dict(self.extras)
        data["name"] = self.name
        if self.synonyms:
            data["synonyms"] = list(self.synonyms)
        if self.dtype:
            data["dtype"] = self.dtype
        if self.patterns:
            data["patterns"] = list(self.patterns)
        if self.fuzzy_threshold is not None:
            data["fuzzy_threshold"] = self.fuzzy_threshold
        return data

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

    def __init__(
        self,
        columns: Sequence[ColumnSpec],
        *,
        source_path: str | Path | None = None,
    ):
        if not columns:
            raise ValueError("Column mapping requires at least one column specification")
        self._columns = list(columns)
        self._index: Dict[str, ColumnSpec] = {}
        for spec in self._columns:
            for synonym in spec.canonical_synonyms():
                self._index[synonym] = spec
        self._dirty = False
        self._path = Path(source_path) if source_path else None

    @property
    def columns(self) -> Sequence[ColumnSpec]:
        return list(self._columns)

    @property
    def dirty(self) -> bool:
        return self._dirty

    @property
    def source_path(self) -> Path | None:
        return self._path

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

    def learn(self, spec: ColumnSpec, raw_column: str) -> bool:
        """Add ``raw_column`` as a synonym for ``spec`` when unknown."""

        canon = utils.canonicalize(raw_column)
        existing = self._index.get(canon)
        if existing is spec:
            return False
        if existing is not None and existing is not spec:
            return False

        if spec.add_synonym(raw_column):
            self._index[canon] = spec
            self._dirty = True
            LOGGER.debug("Learned new synonym '%s' for column '%s'", raw_column, spec.name)
            return True

        return False

    def save(self, path: str | Path | None = None) -> bool:
        """Persist learned synonyms back to disk."""

        if not self._dirty:
            return False

        target = Path(path) if path else self._path
        if target is None:
            raise ValueError("No target path provided to save the mapping")

        yaml = get_yaml()
        data = {"columns": [spec.to_dict() for spec in self._columns]}
        with target.open("w", encoding="utf-8") as fh:
            yaml.safe_dump(data, fh, sort_keys=False, allow_unicode=True)

        self._dirty = False
        self._path = target
        LOGGER.info("Updated column mapping saved to %s", target)
        return True


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
        synonyms = list(raw_spec.get("synonyms", []))
        dtype = raw_spec.get("dtype", "string")
        patterns = list(raw_spec.get("patterns", []))
        fuzzy_threshold = raw_spec.get("fuzzy_threshold")
        extras = {
            key: value
            for key, value in raw_spec.items()
            if key
            not in {"name", "synonyms", "dtype", "patterns", "fuzzy_threshold"}
        }
        columns.append(
            ColumnSpec(
                name=name,
                synonyms=synonyms,
                dtype=dtype,
                patterns=patterns,
                fuzzy_threshold=fuzzy_threshold,
                extras=extras,
            )
        )

    return ColumnMapping(columns, source_path=path)
