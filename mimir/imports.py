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
  # level=1 (from .X) stays in current package, level=2 (from ..X) goes up
  # one from current package, etc. Guard: can't go above the scan root.
  up = level - 1
  if up > len(pkg_parts):
    return None
  base = pkg_parts[:len(pkg_parts) - up]
  result = ".".join(base)
  if rest:
    result = f"{result}.{rest}" if result else rest
  return result


@dataclass
class ImportGraph:
  edges: dict[str, set[str]]  # relpath -> set of relpaths it imports
  metrics: list[ImportMetrics]
  cycles: list[list[str]]  # each cycle is a list of relpaths


def _find_cycles(edges: dict[str, set[str]]) -> list[list[str]]:
  """Find all strongly connected components with >1 node (Tarjan's algorithm)."""
  index_counter = [0]
  stack: list[str] = []
  on_stack: set[str] = set()
  index: dict[str, int] = {}
  lowlink: dict[str, int] = {}
  sccs: list[list[str]] = []

  def strongconnect(v: str) -> None:
    index[v] = index_counter[0]
    lowlink[v] = index_counter[0]
    index_counter[0] += 1
    stack.append(v)
    on_stack.add(v)

    for w in edges.get(v, set()):
      if w not in index:
        strongconnect(w)
        lowlink[v] = min(lowlink[v], lowlink[w])
      elif w in on_stack:
        lowlink[v] = min(lowlink[v], index[w])

    if lowlink[v] == index[v]:
      scc: list[str] = []
      while True:
        w = stack.pop()
        on_stack.discard(w)
        scc.append(w)
        if w == v:
          break
      if len(scc) > 1:
        sccs.append(sorted(scc))

  for v in edges:
    if v not in index:
      strongconnect(v)

  return sccs


def build_import_graph(
  root: str, exclude: list[str] | None = None,
) -> ImportGraph:
  """Build the full import graph with fan-in, fan-out, and cycles."""
  files: list[str] = list(iter_py_files(root, exclude))
  module_to_relpath: dict[str, str] = {}

  for filepath in files:
    relpath = os.path.relpath(filepath, root)
    mod = _relpath_to_module(relpath)
    module_to_relpath[mod] = relpath

  all_modules = set(module_to_relpath.keys())

  # Build edges
  edges: dict[str, set[str]] = {}
  for filepath in files:
    relpath = os.path.relpath(filepath, root)
    raw_imports = _collect_imports(filepath)
    targets: set[str] = set()
    for imp in raw_imports:
      resolved = _resolve_relative(relpath, imp) if imp.startswith(".") else imp
      if resolved is None:
        continue
      for mod in all_modules:
        if resolved == mod or resolved.startswith(mod + ".") or mod.startswith(resolved + "."):
          targets.add(module_to_relpath[mod])
    targets.discard(relpath)
    edges[relpath] = targets

  # Fan-in
  fan_in: dict[str, int] = {os.path.relpath(f, root): 0 for f in files}
  for src, dsts in edges.items():
    for dst in dsts:
      fan_in[dst] = fan_in.get(dst, 0) + 1

  metrics: list[ImportMetrics] = []
  for filepath in files:
    relpath = os.path.relpath(filepath, root)
    metrics.append(ImportMetrics(
      file=relpath,
      fan_out=len(edges.get(relpath, set())),
      fan_in=fan_in.get(relpath, 0),
    ))

  cycles = _find_cycles(edges)

  return ImportGraph(edges=edges, metrics=metrics, cycles=cycles)


# Backwards compat
def scan_imports(
  root: str, exclude: list[str] | None = None,
) -> list[ImportMetrics]:
  return build_import_graph(root, exclude).metrics
