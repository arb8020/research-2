"""kelpie::gelu -- the tanh-approximate GELU (gpt2's MLP activation).

Torch has `F.gelu`; kelpie declares its own so nothing registers on `aten::gelu`. The contract
pins `approximate="tanh"`: that is the only variant any kelpie model uses, so it is a fact of
the op rather than an argument every adapter has to honour.
"""

from __future__ import annotations

import torch
import torch.nn.functional as F

from kelpie_models.kernels.op import op


@op
def gelu(x: torch.Tensor) -> torch.Tensor:
    """0.5x(1 + tanh(sqrt(2/pi)(x + 0.044715 x^3))) -- HF's `gelu_new`. -> x's shape/dtype."""
    return F.gelu(x, approximate="tanh")


@gelu.register_fake
def _fake(x: torch.Tensor) -> torch.Tensor:
    return torch.empty_like(x)


@gelu.samples
def _samples(device: str, dtype: torch.dtype) -> tuple:
    return (torch.randn(4, 8, device=device, dtype=dtype),)


def _backward(ctx: object, grad: torch.Tensor) -> tuple:
    del ctx, grad
    raise NotImplementedError("backward: training deferred (branch integrate/train-step)")


gelu.register_autograd(_backward)


@gelu.register("metal", source="kernels.vendored.mps._metal.gelu")
def _metal(x: torch.Tensor) -> torch.Tensor:
    from kelpie_models.kernels.vendored.mps._metal import gelu as kernel

    return kernel(x)
