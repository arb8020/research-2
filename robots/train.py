"""Training step + RL-specific loss functions and eval utilities."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TypeVar

import gymnasium
import torch
import torch.nn.functional as F

from robots.collect import Batch, Step
from robots.models import PolicyWeights, policy_act, policy_forward
from robots.optim import AdamParams, OptimizerHandle, ParamGroup, make_optimizer

log = logging.getLogger("robots.train")


# ---------------------------------------------------------------------------
# Generic training loop (extract to loop.py when a second caller exists)
# ---------------------------------------------------------------------------

GetBatch = Callable[[], Any]
LossFn = Callable[[Any, Any], tuple[torch.Tensor, dict[str, float]]]


def train_step(
    get_batch: GetBatch,
    loss_fn: LossFn,
    weights: Any,
    opt: OptimizerHandle,
    grad_accum_steps: int = 1,
) -> dict[str, float]:
    """One training step: get batch(es), compute loss, update weights.

    With grad_accum_steps > 1, accumulates gradients across multiple
    micro-batches before stepping. Metrics are averaged across micro-batches.
    """
    opt.zero()
    m_accum: dict[str, float] = {}
    for micro in range(grad_accum_steps):
        batch = get_batch()
        loss, m = loss_fn(weights, batch)
        (loss / grad_accum_steps).backward()
        for k, v in m.items():
            m_accum[k] = m_accum.get(k, 0.0) + v / grad_accum_steps
    opt.step()
    return m_accum


OnIter = Callable[[int, dict[str, float]], None]


def train_loop(
    get_batch: GetBatch,
    loss_fn: LossFn,
    weights: Any,
    params: list[torch.Tensor] | None = None,
    optimizer: AdamParams | list[ParamGroup] = AdamParams(),
    num_iters: int = 100,
    grad_accum_steps: int = 1,
    on_iter: OnIter | None = None,
) -> list[dict[str, float]]:
    """Generic: get batch, compute loss, update weights, repeat.

    Returns the full metrics history.
    """
    opt = make_optimizer(params, optimizer)
    history: list[dict[str, float]] = []
    for i in range(num_iters):
        m = train_step(get_batch, loss_fn, weights, opt, grad_accum_steps)
        if on_iter is not None:
            on_iter(i + 1, m)
        history.append(m)
    return history


# ---------------------------------------------------------------------------
# Generic: gradients as data (torch.func)
# ---------------------------------------------------------------------------

W = TypeVar("W")
I = TypeVar("I")
FuncLossFn = Callable[[W, I], tuple[torch.Tensor, dict[str, torch.Tensor]]]


def forward_backward(
    loss_fn: FuncLossFn[W, I],
    weights: W,
    inputs: I,
) -> tuple[W, dict[str, torch.Tensor]]:
    """Gradients of loss_fn w.r.t. weights, plus the loss_fn's metrics.

    grads has the same dataclass type as weights (one grad tensor per weight
    tensor). Nothing is mutated: no .grad, no optimizer. Requires the weight
    dataclass to be registered as a pytree. metrics gains a "loss" entry.
    """
    grad_fn = torch.func.grad_and_value(loss_fn, argnums=0, has_aux=True)
    grads, (loss, metrics) = grad_fn(weights, inputs)
    assert type(grads) is type(weights)
    assert "loss" not in metrics
    return grads, {**metrics, "loss": loss.detach()}


# ---------------------------------------------------------------------------
# RL-specific: batch -> loss inputs (pure)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class LossFnInputs:
    """A processed Batch: exactly the per-step tensors the RL losses read."""

    obs: torch.Tensor         # (T, obs_dim)
    actions: torch.Tensor     # (T,) long
    logprobs: torch.Tensor    # (T,) log pi_old(a|s) from collection time (for PPO ratios)
    returns: torch.Tensor     # (T,) value target
    advantages: torch.Tensor  # (T,) returns - collected V(obs); constants, no grad


def compute_returns(steps: list[Step], last_value: float, gamma: float) -> list[float]:
    """Discounted, bootstrapped returns, computed backwards.

    Where the future comes from, per step:
        episode ended here (terminated or truncated) -> step.bootstrap_value
            (0.0 on termination, V(next_obs) on truncation — recorded at collection)
        otherwise -> the next step's return (last_value for the batch's final step)
    """
    assert 0.0 <= gamma <= 1.0
    returns: list[float] = []
    g = last_value
    for step in reversed(steps):
        ended = step.terminated or step.truncated
        future = step.bootstrap_value if ended else g
        g = step.reward + gamma * future
        returns.append(g)
    returns.reverse()
    return returns


def compute_loss_fn_inputs(batch: Batch, gamma: float) -> LossFnInputs:
    """Batch -> LossFnInputs. Pure: no network calls, everything was recorded at collection."""
    assert len(batch.steps) > 0
    returns = torch.tensor(compute_returns(batch.steps, batch.last_value, gamma), dtype=torch.float32)
    values = torch.tensor([s.value for s in batch.steps], dtype=torch.float32)
    return LossFnInputs(
        obs=torch.stack([s.obs for s in batch.steps]),
        actions=torch.tensor([s.action for s in batch.steps], dtype=torch.long),
        logprobs=torch.tensor([s.logprob for s in batch.steps], dtype=torch.float32),
        returns=returns,
        advantages=returns - values,
    )


# ---------------------------------------------------------------------------
# RL-specific: losses. All (weights, inputs) -> (loss, metrics), torch.func-safe:
# no .item(), no data-dependent Python control flow, metrics are tensors.
#
#   *_from_logits / *_from_values: the loss term given a forward pass you already did
#   reinforce_loss / value_loss:   one forward + one term
#   actor_critic_loss:             one forward + both terms
# ---------------------------------------------------------------------------

def reinforce_loss_from_logits(
    logits: torch.Tensor,
    inputs: LossFnInputs,
) -> tuple[torch.Tensor, dict[str, torch.Tensor]]:
    """Policy-gradient term: mean(-log pi(a|s) * advantage). logits (T, act_dim)."""
    log_probs_all = F.log_softmax(logits, dim=-1)                                   # (T, act_dim)
    logprob = log_probs_all.gather(1, inputs.actions.unsqueeze(1)).squeeze(1)       # (T,)
    entropy = -(log_probs_all.exp() * log_probs_all).sum(dim=-1)                    # (T,)
    advantages = inputs.advantages.detach()
    loss = -(logprob * advantages).mean()
    metrics = {
        "pi_loss": loss.detach(),
        "entropy": entropy.mean().detach(),
        "advantage_mean": advantages.mean(),
        "advantage_std": advantages.std(correction=0),
    }
    return loss, metrics


def value_loss_from_values(
    values: torch.Tensor,
    inputs: LossFnInputs,
) -> tuple[torch.Tensor, dict[str, torch.Tensor]]:
    """Value regression term: mean((V(s) - return)^2). values (T,)."""
    loss = ((values - inputs.returns.detach()) ** 2).mean()
    metrics = {
        "value_loss": loss.detach(),
        "value_mean": values.mean().detach(),
        "return_mean": inputs.returns.mean(),
    }
    return loss, metrics


def reinforce_loss(
    pi: PolicyWeights,
    inputs: LossFnInputs,
) -> tuple[torch.Tensor, dict[str, torch.Tensor]]:
    """Classic REINFORCE (with the collected value as baseline). Does not train the value head."""
    logits, _ = policy_forward(pi, inputs.obs)
    return reinforce_loss_from_logits(logits, inputs)


def value_loss(
    pi: PolicyWeights,
    inputs: LossFnInputs,
) -> tuple[torch.Tensor, dict[str, torch.Tensor]]:
    """Trains V(obs) toward the bootstrapped returns."""
    _, values = policy_forward(pi, inputs.obs)
    return value_loss_from_values(values, inputs)


def actor_critic_loss(
    pi: PolicyWeights,
    inputs: LossFnInputs,
    vf_coef: float = 0.5,
) -> tuple[torch.Tensor, dict[str, torch.Tensor]]:
    """reinforce_loss + vf_coef * value_loss, sharing one forward pass."""
    logits, values = policy_forward(pi, inputs.obs)
    pg, pg_metrics = reinforce_loss_from_logits(logits, inputs)
    vl, v_metrics = value_loss_from_values(values, inputs)
    return pg + vf_coef * vl, {**pg_metrics, **v_metrics}


# ---------------------------------------------------------------------------
# Eval + record
# ---------------------------------------------------------------------------

def evaluate(env: gymnasium.Env, pi: PolicyWeights, num_episodes: int = 3) -> tuple[float, float]:
    """Run policy in real env, return (mean reward, mean episode length)."""
    total = 0.0
    total_len = 0
    for _ in range(num_episodes):
        obs, _ = env.reset()
        obs_t = torch.tensor(obs, dtype=torch.float32)
        ep_reward = 0.0
        ep_len = 0
        done = False
        while not done:
            action = policy_act(pi, obs_t)
            obs, reward, terminated, truncated, _ = env.step(action)
            obs_t = torch.tensor(obs, dtype=torch.float32)
            ep_reward += reward
            ep_len += 1
            done = terminated or truncated
        total += ep_reward
        total_len += ep_len
    return total / num_episodes, total_len / num_episodes


def record_episode(env: gymnasium.Env, pi: PolicyWeights) -> dict[str, Any]:
    """Play one greedy episode and return it as a trajectory artifact payload."""
    obs, _ = env.reset()
    observations: list[list[float]] = [[float(x) for x in obs]]
    actions: list[int] = []
    rewards: list[float] = []

    done = False
    while not done:
        action = policy_act(pi, torch.tensor(obs, dtype=torch.float32))
        obs, reward, terminated, truncated, _ = env.step(action)
        actions.append(int(action))
        rewards.append(float(reward))
        observations.append([float(x) for x in obs])
        done = terminated or truncated

    return {
        "env": env.spec.id if env.spec is not None else "unknown",
        "obs": observations,
        "actions": actions,
        "rewards": rewards,
    }


