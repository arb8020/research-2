"""kelpie::chunk_gated_delta_rule -- the KDA / GDN recurrence.

Kimi-Linear's 20 KDA layers, and qwen3_next's GDN, which KDA generalizes -- one op covers
both. `state` is the per-request temporal ring, mutated in place.
"""

from __future__ import annotations

import torch

from kelpie_models.kernels.op import mutates, op


@op
@mutates("state")
def chunk_gated_delta_rule(q: torch.Tensor, k: torch.Tensor, v: torch.Tensor, gate: torch.Tensor,
    state: torch.Tensor,) -> torch.Tensor:
    """q/k/v [T, H, D], `gate` [T, H] the per-step decay, `state` [R, H, D, D] the recurrent
    carry, written in place. -> [T, H, D]."""
    del q, k, v, gate, state
    raise NotImplementedError(
        "chunk_gated_delta_rule: reference body not written; the flash-linear-attention Triton source it wraps is not vendored into this tree yet"
    )


@chunk_gated_delta_rule.register_fake
def _fake(q: torch.Tensor, k: torch.Tensor, v: torch.Tensor, gate: torch.Tensor,
    state: torch.Tensor,) -> torch.Tensor:
    del k, v, gate, state
    return torch.empty_like(q)


@chunk_gated_delta_rule.samples
def _samples(device: str, dtype: torch.dtype) -> tuple:
    raise NotImplementedError(
        "chunk_gated_delta_rule.sample_args: needs the reference body first -- args with no runnable "
        "reference cannot be opchecked or compared"
    )


def _backward(ctx: object, grad: torch.Tensor) -> tuple:
    del ctx, grad
    raise NotImplementedError("backward: training deferred (branch integrate/train-step)")


chunk_gated_delta_rule.register_autograd(_backward)



@chunk_gated_delta_rule.register("fla", source="fla.ops.gated_delta_rule.chunk")
def _fla(*args: object) -> torch.Tensor:
    del args
    raise NotImplementedError(
        "chunk_gated_delta_rule[fla]: not vendored into this tree yet"
    )
