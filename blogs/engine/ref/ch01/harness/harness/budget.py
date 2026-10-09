"""The correctness rules: the measured fp64 error budget, and the greedy top-k logprob rule.

Budget (from crucible, as kelpie and popcorn use it): run the reference in fp64 (TRUTH) and at
the case's dtype. The reference's own distance from truth is how far a correct implementation
may legitimately land in this precision. A candidate passes iff

    max|candidate - truth| <= max(2 * max|reference - truth|, FLOOR[dtype] * max|truth|)

The floor keeps the bar sane when the reference happens to be exact (e.g. a copy).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import torch

FLOORS = {torch.float32: 2e-5, torch.float16: 1e-3, torch.bfloat16: 2e-2}


@dataclass(frozen=True)
class Graded:
    """A tensor comparison: the candidate's error vs truth, and the band it had to be within."""

    err: float
    band: float

    @property
    def passed(self) -> bool:
        return math.isfinite(self.err) and self.err <= self.band


def band(truth: torch.Tensor, reference: torch.Tensor) -> float:
    """max(2 * reference error, floor * max|truth|): the measured budget for one case."""
    assert truth.dtype == torch.float64, f"truth must be fp64, got {truth.dtype}"
    assert reference.shape == truth.shape, f"reference {reference.shape} vs truth {truth.shape}"
    assert reference.dtype in FLOORS, f"no error floor for {reference.dtype}"
    assert bool(torch.isfinite(truth).all()), "truth has non-finite values: a broken case"
    assert bool(torch.isfinite(reference).all()), "reference has non-finite values at its dtype"
    reference_err = (reference.double() - truth).abs().max().item()
    scale = truth.abs().max().item()
    return max(2.0 * reference_err, FLOORS[reference.dtype] * scale)


def grade(candidate: torch.Tensor, truth: torch.Tensor, budget: float) -> Graded:
    """Shape and dtype are checked by the caller; NaN/inf in the candidate makes err non-finite,
    which fails."""
    assert candidate.shape == truth.shape, "caller checks shape first"
    return Graded((candidate.double() - truth).abs().max().item(), budget)


@dataclass(frozen=True)
class GreedyStep:
    """One decode step from one side: the greedy token and the top-k (token, logprob) pairs."""

    token: int
    topk: tuple[tuple[int, float], ...]


def greedy_step(last_logits: torch.Tensor, k: int) -> GreedyStep:
    """Last-position logits [vocab] -> the greedy token and the top-k logprobs."""
    assert last_logits.dim() == 1, f"want [vocab] logits, got {tuple(last_logits.shape)}"
    logprobs = torch.log_softmax(last_logits.double(), dim=-1)
    values, indices = logprobs.topk(k)
    return GreedyStep(int(indices[0]), tuple(zip(indices.tolist(), values.tolist(), strict=True)))


def compare_greedy(reference: list[GreedyStep], candidate: list[GreedyStep]) -> str | None:
    """vLLM's `check_logprobs_close`: walk the steps; equal tokens continue; at the first
    different token, each side's token must be in the other's top-k (a near tie), and then the
    sequences have diverged so comparison stops. Returns None on pass, else why it failed."""
    assert len(reference) == len(candidate), "both sides decode the same number of steps"
    for step, (ref, cand) in enumerate(zip(reference, candidate, strict=True)):
        if ref.token == cand.token:
            continue
        ref_top = dict(ref.topk)
        cand_top = dict(cand.topk)
        if cand.token in ref_top and ref.token in cand_top:
            return None
        return (f"step {step}: reference token {ref.token} (top-k {list(ref_top)}) vs candidate "
                f"token {cand.token} (top-k {list(cand_top)}): not a near tie")
    return None
