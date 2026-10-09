"""Chapter 1 as a check suite: which ops, where the reader's code is, the dtype x chip matrix, and the self-tests.

    run_checks ch01 --op causal_attention       cwd = the tree; its gpt2.py defines `causal_attention`
      for each requested dtype: declared by the op? the chip can test it honestly? else a visible SKIP verdict
      execute (run.py) -> one Run per case (+ coverage) -> grade (grade.py) -> one verdict per case
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from assay.ch01 import grade as graders
from assay.ch01 import model, mutants, specs
from assay.ch01.cases import sweep
from assay.ch01.registry import Op
from assay.ch01.run import Candidate, Ctx, detect_env, execute, where
from assay.ch01.tensors import SHORT
from assay.grading import grade, verdict

FILE = "gpt2.py"
OPS: dict[str, tuple[Op, str]] = {  # op -> (spec, child adapter); the reader's function has the op's name
    "linear": (specs.linear, "plain"), "gelu": (specs.gelu, "plain"), "layer_norm": (specs.layer_norm, "plain"),
    "causal_attention": (specs.causal_attention, "plain"), "forward": (model.forward, "forward")}

# chip -> dtype -> None (checkable) or why it is skipped. Unknown chips: fp32 only.
_ALL = {"fp32": None, "fp16": None, "bf16": None}
CAPABILITY: dict[str, dict[str, str | None]] = {
    "cpu": {"fp32": None, "bf16": None, "fp16": "CPU has no native fp16 math; checked on GPU"},
    "sm_75": {"fp32": None, "fp16": None, "bf16": "sm_75 (T4) has no native bf16: a bf16 check there would test an "
                                                 "emulation, not the kernel"},
    **{f"sm_{n}": _ALL for n in (80, 86, 87, 89, 90, 100, 120)},
}
MODEL_SKIP = {("cpu", "bf16"): "bf16 gpt2 forward on CPU is ~50x slower than fp32 (no fast bf16 GEMM): checked on GPU"}


def skip_reason(chip: str, dtype: str, kind: str) -> str | None:
    table = CAPABILITY.get(chip, {"fp32": None})
    if dtype not in table:
        return f"{chip}: {dtype} not in the capability table"
    return table[dtype] or (MODEL_SKIP.get((chip, dtype)) if kind == "model" else None)


@dataclass(frozen=True)
class Request:
    ops: list[str]
    dtypes: list[str]
    tree: Path
    warn: set[str]
    warn_all: bool
    grade_only: bool
    call_timeout: float


def checks(args: Any, store: Any, iso: Any, log: Callable[[str], None], zygote: Path | None) -> Iterator[dict]:
    """The CLI's entry: verdicts for the requested ops, or self-test records."""
    unknown = set(args.op) - set(OPS)
    if unknown:
        raise ValueError(f"ch01 has no op {sorted(unknown)}; its ops are {list(OPS)}")
    os.environ.setdefault("HF_HOME", str(Path.home() / ".cache" / "huggingface"))  # the child's HOME is scratch
    ctx = Ctx(store, detect_env(), iso, log, call_timeout=args.timeout, zygote=zygote)
    log(f"env: {ctx.env}")
    req = Request(ops=args.op or list(OPS), dtypes=args.dtype, tree=Path.cwd(), warn=set(args.warn),
                  warn_all=args.warn_all, grade_only=args.grade_only, call_timeout=args.timeout)
    if not args.selftest:
        yield from check(ctx, req)
        return
    scratch = Path(tempfile.gettempdir()) / "assay-mutants"  # readable by the child user, unlike the store
    scratch.mkdir(exist_ok=True)
    scratch.chmod(0o755)
    for test in selftests(scratch):
        if not args.op or test.op in args.op:
            yield run_selftest(ctx, test, req)


def check(ctx: Ctx, req: Request, cand_for: Callable[[str], Candidate] | None = None) -> Iterator[dict[str, Any]]:
    for name in req.ops:
        op, adapter = OPS[name]
        cand = cand_for(name) if cand_for else Candidate((req.tree / FILE).resolve(), name, adapter)
        blocking = op.kind == "model" or not (req.warn_all or name in req.warn)
        yield from check_op(ctx, op, cand, req, blocking)


def check_op(ctx: Ctx, op: Op, cand: Candidate, req: Request, blocking: bool) -> Iterator[dict[str, Any]]:
    chip = ctx.env["chip"]
    declared = [SHORT[d] for d in op.sweep.dtypes]
    runnable = []
    for dtype in req.dtypes or declared:
        why = (f"{op.name} is not declared at {dtype}" if dtype not in declared
               else skip_reason(chip, dtype, op.kind))
        if why is None:
            runnable.append(dtype)
        else:
            yield {"kind": "verdict", "op": op.name, "case": "*", "dtype": dtype, "chip": chip, "outcome": "skip",
                   "metrics": {}, "notes": why, "blocking": False}
    cases = [c for c in sweep(op) if c.dtype_name in runnable]
    if not cases:
        return
    base = {"op": op.name, "chip": chip}
    if not cand.file.exists():
        yield {"kind": "verdict", **base, "case": "*", "dtype": "*", "outcome": "blocked", "metrics": {},
               "notes": f"no {cand.file.name} in {cand.file.parent}", "blocking": True}
        return
    runs = execute(ctx, op, cand, cases, grade_only=req.grade_only)
    if runs.blocked is not None:
        yield {"kind": "verdict", **base, "case": "*", "dtype": "*", "outcome": "blocked", "metrics": {},
               "notes": runs.blocked["notes"], "where": runs.blocked["where"], "blocking": True}
        return
    at = where(cand.file, None, cand.attr)
    for case, run in runs.runs:
        fields = {**base, "case": case.label(), "dtype": case.dtype_name, "where": at}
        if run is None:
            yield {"kind": "verdict", **fields, "outcome": "skip", "metrics": {}, "blocking": False,
                   "notes": "not run: the child died on an earlier case"}
            continue
        grader = graders.model_grader(case.dtype_name) if op.kind == "model" else graders.op_grader(blocking)
        yield verdict(grade(ctx.store, run, grader), blocking=blocking, **fields)
    if runs.coverage is not None:
        yield verdict(grade(ctx.store, runs.coverage, graders.coverage_grader(blocking)), blocking=blocking,
                      **base, case="coverage", dtype="*", where=at)


# ---- self-tests: every planted bug and adversarial candidate must FAIL, for its stated reason --------------------

SELF = Path(__file__).resolve().parent / "selftest"
REF_GPT2 = Path(__file__).resolve().parents[3] / "engine" / "ref" / "ch01" / "gpt2.py"
HANG_TIMEOUT_S = 3.0


@dataclass(frozen=True)
class Expect:
    """`caught_by` None: must PASS (a correct candidate). Else must FAIL with "<check>: <notes>" containing it (or
    one of its `|`-separated alternatives).
    `hole_when`: isolation modes where not catching it is a known, reported hole (not a self-test failure)."""

    op: str
    file: Path
    caught_by: str | None
    call_timeout: float = 60.0
    hole_when: tuple[str, ...] = ()


def selftests(scratch: Path) -> list[Expect]:
    planted, adv, ok = SELF / "planted", SELF / "adversarial", SELF / "ok"
    tests = [Expect(op, ok / f"{op}.py", None) for op in ("linear", "gelu", "layer_norm", "causal_attention")]
    tests += [Expect(op, SELF.parent / "fixture" / FILE, None) for op in OPS]
    tests += [
        Expect("layer_norm", planted / "layer_norm_no_eps.py", "budget: err"),
        Expect("layer_norm", planted / "layer_norm_wrong_axis.py", "budget: err"),
        Expect("layer_norm", planted / "layer_norm_untested_branch.py", "coverage: sweep never executed"),
        Expect("gelu", planted / "gelu_exact.py", "budget: err"),
        Expect("causal_attention", planted / "attention_scale.py", "budget: err"),
        Expect("causal_attention", planted / "attention_mask_off_by_one.py", "budget: err"),
        Expect("linear", planted / "linear_no_bias.py", "budget: err"),
        Expect("layer_norm", adv / "mutates_input.py", "inputs_unchanged: mutated input"),
        Expect("layer_norm", adv / "cached_result.py", "dtype_shape: output shape"),
        Expect("layer_norm", adv / "reads_parent.py", "returned: raised: LookupError: no expected"),
        Expect("layer_norm", adv / "hangs.py", "returned: timed out", HANG_TIMEOUT_S),
        Expect("layer_norm", adv / "lazy_tensor.py", "want a plain torch.Tensor"),
        Expect("layer_norm", adv / "nondeterministic.py", "deterministic: nondeterministic"),
        Expect("layer_norm", adv / "exits.py", "returned: child died: the child exited mid-call"),
        Expect("layer_norm", adv / "forges_reply.py", "returned: bad reply: bad frame magic"),
        Expect("layer_norm", adv / "reads_store.py", "returned: raised: PermissionError", hole_when=("same-uid",)),
    ]
    if REF_GPT2.exists():  # the chapter's real forward, and one-line mutants of it
        tests.append(Expect("forward", REF_GPT2, None))
        tests += [Expect("forward", mutants.write(name, REF_GPT2, scratch),
                         "budget: err|kl: KL max") for name in mutants.MUTANTS]
    return tests


def run_selftest(ctx: Ctx, test: Expect, req: Request) -> dict[str, Any]:
    """Grade one self-test candidate; caught = some failing verdict says why, in the stated words."""
    op, adapter = OPS[test.op]
    sub = Ctx(ctx.store, ctx.env, ctx.iso, ctx.log, ctx.startup_timeout, test.call_timeout)
    blocking = True
    verdicts = list(check_op(sub, op, Candidate(test.file, test.op, adapter), req, blocking))
    fails = [v for v in verdicts if v["outcome"] in ("fail", "blocked")]
    ratios = [v["metrics"].get("ratio") for v in verdicts if isinstance(v["metrics"].get("ratio"), float)]
    kls = [v["metrics"].get("kl_max") for v in verdicts if isinstance(v["metrics"].get("kl_max"), float)]
    if test.caught_by is None:
        ok, by = not fails, (fails[0]["notes"] if fails else "")
    else:
        hits = [v for v in fails if any(alt in v["notes"] for alt in test.caught_by.split("|"))]
        ok, by = bool(hits), (hits or fails or [{"notes": "(nothing failed)"}])[0]["notes"]
    hole = not ok and ctx.iso.mode in test.hole_when
    return {"kind": "selftest", "op": test.op, "candidate": _short(test.file), "expect": test.caught_by or "pass",
            "ok": ok or hole, "hole": hole, "by": by[:300], "cases": len(verdicts),
            "worst_ratio": max(ratios, default=None), "best_ratio": min(ratios, default=None),
            "kl_max": max(kls, default=None)}


def _short(path: Path) -> str:
    parts = path.parts
    return "/".join(parts[-3:]) if "selftest" in parts or "assay-mutants" in str(path) else path.name

