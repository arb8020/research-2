"""The core at its boundaries: store (immutability, interrupted writes, integrity), cache keys, the frame parser (the
trust boundary), grading (order, required halts, skips recorded, creates, unknown keys folded), regrade semantics."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from assay import core
from assay.core import (
    Check,
    Grader,
    ProtocolError,
    Store,
    failed,
    grade,
    key_of,
    parse,
    passed,
    result,
)


def test_same_parts_same_key_and_any_change_changes_it() -> None:
    parts = {"op": "layer_norm", "case": {"rows": 3, "dtype": "fp32"}, "env": {"chip": "cpu", "torch": "2.14"}}
    assert key_of(parts) == key_of(json.loads(json.dumps(parts)))  # stable across a JSON round trip
    assert key_of(parts) == key_of(dict(reversed(list(parts.items()))))  # key order does not matter
    for path, value in (("case.rows", 4), ("case.dtype", "bf16"), ("env.chip", "sm_75"), ("env.torch", "2.15")):
        outer, inner = path.split(".")
        changed = {**parts, outer: {**parts[outer], inner: value}}
        assert key_of(changed) != key_of(parts), f"changing {path} kept the key"


def test_files_fp_tracks_content_and_names(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("x = 1\n")
    before = core.files_fp([tmp_path / "a.py"], tmp_path)
    assert core.files_fp([tmp_path / "a.py"], tmp_path) == before
    (tmp_path / "a.py").write_text("x = 2\n")
    assert core.files_fp([tmp_path / "a.py"], tmp_path) != before


def test_store_entries_are_immutable_and_checked(tmp_path: Path) -> None:
    store = Store(tmp_path / "s")
    first = store.put("run", "ab" * 32, {"facts": 1}, {"out.bin": b"one"})
    again = store.put("run", "ab" * 32, {"facts": 2}, {"out.bin": b"two"})
    assert again.meta["facts"] == 1 and again.read("out.bin") == b"one", "a key is written once"
    (first.path / "out.bin").write_bytes(b"tampered")
    with pytest.raises(core.CorruptEntry):
        first.read("out.bin")


def test_interrupted_write_reads_as_missing(tmp_path: Path) -> None:
    store = Store(tmp_path / "s")
    half = tmp_path / "s" / "run" / "cd" / ("cd" * 32)
    half.mkdir(parents=True)
    (half / "out.bin").write_bytes(b"partial")  # no meta.json: the writer died
    assert store.get("run", "cd" * 32) is None
    assert store.put("run", "cd" * 32, {}, {"out.bin": b"whole"}).read("out.bin") == b"whole"


def test_derive_builds_once(tmp_path: Path) -> None:
    store = Store(tmp_path / "s")
    calls = []

    def build() -> tuple[dict, dict]:
        calls.append(1)
        return {"n": len(calls)}, {}

    a = store.derive("expected", {"x": 1}, build)
    b = store.derive("expected", {"x": 1}, build)
    assert a.key == b.key and len(calls) == 1


# ---- frames ------------------------------------------------------------------------------------------------------


def test_frame_parser_rejects_lies() -> None:
    header, blobs = parse(*_frame({"kind": "returned"}, {"out": b"1234"}))
    assert header == {"kind": "returned"} and blobs == {"out": b"1234"}
    with pytest.raises(ProtocolError, match="not JSON"):
        parse(b"\x80\x04pickle", b"")
    with pytest.raises(ProtocolError, match="string 'kind'"):
        parse(b"[1, 2]", b"")
    good = json.dumps({"kind": "x", "blobs": [{"name": "a", "nbytes": 4}]}).encode()
    with pytest.raises(ProtocolError, match="runs past"):
        parse(good, b"12")
    with pytest.raises(ProtocolError, match="trailing"):
        parse(good, b"12345")
    twice = json.dumps({"kind": "x", "blobs": [{"name": "a", "nbytes": 1}] * 2}).encode()
    with pytest.raises(ProtocolError, match="twice"):
        parse(twice, b"12")
    negative = json.dumps({"kind": "x", "blobs": [{"name": "a", "nbytes": -1}]}).encode()
    with pytest.raises(ProtocolError, match="bad blob spec"):
        parse(negative, b"")


def _frame(header: dict, blobs: dict[str, bytes]) -> tuple[bytes, bytes]:
    data = core.encode(header, blobs)
    _, head_n, _ = core.PREFIX.unpack(data[:core.PREFIX.size])
    return data[core.PREFIX.size:core.PREFIX.size + head_n], data[core.PREFIX.size + head_n:]


# ---- grading -------------------------------------------------------------------------------------------------------


def _run(store: Store, facts: dict) -> core.Entry:
    return store.put("run", key_of(facts), {"facts": facts}, {})


def ok_check(run: core.Entry, cfg: dict) -> core.Result:
    return passed(metrics={"x": run.meta["facts"]["x"]})


def threshold(run: core.Entry, cfg: dict) -> core.Result:
    x = run.meta["facts"]["x"]
    return passed() if x <= cfg["limit"] else failed(f"x {x} > {cfg['limit']}")


def loose(run: core.Entry, cfg: dict) -> core.Result:
    return result(outcome="pass", surprise=42)  # unknown keys fold into details


def no_artifact(run: core.Entry, cfg: dict) -> core.Result:
    return passed()


def test_required_failure_halts_and_skips_are_recorded(tmp_path: Path) -> None:
    store = Store(tmp_path / "s")
    run = _run(store, {"x": 5})
    grader = Grader("g", (Check("first", ok_check), Check("limit", threshold), Check("after", ok_check)),
                    {"limit": 3})
    graded = grade(store, run, grader)
    rows = {row["check"]: row for row in graded.meta["checks"]}
    assert graded.meta["outcome"] == "fail"
    assert rows["limit"]["notes"] == "x 5 > 3"
    assert rows["after"]["outcome"] == "skip" and "limit" in rows["after"]["notes"]
    assert graded.meta["grader"]["config"] == {"limit": 3}, "the grader snapshot is stored with the grade"


def test_unknown_keys_fold_into_details_and_creates_is_enforced(tmp_path: Path) -> None:
    store = Store(tmp_path / "s")
    run = _run(store, {"x": 1})
    graded = grade(store, run, Grader("g", (Check("loose", loose), Check("art", no_artifact, creates=("diff",)))))
    rows = {row["check"]: row for row in graded.meta["checks"]}
    assert rows["loose"]["details"] == {"surprise": 42}
    assert rows["art"]["outcome"] == "fail" and "promised ['diff']" in rows["art"]["notes"]


def test_regrade_with_new_config_reuses_the_run(tmp_path: Path) -> None:
    store = Store(tmp_path / "s")
    run = _run(store, {"x": 5})
    strict = grade(store, run, Grader("g", (Check("limit", threshold),), {"limit": 3}))
    lenient = grade(store, run, Grader("g", (Check("limit", threshold),), {"limit": 10}))
    assert strict.meta["outcome"] == "fail" and lenient.meta["outcome"] == "pass"
    assert strict.meta["run"] == lenient.meta["run"] == run.key
    assert strict.key != lenient.key
    again = grade(store, run, Grader("g", (Check("limit", threshold),), {"limit": 3}))
    assert again.key == strict.key and again.meta["created"] == strict.meta["created"], "same grader: cached"
