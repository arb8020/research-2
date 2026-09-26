"""One kernel's correctness verdict: pass, fail, or skipped.

Three runs of the same sample args: the reference in fp64 (TRUTH), the reference at the case's
native dtype (the ERROR BUDGET -- how far a correct kernel may legitimately land from truth in
this precision), and the candidate. A candidate passes when it is no further from truth than
twice the reference's own error, floored per dtype. That floor is why this is not `allclose`
with a guessed tolerance: the budget is measured, not chosen.

`sample` is skipped (`skipped: distributional`) -- see `bench/distribution.py:kl_check`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import torch

from kelpie_models.bench.correctness import error_budget, within_budget

SKIP_DISTRIBUTIONAL = ("sample",)


@dataclass(frozen=True)
class Verdict:
    """What `build --check` records for one (op, impl, shape). `err` and `budget` are kept even
    on a pass: a kernel that passes at 0.9 of its budget is the next one to break."""

    verdict: str  # "pass" | "fail" | "skipped: <why>" | "error: <why>"
    err: float | None = None
    budget: float | None = None


def compare(op: Any, impl: str, sample_args: tuple) -> Verdict:
    """Grade `op`'s `impl` on `sample_args`. Never raises: a kernel that throws is a `fail`
    with the exception's text, because `build` must record every op, not stop at the first."""
    if op.name in SKIP_DISTRIBUTIONAL:
        return Verdict("skipped: distributional")
    entry = op.impls[impl] if impl in op.impls else op.reference_impl()
    try:
        truth = op.reference(*_upcast(sample_args))
        ref = op.reference(*sample_args)
        out = entry.fn(*sample_args)
    except NotImplementedError as exc:
        return Verdict(f"skipped: {exc}")
    except Exception as exc:  # noqa: BLE001 -- a throwing kernel is a verdict, not a crash
        return Verdict(f"error: {type(exc).__name__}: {exc}")
    if not isinstance(ref, torch.Tensor):
        return Verdict("pass" if within_budget(out, ref, truth) else "fail")
    budget = error_budget(truth, ref)
    err = (out.double() - truth.double()).abs().max().item()
    return Verdict("pass" if err <= budget else "fail", err, budget)


def _upcast(args: tuple) -> tuple:
    """Float tensors to fp64; everything else through unchanged. The fp64 run is the truth the
    budget is measured against."""
    return tuple(
        a.double() if isinstance(a, torch.Tensor) and a.dtype.is_floating_point else a
        for a in args
    )
