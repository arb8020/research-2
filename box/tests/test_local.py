"""`box setup --local`'s cache key: pure, reads a fake tree."""

from __future__ import annotations

from pathlib import Path

from box.kelpie import local


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


def test_child_env_drops_virtual_env(monkeypatch):
    monkeypatch.setenv("VIRTUAL_ENV", "/somewhere/box/.venv")
    env = local.child_env({"X": "1"})
    assert "VIRTUAL_ENV" not in env
    assert env["X"] == "1"
