"""kelpie::silu -- x * sigmoid(x).

Torch has `F.silu`; kelpie declares its own so nothing registers on `aten::silu`. The fused
`silu(gate) * up` is a different op (`silu_mul`), not an argument to this one.
"""

from __future__ import annotations

import torch
import torch.nn.functional as F

from kelpie_models.kernels.op import op


@op
def silu(x: torch.Tensor) -> torch.Tensor:
    """x * sigmoid(x) -> x's shape/dtype."""
    return F.silu(x)


@silu.register_fake
def _fake(x: torch.Tensor) -> torch.Tensor:
    return torch.empty_like(x)


@silu.samples
def _samples(device: str, dtype: torch.dtype) -> tuple:
    return (torch.randn(4, 8, device=device, dtype=dtype),)


def _backward(ctx: object, grad: torch.Tensor) -> tuple:
    del ctx, grad
    raise NotImplementedError("backward: training deferred (branch integrate/train-step)")


silu.register_autograd(_backward)
