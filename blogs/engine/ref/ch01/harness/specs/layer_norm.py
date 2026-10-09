"""layer_norm: standardize the last dim, then scale and shift. The reference is torch math."""

from __future__ import annotations

import torch
from jaxtyping import Float
from torch import Tensor

from harness.registry import op


# rows/hidden = 1 are the degenerate rows (variance exactly 0: only eps keeps it finite);
# 17 / 769 are tile+1 sizes; 768 is gpt2's width. eps=0.1 makes a missing eps visible.
@op(dims={"rows": (1, 2, 3, 17, 64), "hidden": (1, 3, 7, 64, 769)},
    dtypes=(torch.float32, torch.bfloat16), scalars={"eps": (1e-5, 1e-1)})
def layer_norm(x: Float[Tensor, "rows hidden"], weight: Float[Tensor, "hidden"],
               bias: Float[Tensor, "hidden"], eps: float) -> Float[Tensor, "rows hidden"]:
    """(x - mean) / sqrt(var + eps) * weight + bias over the last dim; biased variance."""
    mean = x.mean(dim=-1, keepdim=True)
    var = ((x - mean) ** 2).mean(dim=-1, keepdim=True)
    return (x - mean) / torch.sqrt(var + eps) * weight + bias
