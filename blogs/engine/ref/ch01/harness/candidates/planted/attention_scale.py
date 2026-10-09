"""PLANTED BUG: attention scaled by 1/head_dim instead of 1/sqrt(head_dim)."""

import torch
from torch import Tensor


def causal_attention(q: Tensor, k: Tensor, v: Tensor) -> Tensor:
    seq = q.shape[-2]
    scores = q @ k.transpose(-1, -2) / q.shape[-1]
    allowed = torch.ones(seq, seq, dtype=torch.bool).tril()
    return torch.softmax(scores.masked_fill(~allowed, float("-inf")), dim=-1) @ v
