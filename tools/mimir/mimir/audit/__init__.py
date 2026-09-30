from __future__ import annotations

import json
import os
import sys
from collections.abc import Callable
from dataclasses import asdict, dataclass

from . import astgrep
from .comments import check_citations, check_comments, check_docstrings
from .layout import check_boundaries, check_dir_entries, check_layers, import_facts
from .native import _has_pyright_config, _run_pyright, _run_ruff_check, _run_ruff_format, _run_tsc
from .style import check_scan_thresholds, check_style
from .target import (
  AuditConfig,
  CheckResult,
  ConfigError,
  Target,
  Violation,
  list_files,
  load_config,
)

EXIT_CLEAN = 0
EXIT_VIOLATIONS = 1
EXIT_MISCONFIGURED = 2
DETAIL_LINES = 20


@dataclass(frozen=True)
class Run:
  target: Target
  matches: list[astgrep.Match]
  sg_error: str | None
  fix: bool


@dataclass(frozen=True)
class Check:
  name: str
  enabled: Callable[[AuditConfig, str], bool]
  families: tuple[str, ...]
  run: Callable[[Run], CheckResult]


def _python(cfg: AuditConfig, _root: str) -> bool:
  return "python" in cfg.scope.languages


def _always(_cfg: AuditConfig, _root: str) -> bool:
  return True


def _from_violations(name: str, violations: list[Violation]) -> CheckResult:
  details = f"{len(violations)} violations" if violations else "clean"
  return CheckResult(name, not violations, details, violations)


def _tool_targets(target: Target) -> list[str]:
  return list(target.cfg.scope.src)


def _sg_check(name: str, body: Callable[[Run], list[Violation]]) -> Callable[[Run], CheckResult]:
  def run(r: Run) -> CheckResult:
    if r.sg_error is not None:
      return CheckResult(name, False, r.sg_error, [])
    return _from_violations(name, body(r))

  return run


def _citations(r: Run) -> CheckResult:
  if r.sg_error is not None:
    return CheckResult("citations", False, r.sg_error, [])
  try:
    violations, counts, locks = check_citations(r.target, r.matches)
  except (OSError, ValueError) as e:
    return CheckResult("citations", False, f"cannot read lockfile: {e}", [])
  per_package = ", ".join(f"{k} {n}" for k, n in sorted(counts.items()))
  details = (
    f"{sum(counts.values())} citations ({per_package or 'none'}); "
    f"locks: {', '.join(locks) or 'none'}"
  )
  return CheckResult("citations", not violations, details, violations, dict(sorted(counts.items())))


def _tool(name: str, ok_output: tuple[bool, str]) -> CheckResult:
  ok, output = ok_output
  return CheckResult(name, ok, output, [])


CHECKS: tuple[Check, ...] = (
  Check(
    "ruff",
    _python,
    (),
    lambda r: _tool("ruff", _run_ruff_check(r.target.root, _tool_targets(r.target), fix=r.fix)),
  ),
  Check(
    "ruff-format",
    _python,
    (),
    lambda r: _tool(
      "ruff-format", _run_ruff_format(r.target.root, _tool_targets(r.target), fix=r.fix)
    ),
  ),
  Check(
    "pyright",
    lambda cfg, root: _python(cfg, root) and _has_pyright_config(root),
    (),
    lambda r: _tool("pyright", _run_pyright(r.target.root, _tool_targets(r.target))),
  ),
  Check(
    "tsc",
    lambda cfg, _root: "typescript" in cfg.scope.languages and bool(cfg.scope.tsconfigs),
    (),
    lambda r: _tool("tsc", _run_tsc(r.target.root, r.target.cfg.scope.tsconfigs)),
  ),
  Check(
    "style",
    _python,
    (),
    lambda r: _from_violations("style", check_style(r.target.root, r.target.cfg)),
  ),
  Check(
    "structure",
    _python,
    (),
    lambda r: _from_violations("structure", check_scan_thresholds(r.target.root, r.target.cfg)),
  ),
  Check(
    "directories",
    _always,
    (),
    lambda r: _from_violations("directories", check_dir_entries(r.target)),
  ),
  Check(
    "boundaries",
    _always,
    ("imports",),
    _sg_check(
      "boundaries", lambda r: check_boundaries(r.target, import_facts(r.target, r.matches))
    ),
  ),
  Check(
    "layers",
    lambda cfg, _root: bool(cfg.layers),
    ("imports",),
    _sg_check("layers", lambda r: check_layers(r.target, import_facts(r.target, r.matches))),
  ),
  Check(
    "comments",
    lambda cfg, _root: cfg.comments.enabled,
    ("no-comments",),
    _sg_check("comments", lambda r: check_comments(r.matches)),
  ),
  Check(
    "docstrings",
    lambda cfg, root: cfg.comments.enabled and _python(cfg, root),
    ("no-docstrings",),
    _sg_check("docstrings", lambda r: check_docstrings(r.matches)),
  ),
  Check("citations", lambda cfg, _root: cfg.comments.citations, ("citation",), _citations),
)
CHECK_NAMES = tuple(c.name for c in CHECKS)


def select_checks(cfg: AuditConfig, root: str, only: list[str] | None) -> list[Check]:
  enabled = [c for c in CHECKS if c.enabled(cfg, root)]
  if only is None:
    return enabled
  unknown = [n for n in only if n not in CHECK_NAMES]
  if unknown:
    raise ConfigError(f"unknown checks {unknown}; known: {', '.join(CHECK_NAMES)}")
  enabled_names = {c.name for c in enabled}
  disabled = [n for n in only if n not in enabled_names]
  if disabled:
    raise ConfigError(f"checks {disabled} are not enabled by [tool.mimir] for this target")
  return [c for c in enabled if c.name in only]


def run_audit(
  root: str, *, fix: bool = False, only: list[str] | None = None, config_path: str | None = None
) -> list[CheckResult]:
  root = os.path.abspath(root)
  cfg = load_config(root, config_path)
  checks = select_checks(cfg, root, only)
  target = Target(root, cfg, list_files(root, cfg.scope.data_trees))
  needs_imports = bool(cfg.boundaries or cfg.layers)
  families = tuple(
    sorted({f for c in checks for f in c.families if f != "imports" or needs_imports})
  )
  matches: list[astgrep.Match] = []
  sg_error: str | None = None
  try:
    files = astgrep.code_files(target.files, cfg.scope.languages)
    matches = astgrep.scan(root, files, families, cfg.comments.allow_directives)
  except astgrep.SgError as e:
    sg_error = str(e)
  run = Run(target, matches, sg_error, fix)
  return [c.run(run) for c in checks]


def print_results(results: list[CheckResult]) -> int:
  out = sys.stderr
  print("=== mimir audit ===", file=out)
  for r in results:
    print(f"  [{'pass' if r.passed else 'FAIL'}] {r.name}", file=out)
    if r.stats is not None:
      print(f"    {r.details}", file=out)
    if not r.passed:
      _print_failure(r)
  print(file=out)
  if not all(r.passed for r in results):
    print("FAIL", file=out)
    return EXIT_VIOLATIONS
  print("ok", file=out)
  return EXIT_CLEAN


def _print_failure(r: CheckResult) -> int:
  out = sys.stderr
  for v in r.violations:
    loc = f"{v.file}:{v.line}" if v.line else v.file
    print(f"    {loc}: {v.kind}: {v.message}", file=out)
  if r.violations or r.stats is not None:
    return len(r.violations)
  lines = r.details.splitlines()
  for line in lines[:DETAIL_LINES]:
    print(f"    {line}", file=out)
  if len(lines) > DETAIL_LINES:
    print(f"    ... {len(lines) - DETAIL_LINES} more lines", file=out)
  return min(len(lines), DETAIL_LINES + 1)


def results_json(results: list[CheckResult]) -> str:
  report = {"ok": all(r.passed for r in results), "checks": [asdict(r) for r in results]}
  return json.dumps(report, indent=2)
