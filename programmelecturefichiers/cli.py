"""Interface en ligne de commande pour la normalisation universelle."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict

from . import UniversalNormalizer, discover_config


def _result_to_payload(result) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    for key, df in result.as_dict().items():
        if df is None:
            payload[key] = None
        else:
            payload[key] = {
                "rows": len(df),
                "columns": list(df.columns),
            }
    payload["selected_files"] = {
        k: str(v) if v else None for k, v in result.selected_files.items()
    }
    payload["reasons"] = result.reasons
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Normalisation universelle des fichiers uploads")
    parser.add_argument(
        "command",
        choices={"normalize", "config"},
        help="Action à effectuer. 'normalize' exécute le pipeline, 'config' affiche les chemins détectés.",
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        default=None,
        help="Racine du projet à utiliser (sinon auto-détection).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Écrit le résumé JSON sur stdout (utile pour les tests / intégrations).",
    )
    return parser


def main(argv: Any = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    config = discover_config(args.project_root)

    if args.command == "config":
        print("📁 Configuration détectée :")
        print(f"  project_root = {config.project_root}")
        print(f"  uploads_dir  = {config.uploads_dir}")
        print(f"  entree_dir   = {config.entree_dir}")
        print(f"  logs_dir     = {config.logs_dir}")
        print(f"  archives_dir = {config.archives_dir}")
        print(f"  rappel_link  = {config.rappel_symlink}")
        return 0

    normalizer = UniversalNormalizer(config)
    result = normalizer.run()

    if args.json:
        print(json.dumps(_result_to_payload(result), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
