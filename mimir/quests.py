"""mimir quests — where pending intent stands relative to the code.

v1: the "turn in" section — branches and worktrees whose work is already
in the default branch. Pure git; read-only; prints remedies, never runs them.

Verdict chain, decreasing certainty:
  merged          — branch tip is an ancestor of the default branch
  content-merged  — every commit is patch-equivalent (git cherry), or the
                    branch's diff against its merge-base is empty
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass


@dataclass
class BranchVerdict:
  branch: str
  verdict: str  # "merged" | "content-merged"
  reverted: bool = False  # content landed, but main no longer carries it
  age: str = ""  # relative committer date, e.g. "3 weeks ago"
  last_commit: str = ""  # iso-strict committer date
  upstream: str = "none"  # "none" | "gone" | "synced" | "ahead N, behind M"


@dataclass
class WorktreeVerdict:
  path: str
  branch: str | None  # None = detached HEAD
  head: str
  verdict: str  # "merged" | "content-merged" | "ancestor"
  dirty: bool
  age: str = ""  # empty for detached HEAD
  last_commit: str = ""
  upstream: str = ""


@dataclass
class TriageItem:
  path: str
  branch: str
  verdict: str  # branch is done, but the worktree has uncommitted changes


@dataclass
class TurnIn:
  default_branch: str
  worktrees: list[WorktreeVerdict]
  branches: list[BranchVerdict]
  triage: list[TriageItem]  # done branches with dirty worktrees — human decides
  skipped_dirty: list[str]  # dirty worktrees on live branches
  live_worktrees: int
  live_branches: int


def _git(root: str, *args: str) -> str | None:
  """Run git in `root`; None on failure."""
  try:
    res = subprocess.run(
      ["git", "-C", root, *args],
      capture_output=True, text=True, timeout=30,
    )
  except (OSError, subprocess.TimeoutExpired):
    return None
  if res.returncode != 0:
    return None
  return res.stdout


def _default_branch(root: str) -> str | None:
  ref = _git(root, "symbolic-ref", "--short", "refs/remotes/origin/HEAD")
  if ref:
    return ref.strip().split("/", 1)[-1]
  for cand in ("main", "master"):
    if _git(root, "rev-parse", "--verify", "--quiet", f"refs/heads/{cand}") is not None:
      return cand
  return None


def _is_ancestor(root: str, ref: str, of: str) -> bool:
  return _git(root, "merge-base", "--is-ancestor", ref, of) is not None


def _content_merged(root: str, branch: str, base: str) -> bool:
  """True if the branch's work already exists on `base` under other shas."""
  cherry = _git(root, "cherry", base, branch)
  if cherry is not None:
    lines = [ln for ln in cherry.splitlines() if ln.strip()]
    if lines and all(ln.startswith("-") for ln in lines):
      return True
  # Squash-merges can defeat patch-id matching; a branch whose tree adds
  # nothing beyond its merge-base is also done.
  diff = _git(root, "diff", "--name-only", f"{base}...{branch}")
  return diff is not None and not diff.strip()


_REVERTS_RE = re.compile(r"This reverts commit ([0-9a-f]{7,40})")


def _patch_id(root: str, commit: str) -> str | None:
  """Stable patch-id of a commit's diff; None for empty/unreadable diffs."""
  try:
    show = subprocess.run(
      ["git", "-C", root, "show", "--format=", commit],
      capture_output=True, text=True, timeout=30,
    )
    if show.returncode != 0 or not show.stdout.strip():
      return None
    pid = subprocess.run(
      ["git", "-C", root, "patch-id", "--stable"],
      input=show.stdout, capture_output=True, text=True, timeout=30,
    )
  except (OSError, subprocess.TimeoutExpired):
    return None
  if pid.returncode != 0 or not pid.stdout.strip():
    return None
  return pid.stdout.split()[0]


def _reverted_patch_ids(root: str, base: str) -> set[str]:
  """Patch-ids of every commit that `base`'s history explicitly reverted."""
  log = _git(root, "log", "--format=%B", "--grep=This reverts commit", base) or ""
  ids = set()
  for sha in _REVERTS_RE.findall(log):
    pid = _patch_id(root, sha)
    if pid:
      ids.add(pid)
  return ids


def _was_reverted(root: str, branch: str, base: str, reverted_ids: set[str]) -> bool:
  """True if any of the branch's own commits match a revert on `base`."""
  if not reverted_ids:
    return False
  shas = (_git(root, "rev-list", f"{base}..{branch}") or "").split()
  return any(_patch_id(root, sha) in reverted_ids for sha in shas)


def _branch_verdict(root: str, branch: str, base: str, merged_set: set[str]) -> str | None:
  if branch == base:
    return None
  if branch in merged_set:
    return "merged"
  if _content_merged(root, branch, base):
    return "content-merged"
  return None


def _list_branches(root: str, merged_into: str | None = None) -> list[str]:
  """All local branches; with merged_into, only those whose tip is its ancestor."""
  flags = [f"--merged={merged_into}"] if merged_into else []
  out = _git(root, "for-each-ref", "--format=%(refname:short)", *flags, "refs/heads/")
  return [ln.strip() for ln in (out or "").splitlines() if ln.strip()]


@dataclass
class _BranchMeta:
  age: str  # relative committer date
  last_commit: str  # iso-strict committer date
  upstream: str  # "none" | "gone" | "synced" | e.g. "ahead 1, behind 2"


def _branch_meta(root: str) -> dict[str, _BranchMeta]:
  """Per-branch commit age and upstream state, from one for-each-ref call."""
  fmt = "%(refname:short)%09%(committerdate:iso-strict)%09%(committerdate:relative)%09%(upstream:short)%09%(upstream:track)"
  out = _git(root, "for-each-ref", f"--format={fmt}", "refs/heads/")
  meta: dict[str, _BranchMeta] = {}
  for ln in (out or "").splitlines():
    if not ln.strip():
      continue
    name, iso, rel, up_short, up_track = (ln.split("\t") + [""] * 5)[:5]
    if not up_short:
      upstream = "none"
    elif up_track == "[gone]":
      upstream = "gone"
    elif not up_track:
      upstream = "synced"
    else:
      upstream = up_track.strip("[]")
    meta[name] = _BranchMeta(age=rel, last_commit=iso, upstream=upstream)
  return meta


def _list_worktrees(root: str) -> list[dict[str, str | None]]:
  """Parse `git worktree list --porcelain` into dicts, main worktree excluded."""
  out = _git(root, "worktree", "list", "--porcelain")
  if not out:
    return []
  worktrees: list[dict[str, str | None]] = []
  current: dict[str, str | None] = {}
  for line in [*out.splitlines(), ""]:
    if not line.strip():
      if current:
        worktrees.append(current)
        current = {}
      continue
    if line.startswith("worktree "):
      current = {"path": line.split(" ", 1)[1], "branch": None, "head": ""}
    elif line.startswith("HEAD "):
      current["head"] = line.split(" ", 1)[1]
    elif line.startswith("branch "):
      current["branch"] = line.split(" ", 1)[1].removeprefix("refs/heads/")
  main_path = os.path.realpath(root)
  return [w for w in worktrees if os.path.realpath(w["path"] or "") != main_path]


def _worktree_dirty(path: str) -> bool:
  status = _git(path, "status", "--porcelain")
  return status is None or bool(status.strip())


def collect_turn_in(root: str) -> TurnIn | None:
  """None if `root` is not a git repo (or has no default branch)."""
  base = _default_branch(root)
  if base is None:
    return None

  merged_set = set(_list_branches(root, merged_into=base))
  meta = _branch_meta(root)
  no_meta = _BranchMeta(age="", last_commit="", upstream="none")

  wt_verdicts: list[WorktreeVerdict] = []
  triage: list[TriageItem] = []
  skipped_dirty: list[str] = []
  worktrees = _list_worktrees(root)
  claimed_branches: set[str] = set()
  for wt in worktrees:
    path, branch, head = wt["path"] or "", wt["branch"], wt["head"] or ""
    if branch:
      claimed_branches.add(branch)
    if _worktree_dirty(path):
      verdict = _branch_verdict(root, branch, base, merged_set) if branch else None
      if branch and verdict:
        triage.append(TriageItem(path=path, branch=branch, verdict=verdict))
      else:
        skipped_dirty.append(path)
      continue
    if branch:
      verdict = _branch_verdict(root, branch, base, merged_set)
    else:
      verdict = "ancestor" if head and _is_ancestor(root, head, base) else None
    if verdict:
      m = meta.get(branch, no_meta) if branch else None
      wt_verdicts.append(WorktreeVerdict(
        path=path, branch=branch, head=head[:8], verdict=verdict, dirty=False,
        age=m.age if m else "", last_commit=m.last_commit if m else "",
        upstream=m.upstream if m else "",
      ))

  reverted_ids = _reverted_patch_ids(root, base)
  br_verdicts: list[BranchVerdict] = []
  branches = list(meta)
  current = (_git(root, "rev-parse", "--abbrev-ref", "HEAD") or "").strip()
  for branch in branches:
    if branch in (base, current) or branch in claimed_branches:
      continue  # worktree-claimed branches are reported with their worktree
    verdict = _branch_verdict(root, branch, base, merged_set)
    if verdict:
      reverted = verdict == "content-merged" and _was_reverted(root, branch, base, reverted_ids)
      m = meta.get(branch, no_meta)
      br_verdicts.append(BranchVerdict(
        branch=branch, verdict=verdict, reverted=reverted,
        age=m.age, last_commit=m.last_commit, upstream=m.upstream,
      ))

  judged_wt = len(worktrees) - len(skipped_dirty) - len(triage)
  candidate_branches = [
    b for b in branches if b not in (base, current) and b not in claimed_branches
  ]
  return TurnIn(
    default_branch=base,
    worktrees=wt_verdicts,
    branches=br_verdicts,
    triage=triage,
    skipped_dirty=skipped_dirty,
    live_worktrees=judged_wt - len(wt_verdicts),
    live_branches=len(candidate_branches) - len(br_verdicts),
  )
