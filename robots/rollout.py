"""Produce experience for the world model, and imagined experience from it.

On-policy collection from the real env lives in robots/collect.py.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import gymnasium
import torch

from robots.models import (
    PolicyWeights,
    Transition,
    WMWeights,
    policy_act,
    policy_forward,
    wm_forward,
)


@dataclass(frozen=True)
class PolicyStep:
    """One step of policy experience. Works for both real and imagined rollouts."""

    obs: torch.Tensor
    action: int
    reward: float
    done: bool
    logprob: float
    value: float


# ---------------------------------------------------------------------------
# Collect from real env
# ---------------------------------------------------------------------------

def collect_transitions(
    env: gymnasium.Env,
    num_steps: int,
    act: Callable[[torch.Tensor], int] | None = None,
) -> list[Transition]:
    """Step through env for num_steps, return transitions.

    act: given an obs tensor, return an action int.
         None = random actions (for world-model pre-training).
    """
    transitions: list[Transition] = []
    obs, _ = env.reset()
    obs_t = torch.tensor(obs, dtype=torch.float32)

    for _ in range(num_steps):
        action = act(obs_t) if act is not None else env.action_space.sample()
        next_obs, reward, terminated, truncated, _ = env.step(action)
        next_obs_t = torch.tensor(next_obs, dtype=torch.float32)
        done = terminated or truncated

        transitions.append(
            Transition(
                obs=obs_t,
                action=action,
                next_obs=next_obs_t,
                reward=float(reward),
                done=done,
            )
        )

        if done:
            obs, _ = env.reset()
            obs_t = torch.tensor(obs, dtype=torch.float32)
        else:
            obs_t = next_obs_t

    return transitions


# ---------------------------------------------------------------------------
# Imagine from world model
# ---------------------------------------------------------------------------

def imagine_rollout(
    wm: WMWeights,
    pi: PolicyWeights,
    start_obs: torch.Tensor,
    horizon: int,
) -> list[PolicyStep]:
    """Roll out the policy inside the world model for up to `horizon` steps.

    PHASE B: still emits the old PolicyStep (merged `done`) and cannot feed
    compute_loss_fn_inputs. To migrate it should return a collect.Batch:
      - terminated = predicted done; truncated = never (the horizon is a batch cut)
      - bootstrap_value = 0.0 (no truncation inside imagination)
      - last_value = V(final predicted obs) if the rollout hit the horizon, else
        irrelevant (last step terminated)
      - next_obs = predicted obs; policy_forward under no_grad (logprob/value are
        detached floats anyway)
    """
    steps: list[PolicyStep] = []
    obs = start_obs

    for _ in range(horizon):
        logits, value = policy_forward(pi, obs.unsqueeze(0))  # (1, act_dim), (1,)
        dist = torch.distributions.Categorical(logits=logits)
        action = dist.sample()
        logprob = dist.log_prob(action).item()

        with torch.no_grad():
            pred_obs, pred_reward, pred_done = wm_forward(wm, obs.unsqueeze(0), action)

        steps.append(
            PolicyStep(
                obs=obs.detach(),
                action=action.item(),
                reward=pred_reward.item(),
                done=pred_done.sigmoid().item() > 0.5,
                logprob=logprob,
                value=value.item(),
            )
        )

        obs = pred_obs.squeeze(0).detach()
        if steps[-1].done:
            break

    return steps
