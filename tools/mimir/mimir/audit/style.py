from __future__ import annotations

import ast
import os
from pathlib import Path

from ..scan import iter_py_files, scan_dir
from .target import AuditConfig, Violation

_DUNDER_PREFIXES = ("__",)
_VOID_EXEMPT_PREFIXES = ("test_", "check_")
_VOID_EXEMPT_NAMES = {
  "main",
  "setup",
  "teardown",
  "setup_module",
  "teardown_module",
  "setUp",
  "tearDown",
  "setUpClass",
  "tearDownClass",
}
_VOID_EXEMPT_DECORATOR_FRAGMENTS = {"command", "group", "fixture"}


def _returns_none(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
  if (
    len(node.body) == 1
    and isinstance(node.body[0], ast.Expr)
    and isinstance(node.body[0].value, ast.Constant)
    and node.body[0].value.value is Ellipsis
  ):
    return False

  for child in ast.walk(node):
    if isinstance(child, (ast.Yield, ast.YieldFrom)):
      return False

  annotation = node.returns
  if annotation is not None:
    return (isinstance(annotation, ast.Constant) and annotation.value is None) or (
      isinstance(annotation, ast.Name) and annotation.id == "None"
    )

  for child in ast.walk(node):
    if isinstance(child, ast.Return) and child.value is not None:
      return False
  return True


def _is_void_exempt(
  node: ast.FunctionDef | ast.AsyncFunctionDef,
  *,
  in_class: bool,
  exempt_methods: frozenset[str],
) -> bool:
  if node.name.startswith("__"):
    return True
  if node.name in _VOID_EXEMPT_NAMES:
    return True
  if any(node.name.startswith(p) for p in _VOID_EXEMPT_PREFIXES):
    return True
  if in_class and node.name in exempt_methods:
    return True
  for dec in node.decorator_list:
    dec_name = _decorator_name(dec)
    if any(frag in dec_name for frag in _VOID_EXEMPT_DECORATOR_FRAGMENTS):
      return True
  return False


def _decorator_name(dec: ast.expr) -> str:
  if isinstance(dec, ast.Name):
    return dec.id
  if isinstance(dec, ast.Attribute):
    parts: list[str] = []
    cur: ast.expr = dec
    while isinstance(cur, ast.Attribute):
      parts.append(cur.attr)
      cur = cur.value
    if isinstance(cur, ast.Name):
      parts.append(cur.id)
    return ".".join(reversed(parts))
  if isinstance(dec, ast.Call):
    return _decorator_name(dec.func)
  return ""


def check_style(root: str, cfg: AuditConfig) -> list[Violation]:
  violations: list[Violation] = []

  for src_dir in cfg.scope.src:
    full_dir = os.path.join(root, src_dir)
    if not os.path.isdir(full_dir):
      continue

    for filepath in iter_py_files(full_dir, exclude=list(cfg.scope.exclude)):
      relpath = os.path.relpath(filepath, root)
      try:
        source = Path(filepath).read_text()
      except (OSError, UnicodeDecodeError):
        continue

      lines = source.splitlines()
      if len(lines) > cfg.style.max_file_lines:
        violations.append(
          Violation(
            relpath,
            len(lines),
            "file-too-long",
            f"file is {len(lines)} lines (max {cfg.style.max_file_lines})",
          )
        )

      try:
        tree = ast.parse(source, filename=filepath)
      except SyntaxError:
        continue

      _check_functions(tree, relpath, cfg, violations, in_class=False)

  return violations


def _check_functions(
  node: ast.AST,
  relpath: str,
  cfg: AuditConfig,
  violations: list[Violation],
  *,
  in_class: bool,
) -> None:
  for child in ast.iter_child_nodes(node):
    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
      _check_one_function(child, relpath, cfg, violations, in_class=in_class)
    elif isinstance(child, ast.ClassDef):
      _check_functions(child, relpath, cfg, violations, in_class=True)


def _check_one_function(
  child: ast.FunctionDef | ast.AsyncFunctionDef,
  relpath: str,
  cfg: AuditConfig,
  violations: list[Violation],
  *,
  in_class: bool,
) -> None:
  body_lines = (child.end_lineno or child.lineno) - child.lineno + 1
  if body_lines > cfg.style.max_function_lines:
    violations.append(
      Violation(
        relpath,
        child.lineno,
        "function-too-long",
        f"`{child.name}` is {body_lines} lines (max {cfg.style.max_function_lines})",
      )
    )

  is_void_candidate = (
    cfg.style.check_void_returns
    and not _is_void_exempt(child, in_class=in_class, exempt_methods=cfg.style.void_exempt_methods)
    and _returns_none(child)
  )
  if is_void_candidate:
    violations.append(
      Violation(
        relpath,
        child.lineno,
        "void-return",
        f"`{child.name}` returns None — must return evidence of what it did",
      )
    )

  if cfg.style.check_isinstance:
    violations.extend(
      Violation(
        relpath,
        desc.lineno,
        "isinstance",
        f"isinstance() in `{child.name}` — prefer match/case",
      )
      for desc in ast.walk(child)
      if (
        isinstance(desc, ast.Call)
        and isinstance(desc.func, ast.Name)
        and desc.func.id == "isinstance"
      )
    )


def check_scan_thresholds(root: str, cfg: AuditConfig) -> list[Violation]:
  violations: list[Violation] = []

  for src_dir in cfg.scope.src:
    full_dir = os.path.join(root, src_dir)
    if not os.path.isdir(full_dir):
      continue

    fn_metrics, _ = scan_dir(full_dir, exclude=list(cfg.scope.exclude))

    for m in fn_metrics:
      relpath = os.path.relpath(m.file, root)

      if m.max_nesting > cfg.style.max_nesting:
        violations.append(
          Violation(
            relpath,
            m.line,
            "nesting",
            f"`{m.name}` nesting depth {m.max_nesting} (max {cfg.style.max_nesting})",
          )
        )

      if m.cyclomatic > cfg.style.max_cyclomatic:
        violations.append(
          Violation(
            relpath,
            m.line,
            "cyclomatic",
            f"`{m.name}` cyclomatic complexity {m.cyclomatic} (max {cfg.style.max_cyclomatic})",
          )
        )

      if m.arg_count > cfg.style.max_args:
        violations.append(
          Violation(
            relpath,
            m.line,
            "too-many-args",
            f"`{m.name}` has {m.arg_count} args (max {cfg.style.max_args})",
          )
        )

  return violations
