"""Shared reader for [tool.mimir] in a target project's pyproject.toml."""

from __future__ import annotations

import os


def pyproject_path(root: str) -> str:
  return os.path.join(root, "pyproject.toml")


def load_tool_mimir(root: str) -> dict:
  """Return the [tool.mimir] table for the project at `root` ({} if absent)."""
  toml_path = pyproject_path(root)
  if not os.path.isfile(toml_path):
    return {}
  try:
    import tomllib
  except ModuleNotFoundError:
    import tomli as tomllib  # type: ignore[no-redef]
  try:
    with open(toml_path, "rb") as f:
      data = tomllib.load(f)
  except (OSError, ValueError):
    return {}
  tool = data.get("tool", {})
  if not isinstance(tool, dict):
    return {}
  cfg = tool.get("mimir", {})
  return cfg if isinstance(cfg, dict) else {}


def feature_enabled(root: str, key: str, env_var: str) -> bool:
  """Is feature `key` on? Env override wins over pyproject; default off.

  `MIMIR_<X>=1/true/yes/on` forces on, `0/false/no/off` forces off.
  """
  raw = os.environ.get(env_var)
  if raw is not None and raw.strip():
    return raw.strip().lower() in {"1", "true", "yes", "on"}
  return bool(load_tool_mimir(root).get(key, False))
