"""Correct linear candidate: torch's F.linear (which wants [out, in] weights, so transpose GPT-2's [in, out])."""

import torch.nn.functional as F
from torch import Tensor


def linear(x: Tensor, weight: Tensor, bias: Tensor) -> Tensor:
    return F.linear(x, weight.T, bias)
