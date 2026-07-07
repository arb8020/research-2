"""mimir imports — fan-in/fan-out from import graph."""

from __future__ import annotations

import ast
import os
from dataclasses import dataclass

from .scan import iter_py_files


@dataclass
class ImportMetrics:
  file: str
  fan_out: int  # how many internal modules this file imports
  fan_in: int   # how many internal files import this module


def _collect_imports(filepath: str) -> list[str]:
  """Return list of imported module names (dotted) from a file."""
  try:
    with open(filepath, encoding="utf-8") as f:
      source = f.read()
    tree = ast.parse(source, filename=filepath)
  except (OSError, SyntaxError):
    return []

  modules: list[str] = []
  for node in ast.walk(tree):
    if isinstance(node, ast.Import):
      for alias in node.names:
        modules.append(alias.name)
    elif isinstance(node, ast.ImportFrom):
      if node.module and node.level == 0:
        modules.append(node.module)
      elif node.level > 0 and node.module:
        # Relative import — store with dots prefix for resolution
        modules.append("." * node.level + node.module)
      elif node.level > 0:
        modules.append("." * node.level)
  return modules


def _relpath_to_module(relpath: str) -> str:
  """Convert a file path to a dotted module name."""
  no_ext = relpath[:-3] if relpath.endswith(".py") else relpath
  parts = [p for p in no_ext.replace("\\", "/").split("/") if p]
  if parts and parts[-1] == "__init__":
    parts = parts[:-1]
  return ".".join(parts)


def _resolve_relative(importing_file: str, dotted: str) -> str | None:
  """Best-effort resolve a relative import to a dotted module name."""
  if not dotted.startswith("."):
    return dotted

  level = 0
  for c in dotted:
    if c == ".":
      level += 1
    else:
      break
  rest = dotted[level:]

  parts = importing_file.replace("\\", "/").split("/")
  # Go up `level` directories from the file's directory
  pkg_parts = parts[:-1]  # drop filename
  if level > len(pkg_parts):
    return None
  base = pkg_parts[:len(pkg_parts) - level + 1]
  result = ".".join(base)
  if rest:
    result = f"{result}.{rest}" if result else rest
  return result


def scan_imports(
  root: str, exclude: list[str] | None = None,
) -> list[ImportMetrics]:
  """Compute fan-in and fan-out for all Python files."""
  # Collect all files and their module names
  files: list[str] = list(iter_py_files(root, exclude))
  relpath_map: dict[str, str] = {}  # relpath -> module name
  module_to_relpath: dict[str, str] = {}  # module name -> relpath

  for filepath in files:
    relpath = os.path.relpath(filepath, root)
    mod = _relpath_to_module(relpath)
    relpath_map[relpath] = mod
    module_to_relpath[mod] = relpath

  all_modules = set(module_to_relpath.keys())

  # Build edges: relpath -> set of relpaths it imports (internal only)
  edges: dict[str, set[str]] = {}
  for filepath in files:
    relpath = os.path.relpath(filepath, root)
    raw_imports = _collect_imports(filepath)
    targets: set[str] = set()
    for imp in raw_imports:
      resolved = _resolve_relative(relpath, imp) if imp.startswith(".") else imp
      if resolved is None:
        continue
      # Match against internal modules (exact or prefix)
      for mod in all_modules:
        if resolved == mod or resolved.startswith(mod + ".") or mod.startswith(resolved + "."):
          targets.add(module_to_relpath[mod])
    # Don't count self-imports
    targets.discard(relpath)
    edges[relpath] = targets

  # Compute fan-in
  fan_in: dict[str, int] = {os.path.relpath(f, root): 0 for f in files}
  for src, dsts in edges.items():
    for dst in dsts:
      fan_in[dst] = fan_in.get(dst, 0) + 1

  results: list[ImportMetrics] = []
  for filepath in files:
    relpath = os.path.relpath(filepath, root)
    results.append(ImportMetrics(
      file=relpath,
      fan_out=len(edges.get(relpath, set())),
      fan_in=fan_in.get(relpath, 0),
    ))

  return results
