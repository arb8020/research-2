"""Shared plumbing for the append-only journals (papercut, breadcrumb).

papercut.py and breadcrumb.py were near-clones of this module; both now
delegate here, parameterized by a `JournalSpec` (filename, tag field, entry
format, and the toggle that gates the whole command).
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .config import feature_enabled, pyproject_path


def _git(*args: str) -> str | None:
  try:
    return subprocess.check_output(
      ["git", *args], stderr=subprocess.DEVNULL, text=True
    ).strip()
  except (subprocess.CalledProcessError, FileNotFoundError):
    return None


def repo_root() -> Path | None:
  root = _git("rev-parse", "--show-toplevel")
  return Path(root) if root else None


def user() -> str:
  return _git("config", "user.name") or os.environ.get("USER", "unknown")


@dataclass(frozen=True)
class JournalSpec:
  """Describes one journal: where it lives, how entries look, how it's gated."""

  name: str          # command name, e.g. "breadcrumb"
  filename: str      # e.g. "BREADCRUMBS.md"
  config_key: str    # [tool.mimir] key, e.g. "breadcrumb"
  env_var: str       # e.g. "MIMIR_BREADCRUMB"
  header: str | None  # written once when the file is empty
  empty_text: str    # printed by --list when nothing is logged yet
  dated: bool        # True = full ISO stamp + blank-line body (papercut style)


PAPERCUT = JournalSpec(
  name="papercut",
  filename="PAPERCUTS.md",
  config_key="papercut",
  env_var="MIMIR_PAPERCUT",
  header=None,
  empty_text="(no papercuts yet)",
  dated=True,
)

BREADCRUMB = JournalSpec(
  name="breadcrumb",
  filename="BREADCRUMBS.md",
  config_key="breadcrumb",
  env_var="MIMIR_BREADCRUMB",
  header="# Breadcrumbs\n\n",
  empty_text="(no breadcrumbs yet)",
  dated=False,
)


def resolve_path(spec: JournalSpec, file_override: str | None = None) -> Path:
  if file_override:
    return Path(file_override)
  root = repo_root() or Path.cwd()
  return root / spec.filename


def append_entry(spec: JournalSpec, tag: str, message: str, path: Path) -> None:
  if spec.dated:
    ts = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    with open(path, "a") as f:
      f.write(f"\n{ts} - {tag} - {user()}\n\n{message}\n")
    return
  ts = datetime.now(UTC).strftime("%H:%M:%S")
  needs_header = not path.exists() or path.stat().st_size == 0
  with open(path, "a") as f:
    if needs_header and spec.header:
      f.write(spec.header)
    f.write(f"{ts} [{tag}] {message}\n")


def list_entries(spec: JournalSpec, path: Path) -> str:
  if path.exists():
    return path.read_text()
  return spec.empty_text


def is_enabled(spec: JournalSpec, root: str | None = None) -> bool:
  """Off by default. `[tool.mimir] <key> = true`, or MIMIR_<NAME>=1 (env wins)."""
  base = root or str(repo_root() or Path.cwd())
  return feature_enabled(base, spec.config_key, spec.env_var)


def disabled_message(spec: JournalSpec, root: str | None = None) -> str:
  base = root or str(repo_root() or Path.cwd())
  return (
    f"error: mimir {spec.name} is disabled — "
    f"add `{spec.config_key} = true` under [tool.mimir] in {pyproject_path(base)} "
    f"(or set {spec.env_var}=1 for this session)"
  )


def require_enabled(spec: JournalSpec, root: str | None = None) -> None:
  """Exit 1 with a one-line how-to-enable message unless the command is on."""
  if is_enabled(spec, root):
    return
  print(disabled_message(spec, root), file=sys.stderr)
  sys.exit(1)
