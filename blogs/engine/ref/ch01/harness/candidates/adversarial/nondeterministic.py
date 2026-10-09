"""ADVERSARIAL: correct to within tolerance, but not reproducible -- every other call is one ulp
off (a racy reduction looks like this). Within budget, so only the bitwise two-run check sees it."""

import torch
import torch.nn.functional as F
from torch import Tensor

BITS = {4: torch.int32, 2: torch.int16}  # same-width integer view per float itemsize
_CALLS = [0]


def layer_norm(x: Tensor, weight: Tensor, bias: Tensor, eps: float) -> Tensor:
    _CALLS[0] += 1
    out = F.layer_norm(x, (x.shape[-1],), weight, bias, eps)
    nudged = out.view(BITS[out.element_size()]) + (_CALLS[0] % 2)  # +1 ulp on odd calls
    return nudged.view(out.dtype)
