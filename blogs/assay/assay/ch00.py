from __future__ import annotations

import difflib
import hashlib
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from assay.core import (
    Check,
    Entry,
    Grader,
    Isolation,
    Result,
    Store,
    child_env,
    failed,
    files_fp,
    grade,
    key_of,
    passed,
    run_cmd,
    verdict,
)

STEP_TIMEOUT_S = 60.0
KEEP_OUTPUT_CHARS = 20000


@dataclass(frozen=True)
class Cell:
    file: str
    inputs: tuple[str, ...]
    steps: tuple[tuple[str, ...], ...]
    creates: tuple[str, ...] = ()


CELLS = {
    "ring": Cell("ring.cpp", ("Makefile", "core.h", "ring.h", "ring.cpp", "check_ring.cpp"),
                 (("make", "-s", "OUT={out}", "{out}/check_ring"), ("{out}/check_ring",))),
    "loop": Cell("loop.cpp", ("Makefile", "core.h", "ring.h", "ring.cpp", "loop.h", "loop.cpp", "check_trace.cpp",
                              "sched.trace"),
                 (("make", "-s", "OUT={out}", "{out}/check_trace"),
                  ("{out}/check_trace", "sched.trace", "{scratch}/got.trace")), creates=("got.trace",)),
    "budget": Cell("budget.py", ("budget.py", "test_budget.py"), (("{python}", "test_budget.py"),)),
}
FILE_LINE = re.compile(r"([\w./-]+\.(?:cpp|h|py|trace)):(\d+)")


def toolchain() -> dict[str, str]:
    def first_line(argv: list[str]) -> str:
        try:
            out = subprocess.run(argv, capture_output=True, text=True, check=False, timeout=10)
        except (OSError, subprocess.TimeoutExpired):
            return "absent"
        return (out.stdout or out.stderr).splitlines()[0] if (out.stdout or out.stderr) else "?"

    return {"cxx": first_line(["g++", "--version"]), "make": first_line(["make", "--version"]),
            "python": platform.python_version(), "machine": f"{platform.system()} {platform.machine()}"}


def build_dir(tree: Path, iso: Isolation) -> str:
    tag = hashlib.sha256(f"{tree.resolve()}|{iso.uid}".encode()).hexdigest()[:12]
    path = Path(tempfile.gettempdir()) / f"assay-ch00-build-{tag}"
    path.mkdir(exist_ok=True)
    if iso.mode == "unprivileged":
        os.chown(path, iso.uid, iso.gid)
    return str(path)


def execute(store: Store, cell_name: str, tree: Path, iso: Isolation, env: dict[str, str],
            log: Callable[[str], None]) -> Entry:
    cell = CELLS[cell_name]
    missing = [f for f in cell.inputs if not (tree / f).is_file()]
    if missing:
        raise FileNotFoundError(f"{cell_name}: the tree has no {missing}")
    parts = {"chapter": "ch00", "cell": cell_name, "inputs": files_fp([tree / f for f in cell.inputs], tree),
             "env": env, "runner": files_fp([Path(__file__), Path(__file__).with_name("core.py")],
                                            Path(__file__).parent)}
    found = store.get("run", key_of(parts))
    if found is not None:
        log(f"{cell_name}: unchanged since its last check (cached run {found.key[:12]}); its output:")
        for line in found.read("output.txt").decode(errors="replace").splitlines()[-200:]:
            log(line)
        return found
    scratch = iso.scratch("assay-ch00-")
    try:
        fill = {"{python}": sys.executable, "{out}": build_dir(tree, iso), "{scratch}": str(scratch)}
        steps, output = [], []
        for step in cell.steps:
            argv = [fill.get(a, a) for a in step]
            argv = [a.replace("{out}", fill["{out}"]).replace("{scratch}", fill["{scratch}"]) for a in argv]
            log(f"{cell_name}: {' '.join(argv).replace(str(scratch), '$SCRATCH')}")
            res = run_cmd(argv, cwd=tree, iso=iso, env=child_env(scratch), timeout=STEP_TIMEOUT_S,
                          on_line=lambda line: log(line))
            output.append(res.output)
            steps.append({"argv": list(step), "rc": res.rc, "seconds": round(res.seconds, 3),
                          "truncated": res.truncated, "output": res.output[-KEEP_OUTPUT_CHARS:]})
            if res.rc != 0:
                break
        files = {"output.txt": "\n".join(output).encode()}
        for name in cell.creates:
            if (scratch / name).is_file():
                files[name] = (scratch / name).read_bytes()
        if "sched.trace" in cell.inputs:
            files["expected.trace"] = (tree / "sched.trace").read_bytes()
        no_step_timed_out = all(s["rc"] is not None for s in steps)
        meta = {"parts": parts, "facts": {"steps": steps, "cell": cell_name, "file": cell.file},
                "summary": f"ch00 {cell_name}: rc {[s['rc'] for s in steps]}"}
        if no_step_timed_out:
            return store.put("run", key_of(parts), meta, files)
        return Entry("run", key_of(parts), None, {**meta, "files": {}})
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def _step(run: Entry, index: int) -> dict[str, Any] | None:
    steps = run.meta["facts"]["steps"]
    return steps[index] if index < len(steps) else None


def _step_result(step: dict[str, Any] | None, what: str) -> Result:
    if step is None:
        return failed(f"{what} never ran")
    if step["rc"] is None:
        return failed(f"{what} timed out after {STEP_TIMEOUT_S:g}s (an infinite loop?)")
    if step["rc"] != 0:
        lines = [ln for ln in step["output"].splitlines() if ln.strip()]
        key = next((ln for ln in lines if FILE_LINE.search(ln)), lines[-1] if lines else "")
        return failed(f"{what} exited {step['rc']}: {key}"[:500], rc=step["rc"])
    return passed(metrics={"seconds": step["seconds"]})


def build(run: Entry, cfg: Mapping[str, Any]) -> Result:
    if len(CELLS[run.meta["facts"]["cell"]].steps) == 1:
        return Result("skip", notes="nothing to build")
    return _step_result(_step(run, 0), "the build")


def ran(run: Entry, cfg: Mapping[str, Any]) -> Result:
    steps = CELLS[run.meta["facts"]["cell"]].steps
    return _step_result(_step(run, len(steps) - 1), "the check")


def trace(run: Entry, cfg: Mapping[str, Any]) -> Result:
    if "got.trace" not in run.meta["files"]:
        return failed("the replay did not create got.trace")
    want = run.read("expected.trace").decode().splitlines()
    got = run.read("got.trace").decode().splitlines()
    diff = "\n".join(difflib.unified_diff(want, got, "sched.trace", "got.trace", lineterm="")).encode()
    for number, (a, b) in enumerate(zip(want, got, strict=False), start=1):
        if a != b:
            return failed(f"sched.trace:{number}: expected `{a}`, got `{b}`", artifacts={"diff": diff})
    if len(got) != len(want):
        return failed(f"sched.trace:{min(len(got), len(want)) + 1}: the replay stopped after {len(got)} of "
                      f"{len(want)} lines", artifacts={"diff": diff})
    return passed(metrics={"lines": len(want)}, artifacts={"diff": diff})


def grader(cell_name: str) -> Grader:
    has_trace = "got.trace" in CELLS[cell_name].creates
    checks = [Check("build", build), Check("run", ran, required=not has_trace)]
    if has_trace:
        checks.append(Check("trace", trace, creates=("diff",)))
    return Grader(f"ch00-{cell_name}", tuple(checks))


def checks(args: Any, store: Store, iso: Isolation, log: Callable[[str], None], warm: Any) -> Iterator[dict]:
    names = args.op or list(CELLS)
    unknown = set(names) - set(CELLS)
    if unknown:
        raise ValueError(f"ch00 has no cell {sorted(unknown)}; its cells are {list(CELLS)}")
    if args.selftest:
        raise ValueError("ch00 has no self-tests (ref.py verify checks that every start stub fails)")
    tree, env = Path.cwd(), toolchain()
    for name in names:
        run = execute(store, name, tree, iso, env, log)
        graded = grade(store, run, grader(name))
        where = _where(graded, CELLS[name].file)
        yield verdict(graded, blocking=True, op=name, case="*", dtype=None, chip=env["machine"], where=where)


def _where(graded: Entry, cell_file: str) -> dict[str, Any] | None:
    bad = next((row for row in graded.meta["checks"] if row["outcome"] == "fail"), None)
    if bad is None:
        return None
    hits = FILE_LINE.findall(bad["notes"])
    hits.sort(key=lambda hit: not hit[0].endswith(cell_file))
    return {"file": Path(hits[0][0]).name, "line": int(hits[0][1])} if hits else {"file": cell_file, "line": None}
