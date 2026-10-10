"""Chapter 1 through the core: case generator, cache-key stability, regrade without re-run, blocked imports, and the
self-tests (planted bugs + cheats must FAIL for their stated reason) in both the spawn and the warm-process modes."""

from __future__ import annotations

import itertools
import math
import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest
import torch
from conftest import ASSAY, run_checks

from assay import core
from assay.ch01 import ops
from assay.ch01 import run as ch01_run
from assay.ch01.run import Candidate, Ctx, detect_env, execute

FIXTURE = ASSAY / "assay" / "ch01" / "fixture"
HONEST = ASSAY / "assay" / "ch01" / "selftest" / "candidates.py"


# ---- case generator ----------------------------------------------------------------------------------------------


def check_pairwise(axes: list[tuple]) -> None:
    rows = ops._pairwise_with_corners(axes)
    for a, b in itertools.combinations(range(len(axes)), 2):
        seen = {(row[a], row[b]) for row in rows}
        assert seen == set(itertools.product(range(len(axes[a])), range(len(axes[b])))), (a, b)
    assert tuple(0 for _ in axes) in rows and tuple(len(axis) - 1 for axis in axes) in rows
    if len(axes) >= 3:
        assert len(rows) < math.prod(len(axis) for axis in axes)


def test_pairwise_covers_every_pair() -> None:
    check_pairwise([(1, 2, 3), (1, 2, 3)])
    check_pairwise([(1, 2, 3, 4, 5), (1, 2, 3, 4, 5), (0, 1)])
    check_pairwise([(1, 2, 12), (1, 2, 7, 16, 17, 64), (1, 8, 64), ("a", "b")])


def test_sweep_is_reproducible_and_covers_edges() -> None:
    first, again = ops.sweep(ops.causal_attention), ops.sweep(ops.causal_attention)
    assert [(c.label(), c.seed) for c in first] == [(c.label(), c.seed) for c in again]
    for dim, sizes in ops.causal_attention.sweep.dims.items():
        assert {dict(c.sizes)[dim] for c in first} == set(sizes), dim
    a, b = ops.make_inputs(ops.causal_attention, first[3]), ops.make_inputs(ops.causal_attention, first[3])
    assert all(torch.equal(x, y) for x, y in zip(a, b, strict=True))


# ---- cache keys + regrade (in process, spawned children) ----------------------------------------------------------


@pytest.fixture
def ctx(tmp_path: Path) -> Ctx:
    return Ctx(core.Store(tmp_path / "store"), detect_env(), core.isolation(), lambda text: None)


def test_run_keys_are_stable_and_move_with_code_case_and_env(ctx: Ctx, monkeypatch: pytest.MonkeyPatch) -> None:
    op = ops.layer_norm
    cases = ops.sweep(op)[:3]
    cand = Candidate(HONEST, "layer_norm", "plain")
    first = execute(ctx, op, cand, cases)
    assert first.executed and all(run is not None for _, run in first.runs)
    second = execute(ctx, op, cand, cases)
    assert not second.executed, "same inputs: every run comes from the store, no child"
    assert [r.key for _, r in first.runs] == [r.key for _, r in second.runs]

    other_case = execute(ctx, op, cand, ops.sweep(op)[3:4], grade_only=False)
    assert other_case.runs[0][1].key not in {r.key for _, r in first.runs}

    monkeypatch.setattr(ch01_run, "reference_fp", lambda op: "edited-reference-code")
    with pytest.raises(ch01_run.InfraError, match="missing from the store"):
        execute(ctx, op, cand, cases, grade_only=True)  # new reference code -> new expected -> new run keys
    monkeypatch.undo()

    moved = Ctx(ctx.store, {**ctx.env, "torch": "9.9.9"}, ctx.iso, ctx.log)
    with pytest.raises(ch01_run.InfraError, match="missing from the store"):
        execute(moved, op, cand, cases, grade_only=True)  # another env (versions, chip) is another key


def test_regrade_without_rerun(tmp_path: Path) -> None:
    store = tmp_path / "store"
    code, lines = run_checks(["ch01", "--op", "layer_norm"], FIXTURE, store)
    assert code == 0, [line for line in lines if line["kind"] != "verdict"]
    before = {(v["case"], v["dtype"]): v for v in lines if v["kind"] == "verdict"}
    # a different grader config (non-blocking) regrades the stored runs; --grade-only proves nothing re-ran
    code, lines = run_checks(["ch01", "--op", "layer_norm", "--warn", "layer_norm", "--grade-only"], FIXTURE, store)
    assert code == 0, lines
    after = {(v["case"], v["dtype"]): v for v in lines if v["kind"] == "verdict"}
    assert after.keys() == before.keys()
    assert all(after[k]["run"] == before[k]["run"] for k in before), "same runs"
    assert all(after[k]["grade"] != before[k]["grade"] for k in before), "new grades"
    assert not any("isolated child" in line.get("text", "") for line in lines), "nothing executed"


# ---- blocked ---------------------------------------------------------------------------------------------------------


def test_import_failure_is_blocked_with_file_line_region(tmp_path: Path) -> None:
    tree = tmp_path / "tree"
    shutil.copytree(FIXTURE, tree)
    src = (tree / "gpt2.py").read_text()
    (tree / "gpt2.py").write_text(src.replace("    return x @ weight + bias", "    return x @ weight +"))
    code, lines = run_checks(["ch01", "--op", "causal_attention"], tree, tmp_path / "store")
    blocked = [v for v in lines if v["kind"] == "verdict" and v["outcome"] == "blocked"]
    assert code == 1 and blocked, lines
    where = blocked[0]["where"]
    assert where["file"] == "gpt2.py" and where["region"] == "linear", where
    assert src.splitlines()[where["line"] - 1].strip() == "return x @ weight + bias"
    assert lines[-1]["outcome"] == "blocked"


def test_missing_function_is_blocked(tmp_path: Path) -> None:
    tree = tmp_path / "tree"
    tree.mkdir()
    (tree / "gpt2.py").write_text("import torch\n")
    code, lines = run_checks(["ch01", "--op", "gelu"], tree, tmp_path / "store")
    blocked = next(v for v in lines if v["kind"] == "verdict" and v["outcome"] == "blocked")
    assert code == 1 and "defines no `gelu`" in blocked["notes"]


# ---- self-tests, both isolation paths --------------------------------------------------------------------------------


@pytest.fixture
def warm() -> Iterator[None]:
    yield
    core.stop_warm()


def selftest_ok(lines: list[dict]) -> None:
    tests = [line for line in lines if line["kind"] == "selftest"]
    missed = [t for t in tests if not t["ok"]]
    assert tests and not missed, missed
    assert lines[-1]["outcome"] == "pass"


def test_layer_norm_selftest_spawned(tmp_path: Path) -> None:
    code, lines = run_checks(["ch01", "--selftest", "--op", "layer_norm"], FIXTURE, tmp_path / "store")
    assert code == 0
    selftest_ok(lines)


def test_layer_norm_selftest_forked_from_the_warm_process(tmp_path: Path, warm: None) -> None:
    code, lines = run_checks(["ch01", "--selftest", "--op", "layer_norm"], FIXTURE, tmp_path / "store", spawn=False)
    assert code == 0
    assert any("forked from the warm process" in line.get("text", "") for line in lines)
    selftest_ok(lines)


@pytest.mark.slow
def test_full_selftest_including_model_level(tmp_path: Path, warm: None) -> None:
    code, lines = run_checks(["ch01", "--selftest"], FIXTURE, tmp_path / "store", spawn=False)
    assert code == 0
    selftest_ok(lines)
    names = {t["candidate"] for t in lines if t["kind"] == "selftest"}
    assert any("c_gelu_exact" in n for n in names), "model-level mutants ran"
