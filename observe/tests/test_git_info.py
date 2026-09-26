"""Provenance is honest or absent — never a plausible-looking lie.

`git_info` used to return `git_sha="unknown", git_dirty=False` for every
failure, which a reader cannot distinguish from a real run on a clean tree.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from observe.git import git_info


def test_git_info_returns_null_provenance_outside_a_repo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Not-a-repo makes `rev-parse` exit non-zero: both fields are None, not faked."""
    monkeypatch.chdir(tmp_path)
    assert git_info() == {"git_sha": None, "git_dirty": None}


def test_git_info_returns_null_provenance_without_a_git_binary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No git on PATH is the other honest absence."""

    def missing(*_args: object, **_kwargs: object) -> bytes:
        raise FileNotFoundError("git")

    monkeypatch.setattr(subprocess, "check_output", missing)
    assert git_info() == {"git_sha": None, "git_dirty": None}


def test_git_info_reads_the_real_repo() -> None:
    """Inside the repo the happy path still yields a real short sha and a bool."""
    info = git_info()
    sha = info["git_sha"]
    assert isinstance(sha, str)
    assert len(sha) >= 7
    assert isinstance(info["git_dirty"], bool)


def test_git_info_propagates_unexpected_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    """Only not-a-repo / no-git are caught. A timeout is a real problem: it escapes."""

    def boom(*_args: object, **_kwargs: object) -> bytes:
        raise subprocess.TimeoutExpired(cmd="git", timeout=1)

    monkeypatch.setattr(subprocess, "check_output", boom)
    with pytest.raises(subprocess.TimeoutExpired):
        git_info()
