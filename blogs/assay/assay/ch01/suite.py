from __future__ import annotations

import math
import os
import tempfile
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from assay.ch01 import ops
from assay.ch01.ops import SHORT, Op, load_frontier, sweep, tolerance_ratio
from assay.ch01.run import Candidate, Ctx, detect_env, execute, where
from assay.core import Check, Entry, Grader, Result, failed, grade, passed, verdict

TOL = {"fp32": (1.5e-4, 1e-5), "fp16": (2e-2, 2e-2), "bf16": (0.15, 0.15)}
KL_MAX = {"fp32": 1e-7, "fp16": 0.1, "bf16": 0.1}


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


def allclose(run: Entry, cfg: Mapping[str, Any]) -> Result:
    facts = _facts(run)
    atol, rtol = cfg["tol"][_dtype(run)]
    ratio, at, err = tolerance_ratio(load_frontier(facts["frontier"]), atol, rtol)
    ref = facts.get("ref_frontier")
    metrics = {"ratio": ratio, "err": float(facts["err"]), "atol": atol, "rtol": rtol,
               "ref_ratio": tolerance_ratio(load_frontier(ref), atol, rtol)[0] if ref is not None else None}
    if not (math.isfinite(ratio) and ratio <= 1.0):
        return failed(f"|out - fp64 truth| up to {ratio:.3g}x the tolerance (atol {atol:g} + rtol {rtol:g} |T|; worst "
                      f"element: error {err:.3g} where |T| = {at:.3g})", metrics=metrics)
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
    facts = _facts(run)
    if not facts["topk_ok"]:
        return failed(f"top-1 not in the other's top-5 at position {facts['topk_first_bad']}",
                      metrics={"top1_agree": facts.get("top1_agree")})
    return passed(metrics={"top1_agree": facts.get("top1_agree")})


def tokens(run: Entry, cfg: Mapping[str, Any]) -> Result:
    facts = _facts(run)
    diff = facts.get("first_diff")
    if diff is not None:
        return failed(f"new token {diff['at']}: got id {diff['got']}, HF's greedy picked {diff['want']}",
                      metrics={"first_diff": diff["at"]})
    return passed(metrics={"tokens": facts["want"]["shape"][0]})


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
    return Grader("ch01-op", (*CALL, Check("allclose", allclose)), {"tol": TOL, "blocking": blocking})


def coverage_grader(blocking: bool) -> Grader:
    return Grader("ch01-coverage", (Check("coverage", coverage),), {"blocking": blocking})


def model_grader(dtype: str) -> Grader:
    return Grader(f"ch01-model-{dtype}", (*CALL, Check("kl", kl), Check("topk", topk)),
                  {"kl_max": KL_MAX, "blocking": True})


def tokens_grader() -> Grader:
    return Grader("ch01-tokens", (*CALL, Check("tokens", tokens)), {"blocking": True})


def grader_for(op: Op, dtype: str, blocking: bool) -> Grader:
    if op.name == "forward":
        return model_grader(dtype)
    if op.name == "generate":
        return tokens_grader()
    return op_grader(blocking)


KL_CATCH, TOL_CATCH = "kl: KL max", "allclose: |out - fp64 truth|"

MUTANTS: dict[str, tuple[str, str, str, dict[str, str]]] = {
    "a_scale_1/H": ("attention scale 1/H instead of 1/sqrt(H)", "/ math.sqrt(H)", "/ H",
                    {"block": TOL_CATCH, "forward": KL_CATCH}),
    "b_no_ln_f": ("final layer norm skipped", "    x_TD = layer_norm(x_TD, w.lnf_w_D, w.lnf_b_D, cfg.eps)\n", "",
                  {"forward": KL_CATCH}),
    "c_gelu_exact": ("exact erf GELU instead of GPT-2's tanh approximation", "(1 + torch.tanh(inner_TF))",
                     "(1 + torch.erf(x_TF / math.sqrt(2)))", {"block": TOL_CATCH, "forward": KL_CATCH}),
    "d_mask_leak": ("causal mask off by one: each query also sees the next key", "future_TS.triu(1)",
                    "future_TS.triu(2)", {"block": TOL_CATCH, "forward": KL_CATCH}),
    "e_first_row": ("generate picks the next token from the first row, not the last", "logits_TV[-1].argmax()",
                    "logits_TV[0].argmax()", {"generate": "tokens: new token"}),
    "f_with_prompt": ("generate returns the prompt too", "return ids[len(prompt):]", "return ids",
                      {"generate": "dtype_shape: output shape"}),
}


MUTANT_MISSED: dict[str, tuple[str, ...]] = {"c_gelu_exact": ("fp16", "bf16")}


def write_mutant(name: str, source: Path, out_dir: Path) -> Path:
    _, old, new, _ = MUTANTS[name]
    src = source.read_text()
    assert src.count(old) == 1, f"mutant {name}: {old!r} appears {src.count(old)} times in {source}"
    path = out_dir / name.replace("/", "_") / "gpt2.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    text = src.replace(old, new)
    if not path.exists() or path.read_text() != text:
        path.write_text(text)
    return path


FILE = "gpt2.py"
OPS: dict[str, tuple[Op, str]] = {
    "linear": (ops.linear, "plain"), "gelu": (ops.gelu, "plain"), "layer_norm": (ops.layer_norm, "plain"),
    "attention": (ops.attention, "plain"), "block": (ops.block, "block"), "forward": (ops.forward, "forward"),
    "generate": (ops.generate, "generate")}

_SM80 = {"fp32": {"testable": True}, "fp16": {"testable": True}, "bf16": {"testable": True}}
CHIPS: dict[str, dict[str, Any]] = {
    "cpu": {"device_name": "CPU (the laptop rule)", "dtypes": {
        "fp32": {"testable": True},
        "bf16": {"testable": True, "model": {"testable": False, "skip_reason": (
            "bf16 gpt2 on CPU is ~50x slower than fp32 (no fast bf16 GEMM, RESULTS.md): checked on a bf16 GPU")}},
        "fp16": {"testable": False, "skip_reason": "CPU has no native fp16 math: checked on GPU"}}},
    "sm_75": {"device_name": "Tesla T4", "dtypes": {
        "fp32": {"testable": True}, "fp16": {"testable": True},
        "bf16": {"testable": False, "skip_reason": (
            "sm_75 has no bf16 hardware: torch.cuda.is_bf16_supported(including_emulation=False) is False; bf16 "
            "runs only emulated, so it does not test the bf16 kernels a bf16 chip (sm_80+) would run")}}},
    **{f"sm_{n}": {"dtypes": _SM80} for n in (80, 86, 87, 89, 90, 100, 120)},
}


def skip_reason(chip: str, dtype: str, kind: str) -> str | None:
    row = CHIPS.get(chip, {"dtypes": {"fp32": {"testable": True}}})["dtypes"].get(dtype)
    if row is None:
        return f"{chip}: {dtype} is not in the capability table"
    row = row.get(kind, row) if kind == "model" else row
    return None if row["testable"] else row["skip_reason"]


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
    unknown = set(args.op) - set(OPS)
    if unknown:
        raise ValueError(f"ch01 has no op {sorted(unknown)}; its ops are {list(OPS)}")
    os.environ.setdefault("HF_HOME", str(Path.home() / ".cache" / "huggingface"))
    ctx = Ctx(store, detect_env(), iso, log, call_timeout=args.timeout, warm=warm)
    log(f"env: {ctx.env}")
    req = Request(ops=args.op or list(OPS), dtypes=args.dtype, tree=Path.cwd(), warn=set(args.warn),
                  warn_all=args.warn_all, grade_only=args.grade_only, call_timeout=args.timeout)
    if not args.selftest:
        yield from check(ctx, req)
        return
    if not REF_GPT2.exists():
        log(f"model mutants skipped: no reference {REF_GPT2.name} (sandbox)")
    scratch = Path(tempfile.gettempdir()) / "assay-mutants"
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
        raised_at = run.meta["facts"].get("line")
        if isinstance(raised_at, int):
            fields["where"] = where(cand.file, raised_at)
        yield verdict(grade(ctx.store, run, grader_for(op, case.dtype_name, blocking)), blocking=blocking, **fields)
    if runs.coverage is not None:
        yield verdict(grade(ctx.store, runs.coverage, coverage_grader(blocking)), blocking=blocking,
                      **base, case="coverage", dtype="*", where=at)


SELF = Path(__file__).resolve().parent / "selftest"
REF_GPT2 = Path(__file__).resolve().parents[3] / "engine" / "ref" / "ch01" / "files" / "gpt2.py"
HANG_TIMEOUT_S = 3.0


LOW = ("fp16", "bf16")


@dataclass(frozen=True)
class Expect:
    op: str
    file: Path
    attr: str
    caught_by: str | None
    call_timeout: float = 60.0
    hole_when: tuple[str, ...] = ()
    every_dtype: bool = False
    missed_at: tuple[str, ...] = ()


def selftests(scratch: Path) -> list[Expect]:
    honest, adv = SELF / "candidates.py", SELF / "adversarial.py"
    tests = [Expect(op, honest, op, None) for op in ("linear", "gelu", "layer_norm", "attention")]
    tests += [Expect(op, honest, attr, why, every_dtype=True, missed_at=missed) for op, attr, why, missed in (
        ("layer_norm", "layer_norm_no_eps", TOL_CATCH, ()),
        ("layer_norm", "layer_norm_wrong_axis", TOL_CATCH, ()),
        ("gelu", "gelu_exact", TOL_CATCH, LOW),
        ("attention", "attention_scale", TOL_CATCH, ()),
        ("attention", "attention_mask_off_by_one", TOL_CATCH, ()),
        ("linear", "linear_no_bias", TOL_CATCH, ()))]
    tests += [Expect("layer_norm", honest, attr, "coverage: sweep never executed")
              for attr in ("layer_norm_untested_branch", "layer_norm_pragma_hides_branch")]
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
    if REF_GPT2.exists():
        tests += [Expect(op, REF_GPT2, op, None) for op in OPS]
        tests += [Expect(op, write_mutant(name, REF_GPT2, scratch), op, why, missed_at=MUTANT_MISSED.get(name, ()))
                  for name, (_, _, _, catches) in MUTANTS.items() for op, why in catches.items()]
    return tests


def _hits(verdict_: dict[str, Any], caught_by: str) -> bool:
    return verdict_["outcome"] in ("fail", "blocked") and any(alt in verdict_["notes"] for alt in caught_by.split("|"))


def run_selftest(ctx: Ctx, test: Expect, req: Request) -> dict[str, Any]:
    op, adapter = OPS[test.op]
    sub = Ctx(ctx.store, ctx.env, ctx.iso, ctx.log, ctx.startup_timeout, test.call_timeout, ctx.warm)
    verdicts = list(check_op(sub, op, Candidate(test.file, test.attr, adapter), req, blocking=True))
    ran = [v for v in verdicts if v["outcome"] != "skip"]
    dtypes = sorted({v["dtype"] for v in ran} - {"*"})
    anywhere = [v for v in ran if v["dtype"] == "*"]
    per: dict[str, dict[str, Any]] = {}
    for dtype in dtypes:
        rows = [v for v in ran if v["dtype"] == dtype]
        ratios = [v["metrics"]["ratio"] for v in rows if isinstance(v["metrics"].get("ratio"), float)]
        kls = [v["metrics"]["kl_max"] for v in rows if isinstance(v["metrics"].get("kl_max"), float)]
        fails = [v for v in rows + anywhere if v["outcome"] in ("fail", "blocked")]
        if test.caught_by is None:
            state = "pass" if not fails else "WRONGLY FAILED"
        elif dtype in test.missed_at:
            state = "missed (expected)" if not fails else "CAUGHT (expected a miss: update missed_at)"
        else:
            state = "caught" if any(_hits(v, test.caught_by) for v in rows + anywhere) else (
                "caught for another reason" if fails else "MISSED")
        per[dtype] = {"state": state, "cases": len(rows), "worst_ratio": max(ratios, default=None),
                      "best_ratio": min(ratios, default=None), "kl_max": max(kls, default=None)}
    fails = [v for v in ran if v["outcome"] in ("fail", "blocked")]
    if test.caught_by is None:
        ok, by = not fails, (fails[0]["notes"] if fails else "")
    else:
        hits = [v for v in fails if _hits(v, test.caught_by) and v["dtype"] not in test.missed_at]
        misses_clean = all(per[d]["state"] == "missed (expected)" for d in dtypes if d in test.missed_at)
        caught_each = all(per[d]["state"] == "caught" for d in dtypes if d not in test.missed_at)
        ok = bool(hits) and misses_clean and (caught_each or not test.every_dtype)
        by = (hits or fails or [{"notes": "(nothing failed)"}])[0]["notes"]
    hole = not ok and ctx.iso.mode in test.hole_when
    return {"kind": "selftest", "op": test.op, "candidate": f"{_short(test.file)}:{test.attr}",
            "expect": test.caught_by or "pass", "missed_at": list(test.missed_at),
            "ok": ok or hole, "hole": hole, "by": by[:300], "cases": len(verdicts), "dtypes": per}


def _short(path: Path) -> str:
    parts = path.parts
    return "/".join(parts[-3:]) if "selftest" in parts or "assay-mutants" in str(path) else path.name
