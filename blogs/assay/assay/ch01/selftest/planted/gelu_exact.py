"""PLANTED BUG: exact (erf) GELU where gpt2 uses the tanh approximation."""

import torch.nn.functional as F
from torch import Tensor


def gelu(x: Tensor) -> Tensor:
    return F.gelu(x)
