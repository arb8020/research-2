"""Tests for the state-in/state-out collector (robots/collect.py)."""

from __future__ import annotations

import gymnasium
import pytest
import torch

from robots.collect import collect, rollout_init
from robots.models import init_policy, init_value, value_forward


def _v(vf, obs: torch.Tensor) -> float:
    with torch.no_grad():
        value = value_forward(vf, obs.unsqueeze(0))
    return value.item()


def _setup(max_episode_steps: int, seed: int = 0):
    torch.manual_seed(seed)
    env = gymnasium.make("CartPole-v1", max_episode_steps=max_episode_steps)
    env.action_space.seed(seed)
    pi = init_policy(obs_dim=4, act_dim=2)
    vf = init_value(obs_dim=4)
    state = rollout_init(env, seed=seed)
    return env, pi, vf, state


class TestEpisodesSpanBatches:
    def test_episode_len_carried_across_batches(self) -> None:
        # Time limit 5 is short enough that random CartPole never falls first.
        env, pi, vf, state = _setup(max_episode_steps=5)

        state, b1 = collect(env, pi, vf, state, num_steps=3)
        assert state.episode_len == 3, "episode should still be running after batch 1"
        assert b1.episodes == []

        state, b2 = collect(env, pi, vf, state, num_steps=3)
        assert len(b2.episodes) == 1
        assert b2.episodes[0].episode_len == 5, "episode started in batch 1 must finish in batch 2"
        assert state.episode_len == 1, "new episode has taken one step"

    def test_episodes_longer_than_batch(self) -> None:
        # The old bug: reset every batch capped episodes at the batch size.
        env, pi, vf, state = _setup(max_episode_steps=20)
        finished = []
        for _ in range(20):
            state, batch = collect(env, pi, vf, state, num_steps=4)
            finished.extend(batch.episodes)
        assert finished
        assert max(e.episode_len for e in finished) > 4


class TestTerminatedTruncated:
    def _steps(self, max_episode_steps: int, n: int, seed: int = 0):
        env, pi, vf, state = _setup(max_episode_steps, seed)
        state, batch = collect(env, pi, vf, state, num_steps=n)
        return vf, batch

    @pytest.mark.parametrize("seed", range(40))
    def test_flags_match_time_limit(self, seed: int) -> None:
        # Limit 30: random CartPole sometimes falls before 30 (terminated), sometimes hits 30 (truncated).
        vf, batch = self._steps(max_episode_steps=30, n=600, seed=seed)
        terminated = [s for s in batch.steps if s.terminated]
        truncated = [s for s in batch.steps if s.truncated]
        assert terminated, "expected some real endings"
        assert truncated, "expected some time-limit endings"
        # A time-out happens exactly at the limit. A real ending can happen at any
        # length <= 30 -- including ON the limit step, where gymnasium sets both
        # flags and termination wins (timed_out=False, len 30).
        timed_out_eps = [e for e in batch.episodes if e.timed_out]
        terminated_eps = [e for e in batch.episodes if not e.timed_out]
        assert all(e.episode_len == 30 for e in timed_out_eps)
        assert all(e.episode_len <= 30 for e in terminated_eps)
        # Step flags -> EpisodeEnd.timed_out, one ending step per finished episode.
        ending_steps = [s for s in batch.steps if s.terminated or s.truncated]
        assert len(ending_steps) == len(batch.episodes)
        for s, e in zip(ending_steps, batch.episodes):
            assert e.timed_out == (s.truncated and not s.terminated)

    def test_bootstrap_value_only_on_truncated(self) -> None:
        vf, batch = self._steps(max_episode_steps=30, n=600)
        for s in batch.steps:
            if s.truncated and not s.terminated:
                assert s.bootstrap_value != 0.0
                assert abs(s.bootstrap_value - _v(vf, s.next_obs)) < 1e-6
            else:
                assert s.bootstrap_value == 0.0

    def test_last_value_is_v_of_last_obs(self) -> None:
        vf, batch = self._steps(max_episode_steps=30, n=37)
        assert abs(batch.last_value - _v(vf, batch.last_obs)) < 1e-6

    def test_value_and_next_obs_recorded(self) -> None:
        vf, batch = self._steps(max_episode_steps=30, n=50)
        for s, nxt in zip(batch.steps, batch.steps[1:]):
            assert abs(s.value - _v(vf, s.obs)) < 1e-6
            ended = s.terminated or s.truncated
            if not ended:
                assert torch.equal(s.next_obs, nxt.obs), "within an episode, next_obs is the next step's obs"
