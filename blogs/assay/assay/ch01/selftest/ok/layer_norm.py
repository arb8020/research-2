"""Correct layer_norm candidate: torch's fused kernel."""

import torch.nn.functional as F
from torch import Tensor


def layer_norm(x: Tensor, weight: Tensor, bias: Tensor, eps: float) -> Tensor:
    return F.layer_norm(x, (x.shape[-1],), weight, bias, eps)
