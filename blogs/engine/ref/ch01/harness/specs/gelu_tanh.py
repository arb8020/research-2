"""gelu_tanh: GPT-2's GELU, the tanh approximation (not the exact erf form)."""

from __future__ import annotations

import math

import torch
from jaxtyping import Float
from torch import Tensor

from harness.registry import op


@op(dims={"rows": (1, 3, 64), "cols": (1, 7, 768, 3072)},
    dtypes=(torch.float32, torch.bfloat16))
def gelu_tanh(x: Float[Tensor, "rows cols"]) -> Float[Tensor, "rows cols"]:
    """0.5 x (1 + tanh(sqrt(2/pi) (x + 0.044715 x^3)))."""
    return 0.5 * x * (1.0 + torch.tanh(math.sqrt(2.0 / math.pi) * (x + 0.044715 * x ** 3)))
