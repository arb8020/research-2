"""kelpie::rope -- rotary position embedding, HF's rotate-half convention.

Torch has no rope op. The cos/sin tables are built once per forward by
`kernels/functional.py:rope_tables` (table construction, not an op) and passed in.
"""

from __future__ import annotations

import torch

from kelpie_models.kernels.op import op


@op
def rope(x: torch.Tensor, cos: torch.Tensor, sin: torch.Tensor) -> torch.Tensor:
    """x [T, H, D], cos/sin [T, D]. Splitting x into halves x1, x2 on the last dim,
    out = x * cos + cat(-x2, x1) * sin -- HF's rotate-half layout, where the tables carry each
    frequency twice. -> [T, H, D] in x's dtype."""
    half = x.shape[-1] // 2
    x1, x2 = x[..., :half], x[..., half:]
    rot = torch.cat([-x2, x1], dim=-1)
    return x * cos[:, None, :] + rot * sin[:, None, :]


@rope.register_fake
def _fake(x: torch.Tensor, cos: torch.Tensor, sin: torch.Tensor) -> torch.Tensor:
    del cos, sin
    return torch.empty_like(x)


@rope.samples
def _samples(device: str, dtype: torch.dtype) -> tuple:
    return (
        torch.randn(2, 1, 4, device=device, dtype=dtype),
        torch.randn(2, 4, device=device, dtype=dtype),
        torch.randn(2, 4, device=device, dtype=dtype),
    )


def _backward(ctx: object, grad: torch.Tensor) -> tuple:
    del ctx, grad
    raise NotImplementedError("backward: training deferred (branch integrate/train-step)")


rope.register_autograd(_backward)


@rope.register("triton", source="kernels.vendored.cuda._triton.rope")
def _triton(x: torch.Tensor, cos: torch.Tensor, sin: torch.Tensor) -> torch.Tensor:
    from kelpie_models.kernels.vendored.cuda import _triton as kernel

    return kernel.rope(x, cos, sin)


@rope.register("liger", source="liger_kernel.ops.rope.LigerRopeFunction")
def _liger(x: torch.Tensor, cos: torch.Tensor, sin: torch.Tensor) -> torch.Tensor:
    """liger's rope takes q and k together in [B, H, T, D] and returns both; kelpie's op is one
    tensor at a time in [T, H, D], so the adapter reshapes and drops the unused half."""
    from liger_kernel.ops.rope import LigerRopeFunction

    t, h, d = x.shape
    packed = x.permute(1, 0, 2).unsqueeze(0)
    out, _ = LigerRopeFunction.apply(packed, packed, cos.unsqueeze(0), sin.unsqueeze(0))
    return out.squeeze(0).permute(1, 0, 2).reshape(t, h, d)
