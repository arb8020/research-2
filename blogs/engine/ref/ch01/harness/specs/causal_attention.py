"""causal_attention: softmax(Q K^T / sqrt(head_dim)) V, each position seeing itself and the past."""

from __future__ import annotations

import math

import torch
from jaxtyping import Float
from torch import Tensor

from harness.registry import op


# seq=1 is a single query (decode-like); 16/17 straddle a tile; head_dim=1 makes the scale a
# no-op, so the sweep must also cross head_dim 8/64 with seq > 1 (pairwise does).
@op(dims={"batch": (1, 2, 3), "heads": (1, 2, 12), "seq": (1, 2, 7, 16, 17, 64),
          "head_dim": (1, 8, 64)},
    dtypes=(torch.float32, torch.bfloat16))
def causal_attention(q: Float[Tensor, "batch heads seq head_dim"],
                     k: Float[Tensor, "batch heads seq head_dim"],
                     v: Float[Tensor, "batch heads seq head_dim"],
                     ) -> Float[Tensor, "batch heads seq head_dim"]:
    seq = q.shape[-2]
    scores = q @ k.transpose(-1, -2) / math.sqrt(q.shape[-1])
    allowed = torch.ones(seq, seq, dtype=torch.bool).tril()  # key j visible to query i iff j <= i
    masked = scores.masked_fill(~allowed, float("-inf"))
    return torch.softmax(masked, dim=-1) @ v
