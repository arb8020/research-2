"""Neural network weights and forward functions. Data in, data out."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import torch
import torch.nn.functional as F

from robots.tree import register_pytree


# ---------------------------------------------------------------------------
# Shared init helper
# ---------------------------------------------------------------------------

def _linear(out_dim: int, in_dim: int) -> tuple[torch.Tensor, torch.Tensor]:
    """Xavier-uniform weight + zero bias, both with requires_grad=True."""
    w = torch.empty(out_dim, in_dim, requires_grad=True)
    torch.nn.init.xavier_uniform_(w)
    b = torch.zeros(out_dim, requires_grad=True)
    return w, b


# ---------------------------------------------------------------------------
# Policy
# ---------------------------------------------------------------------------

@register_pytree
@dataclass(frozen=True)
class PolicyWeights:
    """All tensors for a 2-layer MLP policy with action and value heads.

    Frozen dataclass — fields can't be reassigned, but the tensors themselves
    are mutable (requires_grad=True, optimizer updates them in place).
    """

    # MLP trunk: two hidden layers
    w1: torch.Tensor  # (hidden, obs_dim)
    b1: torch.Tensor  # (hidden,)
    w2: torch.Tensor  # (hidden, hidden)
    b2: torch.Tensor  # (hidden,)
    # Action head
    w_action: torch.Tensor  # (act_dim, hidden)
    b_action: torch.Tensor  # (act_dim,)
    # Value head
    w_value: torch.Tensor  # (1, hidden)
    b_value: torch.Tensor  # (1,)


def init_policy(obs_dim: int, act_dim: int, hidden: int = 64) -> PolicyWeights:
    """Initialize policy weights with Xavier uniform (matching nn.Linear defaults)."""
    w1, b1 = _linear(hidden, obs_dim)
    w2, b2 = _linear(hidden, hidden)
    w_action, b_action = _linear(act_dim, hidden)
    w_value, b_value = _linear(1, hidden)
    return PolicyWeights(
        w1=w1, b1=b1, w2=w2, b2=b2,
        w_action=w_action, b_action=b_action,
        w_value=w_value, b_value=b_value,
    )


def policy_params(w: PolicyWeights) -> list[torch.Tensor]:
    """All trainable parameters, for optimizer construction."""
    return [w.w1, w.b1, w.w2, w.b2, w.w_action, w.b_action, w.w_value, w.b_value]


def policy_forward(w: PolicyWeights, obs: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
    """obs (batch, obs_dim) -> (logits (batch, act_dim), value (batch,))."""
    h = F.relu(obs @ w.w1.T + w.b1)  # (batch, hidden)
    h = F.relu(h @ w.w2.T + w.b2)  # (batch, hidden)
    logits = h @ w.w_action.T + w.b_action  # (batch, act_dim)
    value = (h @ w.w_value.T + w.b_value)[:, 0]  # (batch, 1) -> (batch,)
    return logits, value


def policy_act(w: PolicyWeights, obs: torch.Tensor) -> int:
    """Sample one action from the policy. obs: (obs_dim,)."""
    with torch.no_grad():
        logits, _ = policy_forward(w, obs.unsqueeze(0))  # (1, act_dim)
        dist = torch.distributions.Categorical(logits=logits)
        return dist.sample().item()


# ---------------------------------------------------------------------------
# World model
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Transition:
    """One real transition: state + action → result. Used for world-model training."""

    obs: torch.Tensor
    action: int
    next_obs: torch.Tensor
    reward: float
    done: bool


@register_pytree
@dataclass(frozen=True)
class WMWeights:
    """All tensors for a 2-layer MLP world model.

    Predicts next obs, reward, done from (obs, one_hot_action).
    """

    obs_dim: int
    act_dim: int
    # MLP trunk
    w1: torch.Tensor  # (hidden, obs_dim + act_dim)
    b1: torch.Tensor  # (hidden,)
    w2: torch.Tensor  # (hidden, hidden)
    b2: torch.Tensor  # (hidden,)
    # Heads
    w_obs: torch.Tensor  # (obs_dim, hidden)
    b_obs: torch.Tensor  # (obs_dim,)
    w_reward: torch.Tensor  # (1, hidden)
    b_reward: torch.Tensor  # (1,)
    w_done: torch.Tensor  # (1, hidden)
    b_done: torch.Tensor  # (1,)


def init_wm(obs_dim: int, act_dim: int, hidden: int = 64) -> WMWeights:
    """Initialize world model weights with Xavier uniform."""
    input_dim = obs_dim + act_dim
    w1, b1 = _linear(hidden, input_dim)
    w2, b2 = _linear(hidden, hidden)
    w_obs, b_obs = _linear(obs_dim, hidden)
    w_reward, b_reward = _linear(1, hidden)
    w_done, b_done = _linear(1, hidden)
    return WMWeights(
        obs_dim=obs_dim, act_dim=act_dim,
        w1=w1, b1=b1, w2=w2, b2=b2,
        w_obs=w_obs, b_obs=b_obs,
        w_reward=w_reward, b_reward=b_reward,
        w_done=w_done, b_done=b_done,
    )


def wm_params(w: WMWeights) -> list[torch.Tensor]:
    """All trainable parameters, for optimizer construction."""
    return [w.w1, w.b1, w.w2, w.b2, w.w_obs, w.b_obs, w.w_reward, w.b_reward, w.w_done, w.b_done]


def wm_forward(
    w: WMWeights,
    obs: torch.Tensor,
    action: torch.Tensor,
) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
    """Predict next_obs, reward, done.

    obs: (batch, obs_dim), action: (batch,) int — one-hot encoded internally.
    """
    action_onehot = torch.zeros(obs.shape[0], w.act_dim, device=obs.device)
    action_onehot.scatter_(1, action.unsqueeze(1), 1.0)

    x = torch.cat([obs, action_onehot], dim=1)  # (batch, obs_dim + act_dim)
    h = F.relu(x @ w.w1.T + w.b1)  # (batch, hidden)
    h = F.relu(h @ w.w2.T + w.b2)  # (batch, hidden)

    pred_obs = h @ w.w_obs.T + w.b_obs  # (batch, obs_dim)
    pred_reward = (h @ w.w_reward.T + w.b_reward)[:, 0]  # (batch,)
    pred_done = (h @ w.w_done.T + w.b_done)[:, 0]  # (batch,)
    return pred_obs, pred_reward, pred_done


def wm_train_step(
    w: WMWeights,
    opt: "robots.optim.OptimizerHandle",
    transitions: list[Transition],
) -> float:
    """One gradient step on a batch of transitions. Returns loss."""
    obs = torch.stack([t.obs for t in transitions])
    actions = torch.tensor([t.action for t in transitions], dtype=torch.long)
    next_obs = torch.stack([t.next_obs for t in transitions])
    rewards = torch.tensor([t.reward for t in transitions], dtype=torch.float32)
    dones = torch.tensor([t.done for t in transitions], dtype=torch.float32)

    pred_obs, pred_reward, pred_done = wm_forward(w, obs, actions)

    loss_obs = F.mse_loss(pred_obs, next_obs)
    loss_reward = F.mse_loss(pred_reward, rewards)
    loss_done = F.binary_cross_entropy_with_logits(pred_done, dones)
    loss = loss_obs + loss_reward + loss_done

    opt.zero()
    loss.backward()
    opt.step()

    return loss.item()
