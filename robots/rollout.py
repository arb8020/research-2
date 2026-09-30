"""Produce experience — from the real env or from the world model."""

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


def collect_policy_rollout(
    env: gymnasium.Env,
    pi: PolicyWeights,
    num_steps: int,
) -> list[PolicyStep]:
    """Collect on-policy experience from a real env.

    Each step records the logprob and value from the policy at collection time,
    which is what REINFORCE needs for its gradient.
    """
    steps: list[PolicyStep] = []
    obs, _ = env.reset()
    obs_t = torch.tensor(obs, dtype=torch.float32)

    for _ in range(num_steps):
        logits, value = policy_forward(pi, obs_t.unsqueeze(0))  # (1, act_dim), (1,)
        dist = torch.distributions.Categorical(logits=logits)
        action = dist.sample()
        logprob = dist.log_prob(action).item()

        next_obs, reward, terminated, truncated, _ = env.step(action.item())
        next_obs_t = torch.tensor(next_obs, dtype=torch.float32)
        done = terminated or truncated

        steps.append(
            PolicyStep(
                obs=obs_t,
                action=action.item(),
                reward=float(reward),
                done=done,
                logprob=logprob,
                value=value.item(),
            )
        )

        if done:
            obs, _ = env.reset()
            obs_t = torch.tensor(obs, dtype=torch.float32)
        else:
            obs_t = next_obs_t

    return steps


def policy_collector(
    env: gymnasium.Env,
    pi: PolicyWeights,
    num_steps: int,
) -> Callable[[], list[PolicyStep]]:
    """Returns a get_batch() callable for model-free RL.

    Each call collects num_steps of on-policy experience (full episodes,
    resetting on done). The returned function closes over env and pi so the
    caller just calls get_batch() with no args.
    """

    def get_batch() -> list[PolicyStep]:
        return collect_policy_rollout(env, pi, num_steps)

    return get_batch


# ---------------------------------------------------------------------------
# Imagine from world model
# ---------------------------------------------------------------------------

def imagine_rollout(
    wm: WMWeights,
    pi: PolicyWeights,
    start_obs: torch.Tensor,
    horizon: int,
) -> list[PolicyStep]:
    """Roll out the policy inside the world model for up to `horizon` steps."""
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
