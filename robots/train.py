"""Training step + RL-specific loss functions and eval utilities."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

import gymnasium
import torch

from robots.models import PolicyWeights, policy_act, policy_forward
from robots.optim import AdamParams, OptimizerHandle, ParamGroup, make_optimizer
from robots.rollout import PolicyStep

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
# RL-specific: loss functions, returns, eval
# ---------------------------------------------------------------------------

def compute_returns(steps: list[PolicyStep], gamma: float = 0.99) -> list[float]:
    """Discounted returns, computed backwards."""
    returns: list[float] = []
    g = 0.0
    for step in reversed(steps):
        g = step.reward + gamma * g * (1.0 - float(step.done))
        returns.insert(0, g)
    return returns


def reinforce_loss(
    pi: PolicyWeights,
    batch: list[PolicyStep],
) -> tuple[torch.Tensor, dict[str, float]]:
    """REINFORCE with baseline. Computes returns internally.

    Returns (loss, metrics_dict).
    """
    returns = compute_returns(batch)
    loss = torch.tensor(0.0)
    entropies: list[float] = []
    value_errors: list[float] = []
    advantages: list[float] = []
    for step, ret in zip(batch, returns, strict=True):
        advantage = ret - step.value
        advantages.append(advantage)
        value_errors.append((ret - step.value) ** 2)
        logits, _ = policy_forward(pi, step.obs.unsqueeze(0))  # (1, act_dim)
        dist = torch.distributions.Categorical(logits=logits)
        entropies.append(dist.entropy().item())
        logprob = dist.log_prob(torch.tensor(step.action))
        loss = loss - logprob * advantage
    n = len(batch)
    adv_t = torch.tensor(advantages)
    m = {
        "pi_loss": (loss / n).item(),
        "entropy": sum(entropies) / n,
        "value_loss": sum(value_errors) / n,
        "advantage_mean": adv_t.mean().item(),
        "advantage_std": adv_t.std().item() if n > 1 else 0.0,
    }
    return loss / n, m



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


