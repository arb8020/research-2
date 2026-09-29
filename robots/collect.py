"""Collect on-policy experience from a real env. State in, state out.

Layers (each built from the one above it):
    rollout_init(env, seed)      -> RolloutState                         # reset once, at the start
    collect_step(env, pi, vf, state) -> (state, Step, EpisodeEnd | None)   # one env step
    collect(env, pi, vf, state, n)   -> (state, Batch)                     # n steps, continues episodes

pi picks actions; vf supplies every recorded value (Step.value, bootstrap_value, last_value).

Nothing here resets between batches: the only resets happen in rollout_init and
inside collect_step when an episode ends. So an episode can span many batches.

Every value needed to compute training targets is recorded here, at collection
time, so turning a Batch into loss inputs is a pure function (no network calls):
    Step.bootstrap_value = V(next_obs) on a truncated step, else 0.0
    Batch.last_value     = V(last_obs), for the cut at the batch end
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import gymnasium
import torch

from robots.models import PolicyWeights, ValueWeights, policy_forward, policy_value


@dataclass(frozen=True)
class RolloutState:
    """What must survive between batches."""

    obs: torch.Tensor          # (obs_dim,) the obs the next step acts on
    episode_return: float      # running reward total of the unfinished episode
    episode_len: int           # steps so far in the unfinished episode


@dataclass(frozen=True)
class Step:
    """One recorded step."""

    obs: torch.Tensor          # (obs_dim,) obs the action was chosen from
    action: int
    reward: float
    terminated: bool           # real ending (pole fell): future reward = 0
    truncated: bool            # time limit: future reward unknown -> bootstrap with V(next_obs)
    next_obs: torch.Tensor     # (obs_dim,) true next obs, BEFORE any reset
    value: float               # detached V(obs), from collection time
    bootstrap_value: float     # detached V(next_obs) if truncated (and not terminated), else 0.0


@dataclass(frozen=True)
class EpisodeEnd:
    """Emitted by collect_step when an episode finishes. For logging."""

    episode_return: float
    episode_len: int
    timed_out: bool   # ended by the time limit with the future unknown (bootstrapped).
                      # False if terminated, even when gymnasium also set Step.truncated
                      # on the same step (termination wins). Not the raw truncated flag.


@dataclass(frozen=True)
class Batch:
    steps: list[Step]
    episodes: list[EpisodeEnd]  # episodes that FINISHED during this batch
    last_obs: torch.Tensor      # (obs_dim,) obs the NEXT batch will act on
    last_value: float           # detached V(last_obs): bootstraps the cut at the batch end


def _to_tensor(obs) -> torch.Tensor:
    return torch.tensor(obs, dtype=torch.float32)


def rollout_init(env: gymnasium.Env, seed: int | None = None) -> RolloutState:
    obs, _ = env.reset(seed=seed)
    return RolloutState(obs=_to_tensor(obs), episode_return=0.0, episode_len=0)


def collect_step(
    env: gymnasium.Env,
    pi: PolicyWeights,
    vf: ValueWeights,
    state: RolloutState,
) -> tuple[RolloutState, Step, EpisodeEnd | None]:
    """Act once, step the env, record it. Resets the env if the episode ended."""
    with torch.no_grad():
        logits = policy_forward(pi, state.obs.unsqueeze(0))  # (1, act_dim)
        dist = torch.distributions.Categorical(logits=logits)
        action = dist.sample()

    value = policy_value(vf, state.obs)
    next_obs, reward, terminated, truncated, _ = env.step(action.item())
    next_obs_t = _to_tensor(next_obs)

    # gymnasium can report terminated AND truncated on the time-limit step.
    # A real ending wins: the future is known to be zero, nothing to bootstrap.
    needs_bootstrap = bool(truncated) and not bool(terminated)
    bootstrap_value = policy_value(vf, next_obs_t) if needs_bootstrap else 0.0

    step = Step(
        obs=state.obs,
        action=action.item(),
        reward=float(reward),
        terminated=bool(terminated),
        truncated=bool(truncated),
        next_obs=next_obs_t,
        value=value,
        bootstrap_value=bootstrap_value,
    )

    ep_return = state.episode_return + float(reward)
    ep_len = state.episode_len + 1

    if terminated or truncated:
        ended = EpisodeEnd(episode_return=ep_return, episode_len=ep_len, timed_out=needs_bootstrap)
        return rollout_init(env), step, ended

    return replace(state, obs=next_obs_t, episode_return=ep_return, episode_len=ep_len), step, None


def collect(
    env: gymnasium.Env,
    pi: PolicyWeights,
    vf: ValueWeights,
    state: RolloutState,
    num_steps: int,
) -> tuple[RolloutState, Batch]:
    """num_steps of experience. Picks up exactly where `state` left off."""
    assert num_steps > 0
    steps: list[Step] = []
    episodes: list[EpisodeEnd] = []
    for _ in range(num_steps):
        state, step, ended = collect_step(env, pi, vf, state)
        steps.append(step)
        if ended is not None:
            episodes.append(ended)
    batch = Batch(
        steps=steps,
        episodes=episodes,
        last_obs=state.obs,
        last_value=policy_value(vf, state.obs),
    )
    return state, batch
