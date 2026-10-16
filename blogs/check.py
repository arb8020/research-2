"""Run a chapter's checks against its hidden solutions (or the reader stubs).

    uv run check.py rl/01-flappy.md              # every cell, in file order
    uv run check.py rl/01-flappy.md sample       # one cell
    uv run check.py rl/01-flappy.md sample --stub
    uv run check.py rl/01-flappy.md flappy --build prod    # check=flappy without asserts/sanitizers

A chapter is one Markdown file. Fenced blocks carry their role in the info string:

    ```python given          shared code every cell sees (wrappers, helpers)
    ```python cell=X         what the reader starts with
    ```python solution=X     hidden reference
    ```python check=X        plain asserts; passing = no exception
    ```python budget=X       speed/memory asserts, run against prod builds (optional)

A c cell/solution is a whole PufferLib env header. Instead of executing it, the runner compiles
it with shim.c against vendor/pufferlib and puts the library path in ENV_SO[X] for the Python that
follows. There are two builds (BUILDS):

    check  asserts on, ASan + UBSan, -Wall -Wextra -Werror on the reader's code (vendor headers are -isystem)
    prod   -O2 -DNDEBUG, asserts stripped: budgets, training and the wasm play widget use this

Checking cell X runs, in a fresh Python subprocess and one namespace: given blocks, the solutions of
every cell before X, then X (solution, or stub with --stub), then check=X. If X is a C cell, ENV_SO[X]
is its check build and the subprocess has the sanitizer runtime preloaded (sanitizer_env). Then
budget=X, if any, runs the same steps in a second, clean subprocess where every ENV_SO is a prod
build: ASan's interceptors slow down even uninstrumented code (the memsets in vec_step), so timing
and peak memory only mean something without them. C cells before X are always prod builds.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import signal
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import traceback
import urllib.request
from collections.abc import Callable
from dataclasses import asdict, dataclass
from functools import cache
from pathlib import Path

FENCE = re.compile(r"^```(\w+)[ \t]+([^\n]*)\n(.*?)^```[ \t]*$", re.MULTILINE | re.DOTALL)
ROLES = ("given", "cell", "solution", "check", "budget")
HIDDEN = ("solution", "check", "budget")  # never on the reader's page
HERE = Path(__file__).resolve().parent
PUFFER = HERE / "vendor" / "pufferlib"
LINUX = platform.system() == "Linux"
RAYLIB = HERE / "vendor" / ("raylib-5.5_linux_amd64" if LINUX else "raylib-5.5_macos")
# Upstream PufferLib 5.0 build.sh CLANG_WARN, plus -Wno-unused-function (pufferenv.h's puf_web_vsync stub).
WARN = [
    "-Wall", "-Wno-narrowing", "-Wno-unreachable-code", "-Wno-unused-function",
    "-Werror=incompatible-pointer-types", "-Werror=return-type",
    "-Wno-incompatible-pointer-types-discards-qualifiers",
]  # fmt: skip
# macOS's assert(e) puts e in parentheses, which hides `assert(a = b)` from -Wparentheses. glibc's
# assert doesn't, so Linux already warns; include/assert.h redefines macOS's the glibc way.
ASSERT_SHIM = [] if LINUX else ["-isystem", str(HERE / "include")]
BUILDS = {
    # Upstream's --debug is -O0 -g + these sanitizers; -O1 is ASan's recommended level and keeps codegen
    # closer to prod, with the same reports. -fno-sanitize-recover: UBSan stops instead of printing and
    # passing. -Wextra/-Werror reach only the reader's header and shim.c, since vendor dirs are -isystem.
    # -Wno-unused-parameter is puffer's convention (SKILL_ISSUES.md), e.g. puf_close(Env* env).
    "check": [
        "-O1", "-g", "-fno-omit-frame-pointer",
        "-fsanitize=address,undefined,bounds,pointer-overflow", "-fno-sanitize-recover=all",
        *(["-shared-libasan"] if LINUX else []),
        *WARN, "-Wextra", "-Werror", "-Wno-unused-parameter", *ASSERT_SHIM,
    ],
    # Differs from upstream (which keeps asserts in prod) on purpose: asserts are a testing tool.
    "prod": ["-O2", "-DNDEBUG", *WARN],
}  # fmt: skip
SANITIZER_EXIT = 86


@dataclass
class Block:
    lang: str
    role: str
    name: str
    source: str
    line: int
    file: str = ""  # file=<path>: a workspace cell or given view (build_page.py), not run by this file


@dataclass(frozen=True)
class Result:
    """A cell's verdict: the full story went to emit; message is one short line for a status bar."""

    passed: bool
    message: str


PASSED = Result(True, "passed")


def one_line(text: str, limit: int = 160) -> str:
    first = text.strip().splitlines()[0] if text.strip() else ""
    return first if len(first) <= limit else first[: limit - 1] + "…"


def parse(text: str) -> list[Block]:
    blocks = []
    for m in FENCE.finditer(text):
        lang, info, source = m.group(1), m.group(2).split(), m.group(3)
        line = text.count("\n", 0, m.start()) + 1
        role, name, file = "", "", ""
        for item in info:
            key, _, value = item.partition("=")
            if key in ROLES:
                assert not role, f"line {line}: block has two roles: {info}"
                role, name = key, value
            elif key == "file":
                file = value
        if role:
            blocks.append(Block(lang, role, name, source, line, file))
    return blocks


def fetch_raylib() -> None:
    if RAYLIB.exists():
        return
    url = f"https://github.com/raysan5/raylib/releases/download/5.5/{RAYLIB.name}.tar.gz"
    print(f"fetching {url}", file=sys.stderr)
    with tempfile.TemporaryDirectory(dir=RAYLIB.parent) as tmp:
        archive = Path(tmp) / "raylib.tar.gz"
        urllib.request.urlretrieve(url, archive)
        with tarfile.open(archive) as tar:
            tar.extractall(tmp, filter="data")
        (Path(tmp) / RAYLIB.name).rename(RAYLIB)


def compile_c(block: Block, out: Path, build: str = "prod") -> tuple[str, str]:
    """PufferLib env header -> shared library via shim.c. Returns (path, "") or ("", errors)."""
    fetch_raylib()
    header, so = out / f"{block.name}.h", out / f"_{block.name}_{block.role}_{build}.so"
    header.write_text(f'#line 1 "{block.role}={block.name}"\n' + block.source)
    lib = RAYLIB / "lib"
    if LINUX:
        link = [str(lib / "libraylib.a"), "-lm", "-lpthread", "-ldl"]
    else:
        link = [f"-L{lib}", "-lraylib", f"-Wl,-rpath,{lib}", "-lm"]
    cmd = [
        "clang", "-shared", "-fPIC", *BUILDS[build], "-DPLATFORM_DESKTOP", "-DPRECISION_FLOAT",
        f'-DENV_HEADER="{header}"', "-isystem", str(PUFFER), "-isystem", str(RAYLIB / "include"),
        str(HERE / "shim.c"), "-o", str(so), *link,
    ]  # fmt: skip
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        return "", proc.stderr
    return str(so), ""


@cache
def sanitizer_env() -> dict[str, str]:
    """Env vars for a Python that dlopens a check build: the ASan runtime must load before anything else.

    macOS: DYLD_INSERT_LIBRARIES. SIP strips it when exec'ing /usr/bin binaries (env, system python),
    so start the interpreter directly; uv's python isn't SIP-protected.
    Linux: the .so links the shared runtime (-shared-libasan) and Python gets it via LD_PRELOAD.
    """
    # Linux: older clangs name it per arch; newer ones (per-target runtime dirs) don't.
    if LINUX:
        names = [f"libclang_rt.asan-{platform.machine()}.so", "libclang_rt.asan.so"]
    else:
        names = ["libclang_rt.asan_osx_dynamic.dylib"]
    found = [subprocess.run(["clang", f"-print-file-name={n}"], capture_output=True, text=True, check=True) for n in names]
    path = next((f.stdout.strip() for f in found if Path(f.stdout.strip()).is_file()), "")
    assert path, f"clang has no ASan runtime; looked for {names}"
    # detect_leaks=0: CPython doesn't free everything at exit. exitcode: tells a report from a check FAIL.
    # print_legend, dump_registers: shorter reports for the reader.
    opts = f"halt_on_error=1:abort_on_error=0:detect_leaks=0:exitcode={SANITIZER_EXIT}"
    opts += ":print_legend=0:dump_registers=0"
    return {
        "LD_PRELOAD" if LINUX else "DYLD_INSERT_LIBRARIES": path,
        "ASAN_OPTIONS": opts,
        "UBSAN_OPTIONS": f"{opts}:print_stacktrace=1",
    }


def cell_order(blocks: list[Block]) -> list[str]:
    order = [b.name for b in blocks if b.role == "cell"]
    assert len(order) == len(set(order)), f"duplicate cell names: {order}"
    for b in blocks:
        if b.role in HIDDEN:
            assert b.name in order, f"line {b.line}: {b.role}={b.name} has no cell={b.name}"
    return order


def find(blocks: list[Block], role: str, name: str) -> Block:
    found = [b for b in blocks if b.role == role and b.name == name]
    assert len(found) == 1, f"expected one {role}={name}, found {len(found)}"
    return found[0]


def echo(text: str) -> None:
    print(text, end="", flush=True)


def run_cell(
    blocks: list[Block], order: list[str], target: str, stub: bool,
    emit: Callable[[str], None] = echo, timeout: float | None = None, build: str = "check",
) -> Result:  # fmt: skip
    """Check cell X: compile the C, then run check=X and budget=X, each in a fresh subprocess.

    build="prod" gives check=X the prod build too (no asserts, no sanitizers): for seeing what they catch.
    Build products and job files live in a temporary directory that is gone when this returns.
    """
    steps = [b for b in blocks if b.role == "given"]
    steps += [find(blocks, "solution", name) for name in order[: order.index(target)]]
    steps.append(find(blocks, "cell" if stub else "solution", target))
    budgets = [b for b in blocks if b.role == "budget" and b.name == target]
    assert len(budgets) <= 1, f"more than one budget={target}"

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        prod: dict[str, str] = {}
        check_so = ""
        for b in steps:
            if b.lang != "c":
                continue
            if b is steps[-1] and build == "check":
                check_so, errors = compile_c(b, out, "check")
                if errors:
                    why = f"{b.role}={b.name} does not compile (warnings count as errors)"
                    emit(f"{target:<12} FAIL: {why}:\n{errors}")
                    return Result(False, why)
            prod[b.name], errors = compile_c(b, out, "prod")
            if errors:
                why = f"{b.role}={b.name} does not compile (prod build)"
                emit(f"{target:<12} FAIL: {why}:\n{errors}")
                return Result(False, why)

        python = [b for b in steps if b.lang != "c"]
        check = python + [find(blocks, "check", target)]
        phases = [(target, check, {**prod, target: check_so}, sanitizer_env()) if check_so else (target, check, prod, {})]
        phases += [(f"{target} budget", python + budgets, prod, {}) for _ in budgets]
        for label, ps, env_so, env in phases:
            result = run_phase(label, ps, env_so, env, out, emit, timeout)
            if not result.passed:
                return result if label == target else Result(False, f"{label.removeprefix(target).strip()}: {result.message}")
        return PASSED


def run_phase(
    label: str, steps: list[Block], env_so: dict[str, str], env: dict[str, str], out: Path,
    emit: Callable[[str], None], timeout: float | None,
) -> Result:  # fmt: skip
    """One subprocess execs steps into one namespace. A crash or hang ends only that process."""
    job = out / f"job_{label.replace(' ', '_')}.json"
    verdict = job.with_suffix(".verdict")  # the worker writes its one-line FAIL reason here
    job.write_text(json.dumps({"label": label, "steps": [asdict(b) for b in steps], "env_so": env_so}))
    proc = subprocess.Popen(
        [sys.executable, "-u", __file__, "--worker", str(job)], cwd=HERE, env={**os.environ, **env},
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )  # fmt: skip
    timer = threading.Timer(timeout, proc.kill) if timeout else None
    if timer:
        timer.start()
    for line in proc.stdout:
        emit(line)
    if timer:
        timer.cancel()
    rc = proc.wait()
    if rc == 0:
        return PASSED
    if rc == SANITIZER_EXIT and env:
        why = "the sanitizer stopped your C at a memory or undefined-behaviour bug"
        emit(f"{label:<12} FAIL: {why}; its report is above (look for the frames in cell=...)\n")
    elif rc == -signal.SIGKILL and timeout:
        why = f"killed after {timeout:.0f}s: an infinite loop, or just too slow?"
        emit(f"{label:<12} FAIL: {why}\n")
    elif rc == -signal.SIGABRT:
        why = "your code aborted (SIGABRT), e.g. a failed assert"
        emit(f"{label:<12} FAIL: {why}; a failed assert prints its condition and line above\n")
    elif rc < 0:
        why = f"your code crashed the process: {signal.Signals(-rc).name}"
        emit(f"{label:<12} FAIL: {why}\n")
    else:
        why = verdict.read_text() if verdict.exists() else f"the check process exited with code {rc}"
    return Result(False, why)


def worker(job_path: str) -> None:
    """Subprocess side of run_phase: exec each block into one namespace; exit 0 iff all pass."""
    job = json.loads(Path(job_path).read_text())
    label = job["label"]
    ns: dict = {"__name__": f"chapter.{label.split()[0]}", "ENV_SO": job["env_so"]}
    start = time.perf_counter()
    for b in (Block(**b) for b in job["steps"]):
        try:
            exec(compile(b.source, f"<{b.role}={b.name or 'given'} line {b.line}>", "exec"), ns)
        except Exception as e:  # noqa: BLE001 - any failure in reader-facing code is a FAIL, reported verbatim
            what = "FAIL" if b.role in ("check", "budget") else f"ERROR in {b.role}={b.name or 'given'}"
            print(f"{label:<12} {what}: {type(e).__name__}: {e}")
            Path(job_path).with_suffix(".verdict").write_text(one_line(f"{what}: {type(e).__name__}: {e}"))
            if not isinstance(e, AssertionError):
                traceback.print_exc(limit=-3)
            sys.exit(1)
    print(f"{label:<12} PASS ({time.perf_counter() - start:.2f}s)")
    sys.exit(0)


def main() -> None:
    if sys.argv[1:2] == ["--worker"]:
        worker(sys.argv[2])
    ap = argparse.ArgumentParser()
    ap.add_argument("chapter", type=Path)
    ap.add_argument("cell", nargs="?")
    ap.add_argument("--stub", action="store_true", help="run checks against the reader stubs instead of solutions")
    ap.add_argument("--build", choices=BUILDS, default="check", help="the build check=X sees (budget=X is always prod)")
    args = ap.parse_args()

    blocks = parse(args.chapter.read_text())
    assert not any(b.file for b in blocks), f"{args.chapter} is a workspace chapter (file= cells): its checks run in the workspace (run_checks)"
    order = cell_order(blocks)
    targets = [args.cell] if args.cell else order
    for t in targets:
        assert t in order, f"no cell={t}; cells are {order}"

    results = [run_cell(blocks, order, t, args.stub, build=args.build) for t in targets]
    sys.exit(0 if all(r.passed for r in results) else 1)


if __name__ == "__main__":
    main()
