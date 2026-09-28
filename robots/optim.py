"""Adam as data + pure functions (optax-style). No torch.optim dependency.

Two granularities, each usable alone:
  adam_update(params, grads, state, cfg, scalars) -> (new_params, new_state)   pure, never mutates
  adam_update_(params, grads, state, cfg, scalars) -> state                    adam_update + tree_copy_

The loop owns the step counter (a Python int). Per step, on the host:
  scalars = adam_scalars(cfg, step, device)   # lr (schedule), bias corrections as 0-d tensors
so a compiled step sees only tensors and never recompiles as step/lr change.

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

from robots.tree import register_pytree, tensor_leaves, tree_copy_, tree_map

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
    """First/second moments, same tree type as the weights. Tensors only; no step.

    The step counter is a plain Python int owned by the training loop, turned into
    tensors by adam_scalars. Keeping it out of the state keeps the compiled region
    free of Python scalars that change every call (which would force recompiles).
    """

    m: W  # first moment (mean of gradients)
    v: W  # second moment (mean of squared gradients)


@register_pytree
@dataclass(frozen=True)
class AdamScalars:
    """This step's per-step numbers as 0-d float32 tensors (compiled graphs take them as inputs)."""

    lr: torch.Tensor  # learning rate for this step
    bc1: torch.Tensor  # 1 - beta1^step
    bc2: torch.Tensor  # 1 - beta2^step


def adam_scalars(cfg: AdamParams, step: int, device: torch.device | str) -> AdamScalars:
    """Host side: per-step lr and bias corrections for a 1-based step, on `device`.

    `device` should be the params' device so the compiled step never does an
    implicit host->device copy. lr_schedule(step) runs here as plain Python.
    """
    assert step >= 1, f"step is 1-based, got {step}"
    lr = cfg.lr_schedule(step) if cfg.lr_schedule is not None else cfg.lr
    assert lr >= 0.0, f"negative lr {lr} at step {step}"

    def scalar(x: float) -> torch.Tensor:
        return torch.tensor(x, dtype=torch.float32, device=device)

    return AdamScalars(lr=scalar(lr), bc1=scalar(1.0 - cfg.beta1**step), bc2=scalar(1.0 - cfg.beta2**step))


def init_adam(params: W) -> AdamState[W]:
    """Zero moments shaped like params."""
    return AdamState(m=tree_map(torch.zeros_like, params), v=tree_map(torch.zeros_like, params))


def adam_update(
    params: W, grads: W, state: AdamState[W], cfg: AdamParams, scalars: AdamScalars
) -> tuple[W, AdamState[W]]:
    """One Adam step as a pure function. Never mutates params, grads or state.

    Matches torch.optim.Adam (no weight decay, no amsgrad) to float tolerance:
      m     = beta1 * m + (1 - beta1) * g
      v     = beta2 * v + (1 - beta2) * g^2
      param = param - lr * (m / bc1) / (sqrt(v / bc2) + eps)
    betas and eps come from cfg (compile-time constants); lr/bc1/bc2 from scalars
    (graph inputs). Build scalars with adam_scalars(cfg, step, device).

    Autograd-transparent: if params require grad, outputs carry a graph. Looping
    the pure path on requires_grad weights therefore grows one autograd graph
    across steps; detach, use torch.no_grad(), or keep weights requires_grad=False
    (torch.func.grad does not need it).

    Per-group settings (e.g. a different lr for embeddings): call adam_update on
    each subtree with its own cfg/scalars.
    """
    b1, b2, eps = cfg.beta1, cfg.beta2, cfg.eps
    lr, bc1, bc2 = scalars.lr, scalars.bc1, scalars.bc2
    m = tree_map(lambda m_, g: b1 * m_ + (1.0 - b1) * g, state.m, grads)
    v = tree_map(lambda v_, g: b2 * v_ + (1.0 - b2) * g * g, state.v, grads)
    new_params = tree_map(
        lambda p, m_, v_: p - lr * (m_ / bc1) / ((v_ / bc2).sqrt() + eps),
        params, m, v,
    )
    return new_params, AdamState(m=m, v=v)


def _assert_no_shared_storage(*trees: Any) -> None:
    storages = [x.untyped_storage().data_ptr() for x in tensor_leaves(trees)]
    assert len(set(storages)) == len(storages), "params/m/v share storage; in-place update would corrupt them"


def adam_update_(
    params: W, grads: W, state: AdamState[W], cfg: AdamParams, scalars: AdamScalars
) -> AdamState[W]:
    """Donating Adam step: adam_update, then copy_ results into params, state.m, state.v.

    Returns `state` itself (its m/v tensors now hold the updated values).
    Runs under torch.no_grad(): an in-place optimizer write is never differentiable,
    and params created with requires_grad=True would otherwise reject copy_.
    torch.compile(fullgraph=True)-friendly; compiled, it becomes in-place kernels.
    """
    if not torch.compiler.is_compiling():  # storage introspection is eager-only
        _assert_no_shared_storage(params, state.m, state.v)
    with torch.no_grad():
        new_params, new_state = adam_update(params, grads, state, cfg, scalars)
        tree_copy_(params, new_params)
        tree_copy_(state.m, new_state.m)
        tree_copy_(state.v, new_state.v)
    return state
