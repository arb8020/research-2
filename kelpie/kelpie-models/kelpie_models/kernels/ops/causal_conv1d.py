"""kelpie::causal_conv1d -- the short causal convolution ahead of a recurrent layer.

Kimi's KDA and DeepSeek-V4-Flash's compress ring both run a width-4 depthwise causal conv
before the recurrence. `state` is the per-request conv ring, mutated in place.
"""

from __future__ import annotations

import torch

from kelpie_models.kernels.op import mutates, op


@op
@mutates("state")
def causal_conv1d(x: torch.Tensor, weight: torch.Tensor, state: torch.Tensor) -> torch.Tensor:
    """x [T, C], `weight` [C, W] the depthwise kernel, `state` [R, C, W-1] the carry, written
    in place. -> [T, C]."""
    del x, weight, state
    raise NotImplementedError(
        "causal_conv1d: reference body not written; the flash-linear-attention Triton source it wraps is not vendored into this tree yet"
    )


@causal_conv1d.register_fake
def _fake(x: torch.Tensor, weight: torch.Tensor, state: torch.Tensor) -> torch.Tensor:
    del weight, state
    return torch.empty_like(x)


@causal_conv1d.samples
def _samples(device: str, dtype: torch.dtype) -> tuple:
    raise NotImplementedError(
        "causal_conv1d.sample_args: needs the reference body first -- args with no runnable "
        "reference cannot be opchecked or compared"
    )


def _backward(ctx: object, grad: torch.Tensor) -> tuple:
    del ctx, grad
    raise NotImplementedError("backward: training deferred (branch integrate/train-step)")


causal_conv1d.register_autograd(_backward)



@causal_conv1d.register("fla", source="fla.modules.convolution")
def _fla(*args: object) -> torch.Tensor:
    del args
    raise NotImplementedError(
        "causal_conv1d[fla]: not vendored into this tree yet"
    )
