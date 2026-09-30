"""Regression tests: lazy digests, first-writer-wins commit, module_fp default, tmp cleanup."""
import importlib
import sys
from pathlib import Path

import pytest

from tally import Handle, Hashed, Step, keys, open_ctx


def _write(ctx, x: int, out: Path):  # noqa: ANN001, ANN201
    (out / "blob.bin").write_bytes(b"x" * x)


def _use(ctx, h, out: Path) -> int:  # noqa: ANN001
    return len((Path(h.path) / "blob.bin").read_bytes())


WRITE = Step(_write)


def test_recipe_steps_never_hash(tmp_path: Path) -> None:
    ctx = open_ctx(tmp_path)
    h = ctx.fetch(WRITE, 10)
    assert not isinstance(h, Hashed)                          # commit did not read the bytes
    ctx.fetch(Step(_use, key=keys.recipe), h)
    assert not isinstance(ctx.meta.get(h.key), Hashed)        # recipe consumer never asked for it


def test_bytes_consumer_hashes_once_and_remembers(tmp_path: Path) -> None:
    ctx = open_ctx(tmp_path)
    h = ctx.fetch(WRITE, 10)
    ctx.fetch(Step(_use, key=keys.bytes), h)
    stored = ctx.meta.get(h.key)
    assert isinstance(stored, Hashed)                         # hashed lazily, saved to meta
    ctx.fetch(Step(_use, key=keys.bytes), h)                  # second consumer: served from meta
    assert ctx.meta.get(h.key) == stored


def test_second_writer_does_not_clobber_first(tmp_path: Path) -> None:
    a, b = open_ctx(tmp_path), open_ctx(tmp_path)             # two processes, one store
    h = a.fetch(WRITE, 10)
    b.meta.pending(h.key)                                     # late writer: must not demote done
    assert b.meta.state(h.key) == "done"
    tmp = b.blobs.tmp()
    (tmp / "blob.bin").write_bytes(b"late")
    h2 = b.blobs.commit(tmp, h.key)
    assert h2.path == h.path and not tmp.exists()             # first writer wins, late tmp discarded
    assert (Path(h.path) / "blob.bin").read_bytes() == b"x" * 10


def test_module_fp_sees_helper_edits(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    mod = tmp_path / "mod_under_test.py"
    src = "def helper():\n    return {v}\n\ndef work(ctx, out):\n    return helper()\n"
    mod.write_text(src.format(v=1))
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.setattr(sys, "dont_write_bytecode", True)     # else reload may serve a same-second stale .pyc
    m = importlib.import_module("mod_under_test")
    ctx = open_ctx(tmp_path / "store")
    assert ctx.load(ctx.fetch(Step(m.work))) == 1
    mod.write_text(src.format(v=2))                           # edit only the helper
    m = importlib.reload(m)
    assert ctx.load(ctx.fetch(Step(m.work))) == 2             # default code_fp caught it
    assert ctx.ran == ["work", "work"]
    sys.modules.pop("mod_under_test")


def _boom(ctx, out: Path):  # noqa: ANN001, ANN201
    (out / "half.bin").write_bytes(b"partial")
    raise RuntimeError("crash")


def test_raising_step_leaves_no_tmp(tmp_path: Path) -> None:
    ctx = open_ctx(tmp_path)
    with pytest.raises(RuntimeError):
        ctx.fetch(Step(_boom))
    assert list((tmp_path / "tmp").iterdir()) == []


def test_digest_keyfn_rejects_unhashed_handle() -> None:
    step = Step(_use, key=keys.bytes)
    with pytest.raises(TypeError, match="unhashed"):
        keys.bytes(step, (Handle(key="k" * 64, path="/x"),), {})  # called directly, bypassing fetch's hashing
