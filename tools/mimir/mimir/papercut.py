"""papercut — log small frictions to PAPERCUTS.md.

Disabled by default: enable with `papercut = true` under [tool.mimir] in the
repo's pyproject.toml, or MIMIR_PAPERCUT=1 for a single session.
"""

from __future__ import annotations

from pathlib import Path

from . import journal
from .journal import PAPERCUT as SPEC
from .journal import repo_root, user  # re-exported for callers

__all__ = [
  "SPEC",
  "append_entry",
  "disabled_message",
  "is_enabled",
  "list_entries",
  "repo_root",
  "require_enabled",
  "resolve_path",
  "user",
]


def resolve_path(file_override: str | None = None) -> Path:
  return journal.resolve_path(SPEC, file_override)


def append_entry(model: str, message: str, path: Path) -> None:
  journal.append_entry(SPEC, model, message, path)


def list_entries(path: Path) -> str:
  return journal.list_entries(SPEC, path)


def is_enabled(root: str | None = None) -> bool:
  return journal.is_enabled(SPEC, root)


def disabled_message(root: str | None = None) -> str:
  return journal.disabled_message(SPEC, root)


def require_enabled(root: str | None = None) -> None:
  journal.require_enabled(SPEC, root)
