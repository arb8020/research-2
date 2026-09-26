"""Shape and contract tests for models and record_episode."""

from __future__ import annotations

import json

import gymnasium
import torch

from robots.models import PolicyWeights, WMWeights, init_policy, init_wm, policy_forward, wm_forward
from robots.train import record_episode


def _env() -> gymnasium.Env:
    return gymnasium.make("CartPole-v1")


def _wm() -> WMWeights:
    return init_wm(obs_dim=4, act_dim=2)


def _pi() -> PolicyWeights:
    return init_policy(obs_dim=4, act_dim=2)


class TestWorldModel:
    def test_forward_shapes(self) -> None:
        """Forward pass: shapes are wired correctly."""
        wm = _wm()
        pred_obs, pred_reward, pred_done = wm_forward(
            wm, torch.randn(4, 4), torch.tensor([0, 1, 0, 1])
        )
        assert pred_obs.shape == (4, 4)
        assert pred_reward.shape == (4,)
        assert pred_done.shape == (4,)


class TestPolicy:
    def test_forward_shapes(self) -> None:
        """Forward pass: logits and value shapes."""
        logits, value = policy_forward(_pi(), torch.randn(3, 4))
        assert logits.shape == (3, 2)
        assert value.shape == (3,)


class TestRecordEpisode:
    def test_trajectory_is_column_oriented_with_terminal_obs(self) -> None:
        """The artifact payload contract: equal lengths, obs one longer.

        `obs` carries the terminal observation (len(actions) + 1) so a renderer
        can draw the final frame; `obs[t]` is the state the agent saw when it
        chose `actions[t]`.
        """
        traj = record_episode(_env(), _pi())
        assert traj["env"] == "CartPole-v1"
        n = len(traj["actions"])
        assert n >= 1
        assert len(traj["rewards"]) == n
        assert len(traj["obs"]) == n + 1, "obs includes the terminal observation"
        assert all(len(o) == 4 for o in traj["obs"]), "CartPole obs is 4-dim"
        assert all(a in (0, 1) for a in traj["actions"])
        assert all(isinstance(r, float) for r in traj["rewards"])
        # JSON-serializable: no tensors, no numpy scalars.
        json.dumps(traj)
