"""Tests for the state-in/state-out collector (robots/collect.py)."""

from __future__ import annotations

import gymnasium
import torch

from robots.collect import collect, rollout_init
from robots.models import init_policy, policy_forward


def _v(pi, obs: torch.Tensor) -> float:
    with torch.no_grad():
        _, value = policy_forward(pi, obs.unsqueeze(0))
    return value.item()


def _setup(max_episode_steps: int, seed: int = 0):
    torch.manual_seed(seed)
    env = gymnasium.make("CartPole-v1", max_episode_steps=max_episode_steps)
    env.action_space.seed(seed)
    pi = init_policy(obs_dim=4, act_dim=2)
    state = rollout_init(env, seed=seed)
    return env, pi, state


class TestEpisodesSpanBatches:
    def test_episode_len_carried_across_batches(self) -> None:
        # Time limit 5 is short enough that random CartPole never falls first.
        env, pi, state = _setup(max_episode_steps=5)

        state, b1 = collect(env, pi, state, num_steps=3)
        assert state.episode_len == 3, "episode should still be running after batch 1"
        assert b1.episodes == []

        state, b2 = collect(env, pi, state, num_steps=3)
        assert len(b2.episodes) == 1
        assert b2.episodes[0].episode_len == 5, "episode started in batch 1 must finish in batch 2"
        assert state.episode_len == 1, "new episode has taken one step"

    def test_episodes_longer_than_batch(self) -> None:
        # The old bug: reset every batch capped episodes at the batch size.
        env, pi, state = _setup(max_episode_steps=20)
        finished = []
        for _ in range(20):
            state, batch = collect(env, pi, state, num_steps=4)
            finished.extend(batch.episodes)
        assert finished
        assert max(e.episode_len for e in finished) > 4


class TestTerminatedTruncated:
    def _steps(self, max_episode_steps: int, n: int, seed: int = 0):
        env, pi, state = _setup(max_episode_steps, seed)
        state, batch = collect(env, pi, state, num_steps=n)
        return pi, batch

    def test_flags_match_time_limit(self) -> None:
        # Limit 30: random CartPole sometimes falls before 30 (terminated), sometimes hits 30 (truncated).
        pi, batch = self._steps(max_episode_steps=30, n=600)
        terminated = [s for s in batch.steps if s.terminated]
        truncated = [s for s in batch.steps if s.truncated]
        assert terminated, "expected some real endings"
        assert truncated, "expected some time-limit endings"
        # Truncation happens exactly at the limit: its episode is 30 long.
        truncated_eps = [e for e in batch.episodes if e.truncated]
        terminated_eps = [e for e in batch.episodes if not e.truncated]
        assert all(e.episode_len == 30 for e in truncated_eps)
        assert all(e.episode_len < 30 for e in terminated_eps)

    def test_bootstrap_value_only_on_truncated(self) -> None:
        pi, batch = self._steps(max_episode_steps=30, n=600)
        for s in batch.steps:
            if s.truncated and not s.terminated:
                assert s.bootstrap_value != 0.0
                assert abs(s.bootstrap_value - _v(pi, s.next_obs)) < 1e-6
            else:
                assert s.bootstrap_value == 0.0

    def test_last_value_is_v_of_last_obs(self) -> None:
        pi, batch = self._steps(max_episode_steps=30, n=37)
        assert abs(batch.last_value - _v(pi, batch.last_obs)) < 1e-6

    def test_value_and_next_obs_recorded(self) -> None:
        pi, batch = self._steps(max_episode_steps=30, n=50)
        for s, nxt in zip(batch.steps, batch.steps[1:]):
            assert abs(s.value - _v(pi, s.obs)) < 1e-6
            ended = s.terminated or s.truncated
            if not ended:
                assert torch.equal(s.next_obs, nxt.obs), "within an episode, next_obs is the next step's obs"
