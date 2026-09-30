"""Optimizers as data + pure functions. No torch.optim dependency."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import torch


# ---------------------------------------------------------------------------
# Adam config (what the user passes) vs state (what the loop manages)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AdamParams:
    """Optimizer config. Data, not state — pass this to train_loop/run.

    lr_schedule overrides lr when set: called with step number, returns lr.
    """

    lr: float = 3e-4
    beta1: float = 0.9
    beta2: float = 0.999
    eps: float = 1e-8
    lr_schedule: Callable[[int], float] | None = None


@dataclass
class AdamState:
    """Per-parameter running averages. Mutable — updated in place each step."""

    params: list[torch.Tensor]
    m: list[torch.Tensor]  # first moment (mean of gradients)
    v: list[torch.Tensor]  # second moment (mean of squared gradients)
    lr: float = 3e-4
    beta1: float = 0.9
    beta2: float = 0.999
    eps: float = 1e-8
    step: int = 0
    lr_schedule: Callable[[int], float] | None = None


def init_adam(params: list[torch.Tensor], config: AdamParams) -> AdamState:
    """Create optimizer state from config."""
    return AdamState(
        params=params,
        m=[torch.zeros_like(p) for p in params],
        v=[torch.zeros_like(p) for p in params],
        lr=config.lr,
        beta1=config.beta1,
        beta2=config.beta2,
        eps=config.eps,
        lr_schedule=config.lr_schedule,
    )


def set_lr(state: AdamState, lr: float) -> None:
    """Update learning rate (e.g. from a schedule)."""
    state.lr = lr


def adam_step(state: AdamState) -> None:
    """One Adam update. Reads .grad from each param, updates params in place.

    If lr_schedule is set, updates lr before stepping.

    This is the entire algorithm:
      m = beta1 * m + (1 - beta1) * grad          # momentum
      v = beta2 * v + (1 - beta2) * grad^2         # RMS
      m_hat = m / (1 - beta1^t)                     # bias correction
      v_hat = v / (1 - beta2^t)                     # bias correction
      param -= lr * m_hat / (sqrt(v_hat) + eps)     # update
    """
    state.step += 1
    t = state.step

    if state.lr_schedule is not None:
        state.lr = state.lr_schedule(t)

    bc1 = 1.0 - state.beta1 ** t
    bc2 = 1.0 - state.beta2 ** t

    for i, p in enumerate(state.params):
        if p.grad is None:
            continue
        g = p.grad

        state.m[i].mul_(state.beta1).add_(g, alpha=1.0 - state.beta1)
        state.v[i].mul_(state.beta2).addcmul_(g, g, value=1.0 - state.beta2)

        m_hat = state.m[i] / bc1
        v_hat = state.v[i] / bc2
        p.data.add_(m_hat / (v_hat.sqrt() + state.eps), alpha=-state.lr)


def zero_grad(state: AdamState) -> None:
    """Zero all gradients. Separate from step so the caller controls when."""
    for p in state.params:
        if p.grad is not None:
            p.grad.zero_()


# ---------------------------------------------------------------------------
# Param groups: different optimizer configs for different param sets
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ParamGroup:
    """A set of parameters with their own optimizer config."""

    params: list[torch.Tensor]
    optimizer: AdamParams


# ---------------------------------------------------------------------------
# Optimizer handle: (zero, step) pair returned by make_optimizer
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class OptimizerHandle:
    """What the training loop uses. Zero before accumulation, step after."""

    zero: Callable[[], None]
    step: Callable[[], None]


def make_optimizer(
    params: list[torch.Tensor] | None = None,
    config: AdamParams | list[ParamGroup] | None = None,
) -> OptimizerHandle:
    """Build an OptimizerHandle from config.

    Two modes:
      make_optimizer(params, AdamParams(...))     — one optimizer for all params
      make_optimizer(config=[ParamGroup(...), ..]) — per-group optimizers
    """
    if isinstance(config, list):
        # Param groups — each has its own state
        states = [init_adam(g.params, g.optimizer) for g in config]

        def zero_all() -> None:
            for s in states:
                zero_grad(s)

        def step_all() -> None:
            for s in states:
                adam_step(s)

        return OptimizerHandle(zero=zero_all, step=step_all)

    if isinstance(config, AdamParams):
        if params is None:
            raise ValueError("params required when config is AdamParams")
        state = init_adam(params, config)
        return OptimizerHandle(
            zero=lambda: zero_grad(state),
            step=lambda: adam_step(state),
        )

    raise TypeError(f"Unknown optimizer config: {type(config).__name__}")
