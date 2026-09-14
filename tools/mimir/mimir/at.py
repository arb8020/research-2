"""mimir quests --at — sideways blame.

Which live (unmerged) branches/worktrees have pending changes overlapping a
file / line range? git blame looks backward through landed history; --at looks
sideways across unmerged work.

Coordinates: the target range is given in the default branch's current tip
("main coords"). Each branch's diff is expressed relative to its own merge-base
with main, so the query is a two-hop mapping:

  main tip --(reverse map through mb..main diff)--> merge-base coords
           --(intersect with branch hunks; forward map)--> branch coords
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .quests import _default_branch, _git, _list_worktrees

_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


@dataclass
class Hunk:
  old_start: int
  old_len: int
  new_start: int
  new_len: int


@dataclass
class AtHit:
  branch: str
  worktree: str | None
  ranges: list[tuple[int, int]]  # overlapping ranges, branch-side coords
  line_in_branch: int | None  # target range start mapped into the branch's file
  age_hours: float | None


@dataclass
class AtReport:
  file: str
  start: int | None  # None = whole file
  end: int | None
  hits: list[AtHit] = field(default_factory=list)
  branches_scanned: int = 0


def _parse_hunks(diff: str) -> list[Hunk]:
  hunks = []
  for line in diff.splitlines():
    m = _HUNK_RE.match(line)
    if m:
      os_, ol, ns, nl = m.groups()
      hunks.append(Hunk(int(os_), int(ol) if ol is not None else 1,
                        int(ns), int(nl) if nl is not None else 1))
  return hunks


def _diff_hunks(root: str, base: str, ref: str, path: str) -> list[Hunk]:
  out = _git(root, "diff", "-U0", "-M", f"{base}..{ref}", "--", path)
  return _parse_hunks(out) if out else []


def _path_at(root: str, base: str, ref: str, path: str) -> str:
  """Follow a rename backward: the name `path` (at ref) had at base."""
  out = _git(root, "diff", "-M", "--name-status", f"{base}..{ref}")
  for line in (out or "").splitlines():
    parts = line.split("\t")
    if len(parts) == 3 and parts[0].startswith("R") and parts[2] == path:
      return parts[1]
  return path


def _map_pos(pos: int, hunks: list[Hunk], *, new_to_old: bool) -> int:
  """Map a line number across a diff, clamping inside replaced regions.

  new_to_old maps a new-side line back to old-side coords; otherwise forward.
  A position inside a replaced region clamps to the region's start on the
  other side (the honest answer for "roughly here").
  """
  offset = 0
  for h in hunks:
    src_start, src_len = (h.new_start, h.new_len) if new_to_old else (h.old_start, h.old_len)
    dst_start = h.old_start if new_to_old else h.new_start
    # zero-length source (pure insertion on the other side): no source lines
    # to be inside; position numbers after src_start shift.
    if src_len and src_start <= pos < src_start + src_len:
      return dst_start
    anchor = src_start + src_len if src_len else src_start
    if pos >= anchor:
      offset += (h.old_len - h.new_len) if new_to_old else (h.new_len - h.old_len)
    else:
      break
  return pos + offset


def _overlap(h: Hunk, start: int, end: int) -> bool:
  """Does a hunk's old-side extent touch [start, end] (old coords)?"""
  if h.old_len == 0:  # pure insertion at old_start: touches if inside range
    return start <= h.old_start <= end
  return h.old_start <= end and h.old_start + h.old_len - 1 >= start


def query_at(
  root: str,
  path: str,
  start: int | None = None,
  end: int | None = None,
  branches: list[tuple[str, float | None]] | None = None,
) -> AtReport | None:
  """branches: (name, age_hours) pairs to scan; default = unmerged local heads."""
  base = _default_branch(root)
  if base is None:
    return None

  if branches is None:
    merged = set((_git(root, "branch", "--format=%(refname:short)",
                       "--merged", base) or "").split())
    import time
    now = time.time()
    branches = []
    out = _git(root, "for-each-ref", "refs/heads",
               "--format=%(refname:short)|%(committerdate:unix)") or ""
    for line in out.splitlines():
      name, ts = line.split("|")
      if name != base and name not in merged:
        branches.append((name, (now - int(ts)) / 3600))

  wt_by_branch: dict[str, str] = {}
  for wt in _list_worktrees(root):
    if wt.get("branch"):
      wt_by_branch[str(wt["branch"])] = str(wt["path"])

  report = AtReport(file=path, start=start, end=end)
  for branch, age in branches:
    report.branches_scanned += 1
    mb = (_git(root, "merge-base", base, branch) or "").strip()
    if not mb:
      continue

    # hop 1: map target range from main-tip coords back to merge-base coords
    base_path = _path_at(root, mb, base, path)
    to_base = _diff_hunks(root, mb, base, path)
    if start is None:
      mb_start, mb_end = None, None
    else:
      mb_start = _map_pos(start, to_base, new_to_old=True)
      mb_end = _map_pos(end if end is not None else start, to_base, new_to_old=True)
      if mb_end < mb_start:
        mb_start, mb_end = mb_end, mb_start

    # hop 2: intersect with the branch's hunks (expressed in merge-base coords)
    branch_path = _path_at(root, mb, branch, base_path) if base_path != path else base_path
    branch_hunks = _diff_hunks(root, mb, branch, branch_path)
    if not branch_hunks:
      continue
    if mb_start is None:
      overlapping = branch_hunks
    else:
      overlapping = [h for h in branch_hunks if _overlap(h, mb_start, mb_end)]
    if not overlapping:
      continue

    ranges = []
    for h in overlapping:
      if h.new_len:
        ranges.append((h.new_start, h.new_start + h.new_len - 1))
      else:  # pure deletion in branch: report the deletion point
        ranges.append((h.new_start, h.new_start))
    line_in_branch = (
      _map_pos(mb_start, branch_hunks, new_to_old=False) if mb_start is not None else None
    )
    report.hits.append(AtHit(
      branch=branch,
      worktree=wt_by_branch.get(branch),
      ranges=ranges,
      line_in_branch=line_in_branch,
      age_hours=age,
    ))

  report.hits.sort(key=lambda h: (h.worktree is None, h.age_hours or 0))
  return report


def parse_target(target: str) -> tuple[str, int | None, int | None]:
  """file[:line[-line]] -> (path, start, end). Windows-drive-free paths only."""
  path, sep, rng = target.rpartition(":")
  if not sep or not re.fullmatch(r"\d+(-\d+)?", rng):
    return target, None, None
  if "-" in rng:
    a, b = rng.split("-")
    return path, int(a), int(b)
  return path, int(rng), int(rng)
