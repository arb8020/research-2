"""Tests for imagined rollouts and the world-model loss."""

from __future__ import annotations

import dataclasses

import gymnasium
import torch

from robots.models import init_policy, init_value, init_wm, policy_value, transitions_to_inputs, wm_loss
from robots.optim import AdamParams, init_adam
from robots.rollout import collect_transitions, imagine_rollout
from robots.train import compute_loss_fn_inputs, train_step


def _wm_with_done_bias(bias: float):
    wm = init_wm(obs_dim=4, act_dim=2)
    # Zero the done head's weights so the prediction is exactly sigmoid(bias).
    return dataclasses.replace(wm, w_done=torch.zeros_like(wm.w_done), b_done=torch.full((1,), bias))


class TestImagineRollout:
    def test_never_done_runs_full_horizon_and_bootstraps_cut(self) -> None:
        torch.manual_seed(0)
        pi = init_policy(obs_dim=4, act_dim=2)
        vf = init_value(obs_dim=4)
        batch = imagine_rollout(_wm_with_done_bias(-10.0), pi, vf, torch.zeros(4), horizon=7)
        assert len(batch.steps) == 7
        assert not any(s.terminated or s.truncated for s in batch.steps)
        assert batch.episodes == []
        assert abs(batch.last_value - policy_value(vf, batch.last_obs)) < 1e-6
        for s, nxt in zip(batch.steps, batch.steps[1:]):
            assert torch.equal(s.next_obs, nxt.obs)

    def test_always_done_terminates_after_one_step(self) -> None:
        torch.manual_seed(0)
        pi = init_policy(obs_dim=4, act_dim=2)
        vf = init_value(obs_dim=4)
        batch = imagine_rollout(_wm_with_done_bias(10.0), pi, vf, torch.zeros(4), horizon=7)
        assert len(batch.steps) == 1
        step = batch.steps[0]
        assert step.terminated
        assert not step.truncated
        assert step.bootstrap_value == 0.0
        assert len(batch.episodes) == 1
        assert not batch.episodes[0].timed_out
        # Feeds the RL pipeline: return is just the (predicted) reward.
        inputs = compute_loss_fn_inputs(batch, gamma=0.99)
        assert abs(inputs["returns"][0].item() - step.reward) < 1e-6


class TestWorldModelLoss:
    def test_train_step_reduces_wm_loss(self) -> None:
        torch.manual_seed(0)
        env = gymnasium.make("CartPole-v1")
        env.reset(seed=0)
        env.action_space.seed(0)
        inputs = transitions_to_inputs(collect_transitions(env, num_steps=200))
        wm = init_wm(obs_dim=4, act_dim=2)
        cfg = AdamParams(lr=1e-3)
        state = init_adam(wm)
        losses = []
        for step in range(1, 51):
            state, m = train_step(wm_loss, wm, state, inputs, cfg, step)
            losses.append(m["loss"].item())
        assert losses[-1] < 0.5 * losses[0], f"wm loss {losses[0]:.3f} -> {losses[-1]:.3f}"
        assert wm.obs_dim == 4  # static fields survive the pytree round trip
