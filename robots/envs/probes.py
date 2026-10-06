"""Andy Jones' probe environments (andyljones.com/posts/rl-debugging.html), batched.

Env contract shared with the future PufferLib Breakout binding:
  reset(seed) -> obs (N, obs_size) float32
  step(actions (N,) long) -> (obs, reward (N,), terminal (N,)) float32
  log() -> episode stats since the last call, then cleared
Returned tensors are the env's own buffers, overwritten by the next step; copy what you keep.
Envs that end reset themselves inside step, so the returned obs is the next episode's first obs.
"""

from __future__ import annotations

from dataclasses import dataclass

import torch


@dataclass(frozen=True)
class EpisodeStats:
    running_return: torch.Tensor
    running_length: torch.Tensor
    done_return: torch.Tensor
    done_length: torch.Tensor
    done_n: torch.Tensor


def init_episode_stats(num_envs: int) -> EpisodeStats:
    return EpisodeStats(
        running_return=torch.zeros(num_envs),
        running_length=torch.zeros(num_envs),
        done_return=torch.zeros(()),
        done_length=torch.zeros(()),
        done_n=torch.zeros(()),
    )


def episode_stats_update_(stats: EpisodeStats, reward: torch.Tensor, terminal: torch.Tensor) -> EpisodeStats:
    stats.running_return.add_(reward)
    stats.running_length.add_(1.0)
    stats.done_return.add_((stats.running_return * terminal).sum())
    stats.done_length.add_((stats.running_length * terminal).sum())
    stats.done_n.add_(terminal.sum())
    stats.running_return.mul_(1.0 - terminal)
    stats.running_length.mul_(1.0 - terminal)
    return stats


def episode_stats_log_(stats: EpisodeStats) -> dict[str, float]:
    """episode_return/episode_length are absent when no episode ended (a mean of nothing is not a number)."""
    n = stats.done_n.item()
    out = {"n": n}
    if n > 0:
        out["episode_return"] = stats.done_return.item() / n
        out["episode_length"] = stats.done_length.item() / n
    stats.done_return.zero_()
    stats.done_length.zero_()
    stats.done_n.zero_()
    return out


def _random_sign(gen: torch.Generator, out: torch.Tensor) -> torch.Tensor:
    return out.copy_(torch.randint(0, 2, out.shape, generator=gen).float() * 2.0 - 1.0)


class Probe1Value:
    """One action, obs 0, reward +1, every step terminal. Tests: V(0) -> 1."""

    def __init__(self, num_envs: int) -> None:
        assert num_envs > 0
        self.num_envs, self.obs_size, self.num_actions = num_envs, 1, 1
        self.obs = torch.zeros(num_envs, 1)
        self.reward = torch.ones(num_envs)
        self.terminal = torch.ones(num_envs)
        self.stats = init_episode_stats(num_envs)

    def reset(self, seed: int) -> torch.Tensor:
        del seed
        return self.obs

    def step(self, actions: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        assert actions.shape == (self.num_envs,)
        episode_stats_update_(self.stats, self.reward, self.terminal)
        return self.obs, self.reward, self.terminal

    def log(self) -> dict[str, float]:
        return episode_stats_log_(self.stats)


class Probe2Obs:
    """One action, obs +-1 at random, reward = obs, every step terminal. Tests: V(+-1) -> +-1."""

    def __init__(self, num_envs: int) -> None:
        assert num_envs > 0
        self.num_envs, self.obs_size, self.num_actions = num_envs, 1, 1
        self.gen = torch.Generator()
        self.obs = torch.zeros(num_envs, 1)
        self.reward = torch.zeros(num_envs)
        self.terminal = torch.ones(num_envs)
        self.stats = init_episode_stats(num_envs)

    def reset(self, seed: int) -> torch.Tensor:
        self.gen.manual_seed(seed)
        return _random_sign(self.gen, self.obs)

    def step(self, actions: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        assert actions.shape == (self.num_envs,)
        self.reward.copy_(self.obs[:, 0])
        episode_stats_update_(self.stats, self.reward, self.terminal)
        _random_sign(self.gen, self.obs)
        return self.obs, self.reward, self.terminal

    def log(self) -> dict[str, float]:
        return episode_stats_log_(self.stats)


class Probe3Discount:
    """One action, two-step episodes: obs 0 then 1, reward 0 then +1. Tests: V(0) -> gamma, V(1) -> 1."""

    def __init__(self, num_envs: int) -> None:
        assert num_envs > 0
        self.num_envs, self.obs_size, self.num_actions = num_envs, 1, 1
        self.obs = torch.zeros(num_envs, 1)
        self.reward = torch.zeros(num_envs)
        self.terminal = torch.zeros(num_envs)
        self.stats = init_episode_stats(num_envs)

    def reset(self, seed: int) -> torch.Tensor:
        del seed
        return self.obs.zero_()

    def step(self, actions: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        assert actions.shape == (self.num_envs,)
        at_second_step = self.obs[:, 0]
        self.reward.copy_(at_second_step)
        self.terminal.copy_(at_second_step)
        episode_stats_update_(self.stats, self.reward, self.terminal)
        self.obs.copy_(1.0 - self.obs)
        return self.obs, self.reward, self.terminal

    def log(self) -> dict[str, float]:
        return episode_stats_log_(self.stats)


class Probe4Policy:
    """Two actions, obs 0, reward +1 for action 1 else -1, every step terminal. Tests: P(1|0) -> 1, V(0) -> 1."""

    def __init__(self, num_envs: int) -> None:
        assert num_envs > 0
        self.num_envs, self.obs_size, self.num_actions = num_envs, 1, 2
        self.obs = torch.zeros(num_envs, 1)
        self.reward = torch.zeros(num_envs)
        self.terminal = torch.ones(num_envs)
        self.stats = init_episode_stats(num_envs)

    def reset(self, seed: int) -> torch.Tensor:
        del seed
        return self.obs

    def step(self, actions: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        assert actions.shape == (self.num_envs,)
        self.reward.copy_(actions.float() * 2.0 - 1.0)
        episode_stats_update_(self.stats, self.reward, self.terminal)
        return self.obs, self.reward, self.terminal

    def log(self) -> dict[str, float]:
        return episode_stats_log_(self.stats)


class Probe5PolicyValue:
    """Two actions, obs +-1 at random, reward +1 when action 1 on +1 or action 0 on -1, else -1; every step terminal.
    Tests: P(1|+1) -> 1, P(1|-1) -> 0, V(+-1) -> 1."""

    def __init__(self, num_envs: int) -> None:
        assert num_envs > 0
        self.num_envs, self.obs_size, self.num_actions = num_envs, 1, 2
        self.gen = torch.Generator()
        self.obs = torch.zeros(num_envs, 1)
        self.reward = torch.zeros(num_envs)
        self.terminal = torch.ones(num_envs)
        self.stats = init_episode_stats(num_envs)

    def reset(self, seed: int) -> torch.Tensor:
        self.gen.manual_seed(seed)
        return _random_sign(self.gen, self.obs)

    def step(self, actions: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        assert actions.shape == (self.num_envs,)
        action_sign = actions.float() * 2.0 - 1.0
        self.reward.copy_(action_sign * self.obs[:, 0])
        episode_stats_update_(self.stats, self.reward, self.terminal)
        _random_sign(self.gen, self.obs)
        return self.obs, self.reward, self.terminal

    def log(self) -> dict[str, float]:
        return episode_stats_log_(self.stats)
