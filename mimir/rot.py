"""mimir rot — dead code, empty functions.

Finds things that can probably be deleted.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass

from .scan import iter_py_files


@dataclass
class RotFinding:
  file: str
  line: int
  kind: str  # "empty_fn"
  detail: str


def _scan_empty_functions(filepath: str, tree: ast.Module) -> list[RotFinding]:
  """Find functions whose body is just `pass`, `...`, or a single docstring."""
  findings: list[RotFinding] = []

  def walk(node: ast.AST, scope: list[str]) -> None:
    for child in ast.iter_child_nodes(node):
      if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
        qualname = ".".join([*scope, child.name])
        if _is_empty_body(child.body):
          findings.append(RotFinding(
            file=filepath,
            line=child.lineno,
            kind="empty_fn",
            detail=qualname,
          ))
        walk(child, [*scope, child.name])
      elif isinstance(child, ast.ClassDef):
        walk(child, [*scope, child.name])

  walk(tree, [])
  return findings


def _is_empty_body(body: list[ast.stmt]) -> bool:
  """True if the body is just pass, ..., or a docstring (+ optional pass)."""
  stmts = body
  # Strip leading docstring
  if stmts and isinstance(stmts[0], ast.Expr) and isinstance(stmts[0].value, ast.Constant):
    stmts = stmts[1:]
  if not stmts:
    return True
  if len(stmts) == 1:
    s = stmts[0]
    if isinstance(s, ast.Pass):
      return True
    if isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant) and s.value.value is ...:
      return True
  return False


def scan_rot(filepath: str) -> list[RotFinding]:
  try:
    with open(filepath, encoding="utf-8") as f:
      source = f.read()
    tree = ast.parse(source, filename=filepath)
  except (OSError, SyntaxError):
    return []
  return _scan_empty_functions(filepath, tree)


def scan_rot_dir(root: str, exclude: list[str] | None = None) -> list[RotFinding]:
  results: list[RotFinding] = []
  for path in iter_py_files(root, exclude):
    results.extend(scan_rot(path))
  return results
