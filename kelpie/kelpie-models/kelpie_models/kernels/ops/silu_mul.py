"""kelpie::silu_mul -- silu(gate) * up, the SwiGLU MLP's activation as one op.

Torch has `F.silu` but no fused silu-times-up, and fusing it is the whole point: the MLP's two
projections are the widest tensors in the forward.
"""

from __future__ import annotations

import torch
import torch.nn.functional as F

from kelpie_models.kernels.op import op


@op
def silu_mul(gate: torch.Tensor, up: torch.Tensor) -> torch.Tensor:
    """silu(gate) * up, elementwise. gate/up [..., I] and the same dtype -> [..., I]."""
    return F.silu(gate) * up


@silu_mul.register_fake
def _fake(gate: torch.Tensor, up: torch.Tensor) -> torch.Tensor:
    del up
    return torch.empty_like(gate)


@silu_mul.samples
def _samples(device: str, dtype: torch.dtype) -> tuple:
    return (
        torch.randn(2, 4, device=device, dtype=dtype),
        torch.randn(2, 4, device=device, dtype=dtype),
    )


def _backward(ctx: object, grad: torch.Tensor) -> tuple:
    del ctx, grad
    raise NotImplementedError("backward: training deferred (branch integrate/train-step)")


silu_mul.register_autograd(_backward)


@silu_mul.register("triton", source="kernels.vendored.cuda._triton.silu_mul")
def _triton(gate: torch.Tensor, up: torch.Tensor) -> torch.Tensor:
    from kelpie_models.kernels.vendored.cuda import _triton as kernel

    return kernel.silu_mul(gate, up)
