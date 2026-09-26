"""Grading a SAMPLER, which `compare` cannot do.

`sample` returns a draw, so equality against the reference is the wrong question -- two correct
samplers disagree on almost every row. The right question is whether the two draw from the same
distribution, which is a KL divergence over N draws at fixed logits, and that is a different
kind of check with a different failure mode (a flaky threshold).
"""

from __future__ import annotations

from typing import Any


def kl_check(op: Any, impl: str, sample_args: tuple, *, draws: int = 10_000) -> bool:
    del op, impl, sample_args, draws
    raise NotImplementedError(
        "sample check = KL over N draws vs reference; not written"
    )
