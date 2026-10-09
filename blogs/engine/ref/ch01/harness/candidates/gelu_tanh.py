"""Correct gelu_tanh candidate: torch's GELU with the tanh approximation."""

import torch.nn.functional as F
from torch import Tensor

from specs.gelu_tanh import gelu_tanh as spec


@spec.register("torch", source="torch.nn.functional.gelu")
def gelu_tanh(x: Tensor) -> Tensor:
    return F.gelu(x, approximate="tanh")
