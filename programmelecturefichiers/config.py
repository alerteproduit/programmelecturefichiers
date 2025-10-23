"""Gestion centralisée de la configuration du workflow."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

from ._compat import load_toml

_CONFIG_LOCATIONS = (
    "config/lecture_universelle.toml",
    "config/alerteproduit.toml",
)


@dataclass(frozen=True)
class WorkflowConfig:
    """Regroupe les chemins clés manipulés par les scripts du workflow."""

    project_root: Path
    uploads_dir: Path
    entree_dir: Path
    logs_dir: Path
    archives_dir: Path
    rappel_symlink: Path

    def ensure_directories(self) -> None:
        for folder in self.required_directories:
            folder.mkdir(parents=True, exist_ok=True)

    @property
    def required_directories(self) -> Iterable[Path]:
        yield self.uploads_dir
        yield self.entree_dir
        yield self.logs_dir
        yield self.archives_dir

    @classmethod
    def from_root(cls, root: Path) -> "WorkflowConfig":
        root = root.resolve()
        return cls(
            project_root=root,
            uploads_dir=root / "data/uploads",
            entree_dir=root / "data/entree",
            logs_dir=root / "logs",
            archives_dir=root / "data/archives",
            rappel_symlink=root / "rappels.csv",
        )

    def apply_symlink(self, target: Path) -> None:
        """(Re)crée le lien symbolique vers le fichier rappel normalisé."""
        try:
            if self.rappel_symlink.exists() or self.rappel_symlink.is_symlink():
                self.rappel_symlink.unlink()
        except FileNotFoundError:
            pass
        try:
            self.rappel_symlink.symlink_to(target)
        except OSError:
            # Sur Windows ou FS restreint, on copie en fallback.
            self.rappel_symlink.write_text(target.read_text(), encoding="utf-8")


def _load_from_file(root: Path) -> Optional[WorkflowConfig]:
    for rel in _CONFIG_LOCATIONS:
        candidate = root / rel
        if candidate.is_file():
            data = load_toml(candidate.read_bytes())
            base = data.get("paths", {}) if isinstance(data, dict) else {}
            uploads = base.get("uploads", "data/uploads")
            entree = base.get("entree", "data/entree")
            logs = base.get("logs", "logs")
            archives = base.get("archives", "data/archives")
            rappel = base.get("rappel_symlink", "rappels.csv")
            return WorkflowConfig(
                project_root=root,
                uploads_dir=(root / uploads).resolve(),
                entree_dir=(root / entree).resolve(),
                logs_dir=(root / logs).resolve(),
                archives_dir=(root / archives).resolve(),
                rappel_symlink=(root / rappel).resolve(),
            )
    return None


def discover_config(start: Optional[Path] = None) -> WorkflowConfig:
    """Détecte automatiquement la configuration du workflow.

    La recherche s'effectue selon l'ordre suivant :
      1. variable d'environnement ``AP_PROJECT_ROOT`` (si définie).
      2. ``start`` (ou cwd) en remontant l'arborescence jusqu'à trouver
         ``workflow_alerteproduit.command``.
      3. défaut : répertoire courant.
    """

    env_root = os.environ.get("AP_PROJECT_ROOT")
    if env_root:
        root = Path(env_root).expanduser().resolve()
        cfg = _load_from_file(root)
        return cfg or WorkflowConfig.from_root(root)

    start_path = Path(start or Path.cwd()).resolve()
    for current in [start_path, *start_path.parents]:
        marker = current / "workflow_alerteproduit.command"
        if marker.exists():
            cfg = _load_from_file(current)
            return cfg or WorkflowConfig.from_root(current)

    cfg = _load_from_file(start_path)
    if cfg:
        return cfg
    return WorkflowConfig.from_root(start_path)
