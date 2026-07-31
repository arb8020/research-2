"""Data-driven tests at the report boundary.

Style (matklad, "How to Test"): every test feeds a fixture tree of source
files through the real CLI entry point (`mimir scan --json`) and asserts on
the report data. Nothing internal is imported except `main` — replace the
implementation wholesale and these tests still hold.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from mimir.cli import main


def scan(tmp_path: Path, files: dict[str, str], *flags: str, capsys: pytest.CaptureFixture[str]) -> dict:
  """Write `files` under tmp_path, run `mimir scan --json`, return the report."""
  for rel, source in files.items():
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(source)
  argv_backup = sys.argv
  sys.argv = ["mimir", "scan", str(tmp_path), "--json", *flags]
  try:
    main()
  finally:
    sys.argv = argv_backup
  return json.loads(capsys.readouterr().out)


def fn_by_name(report: dict, name: str) -> dict:
  items = report["structure"]["functions"]["items"]
  matches = [f for f in items if f["name"] == name]
  assert len(matches) == 1, f"{name}: {matches}"
  return matches[0]


def test_function_metrics(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
  report = scan(tmp_path, {"a.py": """
def flat(x, y):
  return x + y

def branchy(x):
  if x > 0:
    for i in range(x):
      if i % 2:
        return i
  return 0
"""}, capsys=capsys)
  flat = fn_by_name(report, "flat")
  assert (flat["nest"], flat["cc"], flat["args"], flat["returns"]) == (0, 1, 2, 1)
  branchy = fn_by_name(report, "branchy")
  assert branchy["nest"] == 3
  assert branchy["branches"] == 3  # if, for, if
  assert branchy["returns"] == 2
  assert report["structure"]["functions"]["total"] == 2


def test_methods_and_nested_functions_counted(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
  report = scan(tmp_path, {"a.py": """
class C:
  def method(self):
    def inner():
      pass
    return inner
"""}, capsys=capsys)
  assert report["structure"]["functions"]["total"] == 2
  fn_by_name(report, "C.method")
  fn_by_name(report, "C.method.inner")


def test_rot_flags_empty_but_not_interface_functions(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
  report = scan(tmp_path, {"a.py": """
from abc import ABC, abstractmethod
from typing import Protocol, overload

def dead():
  pass

def dead_docstring():
  '''Looks documented, does nothing.'''

class Iface(Protocol):
  def declared(self): ...

class Base(ABC):
  @abstractmethod
  def must_override(self): ...

@overload
def f(x: int) -> int: ...
def f(x):
  return x
"""}, capsys=capsys)
  flagged = {r["detail"] for r in report["rot"]["items"]}
  assert flagged == {"dead", "dead_docstring"}


def test_todo_markers_and_not_implemented(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
  report = scan(tmp_path, {"a.py": """
# TODO: fix this
# FIXME broken
def later():
  raise NotImplementedError
"""}, capsys=capsys)
  kinds = [f["kind"] for f in report["todo"]["items"]]
  assert kinds.count("TODO") == 1
  assert kinds.count("FIXME") == 1
  assert kinds.count("not_implemented") == 1


def test_import_graph_edges_and_cycle(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
  report = scan(tmp_path, {
    "pkg/__init__.py": "",
    "pkg/a.py": "from . import b\n",
    "pkg/b.py": "from . import a\n",
    "pkg/leaf.py": "x = 1\n",
  }, capsys=capsys)
  surface = report["surface"]
  assert surface["cycles"], "a <-> b cycle not detected"
  edges = {(e["from"], e["to"]) for e in surface["edges"]}
  assert ("pkg/a.py", "pkg/b.py") in edges
  assert ("pkg/b.py", "pkg/a.py") in edges


def test_erosion_zero_for_simple_code(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
  report = scan(tmp_path, {"a.py": "def f():\n  return 1\n"}, capsys=capsys)
  assert report["structure"]["erosion"] == 0.0


def test_excluded_dirs_skipped(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
  report = scan(
    tmp_path,
    {"keep.py": "def kept():\n  return 1\n",
     "vendor/skip.py": "def skipped():\n  return 1\n"},
    "--exclude", "vendor",
    capsys=capsys,
  )
  names = {f["name"] for f in report["structure"]["functions"]["items"]}
  assert names == {"kept"}


def test_syntax_error_file_does_not_crash_scan(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
  report = scan(tmp_path, {
    "good.py": "def ok():\n  return 1\n",
    "bad.py": "def broken(:\n",
  }, capsys=capsys)
  fn_by_name(report, "ok")


def test_heat_ranks_churned_complex_file_first(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
  """Slow-ish: real git repo. heat = commits x max cc."""
  complex_src = """
def tangled(x):
  if x:
    if x > 1:
      if x > 2:
        return 3
  return 0
"""

  def git(*args: str) -> None:

    subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)

  git("init", "-q")
  git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "root")
  (tmp_path / "hot.py").write_text(complex_src)
  (tmp_path / "cold.py").write_text("def calm():\n  return 1\n")
  git("add", ".")
  git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "one")
  (tmp_path / "hot.py").write_text(complex_src + "\n# touched\n")
  git("add", ".")
  git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "two")

  report = scan(tmp_path, {}, capsys=capsys)
  heat = report["heat"]
  assert heat, "no heat output from git repo"
  assert heat[0]["file"] == "hot.py"
  hot = heat[0]
  assert hot["rel_heat"] == hot["commits"] * hot["max_cc"]
