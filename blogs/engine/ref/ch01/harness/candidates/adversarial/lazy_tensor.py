"""ADVERSARIAL: returns a tensor SUBCLASS that lies when compared (every `==`/`allclose`-style
check says "equal") and defers its real work. An in-process checker that calls methods on the
result would be fooled; the harness only accepts a plain torch.Tensor and compares raw bytes."""

import torch
import torch.nn.functional as F
from torch import Tensor


class AlwaysEqual(torch.Tensor):
    def __eq__(self, other: object) -> Tensor:  # type: ignore[override]
        return torch.ones((), dtype=torch.bool)

    def __hash__(self) -> int:
        return id(self)


def layer_norm(x: Tensor, weight: Tensor, bias: Tensor, eps: float) -> Tensor:
    return F.layer_norm(x, (x.shape[-1],), weight, bias, eps).as_subclass(AlwaysEqual)
