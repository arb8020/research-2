"""PLANTED BUG: layer_norm normalizes over rows (dim 0) instead of the hidden dim."""

import torch
from torch import Tensor


def layer_norm(x: Tensor, weight: Tensor, bias: Tensor, eps: float) -> Tensor:
    mean = x.mean(dim=0, keepdim=True)
    var = ((x - mean) ** 2).mean(dim=0, keepdim=True)
    return (x - mean) / torch.sqrt(var + eps) * weight + bias
