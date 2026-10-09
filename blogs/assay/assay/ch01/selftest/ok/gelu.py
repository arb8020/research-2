"""Correct gelu candidate: torch's GELU with the tanh approximation."""

import torch.nn.functional as F
from torch import Tensor


def gelu(x: Tensor) -> Tensor:
    return F.gelu(x, approximate="tanh")
