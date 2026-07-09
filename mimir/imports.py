"""Internal Python import graph construction."""

from __future__ import annotations

import ast
import os
from dataclasses import dataclass

from .scan import iter_py_files


@dataclass(frozen=True)
class ImportMetrics:
  file: str
  fan_out: int
  fan_in: int


@dataclass(frozen=True)
class ImportGraph:
  edges: dict[str, set[str]]
  metrics: list[ImportMetrics]
  cycles: list[list[str]]


@dataclass(frozen=True)
class ImportReference:
  module: str
  names: tuple[str, ...] = ()
  level: int = 0


def _collect_imports(filepath: str) -> list[ImportReference]:
  """Parse imports. Unreadable or invalid Python contributes no graph facts."""
  try:
    with open(filepath, encoding="utf-8") as f:
      tree = ast.parse(f.read(), filename=filepath)
  except (OSError, SyntaxError):
    return []

  imports: list[ImportReference] = []
  for node in ast.walk(tree):
    if isinstance(node, ast.Import):
      imports.extend(ImportReference(alias.name) for alias in node.names)
    elif isinstance(node, ast.ImportFrom):
      imports.append(ImportReference(
        module=node.module or "",
        names=tuple(alias.name for alias in node.names if alias.name != "*"),
        level=node.level,
      ))
  return imports


def _relpath_to_module(relpath: str) -> str:
  no_ext = relpath[:-3] if relpath.endswith(".py") else relpath
  parts = [part for part in no_ext.replace("\\", "/").split("/") if part]
  if parts and parts[-1] == "__init__":
    parts.pop()
  return ".".join(parts)


def _absolute_module(importing_file: str, ref: ImportReference) -> str | None:
  if ref.level == 0:
    return ref.module

  importing_module = _relpath_to_module(importing_file)
  package = importing_module if importing_file.endswith("/__init__.py") else importing_module.rpartition(".")[0]
  parts = package.split(".") if package else []
  parents = ref.level - 1
  if parents > len(parts):
    return None
  base = parts[:len(parts) - parents]
  if ref.module:
    base.extend(ref.module.split("."))
  return ".".join(base)


def _resolve_reference(
  importing_file: str,
  ref: ImportReference,
  modules: dict[str, str],
) -> set[str]:
  """Resolve each imported module to its most-specific represented file."""
  base = _absolute_module(importing_file, ref)
  if base is None:
    return set()

  # ``from package import child`` imports the child module when it exists;
  # otherwise the import belongs to the package's __init__.py.
  if ref.names:
    children = {
      modules[candidate]
      for name in ref.names
      if (candidate := f"{base}.{name}" if base else name) in modules
    }
    if children:
      return children

  candidate = base
  while candidate:
    if candidate in modules:
      return {modules[candidate]}
    candidate = candidate.rpartition(".")[0]
  return set()


def _find_cycles(edges: dict[str, set[str]]) -> list[list[str]]:
  """Return non-trivial strongly connected components."""
  next_index = 0
  stack: list[str] = []
  on_stack: set[str] = set()
  indices: dict[str, int] = {}
  lowlinks: dict[str, int] = {}
  cycles: list[list[str]] = []

  def visit(node: str) -> None:
    nonlocal next_index
    indices[node] = lowlinks[node] = next_index
    next_index += 1
    stack.append(node)
    on_stack.add(node)

    for target in edges.get(node, set()):
      if target not in indices:
        visit(target)
        lowlinks[node] = min(lowlinks[node], lowlinks[target])
      elif target in on_stack:
        lowlinks[node] = min(lowlinks[node], indices[target])

    if lowlinks[node] != indices[node]:
      return
    component: list[str] = []
    while True:
      member = stack.pop()
      on_stack.remove(member)
      component.append(member)
      if member == node:
        break
    if len(component) > 1:
      cycles.append(sorted(component))

  for node in edges:
    if node not in indices:
      visit(node)
  return sorted(cycles)


def build_import_graph(root: str, exclude: list[str] | None = None) -> ImportGraph:
  """Build the internal file-level import graph rooted at ``root``."""
  files = list(iter_py_files(root, exclude))
  module_to_relpath = {
    _relpath_to_module(os.path.relpath(filepath, root)): os.path.relpath(filepath, root)
    for filepath in files
  }
  edges: dict[str, set[str]] = {}
  for filepath in files:
    relpath = os.path.relpath(filepath, root)
    targets = set().union(*(
      _resolve_reference(relpath, ref, module_to_relpath)
      for ref in _collect_imports(filepath)
    ))
    targets.discard(relpath)
    edges[relpath] = targets

  fan_in = dict.fromkeys(edges, 0)
  for targets in edges.values():
    for target in targets:
      fan_in[target] += 1
  metrics = [
    ImportMetrics(file, len(edges[file]), fan_in[file])
    for file in edges
  ]
  return ImportGraph(edges, metrics, _find_cycles(edges))


def scan_imports(root: str, exclude: list[str] | None = None) -> list[ImportMetrics]:
  """Compatibility interface for callers that only need fan metrics."""
  return build_import_graph(root, exclude).metrics
