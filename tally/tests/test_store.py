import sqlite3
from collections.abc import Callable
from pathlib import Path

import pytest

import tally
from tally import (
    EffectFailed,
    Err,
    Handle,
    Ok,
    Step,
    StepCtx,
    StoreError,
    assert_matches_clean,
    derivation,
    derivation_state,
    effect_key,
    open_store,
    rerun,
    start,
)

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


def crash_before_row(*args: object) -> None:
    raise RuntimeError("simulated crash after rename, before row update")


def crash_after_rename(root: Path, kind: str, calls: list[str]) -> Callable[[], object]:
    def make(ctx: StepCtx, *, out: Path) -> str:
        calls.append(kind)
        return "made"

    def send(ctx: StepCtx, *, idem_key: str, out: Path) -> object:
        calls.append(kind)
        return Ok("sent") if kind == "effect ok" else Err("declined")

    def once() -> object:
        ctx = start(open_store(root))
        handle = ctx.fetch(Step(make, label="make")) if kind == "derivation" else ctx.effect("send", send, inputs=0, on_unknown=rerun)
        return ctx.ran, ctx.load(handle)
    return once


def check_crash_after_rename(root: Path, monkeypatch: pytest.MonkeyPatch, kind: str, row_finish: str, expected: tuple) -> None:
    calls: list[str] = []
    once = crash_after_rename(root, kind, calls)
    monkeypatch.setattr(tally, row_finish, crash_before_row)
    with pytest.raises(RuntimeError, match="before row update"):
        once()
    monkeypatch.undo()
    try:
        seen = once()
    except EffectFailed as failed:
        seen = failed.error
    assert (len(calls), seen) == expected, kind


def test_crash_after_rename_before_row_update(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    key = effect_key("send", 0)
    table = [
        ("derivation", "mark_done", (2, (["make"], "made"))),
        ("effect ok", "_finish_row", (1, ([], "sent"))),
        ("effect err", "_finish_row", (1, "declined")),
    ]
    for kind, row_finish, expected in table:
        check_crash_after_rename(tmp_path / kind, monkeypatch, kind, row_finish, expected)
    assert (tmp_path / "effect ok" / "effects" / key / "effect.json").is_file()


def check_open(root: Path, setup: Callable[[sqlite3.Connection], None] | None, error: str | None) -> None:
    root.mkdir()
    if setup is not None:
        db = sqlite3.connect(root / "meta.sqlite")
        setup(db)
        db.commit()
        db.close()
    if error is None:
        open_store(root)
        open_store(root)
        return
    with pytest.raises(StoreError, match=error):
        open_store(root)


def test_open_store_checks_schema_version(tmp_path: Path) -> None:
    table = [
        ("fresh", None, None),
        ("no version", lambda db: db.execute("create table derivations (key text primary key)"), "no schema version"),
        ("wrong version", lambda db: db.executescript("create table schema (version integer); insert into schema values (0);"),
         "schema version 0"),
    ]
    for name, setup, error in table:
        check_open(tmp_path / name, setup, error)
