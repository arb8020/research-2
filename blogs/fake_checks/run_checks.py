"""FAKE run_checks: a stand-in for the trusted check core (being built on another branch) that speaks its contract
(notes/ch01-design-2026-10-09.md, "check command"), so the page and workspace.py can be built and proven against it.
It grades nothing numerically. Replace it by pointing ref.TRUSTED_SRC at the real core.

    python3 run_checks.py <chapter> [--op NAME]... [--dtype D]...     # cwd = the tree being checked

ch01 (any chapter with ops): per requested op (default: every op in checks/<chapter>.json)
  - every Python file a cell names must parse: a SyntaxError -> each op BLOCKED with where {file, line, region}
  - the op's function (OP_FUNCTIONS) must exist and not raise NotImplementedError -> else FAIL
  - otherwise PASS for float32 (a made-up err_ratio), and a visible SKIP for bfloat16 ("chip" cpu can't test it)
  - a file containing the line `# fake: infra` -> exit 2 (an infrastructure error; lets a proof check it never commits)
ch00 (the toy, whose cells have no ops): runs the tree's own legacy `run_checks <chapter> <cell>` and passes its
plain-text output and exit code through (the real core will own the ch00 toy instantiation).

stdout: JSON lines {"kind": "log" | "verdict" | "summary", ...}; exit 0 pass, 1 fail or blocked, 2 infrastructure.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

# op name -> the function in the reader's file that implements it (the real core binds ops through its registry)
OP_FUNCTIONS = {
    "linear": "linear",
    "gelu_tanh": "gelu_tanh",
    "layer_norm": "layer_norm",
    "causal_attention": "causal_attention",
    "gpt2.block": "block",
    "gpt2.forward": "forward",
    "gpt2.generate": "generate",
}
MODEL_OPS = {"gpt2.block", "gpt2.forward", "gpt2.generate"}  # fp32 only, like the harness's model-level checks
REGION = re.compile(r"^\s*# region: (\S+)\s*$")
CHIP = "cpu"


def emit(**line: Any) -> None:
    print(json.dumps(line), flush=True)


def region_of(lines: list[str], lineno: int) -> str | None:
    """The `# region: <name>` block holding line `lineno` (1-based), if any."""
    current = None
    for i, line in enumerate(lines[:lineno], start=1):
        if m := REGION.match(line):
            current = m[1]
        elif line.strip() == "# endregion" and i < lineno:
            current = None
    return current


def stubbed(fn: ast.FunctionDef) -> bool:
    for node in ast.walk(fn):
        if isinstance(node, ast.Raise) and node.exc is not None:
            target = node.exc.func if isinstance(node.exc, ast.Call) else node.exc
            if isinstance(target, ast.Name) and target.id == "NotImplementedError":
                return True
    return False


def legacy(chapter: str, cells: list[dict[str, Any]], wanted: list[str]) -> int:
    """ch00: the tree's own run_checks, one cell (named by --op, or the positional cell name) or all."""
    argv = [sys.executable, "run_checks", chapter, *wanted[:1]]
    return subprocess.run(argv, check=False).returncode


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("chapter")
    ap.add_argument("cell", nargs="?", help="ch00 legacy: one cell name")
    ap.add_argument("--op", action="append", default=[])
    ap.add_argument("--dtype", action="append", default=[])
    args = ap.parse_args()
    tree = Path.cwd()
    manifest = json.loads((tree / "checks" / f"{args.chapter}.json").read_text())
    cells = manifest["cells"]
    if not any(c.get("ops") for c in cells):
        return legacy(args.chapter, cells, [args.cell] if args.cell else [])
    ops = args.op or [o for c in cells for o in c["ops"]]
    dtypes = args.dtype or ["float32", "bfloat16"]
    run = "fake-" + "-".join(ops)
    emit(kind="log", text=f"FAKE run_checks {args.chapter} (a stand-in for the trusted core): ops {', '.join(ops)}")
    files = sorted({c["file"] for c in cells if c["file"].endswith(".py")})
    for f in files:
        text = (tree / f).read_text()
        if "\n# fake: infra\n" in f"\n{text}\n":
            emit(kind="log", text=f"{f} asks for an infrastructure error (# fake: infra)")
            return 2
        try:
            ast.parse(text, filename=f)
        except SyntaxError as e:
            line = e.lineno or 1
            where = {"file": f, "line": line, "region": region_of(text.split("\n"), line)}
            for op in ops:
                emit(kind="verdict", op=op, case="import", dtype="-", chip=CHIP, outcome="blocked", metrics={},
                     notes=f"{f} doesn't import: SyntaxError: {e.msg}", where=where)  # fmt: skip
            emit(kind="summary", outcome="blocked", counts={"blocked": len(ops)}, run=run)
            return 1
    counts = {"pass": 0, "fail": 0, "skip": 0}
    for op in ops:
        fn_name = OP_FUNCTIONS.get(op)
        if fn_name is None:
            emit(kind="log", text=f"unknown op {op!r} (known: {sorted(OP_FUNCTIONS)})")
            return 2
        cell = next(c for c in cells if op in c["ops"])
        source = (tree / cell["file"]).read_text()
        fns = {n.name: n for n in ast.walk(ast.parse(source)) if isinstance(n, ast.FunctionDef)}
        fn = fns.get(fn_name)
        for dtype in dtypes:
            case = "seq=17,d=768" if op not in MODEL_OPS else "prompt=long"
            if dtype != "float32" and op in MODEL_OPS:
                continue
            if dtype == "bfloat16":
                counts["skip"] += 1
                emit(kind="verdict", op=op, case=case, dtype=dtype, chip=CHIP, outcome="skip", metrics={},
                     notes=f"{CHIP} can't honestly test {dtype} (capability table)")  # fmt: skip
                continue
            if fn is None or stubbed(fn):
                counts["fail"] += 1
                why = f"no function {fn_name}() in {cell['file']}" if fn is None else f"{fn_name}() still raises NotImplementedError"
                where = {"file": cell["file"], "line": fn.lineno if fn else 1, "region": cell["region"]}
                emit(kind="verdict", op=op, case=case, dtype=dtype, chip=CHIP, outcome="fail", score=0.0,
                     metrics={"err_ratio": None}, notes=why, where=where)  # fmt: skip
                continue
            counts["pass"] += 1
            emit(kind="verdict", op=op, case=case, dtype=dtype, chip=CHIP, outcome="pass", score=1.0,
                 metrics={"err_ratio": 0.62, "budget": 2.0}, notes="fake: not actually measured")  # fmt: skip
    outcome = "fail" if counts["fail"] else "pass"
    emit(kind="summary", outcome=outcome, counts=counts, run=run)
    return 1 if counts["fail"] else 0


if __name__ == "__main__":
    sys.exit(main())
