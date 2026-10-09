"""PLANTED BUG: causal mask off by one -- each query also sees the NEXT key."""

import math

import torch
from torch import Tensor


def causal_attention(q: Tensor, k: Tensor, v: Tensor) -> Tensor:
    seq = q.shape[-2]
    scores = q @ k.transpose(-1, -2) / math.sqrt(q.shape[-1])
    allowed = torch.ones(seq, seq, dtype=torch.bool).tril(diagonal=1)
    return torch.softmax(scores.masked_fill(~allowed, float("-inf")), dim=-1) @ v
