"""Adam as data + pure functions (optax-style). No torch.optim dependency.

Two granularities, each usable alone:
  adam_update(params, grads, state, cfg) -> (new_params, new_state)   pure, never mutates
  adam_update_(params, grads, state, cfg) -> new_state                adam_update + tree_copy_

adam_update_ is exactly `adam_update` followed by `tree_copy_` into params, m, v.
Eager it is just the pure math plus a copy (debuggable, ~2x memory for the step).
Inside torch.compile(fullgraph=True) the copy_ is an input mutation, and Inductor
fuses math + writeback into kernels that read and write the input buffers in place
(no full-size temporaries). A pure compiled update cannot do that: Inductor must
allocate fresh outputs because it cannot know the caller drops the old tensors.
torch has no JAX-style donate_argnums; copy_ inside the compiled region is the
equivalent.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

import torch

from robots.tree import register_pytree, tree_copy_, tree_map

W = TypeVar("W")  # a weight tree: frozen dataclass of tensors (registered pytree)


@dataclass(frozen=True)
class AdamParams:
    """Optimizer config. Data, not state.

    lr_schedule overrides lr when set: called with the 1-based step number, returns lr.
    """

    lr: float = 3e-4
    beta1: float = 0.9
    beta2: float = 0.999
    eps: float = 1e-8
    lr_schedule: Callable[[int], float] | None = None


@register_pytree
@dataclass(frozen=True)
class AdamState(Generic[W]):
    """First/second moments (same tree type as the weights) + completed step count.

    Registered as a pytree: m and v are children, step is static context.
    """

    m: W  # first moment (mean of gradients)
    v: W  # second moment (mean of squared gradients)
    step: int  # number of updates applied so far


def init_adam(params: W) -> AdamState[W]:
    """Zero moments shaped like params, step 0."""
    return AdamState(
        m=tree_map(torch.zeros_like, params),
        v=tree_map(torch.zeros_like, params),
        step=0,
    )


def adam_update(params: W, grads: W, state: AdamState[W], cfg: AdamParams) -> tuple[W, AdamState[W]]:
    """One Adam step as a pure function. Never mutates params, grads or state.

    Matches torch.optim.Adam (no weight decay, no amsgrad) to float tolerance:
      t     = step + 1
      m     = beta1 * m + (1 - beta1) * g
      v     = beta2 * v + (1 - beta2) * g^2
      param = param - lr * (m / (1 - beta1^t)) / (sqrt(v / (1 - beta2^t)) + eps)

    Autograd-transparent: if inputs require grad, the outputs carry a graph.
    """
    assert state.step >= 0, f"negative step {state.step}"
    t = state.step + 1
    lr = cfg.lr_schedule(t) if cfg.lr_schedule is not None else cfg.lr
    b1, b2, eps = cfg.beta1, cfg.beta2, cfg.eps
    bc1 = 1.0 - b1**t
    bc2 = 1.0 - b2**t

    m = tree_map(lambda m_, g: b1 * m_ + (1.0 - b1) * g, state.m, grads)
    v = tree_map(lambda v_, g: b2 * v_ + (1.0 - b2) * g * g, state.v, grads)
    new_params = tree_map(
        lambda p, m_, v_: p - lr * (m_ / bc1) / ((v_ / bc2).sqrt() + eps),
        params, m, v,
    )
    return new_params, AdamState(m=m, v=v, step=t)


def adam_update_(params: W, grads: W, state: AdamState[W], cfg: AdamParams) -> AdamState[W]:
    """Donating Adam step: adam_update, then copy_ results into params, state.m, state.v.

    Returns the new state, whose m/v are the SAME tensors as state.m/state.v
    (now holding updated values) and whose step is state.step + 1.
    Runs under torch.no_grad(): an in-place optimizer write is never differentiable,
    and params created with requires_grad=True would otherwise reject copy_.
    torch.compile(fullgraph=True)-friendly; compiled, it becomes in-place kernels.
    """
    with torch.no_grad():
        new_params, new_state = adam_update(params, grads, state, cfg)
        tree_copy_(params, new_params)
        tree_copy_(state.m, new_state.m)
        tree_copy_(state.v, new_state.v)
    return AdamState(m=state.m, v=state.v, step=new_state.step)
