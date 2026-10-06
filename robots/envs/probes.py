"""Andy Jones' probe environments (andyljones.com/posts/rl-debugging.html), batched.

Env contract shared with the future PufferLib Breakout binding:
  reset(seed) -> obs (N, obs_size) float32
  step(actions (N,) long) -> (obs, reward (N,), terminal (N,)) float32
  log() -> episode stats since the last call, then cleared
Returned tensors are the env's own buffers, overwritten by the next step; copy what you keep.
Envs that end reset themselves inside step, so the returned obs is the next episode's first obs.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from functools import partial

import torch


@dataclass(frozen=True)
class ProbeSpec:
    num_actions: int
    episode_length: int
    draw_obs: Callable[[torch.Generator, torch.Tensor], torch.Tensor]  # (gen, t (N,)) -> obs (N,)
    reward: Callable[[torch.Tensor, torch.Tensor, torch.Tensor], torch.Tensor]  # (obs, actions, t) -> (N,)


class Probe:
    """obs_size 1. t is each env's step within its episode; the episode ends at t == episode_length - 1."""

    def __init__(self, spec: ProbeSpec, num_envs: int) -> None:
        assert num_envs > 0
        self.spec = spec
        self.num_envs, self.obs_size, self.num_actions = num_envs, 1, spec.num_actions
        self.gen = torch.Generator()
        self.t = torch.zeros(num_envs)
        self.obs = torch.zeros(num_envs, 1)
        self.reward = torch.zeros(num_envs)
        self.terminal = torch.zeros(num_envs)
        self.running_return = torch.zeros(num_envs)
        self.done_return_and_n = torch.zeros(2)

    def reset(self, seed: int) -> torch.Tensor:
        self.gen.manual_seed(seed)
        self.t.zero_()
        self.running_return.zero_()
        self.obs[:, 0] = self.spec.draw_obs(self.gen, self.t)
        return self.obs

    def step(self, actions: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        assert actions.shape == (self.num_envs,)
        self.reward.copy_(self.spec.reward(self.obs[:, 0], actions.float(), self.t))
        self.terminal.copy_(self.t == self.spec.episode_length - 1)
        self.running_return.add_(self.reward)
        self.done_return_and_n.add_(torch.stack([(self.running_return * self.terminal).sum(), self.terminal.sum()]))
        self.running_return.mul_(1.0 - self.terminal)
        self.t.add_(1.0).mul_(1.0 - self.terminal)
        self.obs[:, 0] = self.spec.draw_obs(self.gen, self.t)
        return self.obs, self.reward, self.terminal

    def log(self) -> dict[str, float]:
        """episode_return/episode_length are absent when no episode ended (a mean of nothing is not a number)."""
        done_return, n = self.done_return_and_n.tolist()
        self.done_return_and_n.zero_()
        if n == 0:
            return {"n": n}
        return {"n": n, "episode_return": done_return / n, "episode_length": float(self.spec.episode_length)}


def zeros(gen: torch.Generator, t: torch.Tensor) -> torch.Tensor:
    return torch.zeros_like(t)


def random_sign(gen: torch.Generator, t: torch.Tensor) -> torch.Tensor:
    return torch.randint(0, 2, t.shape, generator=gen).float() * 2.0 - 1.0


# One action, obs 0, reward +1, every step terminal. Tests: V(0) -> 1.
Probe1Value = partial(Probe, ProbeSpec(1, 1, zeros, lambda obs, a, t: torch.ones_like(obs)))
# One action, obs +-1 at random, reward = obs, every step terminal. Tests: V(+-1) -> +-1.
Probe2Obs = partial(Probe, ProbeSpec(1, 1, random_sign, lambda obs, a, t: obs))
# One action, two-step episodes: obs 0 then 1, reward 0 then +1. Tests: V(0) -> gamma, V(1) -> 1.
Probe3Discount = partial(Probe, ProbeSpec(1, 2, lambda gen, t: t, lambda obs, a, t: obs))
# Two actions, obs 0, reward +1 for action 1 else -1, every step terminal. Tests: P(1|0) -> 1, V(0) -> 1.
Probe4Policy = partial(Probe, ProbeSpec(2, 1, zeros, lambda obs, a, t: a * 2.0 - 1.0))
# Two actions, obs +-1 at random, reward +1 when action 1 on +1 or action 0 on -1, else -1; every step terminal.
# Tests: P(1|+1) -> 1, P(1|-1) -> 0, V(+-1) -> 1.
Probe5PolicyValue = partial(Probe, ProbeSpec(2, 1, random_sign, lambda obs, a, t: (a * 2.0 - 1.0) * obs))
