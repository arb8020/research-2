from pathlib import Path

import pytest

import tally
from tally import Handle, Step, StepCtx, assert_matches_clean, derivation, derivation_state, open_store, start

CRASH = {"on": True}


def two_files(ctx: StepCtx, n: int, *, out: Path) -> None:
    (out / "first.txt").write_text(f"first {n}")
    if CRASH["on"]: raise RuntimeError("simulated crash mid-step")
    (out / "second.txt").write_text(f"second {n}")


TWO = Step(two_files)


def test_crash_mid_step_leaves_no_done_row(tmp_path: Path) -> None:
    store = open_store(tmp_path)
    ctx = start(store)
    key = TWO.key(TWO, (1,), {})
    CRASH["on"] = True
    with pytest.raises(RuntimeError, match="mid-step"):
        ctx.fetch(TWO, 1)
    assert derivation_state(store, key) == "pending"
    assert derivation(store, key) is None
    assert not (tmp_path / "blobs" / key).exists()  # half-written dir never reached blobs/
    assert ctx.ran == []

    CRASH["on"] = False
    store2 = open_store(tmp_path)
    ctx2 = start(store2)
    h = ctx2.fetch(TWO, 1)
    assert ctx2.ran == ["two_files"]
    assert sorted(p.name for p in Path(h.path).iterdir()) == ["first.txt", "second.txt"]
    assert_matches_clean(lambda c: c.fetch(TWO, 1), store2)


def crash_on_done(store: object, h: Handle) -> None:
    raise RuntimeError("simulated crash after rename, before meta.done")


def test_crash_after_rename_blob_is_not_served(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    CRASH["on"] = False
    ok = open_store(tmp_path)
    monkeypatch.setattr(tally, "mark_done", crash_on_done)
    crashy = start(ok)
    key = TWO.key(TWO, (2,), {})
    with pytest.raises(RuntimeError, match="before meta.done"):
        crashy.fetch(TWO, 2)
    monkeypatch.undo()
    assert (tmp_path / "blobs" / key).exists()  # renamed blob exists...
    assert derivation(ok, key) is None           # ...but is not a hit
    ok_ctx = start(ok)
    h = ok_ctx.fetch(TWO, 2)                     # recompute replaces it
    assert ok_ctx.ran == ["two_files"]
    assert h.path == str(tmp_path / "blobs" / key)
