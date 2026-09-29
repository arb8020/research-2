from pathlib import Path

import pytest

from tally import Ctx, Handle, Meta, Step, assert_matches_clean, open_ctx

CRASH = {"on": True}


def two_files(ctx: Ctx, n: int, *, out: Path) -> None:
    (out / "first.txt").write_text(f"first {n}")
    if CRASH["on"]: raise RuntimeError("simulated crash mid-step")
    (out / "second.txt").write_text(f"second {n}")


TWO = Step(two_files)


def test_crash_mid_step_leaves_no_done_row(tmp_path: Path) -> None:
    ctx = open_ctx(tmp_path)
    key = TWO.key(TWO, (1,), {})
    CRASH["on"] = True
    with pytest.raises(RuntimeError, match="mid-step"):
        ctx.fetch(TWO, 1)
    assert ctx.meta.state(key) == "pending"
    assert ctx.meta.get(key) is None
    assert not (tmp_path / "blobs" / key).exists()  # half-written dir never reached blobs/
    assert ctx.ran == []

    CRASH["on"] = False
    ctx2 = open_ctx(tmp_path)
    h = ctx2.fetch(TWO, 1)
    assert ctx2.ran == ["two_files"]
    assert sorted(p.name for p in Path(h.path).iterdir()) == ["first.txt", "second.txt"]
    assert_matches_clean(lambda c: c.fetch(TWO, 1), ctx2)


class CrashOnDone(Meta):
    def done(self, h: Handle) -> None:
        raise RuntimeError("simulated crash after rename, before meta.done")


def test_crash_after_rename_blob_is_not_served(tmp_path: Path) -> None:
    CRASH["on"] = False
    ok = open_ctx(tmp_path)
    crashy = Ctx(CrashOnDone(ok.meta.db), ok.blobs)
    key = TWO.key(TWO, (2,), {})
    with pytest.raises(RuntimeError, match="before meta.done"):
        crashy.fetch(TWO, 2)
    assert (tmp_path / "blobs" / key).exists()  # renamed blob exists...
    assert ok.meta.get(key) is None              # ...but is not a hit
    h = ok.fetch(TWO, 2)                         # recompute replaces it
    assert ok.ran == ["two_files"]
    assert h.path == str(tmp_path / "blobs" / key)
