"""kelpie::layer_norm -- LayerNorm over the last dim.

Torch has `F.layer_norm`; this is a kelpie op for the same reason `rms_norm` is (never override
`aten::*`, it is process-global). The kelpie contract is the 4-argument one -- `aten::layer_norm`
carries a trailing `cudnn_enable` that `F.layer_norm` does not expose, and declaring our own op
is what makes that quirk somebody else's problem.
"""

from __future__ import annotations

import torch
import torch.nn.functional as F

from kelpie_models.kernels.op import op


@op
def layer_norm(
    x: torch.Tensor, weight: torch.Tensor, bias: torch.Tensor, eps: float
) -> torch.Tensor:
    """(x - mean) / sqrt(var + eps) * weight + bias over the last dim. x [..., H],
    weight/bias [H] -> [..., H]."""
    return F.layer_norm(x, (x.shape[-1],), weight, bias, eps=eps)


@layer_norm.register_fake
def _fake(
    x: torch.Tensor, weight: torch.Tensor, bias: torch.Tensor, eps: float
) -> torch.Tensor:
    del weight, bias, eps
    return torch.empty_like(x)


@layer_norm.samples
def _samples(device: str, dtype: torch.dtype) -> tuple:
    return (
        torch.randn(4, 8, device=device, dtype=dtype),
        torch.randn(8, device=device, dtype=dtype),
        torch.randn(8, device=device, dtype=dtype),
        1e-5,
    )


def _backward(ctx: object, grad: torch.Tensor) -> tuple:
    del ctx, grad
    raise NotImplementedError("backward: training deferred (branch integrate/train-step)")


layer_norm.register_autograd(_backward)


@layer_norm.register("metal", source="kernels.vendored.mps._metal.layer_norm")
def _metal(
    x: torch.Tensor, weight: torch.Tensor, bias: torch.Tensor, eps: float
) -> torch.Tensor:
    from kelpie_models.kernels.vendored.mps._metal import layer_norm as kernel

    return kernel(x, (x.shape[-1],), weight, bias, eps)
