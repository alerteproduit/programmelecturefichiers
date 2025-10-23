"""Entrypoint used by the "lecture universelle" step of the workflow."""

from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path
from typing import Iterable

from normalizer import config as norm_config
from normalizer.pipeline import NormalizationError, normalize_directory

LOGGER = logging.getLogger(__name__)

# Environment variable fallbacks for the workflow integration. The workflow that
# hosts this project already defines ``AP_*`` variables for most directories, so
# we look them up in order before falling back to our internal defaults.
_INPUT_ENV_VARS: tuple[str, ...] = (
    "AP_LU_INPUT_DIR",
    "AP_ENTREE_DIR",
)
_OUTPUT_ENV_VARS: tuple[str, ...] = (
    "AP_LU_OUTPUT_DIR",
    "AP_NORMALIZED_DIR",
)
_CONFIG_ENV_VARS: tuple[str, ...] = (
    "AP_LU_CONFIG",
    "AP_COLUMN_MAPPING",
)
_ENCODING_ENV_VARS: tuple[str, ...] = (
    "AP_LU_ENCODING",
    "AP_DEFAULT_ENCODING",
)
_OUTPUT_FORMAT_ENV_VARS: tuple[str, ...] = (
    "AP_LU_OUTPUT_FORMAT",
    "AP_NORMALIZED_FORMAT",
)
_AUTO_LEARN_ENV_VARS: tuple[str, ...] = (
    "AP_LU_AUTO_LEARN",
    "AP_AUTO_LEARN",
)


def _first_set(env_vars: Iterable[str], default: str) -> str:
    """Return the first environment variable defined among ``env_vars``."""

    for name in env_vars:
        value = os.getenv(name)
        if value:
            return value
    return default


def _env_flag(env_vars: Iterable[str], default: bool = False) -> bool:
    """Return ``True`` when any of ``env_vars`` is set to a truthy value."""

    truthy = {"1", "true", "t", "yes", "y", "on"}
    falsy = {"0", "false", "f", "no", "n", "off"}

    for name in env_vars:
        value = os.getenv(name)
        if value is None:
            continue
        normalized = value.strip().lower()
        if normalized in truthy:
            return True
        if normalized in falsy:
            return False
        LOGGER.warning(
            "Valeur d'environnement inattendue pour %s: %r (attendu: %s ou %s)",
            name,
            value,
            ",".join(sorted(truthy)),
            ",".join(sorted(falsy)),
        )
    return default


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Normalise les fichiers déposés par le workflow et alimente le dossier "
            "de sortie pour les étapes suivantes."
        )
    )
    parser.add_argument(
        "--input-dir",
        default=_first_set(_INPUT_ENV_VARS, "data/entree"),
        help="Dossier contenant les fichiers bruts à normaliser",
    )
    parser.add_argument(
        "--output-dir",
        default=_first_set(_OUTPUT_ENV_VARS, "data/normalized"),
        help="Dossier de sortie pour les fichiers normalisés",
    )
    parser.add_argument(
        "--config",
        default=_first_set(_CONFIG_ENV_VARS, "config/column_mappings.yaml"),
        help="Chemin vers le mapping de colonnes YAML",
    )
    parser.add_argument(
        "--encoding",
        default=_first_set(_ENCODING_ENV_VARS, ""),
        help="Encodage forcé pour la lecture des CSV (optionnel)",
    )
    parser.add_argument(
        "--output-format",
        default=_first_set(_OUTPUT_FORMAT_ENV_VARS, "csv"),
        choices=["csv", "xlsx"],
        help="Format de sortie désiré",
    )
    parser.add_argument(
        "--auto-learn",
        dest="auto_learn",
        action="store_true",
        help=(
            "Enregistre automatiquement les nouveaux intitulés de colonnes "
            "découverts pendant la normalisation"
        ),
    )
    parser.add_argument(
        "--no-auto-learn",
        dest="auto_learn",
        action="store_false",
        help="Désactive l'enregistrement automatique des nouveaux intitulés",
    )
    parser.set_defaults(auto_learn=_env_flag(_AUTO_LEARN_ENV_VARS, False))
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Active le niveau de log DEBUG",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)
    config_path = Path(args.config)
    encoding = args.encoding or None

    if not input_dir.exists():
        LOGGER.warning("Le dossier d'entrée %s est introuvable, aucune action effectuée.", input_dir)
        return 0

    try:
        mapping = norm_config.load_mapping(config_path)
    except Exception as exc:  # pragma: no cover - robust CLI
        LOGGER.error("Impossible de charger la configuration %s: %s", config_path, exc)
        return 1

    LOGGER.info("Normalisation des fichiers depuis %s vers %s", input_dir, output_dir)
    try:
        results = normalize_directory(
            input_dir,
            output_dir,
            mapping,
            encoding=encoding,
            output_format=args.output_format,
            learn=args.auto_learn,
        )
    except NormalizationError as exc:
        LOGGER.error("La normalisation a échoué: %s", exc)
        return 1

    if not results:
        LOGGER.info("Aucun fichier compatible trouvé dans %s", input_dir)
    else:
        for path in results:
            LOGGER.info("Fichier normalisé: %s", path)

    if args.auto_learn:
        try:
            if mapping.save():
                LOGGER.info("Mapping mis à jour: %s", mapping.source_path)
        except Exception as exc:  # pragma: no cover - robust CLI
            LOGGER.error("Impossible d'enregistrer le mapping: %s", exc)
            return 1

    return 0


if __name__ == "__main__":  # pragma: no cover - script execution helper
    raise SystemExit(main())
