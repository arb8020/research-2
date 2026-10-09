"""COVERAGE DEMO: numerically correct on every case, but has a fast path for hidden sizes that
are a multiple of 1024 -- a size the sweep never generates -- so that branch never runs."""

import torch.nn.functional as F
from torch import Tensor


def layer_norm(x: Tensor, weight: Tensor, bias: Tensor, eps: float) -> Tensor:
    if x.shape[-1] % 1024 == 0:
        return F.layer_norm(x.float(), (x.shape[-1],), weight.float(), bias.float(), eps).to(x.dtype)
    return F.layer_norm(x, (x.shape[-1],), weight, bias, eps)
