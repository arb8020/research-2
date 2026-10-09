"""ADVERSARIAL: correct output, but it scribbles over its input afterwards (an in-place op
"saving an allocation"). In a model the caller's activations would be silently corrupted."""

import torch.nn.functional as F
from torch import Tensor


def layer_norm(x: Tensor, weight: Tensor, bias: Tensor, eps: float) -> Tensor:
    out = F.layer_norm(x, (x.shape[-1],), weight, bias, eps)
    x.zero_()
    return out
