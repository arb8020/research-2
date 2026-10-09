"""linear: x W^T + b, torch's weight layout ([out_features, in_features])."""

from __future__ import annotations

import torch
from jaxtyping import Float
from torch import Tensor

from harness.registry import op


# 768 -> 2304 is gpt2's qkv projection; 1 and 7 are the odd edges.
@op(dims={"rows": (1, 3, 17, 64), "in_features": (1, 7, 768), "out_features": (1, 5, 2304)},
    dtypes=(torch.float32, torch.bfloat16))
def linear(x: Float[Tensor, "rows in_features"], weight: Float[Tensor, "out_features in_features"],
           bias: Float[Tensor, "out_features"]) -> Float[Tensor, "rows out_features"]:
    return x @ weight.T + bias
