"""Chapter 1's graders: ordered checks over a stored Run's facts. Thresholds live here, as grader config, so changing
one regrades stored runs without re-running anything.

    per-op case     returned > dtype_shape > inputs_unchanged > deterministic > budget        (all required)
    per-op sweep    coverage: every line + branch of the bound function ran on some case
    model fp32      returned > ... > budget (2x fp64) > kl (per-position max < 1e-7) > topk (smoke)
    model bf16/fp16 returned > ... > kl (max < 0.1, vs fp64 truth ~ the fp32 reference) > topk (smoke)

Floors (fraction of max|truth|, the budget when the reference itself is exact) were set against the planted-bug
table (`run_checks ch01 --selftest` prints each planted bug's err / budget): every planted bug is >= 10x over its
budget at fp32, and every correct candidate is under it.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from assay.ch01.numerics import band
from assay.grading import Check, Grader, Result, failed, passed
from assay.store import Entry

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
