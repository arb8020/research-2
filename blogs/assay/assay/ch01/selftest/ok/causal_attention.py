"""Correct causal_attention candidate: torch's scaled_dot_product_attention."""

import torch.nn.functional as F
from torch import Tensor


def causal_attention(q: Tensor, k: Tensor, v: Tensor) -> Tensor:
    return F.scaled_dot_product_attention(q, k, v, is_causal=True)
