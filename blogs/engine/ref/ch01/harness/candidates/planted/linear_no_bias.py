"""PLANTED BUG: linear that forgets the bias."""

from torch import Tensor


def linear(x: Tensor, weight: Tensor, bias: Tensor) -> Tensor:
    return x @ weight.T
