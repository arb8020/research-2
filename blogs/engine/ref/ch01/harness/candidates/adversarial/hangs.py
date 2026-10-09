"""ADVERSARIAL: never returns (a deadlock, or stalling to game a time budget)."""

from torch import Tensor


def layer_norm(x: Tensor, weight: Tensor, bias: Tensor, eps: float) -> Tensor:
    while True:
        pass
