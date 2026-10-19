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
from conftest import ASSAY, BLOGS, run_checks

from assay import core
from assay.ch01 import ops
from assay.ch01 import run as ch01_run
from assay.ch01.run import Candidate, Ctx, detect_env, execute

REF = BLOGS / "engine" / "ref" / "ch01" / "files"  # the chapter's solution tree (gpt2.py + checks/)
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
    first, again = ops.sweep(ops.attention), ops.sweep(ops.attention)
    assert [(c.label(), c.seed) for c in first] == [(c.label(), c.seed) for c in again]
    for dim, sizes in ops.attention.sweep.dims.items():
        assert {dict(c.sizes)[dim] for c in first} == set(sizes), dim
    a, b = ops.make_inputs(ops.attention, first[3]), ops.make_inputs(ops.attention, first[3])
    assert all(torch.equal(x, y) for x, y in zip(a, b, strict=True))
    assert a[0].shape == a[1].shape, "S is tied to T: q is [T, N, H], k [S, N, H] with S = T"


def test_frontier_gives_the_exact_allclose_ratio_for_any_tolerance() -> None:
    gen = torch.Generator().manual_seed(0)
    truth = torch.randn(64, 33, generator=gen, dtype=torch.float64) * 10
    truth[0, :5] = 2.5  # ties in |T|
    out = (truth + torch.randn(64, 33, generator=gen, dtype=torch.float64) * 1e-3).float()
    points = ops.frontier(out, truth)
    assert len(points) < truth.numel() // 10, "the frontier is a small summary"
    err, size = (out.double() - truth).abs(), truth.abs()
    for atol, rtol in ((1e-4, 0.0), (0.0, 1e-3), (1.5e-4, 1e-5), (2e-2, 2e-2), (1.0, 1e-9)):
        brute = float((err / (atol + rtol * size)).max())
        assert ops.tolerance_ratio(points, atol, rtol)[0] == pytest.approx(brute, rel=1e-12), (atol, rtol)
    out[3, 4] = float("nan")
    assert ops.tolerance_ratio(ops.frontier(out, truth), 1.0, 1.0)[0] == math.inf
    assert ops.tolerance_ratio([[0.0, "inf"]], 1.0, 1.0)[0] == math.inf, "the store writes inf as a string"


def test_op_inputs_include_offset_cases() -> None:
    for name in ("linear", "gelu", "layer_norm", "attention"):
        cases = ops.sweep(ops.REGISTRY[name])
        offset = [c for c in cases if c.inputs == "offset"]
        assert offset and len(offset) < len(cases), name
        x = ops.make_inputs(ops.REGISTRY[name], offset[0])[0].double()
        assert 2.0 < float(x.mean()) < 4.0 or x.numel() < 4, (name, float(x.mean()))


# ---- cache keys + regrade (in process, spawned children) ----------------------------------------------------------


@pytest.fixture
def ctx(store_dir: Path) -> Ctx:
    return Ctx(core.Store(store_dir), detect_env(), core.isolation(), lambda text: None)


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


def test_regrade_without_rerun(store_dir: Path) -> None:
    store = store_dir
    code, lines = run_checks(["ch01", "--op", "layer_norm"], REF, store)
    assert code == 0, [line for line in lines if line["kind"] != "verdict"]
    before = {(v["case"], v["dtype"]): v for v in lines if v["kind"] == "verdict" and v["outcome"] != "skip"}
    # a different grader config (non-blocking) regrades the stored runs; --grade-only proves nothing re-ran
    code, lines = run_checks(["ch01", "--op", "layer_norm", "--warn", "layer_norm", "--grade-only"], REF, store)
    assert code == 0, lines
    after = {(v["case"], v["dtype"]): v for v in lines if v["kind"] == "verdict" and v["outcome"] != "skip"}
    assert after.keys() == before.keys()
    assert all(after[k]["run"] == before[k]["run"] for k in before), "same runs"
    assert all(after[k]["grade"] != before[k]["grade"] for k in before), "new grades"
    assert not any("isolated child" in line.get("text", "") for line in lines), "nothing executed"


# ---- blocked ---------------------------------------------------------------------------------------------------------


def test_import_failure_is_blocked_with_file_line_region(tmp_path: Path, store_dir: Path) -> None:
    tree = tmp_path / "tree"
    shutil.copytree(REF, tree)
    src = (tree / "gpt2.py").read_text()
    line = '    return einsum(x_TD, w_DF, "T D, D F -> T F") + b_F'
    (tree / "gpt2.py").write_text(src.replace(line, line.removesuffix(" b_F")))
    code, lines = run_checks(["ch01", "--op", "attention"], tree, store_dir)
    blocked = [v for v in lines if v["kind"] == "verdict" and v["outcome"] == "blocked"]
    assert code == 1 and blocked, lines
    where = blocked[0]["where"]
    assert where["file"] == "gpt2.py" and where["region"] == "linear", where
    assert src.splitlines()[where["line"] - 1] == line
    assert lines[-1]["outcome"] == "blocked"


def test_missing_function_is_blocked(tmp_path: Path, store_dir: Path) -> None:
    tree = tmp_path / "tree"
    tree.mkdir()
    (tree / "gpt2.py").write_text("import torch\n")
    code, lines = run_checks(["ch01", "--op", "gelu"], tree, store_dir)
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


def test_layer_norm_selftest_spawned(store_dir: Path) -> None:
    code, lines = run_checks(["ch01", "--selftest", "--op", "layer_norm", "--timeout", "1"], REF, store_dir)
    assert code == 0
    selftest_ok(lines)


def test_layer_norm_selftest_forked_from_the_warm_process(store_dir: Path, warm: None) -> None:
    code, lines = run_checks(["ch01", "--selftest", "--op", "layer_norm", "--timeout", "1"], REF, store_dir,
                             spawn=False)
    assert code == 0
    assert any("forked from the warm process" in line.get("text", "") for line in lines)
    selftest_ok(lines)


@pytest.mark.slow
def test_full_selftest_including_model_level(store_dir: Path, warm: None) -> None:
    code, lines = run_checks(["ch01", "--selftest"], REF, store_dir, spawn=False)
    assert code == 0
    selftest_ok(lines)
    names = {t["candidate"] for t in lines if t["kind"] == "selftest"}
    assert any("c_gelu_exact" in n for n in names), "model-level mutants ran"


def test_a_stub_that_raises_points_at_its_line(tmp_path: Path) -> None:
    """The starter's forward calls the starter's block, a stub: the verdict says so and points at the stub's raise."""
    tree = tmp_path / "tree"
    shutil.copytree(REF, tree)
    start = (REF.parent / "start" / "gpt2.py").read_text()
    solution = (tree / "gpt2.py").read_text()
    stub = start[start.index("# region: block"):start.index("# region: forward")]
    (tree / "gpt2.py").write_text(solution[:solution.index("# region: block")] + stub
                                  + solution[solution.index("# region: forward"):])
    code, lines = run_checks(["ch01", "--op", "forward", "--dtype", "fp32"], tree, tmp_path / "store")
    bad = [v for v in lines if v["kind"] == "verdict" and v["outcome"] == "fail"]
    assert code == 1 and bad, lines
    assert "NotImplementedError: mlp: write this in the block cell" in bad[0]["notes"] or (
        "NotImplementedError: block: write this in the block cell" in bad[0]["notes"]), bad[0]["notes"]
    text = (tree / "gpt2.py").read_text().splitlines()
    assert bad[0]["where"]["region"] == "block" and "raise NotImplementedError" in text[bad[0]["where"]["line"] - 1]
