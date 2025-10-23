"""Command-line interface for the normalization pipeline."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from . import config, pipeline


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Normalize heterogenous tabular files")
    subparsers = parser.add_subparsers(dest="command", required=True)

    normalize_parser = subparsers.add_parser(
        "normalize", help="Normalize all supported files in a directory"
    )
    normalize_parser.add_argument("input", help="Input directory containing raw files")
    normalize_parser.add_argument("output", help="Output directory for normalized files")
    normalize_parser.add_argument(
        "--config",
        required=True,
        help="Path to the YAML configuration describing the column mapping",
    )
    normalize_parser.add_argument(
        "--encoding",
        help="Optional text encoding to force when reading CSV files",
    )
    normalize_parser.add_argument(
        "--output-format",
        default="csv",
        choices=["csv", "xlsx"],
        help="File format for the normalized exports (default: csv)",
    )
    normalize_parser.add_argument(
        "--auto-learn",
        action="store_true",
        help=(
            "Store newly discovered column headers back into the mapping file "
            "for future runs"
        ),
    )

    return parser


def setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="%(levelname)s %(name)s: %(message)s")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging")
    args = parser.parse_args(argv)

    setup_logging(args.verbose)

    mapping = config.load_mapping(args.config)

    if args.command == "normalize":
        results = pipeline.normalize_directory(
            args.input,
            args.output,
            mapping,
            encoding=args.encoding,
            output_format=args.output_format,
            learn=args.auto_learn,
        )
        for result in results:
            print(result)
        if args.auto_learn:
            if mapping.save():
                print(f"Updated mapping written to {mapping.source_path}")
            elif mapping.dirty:
                # ``mapping.save`` may raise when the mapping is dirty but no
                # path is available. Re-raise to make the failure explicit.
                mapping.save()
        return 0

    parser.error(f"Unknown command: {args.command}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
