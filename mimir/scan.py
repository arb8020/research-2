"""Structural health scan — AST-based metrics for Python files."""

from __future__ import annotations

import ast
import os
from collections.abc import Generator
from dataclasses import dataclass

SKIP_DIRS = {
  "__pycache__", ".venv", "venv", ".git", "build", "dist",
  ".mypy_cache", ".pytest_cache", "node_modules", ".tox", ".eggs",
  "worktrees",
}

# Thresholds — graduated severity.
# These converge across Linux kernel (3), MISRA (3-4), TigerStyle (implicit),
# SonarQube, clippy, ESLint. We use 4 as the warn line.
NESTING_THRESHOLDS = {"clean": 2, "info": 3, "warn": 4, "alert": 5}


@dataclass
class FunctionMetrics:
  file: str
  name: str
  line: int
  max_nesting: int
  stmt_count: int
  arg_count: int
  cyclomatic: int
  branches: int
  returns: int


def severity(nesting: int) -> str:
  if nesting <= NESTING_THRESHOLDS["clean"]:
    return "clean"
  if nesting <= NESTING_THRESHOLDS["info"]:
    return "info"
  if nesting <= NESTING_THRESHOLDS["warn"]:
    return "warn"
  return "alert"


def _nesting_depth(node: ast.AST, depth: int = 0) -> int:
  """Walk an AST node and return the maximum nesting depth of control flow.

  Counts: if/elif/else, for, while, with, try, match.
  Does NOT count: function/class defs (those are new scopes).
  """
  max_d = depth
  nesting_types = (
    ast.If, ast.For, ast.While, ast.With,
    ast.Try, ast.TryStar,
    ast.AsyncFor, ast.AsyncWith,
    ast.Match,
  )

  for child in ast.iter_child_nodes(node):
    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
      continue  # new scope, don't count
    if isinstance(child, nesting_types):
      max_d = max(max_d, _nesting_depth(child, depth + 1))
    else:
      max_d = max(max_d, _nesting_depth(child, depth))

  return max_d


def _count_stmts(body: list[ast.stmt]) -> int:
  """Count statements in a function body (non-recursive — top-level only)."""
  count = 0
  for node in ast.walk(ast.Module(body=body, type_ignores=[])):
    if isinstance(node, ast.stmt) and not isinstance(
      node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
    ):
      count += 1
  return count


def _cyclomatic_complexity(node: ast.AST) -> int:
  """Cyclomatic complexity from AST. Start at 1, +1 per branch point.

  Walks the function body but stops at nested function/class scopes.
  """
  cc = 1
  branch_nodes = (ast.If, ast.For, ast.While, ast.AsyncFor, ast.ExceptHandler)

  def walk(n: ast.AST) -> None:
    nonlocal cc
    for child in ast.iter_child_nodes(n):
      if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        if child is not node:
          continue  # nested scope — skip
      if isinstance(child, branch_nodes):
        cc += 1
      elif isinstance(child, ast.BoolOp):
        cc += len(child.values) - 1
      elif isinstance(child, ast.Match):
        cc += len(child.cases) - 1
      walk(child)

  walk(node)
  return cc


def _count_branches(node: ast.AST) -> int:
  """Count branch points in a function (if/elif/else/for/while/match arms).

  Stops at nested function/class scopes.
  """
  count = 0

  def walk(n: ast.AST) -> None:
    nonlocal count
    for child in ast.iter_child_nodes(n):
      if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        if child is not node:
          continue
      if isinstance(child, (ast.If, ast.For, ast.While, ast.AsyncFor)):
        count += 1
      elif isinstance(child, ast.Match):
        count += len(child.cases)
      walk(child)

  walk(node)
  return count


def _count_returns(node: ast.AST) -> int:
  """Count return statements in a function. Stops at nested scopes."""
  count = 0

  def walk(n: ast.AST) -> None:
    nonlocal count
    for child in ast.iter_child_nodes(n):
      if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        if child is not node:
          continue
      if isinstance(child, ast.Return):
        count += 1
      walk(child)

  walk(node)
  return count


def _arg_count(func: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
  args = func.args
  return (
    len(args.posonlyargs)
    + len(args.args)
    + len(args.kwonlyargs)
    + (1 if args.vararg else 0)
    + (1 if args.kwarg else 0)
  )


def _extract_functions(
  tree: ast.Module,
  filepath: str,
) -> Generator[FunctionMetrics, None, None]:
  """Extract metrics for every function/method in a module."""

  def walk(node: ast.AST, scope: list[str]) -> Generator[FunctionMetrics, None, None]:
    for child in ast.iter_child_nodes(node):
      if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
        qualname = ".".join([*scope, child.name])
        yield FunctionMetrics(
          file=filepath,
          name=qualname,
          line=child.lineno,
          max_nesting=_nesting_depth(child),
          stmt_count=_count_stmts(child.body),
          arg_count=_arg_count(child),
          cyclomatic=_cyclomatic_complexity(child),
          branches=_count_branches(child),
          returns=_count_returns(child),
        )
        yield from walk(child, [*scope, child.name])
      elif isinstance(child, ast.ClassDef):
        yield from walk(child, [*scope, child.name])

  yield from walk(tree, [])


def scan_file(filepath: str) -> tuple[list[FunctionMetrics], list[ClassMetrics]]:
  """Scan a single Python file and return per-function and per-class metrics."""
  try:
    with open(filepath, encoding="utf-8") as f:
      source = f.read()
    tree = ast.parse(source, filename=filepath)
  except (OSError, SyntaxError):
    return [], []
  return list(_extract_functions(tree, filepath)), list(_extract_classes(tree, filepath))


def iter_py_files(
  root: str,
  exclude: list[str] | None = None,
) -> Generator[str, None, None]:
  """Walk a directory tree yielding .py file paths."""
  if os.path.isfile(root):
    if root.endswith(".py"):
      yield root
    return
  exclude_abs = {os.path.abspath(os.path.join(root, e)) for e in (exclude or [])}
  for dirpath, dirnames, filenames in os.walk(root):
    dirnames[:] = sorted(
      d for d in dirnames
      if d not in SKIP_DIRS and os.path.join(dirpath, d) not in exclude_abs
    )
    for fn in sorted(filenames):
      if fn.endswith(".py"):
        yield os.path.join(dirpath, fn)


def scan_dir(
  root: str, exclude: list[str] | None = None,
) -> tuple[list[FunctionMetrics], list[ClassMetrics]]:
  """Scan all Python files under root."""
  fn_results: list[FunctionMetrics] = []
  cls_results: list[ClassMetrics] = []
  for path in iter_py_files(root, exclude):
    fns, clses = scan_file(path)
    fn_results.extend(fns)
    cls_results.extend(clses)
  return fn_results, cls_results


import math


@dataclass
class ClassMetrics:
  file: str
  name: str
  line: int
  field_count: int


def _extract_classes(
  tree: ast.Module,
  filepath: str,
) -> Generator[ClassMetrics, None, None]:
  """Extract field counts for every class in a module."""

  def walk(node: ast.AST, scope: list[str]) -> Generator[ClassMetrics, None, None]:
    for child in ast.iter_child_nodes(node):
      if isinstance(child, ast.ClassDef):
        qualname = ".".join([*scope, child.name])
        fields = _count_class_fields(child)
        yield ClassMetrics(
          file=filepath,
          name=qualname,
          line=child.lineno,
          field_count=fields,
        )
        yield from walk(child, [*scope, child.name])
      elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
        # don't descend into function bodies for class discovery
        pass

  yield from walk(tree, [])


def _count_class_fields(cls: ast.ClassDef) -> int:
  """Count fields: class-level assignments + __init__ self.x assignments."""
  fields: set[str] = set()

  # Class-level: annotated assignments and plain assignments
  for node in cls.body:
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
      fields.add(node.target.id)
    elif isinstance(node, ast.Assign):
      for target in node.targets:
        if isinstance(target, ast.Name):
          fields.add(target.id)

  # __init__ self.x = ... assignments
  for node in cls.body:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "__init__":
      for child in ast.walk(node):
        if (
          isinstance(child, ast.Assign)
          and len(child.targets) == 1
          and isinstance(child.targets[0], ast.Attribute)
          and isinstance(child.targets[0].value, ast.Name)
          and child.targets[0].value.id == "self"
        ):
          fields.add(child.targets[0].attr)
        elif (
          isinstance(child, ast.AnnAssign)
          and isinstance(child.target, ast.Attribute)
          and isinstance(child.target.value, ast.Name)
          and child.target.value.id == "self"
        ):
          fields.add(child.target.attr)

  return len(fields)


@dataclass
class FileMetrics:
  file: str
  lines: int


def scan_file_length(filepath: str) -> FileMetrics | None:
  try:
    with open(filepath, encoding="utf-8") as f:
      lines = sum(1 for _ in f)
    return FileMetrics(file=filepath, lines=lines)
  except OSError:
    return None


def scan_file_lengths(root: str, exclude: list[str] | None = None) -> list[FileMetrics]:
  results: list[FileMetrics] = []
  for path in iter_py_files(root, exclude):
    fm = scan_file_length(path)
    if fm is not None:
      results.append(fm)
  return results


def structural_erosion(metrics: list[FunctionMetrics], cc_threshold: int = 10) -> float:
  """SlopCodeBench structural erosion: fraction of complexity mass in high-CC functions.

  mass(f) = CC(f) * sqrt(SLOC(f))
  erosion = sum(mass for f where CC > threshold) / sum(mass for all f)

  Human codebases: ~0.31. Agent-generated: ~0.68.
  """
  if not metrics:
    return 0.0
  total_mass = 0.0
  hot_mass = 0.0
  for m in metrics:
    mass = m.cyclomatic * math.sqrt(max(m.stmt_count, 1))
    total_mass += mass
    if m.cyclomatic > cc_threshold:
      hot_mass += mass
  if total_mass == 0:
    return 0.0
  return hot_mass / total_mass
