"""mimir audit — pass/fail code quality gate for Python projects.

Ports crucible's audit stack (ruff + pyright + AST style checks) into a
reusable command. Config lives in the target project's pyproject.toml under
[tool.mimir].

Exit 0 = clean. Exit 1 = violations found.
"""

from __future__ import annotations

import ast
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from .config import load_tool_mimir
from .scan import iter_py_files, scan_dir

# --- defaults (match crucible's thresholds) ---

DEFAULTS: dict[str, int] = {
  "max-function-lines": 70,
  "max-file-lines": 1000,
  "max-nesting": 4,
  "max-cyclomatic": 10,
  "max-args": 6,
  "max-dir-entries": 7,
}

# --- void-return check (ported from crucible check_style.py) ---

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

# Methods on abstract/protocol classes that are inherently void.
# Configurable via [tool.mimir] void-exempt-methods.
_DEFAULT_VOID_EXEMPT_METHODS: set[str] = {
  "start",
  "stop",
  "close",
  "reply",
  "upload_file",
  "upload_dir",
  "download_file",
  "download_dir",
  "_validate_definition",
  "_reset_task_workspace",
  "_run_setup_scripts",
  "find_spec",
  "find_module",
  "load_module",
  # HTTP handler methods
  "do_GET",
  "do_POST",
  "do_PUT",
  "do_DELETE",
  "do_HEAD",
  "do_OPTIONS",
  "log_message",
  "log_request",
}


@dataclass
class Boundary:
  src: str
  forbid: list[str]


@dataclass
class AuditConfig:
  src: list[str]
  exclude: list[str]
  max_function_lines: int
  max_file_lines: int
  max_nesting: int
  max_cyclomatic: int
  max_args: int
  max_dir_entries: int
  check_void_returns: bool
  check_isinstance: bool
  void_exempt_methods: set[str]
  boundaries: list[Boundary]


@dataclass
class Violation:
  file: str
  line: int
  kind: str
  message: str


def load_config(root: str) -> AuditConfig:
  """Read [tool.mimir] from the target project's pyproject.toml."""
  cfg = load_tool_mimir(root)

  src_raw = cfg.get("src", None)
  if src_raw is None:
    # auto-detect: find directories containing .py files at root level
    src_raw = _auto_detect_src(root)

  return AuditConfig(
    src=[s.rstrip("/") for s in src_raw],
    exclude=cfg.get("exclude", []),
    max_function_lines=cfg.get("max-function-lines", DEFAULTS["max-function-lines"]),
    max_file_lines=cfg.get("max-file-lines", DEFAULTS["max-file-lines"]),
    max_nesting=cfg.get("max-nesting", DEFAULTS["max-nesting"]),
    max_cyclomatic=cfg.get("max-cyclomatic", DEFAULTS["max-cyclomatic"]),
    max_args=cfg.get("max-args", DEFAULTS["max-args"]),
    max_dir_entries=cfg.get("max-dir-entries", DEFAULTS["max-dir-entries"]),
    check_void_returns=cfg.get("check-void-returns", True),
    check_isinstance=cfg.get("check-isinstance", False),
    void_exempt_methods=set(
      cfg.get(
        "void-exempt-methods",
        list(_DEFAULT_VOID_EXEMPT_METHODS),
      )
    ),
    boundaries=[
      Boundary(src=b["src"], forbid=list(b["forbid"])) for b in cfg.get("boundaries", [])
    ],
  )


def _auto_detect_src(root: str) -> list[str]:
  """Find top-level directories that look like Python packages."""
  candidates = []
  for entry in sorted(os.listdir(root)):
    full = os.path.join(root, entry)
    if not os.path.isdir(full):
      continue
    if entry.startswith((".", "_")):
      continue
    if entry in {"build", "dist", "node_modules", "worktrees", "docs", "scripts"}:
      continue
    init = os.path.join(full, "__init__.py")
    if os.path.isfile(init):
      candidates.append(entry)
  return candidates if candidates else ["."]


# --- external tool runners ---


def _find_tool(root: str, name: str) -> list[str]:
  """Find a tool: prefer the target's venv, then PATH, then uvx."""
  venv_bin = os.path.join(root, ".venv", "bin", name)
  if os.path.isfile(venv_bin):
    return [venv_bin]
  # check if on PATH
  import shutil

  if shutil.which(name):
    return [name]
  # fall back to uvx
  return ["uvx", name]


def _run_ruff_check(root: str, targets: list[str], *, fix: bool) -> tuple[bool, str]:
  cmd = [*_find_tool(root, "ruff"), "check"]
  if fix:
    cmd.append("--fix")
  cmd.extend(targets)
  result = subprocess.run(cmd, cwd=root, capture_output=True, text=True)
  output = result.stdout + result.stderr
  return result.returncode == 0, output.strip()


def _run_ruff_format(root: str, targets: list[str], *, fix: bool) -> tuple[bool, str]:
  cmd = [*_find_tool(root, "ruff"), "format"]
  if not fix:
    cmd.append("--check")
  cmd.extend(targets)
  result = subprocess.run(cmd, cwd=root, capture_output=True, text=True)
  output = result.stdout + result.stderr
  return result.returncode == 0, output.strip()


def _run_pyright(root: str, targets: list[str]) -> tuple[bool, str]:
  cmd = [*_find_tool(root, "pyright"), *targets]
  result = subprocess.run(cmd, cwd=root, capture_output=True, text=True)
  output = result.stdout + result.stderr
  return result.returncode == 0, output.strip()


def _has_pyright_config(root: str) -> bool:
  if os.path.isfile(os.path.join(root, "pyrightconfig.json")):
    return True
  toml_path = os.path.join(root, "pyproject.toml")
  if os.path.isfile(toml_path):
    try:
      import tomllib
    except ModuleNotFoundError:
      import tomli as tomllib  # type: ignore[no-redef]
    with open(toml_path, "rb") as f:
      data = tomllib.load(f)
    if "pyright" in data.get("tool", {}):
      return True
  return False


# --- AST style checks ---


def _returns_none(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
  """True if the function returns None (explicitly annotated or no return value)."""
  # stub body (just ...) is not void
  if (
    len(node.body) == 1
    and isinstance(node.body[0], ast.Expr)
    and isinstance(node.body[0].value, ast.Constant)
    and node.body[0].value.value is Ellipsis
  ):
    return False

  # generators are not void
  for child in ast.walk(node):
    if isinstance(child, (ast.Yield, ast.YieldFrom)):
      return False

  annotation = node.returns
  if annotation is not None:
    return (isinstance(annotation, ast.Constant) and annotation.value is None) or (
      isinstance(annotation, ast.Name) and annotation.id == "None"
    )

  # no annotation: void if no return with a value
  for child in ast.walk(node):
    if isinstance(child, ast.Return) and child.value is not None:
      return False
  return True


def _is_void_exempt(
  node: ast.FunctionDef | ast.AsyncFunctionDef,
  *,
  in_class: bool,
  exempt_methods: set[str],
) -> bool:
  if node.name.startswith("__"):
    return True
  if node.name in _VOID_EXEMPT_NAMES:
    return True
  if any(node.name.startswith(p) for p in _VOID_EXEMPT_PREFIXES):
    return True
  if in_class and node.name in exempt_methods:
    return True
  # check decorators for framework exemptions
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
  """Run AST-based style checks on all Python files under cfg.src."""
  violations: list[Violation] = []

  for src_dir in cfg.src:
    full_dir = os.path.join(root, src_dir)
    if not os.path.isdir(full_dir):
      continue

    for filepath in iter_py_files(full_dir, exclude=cfg.exclude):
      relpath = os.path.relpath(filepath, root)
      try:
        source = Path(filepath).read_text()
      except (OSError, UnicodeDecodeError):
        continue

      lines = source.splitlines()
      if len(lines) > cfg.max_file_lines:
        violations.append(
          Violation(
            relpath,
            len(lines),
            "file-too-long",
            f"file is {len(lines)} lines (max {cfg.max_file_lines})",
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
  if body_lines > cfg.max_function_lines:
    violations.append(
      Violation(
        relpath,
        child.lineno,
        "function-too-long",
        f"`{child.name}` is {body_lines} lines (max {cfg.max_function_lines})",
      )
    )

  is_void_candidate = (
    cfg.check_void_returns
    and not _is_void_exempt(child, in_class=in_class, exempt_methods=cfg.void_exempt_methods)
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

  if cfg.check_isinstance:
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
  """Use mimir's scan infrastructure to check structural thresholds."""
  violations: list[Violation] = []

  for src_dir in cfg.src:
    full_dir = os.path.join(root, src_dir)
    if not os.path.isdir(full_dir):
      continue

    fn_metrics, _ = scan_dir(full_dir, exclude=cfg.exclude)

    for m in fn_metrics:
      relpath = os.path.relpath(m.file, root)

      if m.max_nesting > cfg.max_nesting:
        violations.append(
          Violation(
            relpath,
            m.line,
            "nesting",
            f"`{m.name}` nesting depth {m.max_nesting} (max {cfg.max_nesting})",
          )
        )

      if m.cyclomatic > cfg.max_cyclomatic:
        violations.append(
          Violation(
            relpath,
            m.line,
            "cyclomatic",
            f"`{m.name}` cyclomatic complexity {m.cyclomatic} (max {cfg.max_cyclomatic})",
          )
        )

      if m.arg_count > cfg.max_args:
        violations.append(
          Violation(
            relpath,
            m.line,
            "too-many-args",
            f"`{m.name}` has {m.arg_count} args (max {cfg.max_args})",
          )
        )

  return violations


def check_dir_entries(root: str, cfg: AuditConfig) -> list[Violation]:
  """Check that no non-test directory has too many entries."""
  violations: list[Violation] = []
  seen: set[str] = set()

  for src_dir in cfg.src:
    full_dir = os.path.join(root, src_dir)
    if not os.path.isdir(full_dir):
      continue

    _skip_dirs = {
      "tests",
      "test",
      "__pycache__",
      ".git",
      "node_modules",
      ".venv",
      "venv",
      "build",
      "dist",
      ".mypy_cache",
      ".pytest_cache",
      ".tox",
      ".eggs",
      "worktrees",
    }

    for dirpath, dirnames, filenames in os.walk(full_dir):
      # prune skipped dirs from walk
      dirnames[:] = [d for d in dirnames if d not in _skip_dirs]

      if dirpath in seen:
        continue
      seen.add(dirpath)

      dirname = os.path.basename(dirpath)
      if dirname in _skip_dirs:
        continue

      entries = [
        e
        for e in (list(dirnames) + list(filenames))
        if not e.startswith(".") and e not in ("__pycache__", "__init__.py", "__main__.py")
      ]
      if len(entries) > cfg.max_dir_entries:
        relpath = os.path.relpath(dirpath, root)
        violations.append(
          Violation(
            relpath,
            0,
            "dir-too-wide",
            f"{len(entries)} entries (max {cfg.max_dir_entries})",
          )
        )

  return violations


def _imported_modules(tree: ast.AST) -> list[str]:
  """Module names referenced by Import and ImportFrom nodes, including `from X import Y`
  forms as both `X` and `X.Y` (so a forbidden prefix matches either)."""
  names: list[str] = []
  for node in ast.walk(tree):
    if isinstance(node, ast.Import):
      names.extend(a.name for a in node.names)
    elif isinstance(node, ast.ImportFrom) and node.module:
      names.append(node.module)
      names.extend(f"{node.module}.{a.name}" for a in node.names)
  return names


def check_boundaries(root: str, cfg: AuditConfig) -> list[Violation]:
  """Enforce [tool.mimir] boundaries: files matching `src` must not import anything
  under a `forbid` prefix."""
  violations: list[Violation] = []

  for boundary in cfg.boundaries:
    for filepath in sorted(Path(root).glob(boundary.src)):
      if not filepath.is_file():
        continue
      relpath = os.path.relpath(filepath, root)
      try:
        tree = ast.parse(filepath.read_text())
      except (OSError, UnicodeDecodeError, SyntaxError):
        continue

      for module in _imported_modules(tree):
        hit = next((f for f in boundary.forbid if module == f or module.startswith(f + ".")), None)
        if hit is not None:
          violations.append(
            Violation(
              relpath,
              0,
              "import-boundary",
              f"{relpath} imports {module}; forbidden by boundary {boundary.src}",
            )
          )

  return violations


# --- main audit orchestrator ---


@dataclass
class CheckResult:
  name: str
  passed: bool
  details: str
  violations: list[Violation]


def run_audit(root: str, *, fix: bool = False) -> list[CheckResult]:
  """Run the full audit suite. Returns a list of check results."""
  root = os.path.abspath(root)
  cfg = load_config(root)
  results: list[CheckResult] = []

  targets = cfg.src if cfg.src != ["."] else ["."]

  # 1. ruff check
  ok, output = _run_ruff_check(root, targets, fix=fix)
  results.append(CheckResult("ruff check", ok, output, []))

  # 2. ruff format
  ok, output = _run_ruff_format(root, targets, fix=fix)
  results.append(CheckResult("ruff format", ok, output, []))

  # 3. pyright (only if configured)
  if _has_pyright_config(root):
    ok, output = _run_pyright(root, targets)
    results.append(CheckResult("pyright", ok, output, []))

  # 4. AST style checks
  style_violations = check_style(root, cfg)
  results.append(
    CheckResult(
      "style",
      len(style_violations) == 0,
      f"{len(style_violations)} violations" if style_violations else "clean",
      style_violations,
    )
  )

  # 5. structural thresholds (from mimir scan)
  scan_violations = check_scan_thresholds(root, cfg)
  results.append(
    CheckResult(
      "structure",
      len(scan_violations) == 0,
      f"{len(scan_violations)} violations" if scan_violations else "clean",
      scan_violations,
    )
  )

  # 6. directory entry counts
  dir_violations = check_dir_entries(root, cfg)
  results.append(
    CheckResult(
      "directories",
      len(dir_violations) == 0,
      f"{len(dir_violations)} violations" if dir_violations else "clean",
      dir_violations,
    )
  )

  # 7. import boundaries
  boundary_violations = check_boundaries(root, cfg)
  results.append(
    CheckResult(
      "boundaries",
      len(boundary_violations) == 0,
      f"{len(boundary_violations)} violations" if boundary_violations else "clean",
      boundary_violations,
    )
  )

  return results


def print_results(results: list[CheckResult]) -> int:
  """Print audit results to stderr and return exit code."""
  out = sys.stderr
  print("=== mimir audit ===", file=out)
  failed = False

  for r in results:
    icon = "pass" if r.passed else "FAIL"
    print(f"  [{icon}] {r.name}", file=out)

    if not r.passed:
      failed = True
      # print violations if any
      for v in r.violations:
        loc = f"{v.file}:{v.line}" if v.line else v.file
        print(f"    {loc}: {v.kind}: {v.message}", file=out)
      # print tool output for external tools (ruff, pyright)
      if not r.violations and r.details:
        for line in r.details.splitlines()[:20]:
          print(f"    {line}", file=out)
        remaining = len(r.details.splitlines()) - 20
        if remaining > 0:
          print(f"    ... {remaining} more lines", file=out)

  print(file=out)
  if failed:
    print("FAIL", file=out)
    return 1
  print("ok", file=out)
  return 0
