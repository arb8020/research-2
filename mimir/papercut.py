"""papercut — log small frictions to PAPERCUTS.md."""

from __future__ import annotations

import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path


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


def resolve_path(file_override: str | None = None) -> Path:
  if file_override:
    return Path(file_override)
  root = repo_root() or Path.cwd()
  return root / "PAPERCUTS.md"


def append_entry(model: str, message: str, path: Path) -> None:
  ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
  u = user()
  entry = f"\n{ts} - {model} - {u}\n\n{message}\n"
  with open(path, "a") as f:
    f.write(entry)


def list_entries(path: Path) -> str:
  if path.exists():
    return path.read_text()
  return "(no papercuts yet)"
