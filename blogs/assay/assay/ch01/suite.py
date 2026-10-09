"""Chapter 1 as a check suite: graders (thresholds as config), the dtype x chip matrix, the reader's file, self-tests.

Sections: graders, model-level planted bugs (mutants), suite.
"""

from __future__ import annotations

import math
import os
import tempfile
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from assay.ch01 import ops
from assay.ch01.ops import SHORT, Op, band, sweep
from assay.ch01.run import Candidate, Ctx, detect_env, execute, where
from assay.core import Check, Entry, Grader, Result, failed, grade, passed, verdict

# --------------------------------------------------------------------------------------------------------------------
# graders
#
# Chapter 1's graders: ordered checks over a stored Run's facts. Thresholds live here, as grader config, so changing
# one regrades stored runs without re-running anything.
#
#     per-op case     returned > dtype_shape > inputs_unchanged > deterministic > budget        (all required)
#     per-op sweep    coverage: every line + branch of the bound function ran on some case
#     model fp32      returned > ... > budget (2x fp64) > kl (per-position max < 1e-7) > topk (smoke)
#     model bf16/fp16 returned > ... > kl (max < 0.1, vs fp64 truth ~ the fp32 reference) > topk (smoke)
#
# Floors (fraction of max|truth|, the budget when the reference itself is exact) were set against the planted-bug
# table (`run_checks ch01 --selftest` prints each planted bug's err / budget): every planted bug is >= 10x over its
# budget at fp32, and every correct candidate is under it.
# --------------------------------------------------------------------------------------------------------------------

FLOORS = {"fp32": 2e-5, "fp16": 1e-3, "bf16": 2e-2}
MULT = 2.0
KL_MAX = {"fp32": 1e-7, "fp16": 0.1, "bf16": 0.1}  # fp32: correct 5e-10, exact-GELU bug 4e-5; bf16: ~2x HF's own


def _facts(run: Entry) -> dict[str, Any]:
    return run.meta["facts"]


def _dtype(run: Entry) -> str:
    return run.meta["parts"]["case"]["dtype"]


def returned(run: Entry, cfg: Mapping[str, Any]) -> Result:
    facts = _facts(run)
    if facts["status"] != "returned":
        return failed(facts.get("notes", facts["status"]), status=facts["status"])
    return passed(metrics={"seconds": facts.get("seconds")})


def dtype_shape(run: Entry, cfg: Mapping[str, Any]) -> Result:
    facts = _facts(run)
    out, want = facts["out"], facts["want"]
    if out["dtype"] != want["dtype"]:
        return failed(f"output dtype {out['dtype']}, want {want['dtype']}")
    if out["shape"] != want["shape"]:
        return failed(f"output shape {out['shape']}, want {want['shape']}")
    return passed()


def inputs_unchanged(run: Entry, cfg: Mapping[str, Any]) -> Result:
    facts = _facts(run)
    if not facts["inputs_unchanged"]:
        run_index, arg = facts["mutated"][0]
        return failed(f"mutated input arg {arg} during run {run_index}")
    return passed()


def deterministic(run: Entry, cfg: Mapping[str, Any]) -> Result:
    if not _facts(run)["deterministic"]:
        return failed("nondeterministic: two runs on identical inputs differ bitwise")
    return passed()


def budget(run: Entry, cfg: Mapping[str, Any]) -> Result:
    facts = _facts(run)
    limit = band(facts["ref_err"], facts["scale"], _dtype(run), cfg["mult"], cfg["floors"])
    err = float(facts["err"])
    metrics = {"err": err, "budget": limit, "ratio": err / limit if limit else math.inf, "ref_err": facts["ref_err"]}
    if not (math.isfinite(err) and err <= limit):
        return failed(f"err {err:.3g} > budget {limit:.3g}", metrics=metrics)
    return passed(metrics=metrics)


def kl(run: Entry, cfg: Mapping[str, Any]) -> Result:
    facts = _facts(run)
    limit = cfg["kl_max"][_dtype(run)]
    value = float(facts["kl_max"])
    metrics = {"kl_max": value, "kl_limit": limit, "kl_mean": facts.get("kl_mean"),
               "ref_kl_max": facts.get("ref_kl_max"), "top1_agree": facts.get("top1_agree")}
    if not (math.isfinite(value) and value < limit):
        return failed(f"KL max {value:.3g} >= {limit:g} at position {facts.get('kl_argmax')}", metrics=metrics)
    return passed(metrics=metrics)


def topk(run: Entry, cfg: Mapping[str, Any]) -> Result:
    """vLLM-style, teacher-forced: at every position each side's top-1 is in the other's top-5. A smoke test."""
    facts = _facts(run)
    if not facts["topk_ok"]:
        return failed(f"top-1 not in the other's top-5 at position {facts['topk_first_bad']}",
                      metrics={"top1_agree": facts.get("top1_agree")})
    return passed(metrics={"top1_agree": facts.get("top1_agree")})


def coverage(run: Entry, cfg: Mapping[str, Any]) -> Result:
    facts = _facts(run)
    if facts["status"] != "returned":
        return failed(facts.get("notes", "no coverage"))
    if facts["range"] is None or not facts["executed"]:
        return failed("the sweep never executed the function")
    lines, branches = facts["missing_lines"], facts["missing_branches"]
    if lines or branches:
        return failed(f"sweep never executed lines {lines}, branches {[f'{a}->{b}' for a, b in branches]}",
                      metrics={"missing_lines": len(lines), "missing_branches": len(branches)})
    return passed()


CALL = (Check("returned", returned), Check("dtype_shape", dtype_shape), Check("inputs_unchanged", inputs_unchanged),
        Check("deterministic", deterministic))


def op_grader(blocking: bool) -> Grader:
    return Grader("ch01-op", (*CALL, Check("budget", budget)),
                  {"mult": MULT, "floors": FLOORS, "blocking": blocking})


def coverage_grader(blocking: bool) -> Grader:
    return Grader("ch01-coverage", (Check("coverage", coverage),), {"blocking": blocking})


def model_grader(dtype: str) -> Grader:
    """Model level always blocks. fp32 gates on both the budget and KL; lower precisions on KL vs truth."""
    gates = (Check("budget", budget),) if dtype == "fp32" else ()
    return Grader(f"ch01-model-{dtype}", (*CALL, *gates, Check("kl", kl), Check("topk", topk)),
                  {"mult": MULT, "floors": FLOORS, "kl_max": KL_MAX, "blocking": True})


# --------------------------------------------------------------------------------------------------------------------
# model-level planted bugs
#
# Model-level planted bugs, as one-line source edits of the reference gpt2.py (mutation testing).
#
# Each mutant is gpt2.py with exactly one substring replaced, written out as its own `gpt2.py` so the check imports it
# like any reader's file; the bug is literally the diff. If gpt2.py drifts so a target no longer appears exactly once,
# building the mutant fails loudly.
# --------------------------------------------------------------------------------------------------------------------

# name -> (what the bug is, old substring, new substring)
MUTANTS = {
    "a_scale_1/hd": ("attention scale 1/head_dim instead of 1/sqrt(head_dim)", "/ math.sqrt(hd)", "/ hd"),
    "b_no_ln_f": ("final layer norm skipped",
                  'final = layer_norm(residual_stream(w, cfg, tokens)[-1], w, "ln_f", cfg)',
                  "final = residual_stream(w, cfg, tokens)[-1]"),
    "c_gelu_exact": ("exact erf GELU instead of GPT-2's tanh approximation", 'approximate="tanh"',
                     'approximate="none"'),
    "d_mask_leak": ("causal mask off by one: each query also sees the next key", "triu(diagonal=1)",
                    "triu(diagonal=2)"),
}


def write_mutant(name: str, source: Path, out_dir: Path) -> Path:
    """`out_dir/<name>/gpt2.py`: the source with mutant `name` applied."""
    _, old, new = MUTANTS[name]
    src = source.read_text()
    assert src.count(old) == 1, f"mutant {name}: {old!r} appears {src.count(old)} times in {source}"
    path = out_dir / name.replace("/", "_") / "gpt2.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    text = src.replace(old, new)
    if not path.exists() or path.read_text() != text:
        path.write_text(text)
    return path


# --------------------------------------------------------------------------------------------------------------------
# suite
#
# Chapter 1 as a check suite: which ops, where the reader's code is, the dtype x chip matrix, and the self-tests.
#
#     run_checks ch01 --op causal_attention       cwd = the tree; its gpt2.py defines `causal_attention`
#       for each requested dtype: declared by the op? the chip can test it honestly? else a visible SKIP verdict
#       execute (run.py) -> one Run per case (+ coverage) -> grade (grade.py) -> one verdict per case
# --------------------------------------------------------------------------------------------------------------------

FILE = "gpt2.py"
OPS: dict[str, tuple[Op, str]] = {  # op -> (spec, child adapter); the reader's function has the op's name
    "linear": (ops.linear, "plain"), "gelu": (ops.gelu, "plain"), "layer_norm": (ops.layer_norm, "plain"),
    "causal_attention": (ops.causal_attention, "plain"), "forward": (ops.forward, "forward")}

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


def checks(args: Any, store: Any, iso: Any, log: Callable[[str], None], warm: Path | None) -> Iterator[dict]:
    """The CLI's entry: verdicts for the requested ops, or self-test records."""
    unknown = set(args.op) - set(OPS)
    if unknown:
        raise ValueError(f"ch01 has no op {sorted(unknown)}; its ops are {list(OPS)}")
    os.environ.setdefault("HF_HOME", str(Path.home() / ".cache" / "huggingface"))  # the child's HOME is scratch
    ctx = Ctx(store, detect_env(), iso, log, call_timeout=args.timeout, warm=warm)
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
        grader = model_grader(case.dtype_name) if op.kind == "model" else op_grader(blocking)
        yield verdict(grade(ctx.store, run, grader), blocking=blocking, **fields)
    if runs.coverage is not None:
        yield verdict(grade(ctx.store, runs.coverage, coverage_grader(blocking)), blocking=blocking,
                      **base, case="coverage", dtype="*", where=at)


# ---- self-tests: every planted bug and adversarial candidate must FAIL, for its stated reason --------------------

SELF = Path(__file__).resolve().parent / "selftest"
REF_GPT2 = Path(__file__).resolve().parents[3] / "engine" / "ref" / "ch01" / "gpt2.py"
HANG_TIMEOUT_S = 3.0


@dataclass(frozen=True)
class Expect:
    """`caught_by` None: must PASS (a correct candidate). Else must FAIL with "<check>: <notes>" containing it (or one
    of its `|`-separated alternatives). `hole_when`: isolation modes where not catching it is a known, reported hole
    (not a self-test failure). The candidate is `attr` in `file`, checked as `op`."""

    op: str
    file: Path
    attr: str
    caught_by: str | None
    call_timeout: float = 60.0
    hole_when: tuple[str, ...] = ()


def selftests(scratch: Path) -> list[Expect]:
    honest, adv = SELF / "candidates.py", SELF / "adversarial.py"
    tests = [Expect(op, honest, op, None) for op in ("linear", "gelu", "layer_norm", "causal_attention")]
    tests += [Expect(op, SELF.parent / "fixture" / FILE, op, None) for op in OPS]
    tests += [Expect(op, honest, attr, why) for op, attr, why in (
        ("layer_norm", "layer_norm_no_eps", "budget: err"),
        ("layer_norm", "layer_norm_wrong_axis", "budget: err"),
        ("layer_norm", "layer_norm_untested_branch", "coverage: sweep never executed"),
        ("gelu", "gelu_exact", "budget: err"),
        ("causal_attention", "attention_scale", "budget: err"),
        ("causal_attention", "attention_mask_off_by_one", "budget: err"),
        ("linear", "linear_no_bias", "budget: err"))]
    tests += [Expect("layer_norm", adv, attr, why, *extra) for attr, why, *extra in (
        ("mutates_input", "inputs_unchanged: mutated input"),
        ("cached_result", "dtype_shape: output shape"),
        ("reads_parent", "returned: raised: LookupError: no expected"),
        ("hangs", "returned: timed out", HANG_TIMEOUT_S),
        ("lazy_tensor", "want a plain torch.Tensor"),
        ("nondeterministic", "deterministic: nondeterministic"),
        ("exits", "returned: child died: the child exited mid-call"),
        ("reads_store", "returned: raised: PermissionError", 60.0, ("same-uid",)))]
    tests.append(Expect("layer_norm", SELF / "forges_reply.py", "layer_norm", "returned: bad reply: bad frame magic"))
    if REF_GPT2.exists():  # the chapter's real forward, and one-line mutants of it
        tests.append(Expect("forward", REF_GPT2, "forward", None))
        tests += [Expect("forward", write_mutant(name, REF_GPT2, scratch), "forward", "budget: err|kl: KL max")
                  for name in MUTANTS]
    return tests


def run_selftest(ctx: Ctx, test: Expect, req: Request) -> dict[str, Any]:
    """Grade one self-test candidate; caught = some failing verdict says why, in the stated words."""
    op, adapter = OPS[test.op]
    sub = Ctx(ctx.store, ctx.env, ctx.iso, ctx.log, ctx.startup_timeout, test.call_timeout, ctx.warm)
    blocking = True
    verdicts = list(check_op(sub, op, Candidate(test.file, test.attr, adapter), req, blocking))
    fails = [v for v in verdicts if v["outcome"] in ("fail", "blocked")]
    ratios = [v["metrics"].get("ratio") for v in verdicts if isinstance(v["metrics"].get("ratio"), float)]
    kls = [v["metrics"].get("kl_max") for v in verdicts if isinstance(v["metrics"].get("kl_max"), float)]
    if test.caught_by is None:
        ok, by = not fails, (fails[0]["notes"] if fails else "")
    else:
        hits = [v for v in fails if any(alt in v["notes"] for alt in test.caught_by.split("|"))]
        ok, by = bool(hits), (hits or fails or [{"notes": "(nothing failed)"}])[0]["notes"]
    hole = not ok and ctx.iso.mode in test.hole_when
    return {"kind": "selftest", "op": test.op, "candidate": f"{_short(test.file)}:{test.attr}",
            "expect": test.caught_by or "pass",
            "ok": ok or hole, "hole": hole, "by": by[:300], "cases": len(verdicts),
            "worst_ratio": max(ratios, default=None), "best_ratio": min(ratios, default=None),
            "kl_max": max(kls, default=None)}


def _short(path: Path) -> str:
    parts = path.parts
    return "/".join(parts[-3:]) if "selftest" in parts or "assay-mutants" in str(path) else path.name
