"""kelpie's dev tooling, pure parts: the local shim cache key, the gc staleness rule, setup's Shell.

Runs in box's environment, like the code (dev/__init__.py), from the repo root:

    PYTHONPATH=kelpie/kelpie-http uv run --frozen --project box --extra dev python -m pytest kelpie/kelpie-http/kelpie_http/dev -q
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kelpie_http.dev import local
from kelpie_http.dev.gc import DAY_S, stale_keys
from kelpie_http.dev.setup import TIMEOUT_EXIT, Shell

NOW = 100 * DAY_S
WEEK = 7 * DAY_S


def _tree(root: Path) -> Path:
    for rel in local.SHIM_INPUTS:
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(rel)
    return root


def test_key_is_stable_and_moves_with_every_input(tmp_path: Path):
    kelpie = _tree(tmp_path)
    key = local.xgrammar_key(kelpie, "a" * 40)
    assert key == local.xgrammar_key(kelpie, "a" * 40)
    assert key.startswith("a" * 12)
    assert local.xgrammar_key(kelpie, "b" * 40) != key
    for rel in local.SHIM_INPUTS:
        before = (kelpie / rel).read_text()
        (kelpie / rel).write_text(before + " edited")
        assert local.xgrammar_key(kelpie, "a" * 40) != key, rel
        (kelpie / rel).write_text(before)


def test_child_env_drops_virtual_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("VIRTUAL_ENV", "/somewhere/kelpie-http/.venv")
    env = local.child_env({"X": "1"})
    assert "VIRTUAL_ENV" not in env
    assert env["X"] == "1"


def test_kelpie_is_this_checkouts_tree():
    assert (local.KELPIE / "kelpie-core").is_dir()
    assert len(local.xgrammar_submodule_sha(local.KELPIE)) == 40


def _key(
    name: str, *, complete: float | None, used: float | None, so: float
) -> list[tuple[str, float]]:
    base = f"builds/libkelpie/{name}"
    rows = [(base, so), (f"{base}/libkelpie.so", so)]
    rows += [(f"{base}/.complete", complete)] if complete is not None else []
    rows += [(f"{base}/.used", used)] if used is not None else []
    return rows


def test_used_long_ago_is_stale_recently_used_is_not():
    listing = _key("old", complete=10 * DAY_S, used=NOW - 8 * DAY_S, so=10 * DAY_S)
    listing += _key("hot", complete=10 * DAY_S, used=NOW - DAY_S, so=10 * DAY_S)
    assert [k for k, _ in stale_keys(listing, WEEK, NOW)] == ["builds/libkelpie/old"]


def test_complete_key_without_used_is_never_stale():
    """A checkout from before .used may use it daily; its .complete says only when it was built."""
    assert stale_keys(_key("legacy", complete=DAY_S, used=None, so=DAY_S), WEEK, NOW) == []


def test_dead_build_ages_by_its_newest_file():
    dead = _key("dead", complete=None, used=None, so=NOW - 30 * DAY_S)
    fresh = _key("building", complete=None, used=None, so=NOW - 60)
    assert [k for k, _ in stale_keys(dead + fresh, WEEK, NOW)] == ["builds/libkelpie/dead"]


def test_other_trees_on_the_volume_are_ignored():
    listing = [("builds/other/k/.used", 0.0), ("hf/hub/models--x/.used", 0.0), ("builds", 0.0)]
    assert stale_keys(listing, WEEK, NOW) == []


def test_shell_exec_env_status_and_timeout():
    sh = Shell()
    ok = sh.exec('echo "$FOO"; echo err >&2; exit 3', env={"FOO": "bar"})
    assert (ok.stdout, ok.stderr, ok.returncode) == ("bar\n", "err\n", 3)
    slow = sh.exec("sleep 5", timeout=1)
    assert slow.returncode == TIMEOUT_EXIT
