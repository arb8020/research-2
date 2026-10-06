"""Training step + RL-specific loss functions and eval utilities."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, TypeAlias, TypeVar

import gymnasium
import torch
import torch.nn.functional as F

from robots.collect import Batch, Step
from robots.models import PolicyWeights, ValueWeights, policy_act, policy_forward, value_forward
from robots.core import AdamParams, AdamState, adam_scalars, adam_update_, init_adam
from robots.core import tensor_leaves, tree_map

log = logging.getLogger("robots.train")


# ---------------------------------------------------------------------------
# Generic training step (extract to loop.py when a second caller exists)
#
# Granularity, each level replaceable by a few calls to the one below:
#   train_loop(get_inputs, loss_fn, weights, cfg, num_iters)    the loop owns the int step
#   train_step(loss_fn, weights, opt_state, inputs, cfg, step)
#     = forward_backward(loss_fn, weights, inputs)             -> grads, metrics
#     + adam_update_(weights, grads, opt_state, cfg, adam_scalars(cfg, step, device_of(weights)))
# ---------------------------------------------------------------------------

W = TypeVar("W")
I = TypeVar("I")

# (weights, inputs) -> (scalar loss, metrics). Metrics are tensors so a LossFn
# stays torch.func-safe (no .item()); convert with to_floats at the logging edge.
LossFn = Callable[[W, I], tuple[torch.Tensor, dict[str, torch.Tensor]]]
Metrics = dict[str, torch.Tensor]


def forward_backward(
    loss_fn: LossFn[W, I],
    weights: W,
    inputs: I,
) -> tuple[W, Metrics]:
    """Gradients of loss_fn w.r.t. weights, plus the loss_fn's metrics.

    grads has the same dataclass type as weights (one grad tensor per weight
    tensor). Nothing is mutated: no .grad, no optimizer. Requires the weight
    dataclass to be a registered pytree (robots.core.register_pytree).
    metrics gains a "loss" entry.
    """
    grad_fn = torch.func.grad_and_value(loss_fn, argnums=0, has_aux=True)
    grads, (loss, metrics) = grad_fn(weights, inputs)
    assert type(grads) is type(weights)
    assert "loss" not in metrics
    return grads, {**metrics, "loss": loss.detach()}


def forward_backward_accum(
    loss_fn: LossFn[W, I],
    weights: W,
    micro_inputs: list[I],
) -> tuple[W, Metrics]:
    """forward_backward averaged over micro-batches (gradient accumulation).

    Equal to one forward_backward on the concatenated batch when loss_fn is a
    mean and the micro-batches are the same size.
    """
    assert len(micro_inputs) > 0
    n = len(micro_inputs)
    grads, metrics = forward_backward(loss_fn, weights, micro_inputs[0])
    for inputs in micro_inputs[1:]:
        g, m = forward_backward(loss_fn, weights, inputs)
        grads = tree_map(torch.add, grads, g)
        metrics = {k: metrics[k] + m[k] for k in metrics}
    return tree_map(lambda x: x / n, grads), {k: v / n for k, v in metrics.items()}


def device_of(weights: Any) -> torch.device:
    """The device of a weight tree (asserts all leaves agree)."""
    leaves = tensor_leaves(weights)
    assert len(leaves) > 0
    device = leaves[0].device
    assert all(x.device == device for x in leaves), "weights span multiple devices"
    return device


def train_step(
    loss_fn: LossFn[W, I],
    weights: W,
    opt_state: AdamState[W],
    inputs: I,
    cfg: AdamParams,
    step: int,
) -> tuple[AdamState[W], Metrics]:
    """One update: forward_backward, then Adam in place on weights. step is 1-based."""
    grads, metrics = forward_backward(loss_fn, weights, inputs)
    scalars = adam_scalars(cfg, step, device_of(weights))
    new_state = adam_update_(weights, grads, opt_state, cfg, scalars)
    return new_state, metrics


def to_floats(metrics: Metrics) -> dict[str, float]:
    """Logging edge: tensor metrics -> Python floats (one host sync per metric)."""
    return {k: v.item() for k, v in metrics.items()}


OnIter = Callable[[int, Metrics], None]


def train_loop(
    get_inputs: Callable[[], I],
    loss_fn: LossFn[W, I],
    weights: W,
    cfg: AdamParams = AdamParams(),
    num_iters: int = 100,
    grad_accum_steps: int = 1,
    on_iter: OnIter | None = None,
) -> tuple[AdamState[W], list[Metrics]]:
    """Get inputs, update weights in place, repeat. Owns the 1-based step counter.

    With grad_accum_steps > 1, each step averages grads over that many
    get_inputs() micro-batches. Returns (final optimizer state, metrics history).
    """
    assert num_iters >= 0
    assert grad_accum_steps >= 1
    opt_state = init_adam(weights)
    device = device_of(weights)
    history: list[Metrics] = []
    for step in range(1, num_iters + 1):
        micro_inputs = [get_inputs() for _ in range(grad_accum_steps)]
        grads, m = forward_backward_accum(loss_fn, weights, micro_inputs)
        opt_state = adam_update_(weights, grads, opt_state, cfg, adam_scalars(cfg, step, device))
        if on_iter is not None:
            on_iter(step, m)
        history.append(m)
    return opt_state, history


# ---------------------------------------------------------------------------
# RL-specific: batch -> loss inputs (pure)
# ---------------------------------------------------------------------------

# A processed Batch (Tinker style: named tensors, losses read the keys they need).
# compute_loss_fn_inputs produces:
#   "obs"        (T, obs_dim) float
#   "actions"    (T,) long
#   "returns"    (T,) value target
#   "advantages" (T,) returns - collected V(obs); constants, no grad
LossFnInputs: TypeAlias = dict[str, torch.Tensor]


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
        # Invalid state: a real ending has no future to bootstrap from.
        assert not step.terminated or step.bootstrap_value == 0.0, step
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
    return {
        "obs": torch.stack([s.obs for s in batch.steps]),
        "actions": torch.tensor([s.action for s in batch.steps], dtype=torch.long),
        "returns": returns,
        "advantages": returns - values,
    }


# ---------------------------------------------------------------------------
# RL-specific: losses. All (weights, inputs) -> (loss, metrics), torch.func-safe:
# no .item(), no data-dependent Python control flow, metrics are tensors.
# Policy and value are separate weight objects, trained by separate train_steps.
# ---------------------------------------------------------------------------

def reinforce_loss(
    pi: PolicyWeights,
    inputs: LossFnInputs,
) -> tuple[torch.Tensor, dict[str, torch.Tensor]]:
    """Policy-gradient term: mean(-log pi(a|s) * advantage). Reads obs, actions, advantages."""
    logits = policy_forward(pi, inputs["obs"])                                      # (T, act_dim)
    log_probs_all = F.log_softmax(logits, dim=-1)                                   # (T, act_dim)
    logprob = log_probs_all.gather(1, inputs["actions"].unsqueeze(1)).squeeze(1)    # (T,)
    entropy = -(log_probs_all.exp() * log_probs_all).sum(dim=-1)                    # (T,)
    advantages = inputs["advantages"].detach()
    loss = -(logprob * advantages).mean()
    metrics = {
        "pi_loss": loss.detach(),
        "entropy": entropy.mean().detach(),
        "advantage_mean": advantages.mean(),
        "advantage_std": advantages.std(correction=0),
    }
    return loss, metrics


def value_loss(
    vf: ValueWeights,
    inputs: LossFnInputs,
) -> tuple[torch.Tensor, dict[str, torch.Tensor]]:
    """Value regression: mean((V(obs) - return)^2). Reads obs, returns."""
    values = value_forward(vf, inputs["obs"])                                       # (T,)
    returns = inputs["returns"].detach()
    loss = ((values - returns) ** 2).mean()
    metrics = {
        "value_loss": loss.detach(),
        "value_mean": values.mean().detach(),
        "return_mean": returns.mean(),
    }
    return loss, metrics


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


