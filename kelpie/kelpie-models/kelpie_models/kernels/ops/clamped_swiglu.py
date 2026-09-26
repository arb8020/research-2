"""kelpie::clamped_swiglu -- gpt-oss's clamped SwiGLU.

Not `silu(gate) * up`: gate is clamped above at `limit`, up to `[-limit, limit]`, and the
result is `(up + 1) * gate * sigmoid(alpha * gate)` with alpha 1.702 (HF GptOssExperts). The
MoE op's reference body calls this reference directly (`kelpie::moe`); a fused MoE backend fuses
it into its first matmul's epilogue.
"""

from __future__ import annotations

import torch

from kelpie_models.kernels.op import op


@op
def clamped_swiglu(gate_up: torch.Tensor, limit: float, alpha: float) -> torch.Tensor:
    """`gate_up` [..., 2 * I] carries gate and up INTERLEAVED on the last dim (gate at ::2,
    up at 1::2, as HF's GptOssExperts packs them). -> [..., I]."""
    gate = gate_up[..., ::2].clamp(max=limit)
    up = gate_up[..., 1::2].clamp(min=-limit, max=limit)
    return (up + 1) * (gate * torch.sigmoid(gate * alpha))


@clamped_swiglu.register_fake
def _fake(gate_up: torch.Tensor, limit: float, alpha: float) -> torch.Tensor:
    del limit, alpha
    return torch.empty(
        *gate_up.shape[:-1], gate_up.shape[-1] // 2, dtype=gate_up.dtype, device=gate_up.device
    )


@clamped_swiglu.samples
def _samples(device: str, dtype: torch.dtype) -> tuple:
    # Scaled past the limit so both clamps bite.
    return (torch.randn(3, 16, device=device, dtype=dtype) * 8, 7.0, 1.702)


def _backward(ctx: object, grad: torch.Tensor) -> tuple:
    del ctx, grad
    raise NotImplementedError("backward: training deferred (branch integrate/train-step)")


clamped_swiglu.register_autograd(_backward)



@clamped_swiglu.register("liger", source="liger_kernel.ops.swiglu")
def _liger(*args: object) -> torch.Tensor:
    del args
    raise NotImplementedError(
        "clamped_swiglu[liger]: not vendored into this tree yet"
    )
