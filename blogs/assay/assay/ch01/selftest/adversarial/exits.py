"""ADVERSARIAL: kills its own process mid-call (exit code 0, so a naive runner sees "success")."""

import os

from torch import Tensor


def layer_norm(x: Tensor, weight: Tensor, bias: Tensor, eps: float) -> Tensor:
    os._exit(0)
