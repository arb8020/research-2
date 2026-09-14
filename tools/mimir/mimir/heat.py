"""mimir heat — git churn × complexity hotspots.

Files that change often AND are complex are where bugs live.
Inspired by Adam Tornhill's "Your Code as a Crime Scene" / code-maat.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass

from .scan import iter_py_files, scan_file


@dataclass
class HeatMetrics:
  file: str
  commits: int
  max_cc: int
  avg_cc: float
  heat: float  # commits * max_cc


def git_churn(root: str, months: int = 6) -> dict[str, int]:
  """Count commits per file over the last N months using git log."""
  try:
    result = subprocess.run(
      [
        "git", "log",
        f"--since={months} months ago",
        "--format=",
        "--name-only",
      ],
      capture_output=True,
      text=True,
      cwd=root,
    )
  except FileNotFoundError:
    return {}

  if result.returncode != 0:
    return {}

  counts: dict[str, int] = {}
  for line in result.stdout.splitlines():
    line = line.strip()
    if line:
      counts[line] = counts.get(line, 0) + 1
  return counts


def compute_heat(
  root: str,
  exclude: list[str] | None = None,
  months: int = 6,
) -> list[HeatMetrics]:
  """Compute heat = churn × complexity for all Python files."""
  churn = git_churn(root, months)
  if not churn:
    return []

  results: list[HeatMetrics] = []
  for filepath in iter_py_files(root, exclude):
    relpath = os.path.relpath(filepath, root)
    commits = churn.get(relpath, 0)
    if commits == 0:
      continue

    fns, _ = scan_file(filepath)
    if not fns:
      continue

    max_cc = max(f.cyclomatic for f in fns)
    avg_cc = sum(f.cyclomatic for f in fns) / len(fns)
    heat = commits * max_cc

    results.append(HeatMetrics(
      file=relpath,
      commits=commits,
      max_cc=max_cc,
      avg_cc=round(avg_cc, 1),
      heat=heat,
    ))

  results.sort(key=lambda h: -h.heat)
  return results
