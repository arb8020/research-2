from __future__ import annotations

import shutil
from pathlib import Path

from conftest import BLOGS, run_checks

from assay.core import Store

FILES = BLOGS / "engine" / "ref" / "ch00" / "files"


def toy_tree(tmp_path: Path) -> Path:
    tree = tmp_path / "tree"
    shutil.copytree(FILES, tree, ignore=shutil.ignore_patterns("build"))
    return tree


def test_toy_passes_through_the_core_and_caches(tmp_path: Path) -> None:
    tree, store = toy_tree(tmp_path), tmp_path / "store"
    code, lines = run_checks(["ch00"], tree, store, shim=tree / "run_checks")
    verdicts = [v for v in lines if v["kind"] == "verdict"]
    assert code == 0, lines
    assert [(v["op"], v["outcome"]) for v in verdicts] == [("ring", "pass"), ("loop", "pass"), ("budget", "pass")]
    summary = lines[-1]
    assert summary["kind"] == "summary" and summary["outcome"] == "pass"
    loop = Store(store).get("grade", verdicts[1]["grade"])
    assert loop is not None and "trace.diff" in loop.meta["files"], "the trace check creates its diff"
    code, again = run_checks(["ch00", "loop"], tree, store, shim=tree / "run_checks")
    assert code == 0
    assert any("cached run" in line.get("text", "") for line in again), "an unchanged cell is a cache hit"


def test_wrong_scheduler_fails_with_the_trace_line(tmp_path: Path) -> None:
    tree, store = toy_tree(tmp_path), tmp_path / "store"
    loop = tree / "loop.cpp"
    loop.write_text(loop.read_text().replace("r->prompt_len : 1;", "r->prompt_len : 2;"))
    code, lines = run_checks(["ch00", "--op", "loop"], tree, store, shim=tree / "run_checks")
    verdict = next(v for v in lines if v["kind"] == "verdict")
    assert code == 1
    assert verdict["outcome"] == "fail" and "sched.trace:" in verdict["notes"], verdict
    assert verdict["where"]["file"] == "sched.trace" and verdict["where"]["line"] > 1
    graded = Store(store).get("grade", verdict["grade"])
    trace_row = next(r for r in graded.meta["checks"] if r["check"] == "trace")
    assert trace_row["outcome"] == "fail" and "expected `step" in trace_row["notes"]
    assert graded.read("trace.diff").startswith(b"--- sched.trace")


def test_compile_error_points_at_the_cell_file(tmp_path: Path) -> None:
    tree, store = toy_tree(tmp_path), tmp_path / "store"
    (tree / "ring.cpp").write_text((tree / "ring.cpp").read_text().replace("r->head = 0;", "r->head = 0"))
    code, lines = run_checks(["ch00", "ring"], tree, store, shim=tree / "run_checks")
    verdict = next(v for v in lines if v["kind"] == "verdict")
    assert code == 1 and verdict["notes"].startswith("build: the build exited")
    assert verdict["where"]["file"] == "ring.cpp" and isinstance(verdict["where"]["line"], int)
