"""mimir todo — intentional debt markers.

TODOs, FIXMEs, HACKs, NotImplementedError raises.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass

from .scan import iter_py_files

MARKER_RE = re.compile(r"#\s*(TODO|FIXME|HACK|XXX)\b", re.IGNORECASE)


@dataclass
class TodoFinding:
  file: str
  line: int
  kind: str  # "TODO", "FIXME", "HACK", "XXX", "not_implemented"
  detail: str


def _scan_comments(filepath: str, source: str) -> list[TodoFinding]:
  findings: list[TodoFinding] = []
  for i, line in enumerate(source.splitlines(), 1):
    match = MARKER_RE.search(line)
    if match:
      kind = match.group(1).upper()
      comment = line[match.start():].strip()
      if len(comment) > 80:
        comment = comment[:77] + "..."
      findings.append(TodoFinding(file=filepath, line=i, kind=kind, detail=comment))
  return findings


def _scan_not_implemented(filepath: str, tree: ast.Module) -> list[TodoFinding]:
  """Find `raise NotImplementedError` statements."""
  findings: list[TodoFinding] = []

  def walk(node: ast.AST, scope: list[str]) -> None:
    for child in ast.iter_child_nodes(node):
      if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
        walk(child, [*scope, child.name])
      elif isinstance(child, ast.ClassDef):
        walk(child, [*scope, child.name])
      elif isinstance(child, ast.Raise) and child.exc is not None:
        # raise NotImplementedError or raise NotImplementedError(...)
        exc = child.exc
        name = None
        if isinstance(exc, ast.Name) and exc.id == "NotImplementedError":
          name = "NotImplementedError"
        elif isinstance(exc, ast.Call) and isinstance(exc.func, ast.Name) and exc.func.id == "NotImplementedError":
          name = "NotImplementedError"
        if name:
          qualname = ".".join(scope) if scope else "<module>"
          findings.append(TodoFinding(
            file=filepath,
            line=child.lineno,
            kind="not_implemented",
            detail=qualname,
          ))
      else:
        walk(child, scope)

  walk(tree, [])
  return findings


def scan_todo(filepath: str) -> list[TodoFinding]:
  try:
    with open(filepath, encoding="utf-8") as f:
      source = f.read()
  except OSError:
    return []

  findings = _scan_comments(filepath, source)

  try:
    tree = ast.parse(source, filename=filepath)
    findings.extend(_scan_not_implemented(filepath, tree))
  except SyntaxError:
    pass

  return findings


def scan_todo_dir(root: str, exclude: list[str] | None = None) -> list[TodoFinding]:
  results: list[TodoFinding] = []
  for path in iter_py_files(root, exclude):
    results.extend(scan_todo(path))
  return results
