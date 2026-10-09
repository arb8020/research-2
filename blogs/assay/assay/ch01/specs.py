"""Chapter 1's op specs: each body is the reference (plain torch math), each annotation names the dims the sweep sizes.
Signatures are the reader's: `gpt2.py` defines functions with these names and arguments, and a check binds by name.
Linear weights use GPT-2's checkpoint layout ([in, out], applied as x @ W), so the reader's file needs no transposes.
"""

from __future__ import annotations

import math

import torch
from jaxtyping import Float
from torch import Tensor

from assay.ch01.registry import op

BOTH = (torch.float32, torch.bfloat16)


# 768 -> 2304 is gpt2's qkv projection; 1 and 7 are the odd edges.
@op(dims={"rows": (1, 3, 17, 64), "in_features": (1, 7, 768), "out_features": (1, 5, 2304)}, dtypes=BOTH)
def linear(x: Float[Tensor, "rows in_features"], weight: Float[Tensor, "in_features out_features"],
           bias: Float[Tensor, "out_features"]) -> Float[Tensor, "rows out_features"]:
    return x @ weight + bias


@op(dims={"rows": (1, 3, 64), "cols": (1, 7, 768, 3072)}, dtypes=BOTH)
def gelu(x: Float[Tensor, "rows cols"]) -> Float[Tensor, "rows cols"]:
    """GPT-2's GELU, the tanh approximation: 0.5 x (1 + tanh(sqrt(2/pi) (x + 0.044715 x^3)))."""
    return 0.5 * x * (1.0 + torch.tanh(math.sqrt(2.0 / math.pi) * (x + 0.044715 * x ** 3)))


# rows/hidden = 1 are the degenerate rows (variance exactly 0: only eps keeps it finite); 17 / 769 are tile+1 sizes;
# eps=0.1 makes a missing eps visible.
@op(dims={"rows": (1, 2, 3, 17, 64), "hidden": (1, 3, 7, 64, 769)}, dtypes=BOTH, scalars={"eps": (1e-5, 1e-1)})
def layer_norm(x: Float[Tensor, "rows hidden"], weight: Float[Tensor, "hidden"], bias: Float[Tensor, "hidden"],
               eps: float) -> Float[Tensor, "rows hidden"]:
    """(x - mean) / sqrt(var + eps) * weight + bias over the last dim; biased variance."""
    mean = x.mean(dim=-1, keepdim=True)
    var = ((x - mean) ** 2).mean(dim=-1, keepdim=True)
    return (x - mean) / torch.sqrt(var + eps) * weight + bias


# One sequence (the reader's forward is unbatched): [heads, seq, head_dim]. seq=1 is a lone query; 16/17 straddle a
# tile; head_dim=1 makes the scale a no-op, so the sweep must also cross head_dim 8/64 with seq > 1 (pairwise does).
@op(dims={"heads": (1, 2, 12), "seq": (1, 2, 7, 16, 17, 64), "head_dim": (1, 8, 64)}, dtypes=BOTH)
def causal_attention(q: Float[Tensor, "heads seq head_dim"], k: Float[Tensor, "heads seq head_dim"],
                     v: Float[Tensor, "heads seq head_dim"]) -> Float[Tensor, "heads seq head_dim"]:
    """softmax(q k^T / sqrt(head_dim)) v, each position seeing itself and the past."""
    seq = q.shape[-2]
    scores = q @ k.transpose(-1, -2) / math.sqrt(q.shape[-1])
    allowed = torch.ones(seq, seq, dtype=torch.bool, device=q.device).tril()  # key j visible to query i iff j <= i
    return torch.softmax(scores.masked_fill(~allowed, float("-inf")), dim=-1) @ v
