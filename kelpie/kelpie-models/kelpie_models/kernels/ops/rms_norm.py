"""kelpie::rms_norm -- RMS normalization.

Torch has `F.rms_norm`, so the reference body is that call. It is a kelpie op anyway: overriding
`aten::rms_norm` is process-global and would leak our kernel into any other torch code in the
process (an HF oracle, a trainer). A model calls `torch.ops.kelpie.rms_norm`.
"""

from __future__ import annotations

import torch
import torch.nn.functional as F

from kelpie_models.kernels.op import op


@op
def rms_norm(x: torch.Tensor, weight: torch.Tensor, eps: float) -> torch.Tensor:
    """x * rsqrt(mean(x^2, dim=-1) + eps) * weight, normalizing over the last dim only.
    x [..., H], weight [H] -> [..., H] in x's dtype."""
    # eps BY KEYWORD: torch 2.13's F.rms_norm takes three positional args and rejects a
    # fourth ("rms_norm() takes 3 positional arguments but 4 were given").
    return F.rms_norm(x, (x.shape[-1],), weight, eps=eps)


@rms_norm.register_fake
def _fake(x: torch.Tensor, weight: torch.Tensor, eps: float) -> torch.Tensor:
    del weight, eps
    return torch.empty_like(x)


@rms_norm.samples
def _samples(device: str, dtype: torch.dtype) -> tuple:
    return (torch.randn(4, 8, device=device, dtype=dtype),
            torch.randn(8, device=device, dtype=dtype), 1e-6)


def _backward(ctx: object, grad: torch.Tensor) -> tuple:
    del ctx, grad
    raise NotImplementedError("backward: training deferred (branch integrate/train-step)")


rms_norm.register_autograd(_backward)


@rms_norm.register("fla", source="fla.modules.layernorm.rms_norm")
def _fla(x: torch.Tensor, weight: torch.Tensor, eps: float) -> torch.Tensor:
    from fla.modules.layernorm import rms_norm as upstream

    return upstream(x, weight, None, eps)


@rms_norm.register("liger", source="liger_kernel.ops.rms_norm.LigerRMSNormFunction")
def _liger(x: torch.Tensor, weight: torch.Tensor, eps: float) -> torch.Tensor:
    from liger_kernel.ops.rms_norm import LigerRMSNormFunction

    return LigerRMSNormFunction.apply(x, weight, eps, 0.0, "llama", False)


@rms_norm.register("triton", source="kernels.vendored.cuda._triton.rms_norm")
def _triton(x: torch.Tensor, weight: torch.Tensor, eps: float) -> torch.Tensor:
    from kelpie_models.kernels.vendored.cuda import _triton as kernel

    return kernel.rms_norm(x, weight, eps)


@rms_norm.register("nki", source="kernels.vendored.neuron._nki.rms_norm")
def _nki(x: torch.Tensor, weight: torch.Tensor, eps: float) -> torch.Tensor:
    from kelpie_models.kernels.vendored.neuron._nki import rms_norm as kernel

    return kernel(x, weight, eps)
