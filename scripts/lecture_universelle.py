"""Étape 5 du workflow : normalisation universelle via le package dédié."""
from __future__ import annotations

from programmelecturefichiers import UniversalNormalizer, discover_config


def lecture_universelle():
    config = discover_config()
    normalizer = UniversalNormalizer(config)
    result = normalizer.run()
    return result.as_dict()


if __name__ == "__main__":  # pragma: no cover
    lecture_universelle()
