from __future__ import annotations

import os
import shutil
import subprocess
import tomllib

TOOL_TIMEOUT_SECONDS = 900


def _find_tool(root: str, name: str) -> list[str]:
  venv_bin = os.path.join(root, ".venv", "bin", name)
  if os.path.isfile(venv_bin):
    return [venv_bin]
  if shutil.which(name):
    return [name]
  return ["uvx", name]


def _run(cmd: list[str], cwd: str) -> tuple[bool, str]:
  try:
    result = subprocess.run(
      cmd, cwd=cwd, capture_output=True, text=True, timeout=TOOL_TIMEOUT_SECONDS
    )
  except subprocess.TimeoutExpired:
    return False, f"{' '.join(cmd)}: timed out after {TOOL_TIMEOUT_SECONDS}s"
  except OSError as e:
    return False, f"{' '.join(cmd)}: {e}"
  output = result.stdout + result.stderr
  return result.returncode == 0, output.strip()


def _run_ruff_check(root: str, targets: list[str], *, fix: bool) -> tuple[bool, str]:
  cmd = [*_find_tool(root, "ruff"), "check"]
  if fix:
    cmd.append("--fix")
  return _run([*cmd, *targets], root)


def _run_ruff_format(root: str, targets: list[str], *, fix: bool) -> tuple[bool, str]:
  cmd = [*_find_tool(root, "ruff"), "format"]
  if not fix:
    cmd.append("--check")
  return _run([*cmd, *targets], root)


def _run_pyright(root: str, targets: list[str]) -> tuple[bool, str]:
  return _run([*_find_tool(root, "pyright"), *targets], root)


def _has_pyright_config(root: str) -> bool:
  if os.path.isfile(os.path.join(root, "pyrightconfig.json")):
    return True
  toml_path = os.path.join(root, "pyproject.toml")
  if os.path.isfile(toml_path):
    with open(toml_path, "rb") as f:
      data = tomllib.load(f)
    if "pyright" in data.get("tool", {}):
      return True
  return False


def _run_tsc(root: str, tsconfigs: tuple[str, ...]) -> tuple[bool, str]:
  results = [_run_one_tsc(root, tsconfig) for tsconfig in tsconfigs]
  output = "\n".join(
    f"{tsconfig}: {out}" for tsconfig, (ok, out) in zip(tsconfigs, results, strict=True)
  )
  return all(ok for ok, _ in results), output


def _run_one_tsc(root: str, tsconfig: str) -> tuple[bool, str]:
  path = os.path.join(root, tsconfig)
  if not os.path.isfile(path):
    return False, "tsconfig not found"
  project_dir = os.path.dirname(path)
  tsc = _find_tsc(root, project_dir)
  if tsc is None:
    return False, f"tsc not found in node_modules/.bin above {project_dir} or on PATH"
  ok, out = _run([tsc, "--noEmit", "-p", path], project_dir)
  return ok, out or "clean"


def _find_tsc(root: str, start: str) -> str | None:
  here = os.path.abspath(start)
  top = os.path.abspath(root)
  while True:
    candidate = os.path.join(here, "node_modules", ".bin", "tsc")
    if os.path.isfile(candidate):
      return candidate
    if here == top or os.path.dirname(here) == here:
      return shutil.which("tsc")
    here = os.path.dirname(here)
