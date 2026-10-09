"""Correct linear candidate: torch's F.linear."""

import torch.nn.functional as F
from torch import Tensor

from specs.linear import linear as spec


@spec.register("torch", source="torch.nn.functional.linear")
def linear(x: Tensor, weight: Tensor, bias: Tensor) -> Tensor:
    return F.linear(x, weight, bias)
