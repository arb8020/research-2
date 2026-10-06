"""Vendored PufferLib 5.0 envs build and step through the ctypes shim."""

import urllib.error

import pytest
import torch

from robots.envs.puffer import build
from robots.envs.puffer.vecenv import make


@pytest.fixture(scope="module", autouse=True)
def built() -> None:
    try:
        for name in build.ENVS:
            build.build(name)
    except NotImplementedError as e:
        pytest.skip(str(e))
    except urllib.error.URLError as e:
        pytest.skip(f"raylib 5.5 not cached and fetch failed (offline?): {e}")


def rollout(
    name: str, num_envs: int, seed: int, steps: int
) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
    env = make(name, num_envs, seed=seed)
    gen = torch.Generator().manual_seed(seed)
    obs, rew, term = [env.reset(seed).clone()], [], []
    for _ in range(steps):
        o, r, d = env.step(torch.randint(env.num_actions, (num_envs,), generator=gen))
        obs.append(o.clone())
        rew.append(r.clone())
        term.append(d.clone())
    env.close()
    return torch.stack(obs), torch.stack(rew), torch.stack(term)


def test_cartpole_shapes_and_episodes_end() -> None:
    env = make("cartpole", 4, seed=0)
    assert (env.num_envs, env.obs_size, env.num_actions) == (4, 4, 2)
    obs = env.reset(0)
    assert obs.shape == (4, 4) and obs.dtype == torch.float32
    assert obs.abs().max() <= 0.04  # upstream init range is uniform(-0.04, 0.04)
    for _ in range(200):  # random-policy episodes last ~22 steps
        o, r, d = env.step(torch.randint(2, (4,)))
    assert (o.shape, r.shape, d.shape) == ((4, 4), (4,), (4,))
    assert (r.dtype, d.dtype) == (torch.float32, torch.float32)
    log = env.log()
    assert log["n"] >= 4
    assert 5 < log["episode_length"] < 100
    assert log["episode_length"] == log["score"]
    assert env.log() == {"n": 0.0}


def test_breakout_shapes_and_episodes_end() -> None:
    env = make("breakout", 2, seed=0)
    assert (env.obs_size, env.num_actions) == (118, 3)
    for _ in range(2000):  # random-policy episodes last ~180 steps (frameskip 3)
        o, r, d = env.step(torch.randint(3, (2,)))
    assert o.shape == (2, 118)
    log = env.log()
    assert log["n"] >= 2
    assert set(log) == {"perf", "score", "episode_return", "episode_length", "n"}


@pytest.mark.parametrize("name", ["cartpole", "breakout"])
def test_seeded_rollouts_are_deterministic_and_envs_differ(name: str) -> None:
    obs_a, rew_a, term_a = rollout(name, 8, seed=3, steps=300)
    obs_b, rew_b, term_b = rollout(name, 8, seed=3, steps=300)
    assert torch.equal(obs_a, obs_b) and torch.equal(rew_a, rew_b) and torch.equal(term_a, term_b)
    assert term_a.sum() > 0
    assert not torch.equal(obs_a[:, 0], obs_a[:, 1])
    obs_c, _, _ = rollout(name, 8, seed=4, steps=300)
    assert not torch.equal(obs_a, obs_c)


def test_cartpole_physics_matches_gymnasium() -> None:
    import gymnasium as gym
    import numpy as np

    env = make("cartpole", 1, seed=0)
    obs = env.reset(0)[0].clone().numpy()
    ref = gym.make("CartPole-v1").unwrapped
    ref.reset(seed=0)
    ref.state = obs.astype(np.float64)
    for _ in range(50):
        action = int(obs[2] + 0.5 * obs[3] > 0)  # crude balancer keeps the episode alive
        o, _, d = env.step(torch.tensor([action]))
        ref.step(action)
        obs = o[0].clone().numpy()
        assert d[0] == 0.0
        np.testing.assert_allclose(obs, ref.state, atol=1e-5)
