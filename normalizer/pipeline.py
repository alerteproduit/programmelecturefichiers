"""High-level pipeline to normalize heterogeneous tabular files."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterable, List, Tuple, TYPE_CHECKING

from . import config, loader, utils
from ._compat import get_pandas

if TYPE_CHECKING:  # pragma: no cover - typing aid
    import pandas as pd

LOGGER = logging.getLogger("normalizer")


class NormalizationError(RuntimeError):
    """Raised when the pipeline fails to normalize a file."""


MATCHED_COLUMN = Tuple[List[str], "pd.Series"]


def normalize_file(
    path: str | Path,
    mapping: config.ColumnMapping,
    *,
    encoding: str | None = None,
):
    """Normalize a single file and return a :class:`~pandas.DataFrame`."""

    raw_df = loader.load_table(path, encoding=encoding)
    normalized_df = _normalize_dataframe(raw_df, mapping)
    return normalized_df


def normalize_directory(
    input_dir: str | Path,
    output_dir: str | Path,
    mapping: config.ColumnMapping,
    *,
    encoding: str | None = None,
    output_format: str = "csv",
) -> list[Path]:
    """Normalize all supported files in ``input_dir`` and store the results."""

    pd = get_pandas()
    input_dir = Path(input_dir)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    results: list[Path] = []
    for file_path in utils.iter_files(str(input_dir), loader.SUPPORTED_EXTENSIONS):
        try:
            normalized = normalize_file(file_path, mapping, encoding=encoding)
        except Exception as exc:  # pragma: no cover - defensive logging
            LOGGER.exception("Failed to normalize %s: %s", file_path, exc)
            raise NormalizationError(str(exc)) from exc

        out_name = Path(file_path).stem + f".normalized.{output_format}"
        destination = output_dir / out_name
        if output_format == "csv":
            normalized.to_csv(destination, index=False)
        elif output_format == "xlsx":
            normalized.to_excel(destination, index=False)
        else:
            raise ValueError(f"Unsupported output format: {output_format}")

        results.append(destination)
    return results


def _normalize_dataframe(df, mapping: config.ColumnMapping):
    """Return a normalized view of ``df`` according to ``mapping``."""

    pd = get_pandas()
    normalized = pd.DataFrame()
    used_columns: set[str] = set()

    for spec in mapping.columns:
        used, series = _find_column(df, mapping, spec)
        used_columns.update(used)
        converted = utils.coerce_dtype(series, spec.dtype)
        normalized[spec.name] = converted

    extra_columns = [col for col in df.columns if col not in used_columns]
    for column in extra_columns:
        normalized[column] = df[column]

    return normalized


def _find_column(
    df, mapping: config.ColumnMapping, spec: config.ColumnSpec
) -> MATCHED_COLUMN:
    """Return a tuple of used column names and the associated Series."""

    pd = get_pandas()
    candidates: list[str] = []
    for column in df.columns:
        if mapping_match(spec, column):
            candidates.append(column)

    if not candidates:
        for column in df.columns:
            matched_spec = mapping.match(column)
            if matched_spec is spec:
                candidates.append(column)

    if candidates:
        column = _choose_best_column(df, candidates)
        return [column], df[column]

    return [], pd.Series([pd.NA] * len(df))


def _choose_best_column(df, candidates: Iterable[str]) -> str:
    """Return the candidate column containing the richest dataset."""

    best_column = None
    best_score = -1
    for column in candidates:
        series = df[column]
        score = int(series.notna().sum())
        if score > best_score:
            best_score = score
            best_column = column

    # ``candidates`` is guaranteed to be non-empty when this helper is used
    assert best_column is not None  # pragma: no cover - defensive programming
    return best_column


def mapping_match(spec: config.ColumnSpec, column: str) -> bool:
    """Return ``True`` when ``column`` matches the provided ``spec``."""

    return spec.matches(column)
