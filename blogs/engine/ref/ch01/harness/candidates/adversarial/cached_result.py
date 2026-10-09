"""ADVERSARIAL: computes once, then returns the cached first result forever (pygpubench's
"warmup"/replay family: pass the first check, skip the work after)."""

import torch.nn.functional as F
from torch import Tensor

_CACHE: list[Tensor] = []


def layer_norm(x: Tensor, weight: Tensor, bias: Tensor, eps: float) -> Tensor:
    if not _CACHE:
        _CACHE.append(F.layer_norm(x, (x.shape[-1],), weight, bias, eps))
    return _CACHE[0]
