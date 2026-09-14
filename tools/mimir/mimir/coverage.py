"""Coverage.py branch data integration for mimir scan.

Reads a coverage.json (produced by `coverage json --pretty-print`) and extracts
per-function branch coverage metrics. Requires coverage.py to have been run with
`--branch` enabled.

Usage:
  coverage run --branch -m pytest
  coverage json
  mimir scan --coverage coverage.json
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass
class FunctionCoverage:
  file: str
  name: str
  start_line: int
  total_branches: int
  covered_branches: int
  missing_branches: int
  branch_coverage_pct: float
  missing_arcs: list[tuple[int, int]]


@dataclass
class FileCoverage:
  file: str
  total_branches: int
  covered_branches: int
  missing_branches: int
  branch_coverage_pct: float
  functions: list[FunctionCoverage]


def load_coverage(
  coverage_path: str,
  target_root: str,
) -> tuple[list[FunctionCoverage], list[FileCoverage]]:
  raw = json.loads(Path(coverage_path).read_text())

  meta = raw.get("meta", {})
  if not meta.get("branch_coverage"):
    msg = (
      f"{coverage_path}: branch_coverage is not enabled. "
      "Re-run with: coverage run --branch -m pytest && coverage json"
    )
    raise ValueError(msg)

  target = Path(target_root).resolve()
  all_fns: list[FunctionCoverage] = []
  all_files: list[FileCoverage] = []

  for abs_path, file_data in raw.get("files", {}).items():
    try:
      rel = str(Path(abs_path).resolve().relative_to(target))
    except ValueError:
      continue

    summary = file_data.get("summary", {})
    file_total = summary.get("num_branches", 0)
    file_covered = summary.get("covered_branches", 0)
    file_missing = summary.get("missing_branches", 0)

    fn_covs: list[FunctionCoverage] = []
    for fn_name, fn_data in file_data.get("functions", {}).items():
      fn_summary = fn_data.get("summary", {})
      total = fn_summary.get("num_branches", 0)
      covered = fn_summary.get("covered_branches", 0)
      missing = fn_summary.get("missing_branches", 0)
      pct = (covered / total * 100) if total > 0 else 100.0

      missing_arcs = [
        (arc[0], arc[1]) for arc in fn_data.get("missing_branches", [])
      ]

      fc = FunctionCoverage(
        file=rel,
        name=fn_name,
        start_line=fn_data.get("start_line", 0),
        total_branches=total,
        covered_branches=covered,
        missing_branches=missing,
        branch_coverage_pct=round(pct, 1),
        missing_arcs=missing_arcs,
      )
      fn_covs.append(fc)

    all_fns.extend(fn_covs)
    file_pct = (file_covered / file_total * 100) if file_total > 0 else 100.0
    all_files.append(FileCoverage(
      file=rel,
      total_branches=file_total,
      covered_branches=file_covered,
      missing_branches=file_missing,
      branch_coverage_pct=round(file_pct, 1),
      functions=fn_covs,
    ))

  all_fns.sort(key=lambda f: f.branch_coverage_pct)
  all_files.sort(key=lambda f: f.branch_coverage_pct)
  return all_fns, all_files
