"""Data-driven tests for CLI text output.

Style (matklad, "How to Test"): a single `check_text` function runs the
full `_print_text` pipeline on a canned report dict and compares against
expected output. When the output format changes, update the expected
strings here — the check function isolates all tests from internal API.

Each section has its own test so failures pinpoint which section broke.
"""

from __future__ import annotations

import io
import sys
import textwrap

from mimir.cli import (
  _print_heat,
  _print_rot,
  _print_structure,
  _print_surface,
  _print_todo,
  _print_text,
)


# ---------------------------------------------------------------------------
# check helper
# ---------------------------------------------------------------------------


def check_text(
  print_fn,
  data,
  expected_stderr: str,
  expected_stdout: str = "",
  **kwargs,
) -> None:
  """Call a _print_* function, capture stdout+stderr, compare to expected.

  This is the single coupling point between tests and the print API.
  If signatures change, update here once.
  """
  old_stdout, old_stderr = sys.stdout, sys.stderr
  sys.stdout = cap_out = io.StringIO()
  sys.stderr = cap_err = io.StringIO()
  try:
    print_fn(data, **kwargs)
  finally:
    sys.stdout, sys.stderr = old_stdout, old_stderr

  got_err = cap_err.getvalue()
  got_out = cap_out.getvalue()
  assert got_err == textwrap.dedent(expected_stderr), (
    f"stderr mismatch:\n--- expected ---\n{expected_stderr}\n--- got ---\n{got_err}"
  )
  assert got_out == textwrap.dedent(expected_stdout), (
    f"stdout mismatch:\n--- expected ---\n{expected_stdout}\n--- got ---\n{got_out}"
  )


# ---------------------------------------------------------------------------
# Fixtures — canned report data
# ---------------------------------------------------------------------------

STRUCTURE = {
  "functions": {
    "total": 3,
    "alerts": {"nest": 1, "cc": 0},
    "items": [
      {"name": "deep", "file": "a.py", "line": 1,
       "nest": 5, "stmts": 10, "args": 1, "cc": 3, "branches": 2, "returns": 1},
      {"name": "ok", "file": "a.py", "line": 10,
       "nest": 0, "stmts": 2, "args": 0, "cc": 1, "branches": 0, "returns": 1},
      {"name": "wide", "file": "b.py", "line": 1,
       "nest": 0, "stmts": 5, "args": 8, "cc": 1, "branches": 0, "returns": 1},
    ],
  },
  "erosion": 0.33,
  "files": {"total": 2, "long": []},
  "classes": {"total": 0, "wide": []},
}

HEAT = [
  {"file": "hot.py", "commits": 5, "max_cc": 20, "rel_heat": 100},
  {"file": "warm.py", "commits": 3, "max_cc": 8, "rel_heat": 24},
]

SURFACE = {
  "edges": [{"from": "a.py", "to": "b.py"}],
  "cycles": [["a.py", "b.py", "a.py"]],
  "high_fan_out": [],
  "high_fan_in": [],
  "wide_dirs": [{"dir": "src", "files": 50}],
}

ROT = {
  "counts": {"empty_fn": 2},
  "items": [
    {"kind": "empty_fn", "file": "a.py", "line": 5, "detail": "noop"},
    {"kind": "empty_fn", "file": "b.py", "line": 10, "detail": "stub"},
  ],
}

TODO = {
  "counts": {"TODO": 1, "FIXME": 1},
  "items": [
    {"kind": "TODO", "file": "a.py", "line": 3, "detail": "# TODO: later"},
    {"kind": "FIXME", "file": "b.py", "line": 7, "detail": "# FIXME: broken"},
  ],
}


# ---------------------------------------------------------------------------
# Tests — one per section
# ---------------------------------------------------------------------------


def test_print_structure_summary():
  check_text(
    _print_structure, STRUCTURE,
    expected_stderr="""\
structure
  functions  3
    nest  1
    cc  0
  erosion  0.33
  files  2
  classes  0
""",
    target="/repo", thresholds={}, only=[],
    list_mode=False, only_filter=None, min_idx=0,
  )


def test_print_structure_list_mode():
  from mimir.cli import DEFAULT_THRESHOLDS
  check_text(
    _print_structure, STRUCTURE,
    expected_stderr="""\
structure
  functions  3
    nest  1
    cc  0
  erosion  0.33
  files  2
  classes  0
""",
    expected_stdout="wide  b.py:1  args=8\ndeep  a.py:1  nest=5\nok  a.py:10  \n",
    target="/repo", thresholds=DEFAULT_THRESHOLDS, only=list(DEFAULT_THRESHOLDS),
    list_mode=True, only_filter=None, min_idx=0,
  )


def test_print_heat():
  check_text(
    _print_heat, HEAT,
    expected_stderr="""\
heat
  hot.py  commits=5  max_cc=20  rel_heat=100
  warm.py  commits=3  max_cc=8  rel_heat=24
""",
    list_mode=False,
  )


def test_print_heat_list_mode():
  check_text(
    _print_heat, HEAT,
    expected_stderr="""\
heat
  hot.py  commits=5  max_cc=20  rel_heat=100
  warm.py  commits=3  max_cc=8  rel_heat=24
""",
    expected_stdout="""\
hot.py  commits=5  max_cc=20  rel_heat=100
warm.py  commits=3  max_cc=8  rel_heat=24
""",
    list_mode=True,
  )


def test_print_heat_truncates_after_five():
  many = [{"file": f"f{i}.py", "commits": 1, "max_cc": 1, "rel_heat": 1} for i in range(8)]
  check_text(
    _print_heat, many,
    expected_stderr="""\
heat
  f0.py  commits=1  max_cc=1  rel_heat=1
  f1.py  commits=1  max_cc=1  rel_heat=1
  f2.py  commits=1  max_cc=1  rel_heat=1
  f3.py  commits=1  max_cc=1  rel_heat=1
  f4.py  commits=1  max_cc=1  rel_heat=1
  ... 3 more
""",
    list_mode=False,
  )


def test_print_surface():
  check_text(
    _print_surface, SURFACE,
    expected_stderr="""\
surface
  cycles  1
  wide_dirs  1
""",
    list_mode=False,
  )


def test_print_surface_empty():
  """No output when nothing interesting in surface."""
  empty = {"edges": [], "cycles": [], "high_fan_out": [], "high_fan_in": [], "wide_dirs": []}
  check_text(
    _print_surface, empty,
    expected_stderr="",
    list_mode=False,
  )


def test_print_rot():
  check_text(
    _print_rot, ROT,
    expected_stderr="""\
rot
  empty_fn  2
""",
    list_mode=False,
  )


def test_print_todo():
  check_text(
    _print_todo, TODO,
    expected_stderr="""\
todo
  FIXME  1
  TODO  1
""",
    list_mode=False,
  )


def test_print_todo_list_mode():
  check_text(
    _print_todo, TODO,
    expected_stderr="""\
todo
  FIXME  1
  TODO  1
""",
    expected_stdout="""\
todo:TODO  a.py:3  # TODO: later
todo:FIXME  b.py:7  # FIXME: broken
""",
    list_mode=True,
  )
