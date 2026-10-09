"""Numbers, no thresholds: the reference's own error vs fp64 truth (what the budget is made of) and the reductions of a
candidate's output vs truth that a Run stores (all a grader needs, so grades never need the full output again).

Budget (crucible / popcorn / FlashAttention): a correct implementation may land as far from fp64 truth as the
reference itself does in this precision, with a factor for slack and a floor for when the reference is exact:

    err(candidate) <= max(mult * err(reference), floor[dtype] * max|truth|)

`mult` and the floors are grader config (grade.py), so changing them regrades stored runs without re-running.
"""

from __future__ import annotations

import math
from typing import Any

import torch

TOPK = 5


def max_abs(a: torch.Tensor, b: torch.Tensor) -> float:
    """max |a - b| in fp64; inf if either side has a non-finite value where the other does not match it."""
    diff = (a.double() - b.double()).abs()
    return float(diff.max()) if diff.numel() and bool(torch.isfinite(diff).all()) else (
        0.0 if diff.numel() == 0 else math.inf)


def reference_stats(truth: torch.Tensor, reference: torch.Tensor) -> dict[str, float]:
    """The reference's own error at its dtype, and the truth's scale. Truth must be finite or the case is broken."""
    assert truth.dtype == torch.float64, f"truth must be fp64, got {truth.dtype}"
    assert reference.shape == truth.shape, f"reference {tuple(reference.shape)} vs truth {tuple(truth.shape)}"
    assert bool(torch.isfinite(truth).all()), "truth has non-finite values: a broken case"
    assert bool(torch.isfinite(reference).all()), "the reference has non-finite values at its dtype"
    stats = {"ref_err": max_abs(reference, truth), "scale": float(truth.abs().max()) if truth.numel() else 0.0}
    if truth.dim() == 2 and truth.shape[-1] > 1000:  # logits: also the reference's own KL, for context
        stats["ref_kl_max"] = float(kl_per_position(truth, reference).max())
    return stats


def band(ref_err: float, scale: float, dtype: str, mult: float, floors: dict[str, float]) -> float:
    return max(mult * ref_err, floors[dtype] * scale)


def kl_per_position(truth: torch.Tensor, ours: torch.Tensor) -> torch.Tensor:
    """KL(softmax(truth) || softmax(ours)) for each row -> [T], nats, fp64."""
    lp_truth = torch.log_softmax(truth.double(), dim=-1)
    lp_ours = torch.log_softmax(ours.double(), dim=-1)
    return (lp_truth.exp() * (lp_truth - lp_ours)).sum(-1)


def reduce_output(out: torch.Tensor, truth: torch.Tensor) -> dict[str, Any]:
    """What a Run keeps about an output that matched truth's shape: its error, and for logits the per-position
    stats + top-k logprobs (the reduced artifact: [T, vocab] logits are ~200 MB at 1024 tokens)."""
    facts: dict[str, Any] = {"err": max_abs(out, truth), "finite": bool(torch.isfinite(out).all())}
    if truth.dim() != 2 or truth.shape[-1] <= 1000:
        return facts
    kl = kl_per_position(truth, out)
    per_pos_err = (out.double() - truth).abs().amax(dim=-1)
    lp_truth = torch.log_softmax(truth, dim=-1).topk(TOPK, dim=-1)
    lp_ours = torch.log_softmax(out.double(), dim=-1).topk(TOPK, dim=-1)
    ok = [(int(o[0]) in set(t.tolist())) and (int(t[0]) in set(o.tolist()))
          for t, o in zip(lp_truth.indices, lp_ours.indices, strict=True)]
    facts.update({
        "kl_max": float(kl.max()) if bool(torch.isfinite(kl).all()) else math.inf,
        "kl_mean": float(kl.mean()),
        "kl_argmax": int(kl.argmax()),
        "topk_ok": all(ok),
        "topk_first_bad": next((i for i, good in enumerate(ok) if not good), None),
        "top1_agree": float((lp_truth.indices[:, 0] == lp_ours.indices[:, 0]).double().mean()),
        "reduced": {"kl": kl.tolist(), "err": per_pos_err.tolist(),
                    "truth_topk": [lp_truth.indices.tolist(), lp_truth.values.tolist()],
                    "ours_topk": [lp_ours.indices.tolist(), lp_ours.values.tolist()]},
    })
    return facts
