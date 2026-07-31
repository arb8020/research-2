"""Boundary tests for `mimir quests` turn-in detection.

Same style as test_report.py: build a real git repo fixture, run the real
CLI with --json, assert on the report data.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from mimir.cli import main


def git(cwd: Path, *args: str) -> str:
  res = subprocess.run(
    ["git", "-C", str(cwd),
     "-c", "user.email=t@t", "-c", "user.name=t",
     "-c", "commit.gpgsign=false", *args],
    check=True, capture_output=True, text=True,
  )
  return res.stdout


def make_repo(tmp_path: Path) -> Path:
  repo = tmp_path / "repo"
  repo.mkdir()
  git(repo, "init", "-q", "-b", "main")
  (repo / "a.txt").write_text("base\n")
  git(repo, "add", ".")
  git(repo, "commit", "-q", "-m", "base")
  return repo


def quests(repo: Path, capsys: pytest.CaptureFixture[str]) -> dict:
  argv_backup = sys.argv
  sys.argv = ["mimir", "quests", str(repo), "--json"]
  try:
    main()
  finally:
    sys.argv = argv_backup
  return json.loads(capsys.readouterr().out)["turn_in"]


def branch_verdicts(report: dict) -> dict[str, str]:
  return {b["branch"]: b["verdict"] for b in report["branches"]}


def add_commit(repo: Path, branch: str, fname: str, content: str) -> None:
  git(repo, "checkout", "-q", "-b", branch)
  (repo / fname).write_text(content)
  git(repo, "add", ".")
  git(repo, "commit", "-q", "-m", f"work on {branch}")
  git(repo, "checkout", "-q", "main")


def test_empty_repo_has_nothing_to_turn_in(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
  repo = make_repo(tmp_path)
  report = quests(repo, capsys)
  assert report["worktrees"] == []
  assert report["branches"] == []
  assert report["default_branch"] == "main"


def test_merge_committed_branch_is_merged(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
  repo = make_repo(tmp_path)
  add_commit(repo, "feat/done", "b.txt", "done\n")
  git(repo, "merge", "-q", "--no-ff", "feat/done", "-m", "merge feat/done")
  report = quests(repo, capsys)
  assert branch_verdicts(report) == {"feat/done": "merged"}


def test_squash_merged_branch_is_content_merged(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
  repo = make_repo(tmp_path)
  add_commit(repo, "feat/squashed", "c.txt", "squash me\n")
  git(repo, "merge", "--squash", "-q", "feat/squashed")
  git(repo, "commit", "-q", "-m", "squash-merge feat/squashed")
  report = quests(repo, capsys)
  assert branch_verdicts(report) == {"feat/squashed": "content-merged"}


def test_unmerged_branch_is_live(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
  repo = make_repo(tmp_path)
  add_commit(repo, "feat/wip", "d.txt", "in progress\n")
  report = quests(repo, capsys)
  assert report["branches"] == []
  assert report["live_branches"] == 1


def test_merged_worktree_reported_with_remedy(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
  repo = make_repo(tmp_path)
  add_commit(repo, "feat/wt", "e.txt", "wt\n")
  git(repo, "merge", "-q", "--no-ff", "feat/wt", "-m", "merge feat/wt")
  wt = tmp_path / "wt-checkout"
  git(repo, "worktree", "add", "-q", str(wt), "feat/wt")
  report = quests(repo, capsys)
  assert len(report["worktrees"]) == 1
  w = report["worktrees"][0]
  assert w["branch"] == "feat/wt"
  assert w["verdict"] == "merged"
  # worktree-claimed branch is not double-reported in branches
  assert report["branches"] == []


def test_dirty_worktree_on_live_branch_is_skipped(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
  repo = make_repo(tmp_path)
  add_commit(repo, "feat/dirty", "f.txt", "dirty\n")  # NOT merged
  wt = tmp_path / "dirty-checkout"
  git(repo, "worktree", "add", "-q", str(wt), "feat/dirty")
  (wt / "uncommitted.txt").write_text("precious\n")
  report = quests(repo, capsys)
  assert report["worktrees"] == []
  assert report["triage"] == []
  assert report["skipped_dirty"] == [str(wt)]


def test_detached_ancestor_worktree_reported(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
  repo = make_repo(tmp_path)
  old_sha = git(repo, "rev-parse", "HEAD").strip()
  (repo / "a.txt").write_text("newer\n")
  git(repo, "add", ".")
  git(repo, "commit", "-q", "-m", "advance main")
  wt = tmp_path / "review-checkout"
  git(repo, "worktree", "add", "-q", "--detach", str(wt), old_sha)
  report = quests(repo, capsys)
  assert len(report["worktrees"]) == 1
  w = report["worktrees"][0]
  assert w["branch"] is None
  assert w["verdict"] == "ancestor"


def test_non_git_dir_errors(tmp_path: Path) -> None:
  argv_backup = sys.argv
  sys.argv = ["mimir", "quests", str(tmp_path), "--json"]
  try:
    with pytest.raises(SystemExit):
      main()
  finally:
    sys.argv = argv_backup


def test_merged_branch_with_dirty_worktree_goes_to_triage(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
  repo = make_repo(tmp_path)
  add_commit(repo, "feat/tri", "g.txt", "tri\n")
  git(repo, "merge", "-q", "--no-ff", "feat/tri", "-m", "merge feat/tri")
  wt = tmp_path / "tri-checkout"
  git(repo, "worktree", "add", "-q", str(wt), "feat/tri")
  (wt / "uncommitted.txt").write_text("wip\n")
  report = quests(repo, capsys)
  assert report["worktrees"] == []
  assert report["skipped_dirty"] == []
  assert len(report["triage"]) == 1
  item = report["triage"][0]
  assert (item["branch"], item["verdict"]) == ("feat/tri", "merged")


def test_squash_merged_then_reverted_branch_is_flagged(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
  repo = make_repo(tmp_path)
  add_commit(repo, "feat/rev", "h.txt", "landed\n")
  git(repo, "merge", "--squash", "-q", "feat/rev")
  git(repo, "commit", "-q", "-m", "squash-merge feat/rev")
  git(repo, "revert", "--no-edit", "HEAD")
  report = quests(repo, capsys)
  verdicts = {b["branch"]: (b["verdict"], b["reverted"]) for b in report["branches"]}
  assert verdicts == {"feat/rev": ("content-merged", True)}


def test_absorbed_content_merged_branch_not_flagged_reverted(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
  repo = make_repo(tmp_path)
  add_commit(repo, "feat/kept", "i.txt", "kept\n")
  git(repo, "merge", "--squash", "-q", "feat/kept")
  git(repo, "commit", "-q", "-m", "squash-merge feat/kept")
  report = quests(repo, capsys)
  verdicts = {b["branch"]: (b["verdict"], b["reverted"]) for b in report["branches"]}
  assert verdicts == {"feat/kept": ("content-merged", False)}
