"""Produce experience for the world model, and imagined experience from it.

On-policy collection from the real env lives in robots/collect.py.
"""

from __future__ import annotations

from collections.abc import Callable

import gymnasium
import torch

from robots.collect import Batch, EpisodeEnd, Step
from robots.models import (
    PolicyWeights,
    Transition,
    ValueWeights,
    WMWeights,
    policy_forward,
    policy_value,
    wm_forward,
)


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
    vf: ValueWeights,
    start_obs: torch.Tensor,
    horizon: int,
) -> Batch:
    """Roll out pi inside the world model (vf supplies the recorded values) for up to `horizon` steps.

    Emits the same Batch as robots.collect.collect, so compute_loss_fn_inputs
    works unchanged:
      terminated      = predicted done (sigmoid > 0.5); the rollout stops there
      truncated       = False (imagination has no time limit)
      bootstrap_value = 0.0 (only truncation bootstraps)
      last_value      = V(final imagined obs): the horizon is a batch cut. Unused
                        when the last step terminated.
    """
    assert horizon > 0
    steps: list[Step] = []
    episodes: list[EpisodeEnd] = []
    obs = start_obs.detach()
    episode_return = 0.0

    for _ in range(horizon):
        with torch.no_grad():
            logits = policy_forward(pi, obs.unsqueeze(0))  # (1, act_dim)
            action = torch.distributions.Categorical(logits=logits).sample()  # (1,)
            pred_obs, pred_reward, pred_done = wm_forward(wm, obs.unsqueeze(0), action)
        next_obs = pred_obs.squeeze(0)
        terminated = pred_done.sigmoid().item() > 0.5
        steps.append(
            Step(
                obs=obs,
                action=action.item(),
                reward=pred_reward.item(),
                terminated=terminated,
                truncated=False,
                next_obs=next_obs,
                value=policy_value(vf, obs),
                bootstrap_value=0.0,
            )
        )
        episode_return += pred_reward.item()
        obs = next_obs
        if terminated:
            episodes.append(EpisodeEnd(episode_return=episode_return, episode_len=len(steps), timed_out=False))
            break

    return Batch(steps=steps, episodes=episodes, last_obs=obs, last_value=policy_value(vf, obs))
