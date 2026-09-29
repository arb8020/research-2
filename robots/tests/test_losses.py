"""Tests for batch -> LossFnInputs, the RL losses, and forward_backward."""

from __future__ import annotations

import dataclasses

import gymnasium
import numpy as np
import torch

from robots.collect import Batch, Step, collect, rollout_init
from robots.models import PolicyWeights, ValueWeights, init_policy, init_value, value_forward
from robots.train import (
    LossFnInputs,
    compute_loss_fn_inputs,
    forward_backward,
    reinforce_loss,
    value_loss,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _step(reward: float, *, terminated: bool = False, truncated: bool = False,
          value: float = 0.0, bootstrap_value: float = 0.0, action: int = 0) -> Step:
    return Step(
        obs=torch.zeros(4), action=action, reward=reward,
        terminated=terminated, truncated=truncated, next_obs=torch.zeros(4),
        value=value, bootstrap_value=bootstrap_value,
    )


def _batch(steps: list[Step], last_value: float) -> Batch:
    return Batch(steps=steps, episodes=[], last_obs=torch.zeros(4), last_value=last_value)


def check_returns(steps: list[Step], last_value: float, gamma: float, expected: list[float]) -> None:
    inputs = compute_loss_fn_inputs(_batch(steps, last_value), gamma)
    got = inputs["returns"].tolist()
    assert np.allclose(got, expected, atol=1e-6), f"returns: expected {expected}, got {got}"


def _random_inputs(T: int = 8, seed: int = 0) -> LossFnInputs:
    g = torch.Generator().manual_seed(seed)
    returns = torch.randn(T, generator=g)
    return {
        "obs": torch.randn(T, 4, generator=g),
        "actions": torch.randint(0, 2, (T,), generator=g),
        "returns": returns,
        "advantages": returns - torch.randn(T, generator=g),
    }


def _sgd(w, g, lr: float):
    """Plain p - lr*g, so these tests don't depend on the optimizer branch."""
    with torch.no_grad():
        return type(w)(**{f.name: getattr(w, f.name) - lr * getattr(g, f.name) for f in dataclasses.fields(w)})


# ---------------------------------------------------------------------------
# compute_loss_fn_inputs: hand-computed returns
# ---------------------------------------------------------------------------

class TestReturns:
    def test_termination_does_not_bootstrap(self) -> None:
        # r=1 each; step 1 terminates. last_value=10 must not reach steps 0-1.
        steps = [_step(1.0), _step(1.0, terminated=True), _step(1.0)]
        # step2: 1 + .5*10 = 6 ; step1: 1 + .5*0 = 1 ; step0: 1 + .5*1 = 1.5
        check_returns(steps, last_value=10.0, gamma=0.5, expected=[1.5, 1.0, 6.0])

    def test_truncation_uses_bootstrap_value(self) -> None:
        steps = [_step(1.0), _step(1.0, truncated=True, bootstrap_value=4.0), _step(2.0)]
        # step2: 2 + .5*0 = 2 ; step1: 1 + .5*4 = 3 ; step0: 1 + .5*3 = 2.5
        check_returns(steps, last_value=0.0, gamma=0.5, expected=[2.5, 3.0, 2.0])

    def test_terminated_and_truncated_is_termination(self) -> None:
        # collect_step records bootstrap_value=0 when both flags are set; returns trust it.
        steps = [_step(1.0, terminated=True, truncated=True, bootstrap_value=0.0)]
        check_returns(steps, last_value=99.0, gamma=0.9, expected=[1.0])

    def test_batch_end_uses_last_value(self) -> None:
        steps = [_step(1.0), _step(1.0)]
        # step1: 1 + .9*5 = 5.5 ; step0: 1 + .9*5.5 = 5.95
        check_returns(steps, last_value=5.0, gamma=0.9, expected=[5.95, 5.5])

    def test_no_leak_across_episode_boundaries(self) -> None:
        # Two episodes in one batch; the huge reward in episode 2 must not reach episode 1.
        steps = [_step(1.0), _step(1.0, terminated=True), _step(100.0), _step(100.0, terminated=True)]
        check_returns(steps, last_value=0.0, gamma=1.0, expected=[2.0, 1.0, 200.0, 100.0])

    def test_gamma_respected(self) -> None:
        steps = [_step(1.0), _step(2.0), _step(3.0)]
        check_returns(steps, last_value=4.0, gamma=0.0, expected=[1.0, 2.0, 3.0])
        check_returns(steps, last_value=4.0, gamma=1.0, expected=[10.0, 9.0, 7.0])

    def test_advantages_are_returns_minus_collected_value(self) -> None:
        steps = [_step(1.0, value=0.25), _step(1.0, terminated=True, value=2.0)]
        inputs = compute_loss_fn_inputs(_batch(steps, last_value=0.0), gamma=1.0)
        assert np.allclose(inputs["returns"].tolist(), [2.0, 1.0])
        assert np.allclose(inputs["advantages"].tolist(), [1.75, -1.0])
        assert not inputs["advantages"].requires_grad

    def test_shapes_and_dtypes(self) -> None:
        steps = [_step(1.0, action=1), _step(0.0)]
        inputs = compute_loss_fn_inputs(_batch(steps, last_value=0.0), gamma=0.9)
        assert inputs["obs"].shape == (2, 4)
        assert inputs["actions"].dtype == torch.long
        assert inputs["actions"].tolist() == [1, 0]
        assert set(inputs) == {"obs", "actions", "returns", "advantages"}
        for t in (inputs["returns"], inputs["advantages"]):
            assert t.shape == (2,)
            assert t.dtype == torch.float32


# ---------------------------------------------------------------------------
# Losses + forward_backward
# ---------------------------------------------------------------------------

def _nonzero_everywhere(grads) -> None:
    for f in dataclasses.fields(grads):
        assert getattr(grads, f.name).abs().sum() > 0, f"no grad reached {f.name}"


class TestLosses:
    def test_reinforce_grads_are_policy_weights(self) -> None:
        # Separate weight objects: reinforce_loss cannot touch the value function by construction.
        pi = init_policy(obs_dim=4, act_dim=2)
        grads, m = forward_backward(reinforce_loss, pi, _random_inputs())
        assert type(grads) is PolicyWeights
        for f in dataclasses.fields(pi):
            assert getattr(grads, f.name).shape == getattr(pi, f.name).shape
        _nonzero_everywhere(grads)
        for key in ("loss", "pi_loss", "entropy", "advantage_mean", "advantage_std"):
            assert key in m, f"missing metric {key}"
            assert isinstance(m[key], torch.Tensor)
            assert m[key].ndim == 0

    def test_value_grads_are_value_weights(self) -> None:
        vf = init_value(obs_dim=4)
        grads, m = forward_backward(value_loss, vf, _random_inputs())
        assert type(grads) is ValueWeights
        for f in dataclasses.fields(vf):
            assert getattr(grads, f.name).shape == getattr(vf, f.name).shape
        _nonzero_everywhere(grads)
        for key in ("loss", "value_loss", "value_mean", "return_mean"):
            assert key in m, f"missing metric {key}"
            assert m[key].ndim == 0

    def test_value_loss_hand_computed(self) -> None:
        # Zero the head so V(obs) = b_value = 0.5 everywhere: loss = mean((0.5 - r)^2).
        vf = init_value(obs_dim=4)
        vf = dataclasses.replace(vf, w_value=torch.zeros_like(vf.w_value), b_value=torch.full((1,), 0.5))
        inputs = {**_random_inputs(T=3), "returns": torch.tensor([0.5, 1.5, -0.5])}
        loss, _ = value_loss(vf, inputs)
        assert abs(loss.item() - (0.0 + 1.0 + 1.0) / 3) < 1e-6

    def test_matches_eager_autograd(self) -> None:
        for loss_fn, w in ((reinforce_loss, init_policy(obs_dim=4, act_dim=2)), (value_loss, init_value(obs_dim=4))):
            inputs = _random_inputs()
            grads, _ = forward_backward(loss_fn, w, inputs)
            loss, _ = loss_fn(w, inputs)
            leaves = [getattr(w, f.name) for f in dataclasses.fields(w)]
            eager = torch.autograd.grad(loss, leaves)
            for f, e in zip(dataclasses.fields(w), eager):
                assert torch.allclose(getattr(grads, f.name), e, atol=1e-6), f.name


# ---------------------------------------------------------------------------
# Probe environment (Andy Jones, "Debugging RL, Without the Agonizing Pain")
# ---------------------------------------------------------------------------

class ConstantRewardEnv(gymnasium.Env):
    """Probe 1: one obs, one-step episodes, reward always 1. V(obs) must learn 1."""

    observation_space = gymnasium.spaces.Box(low=-1.0, high=1.0, shape=(1,), dtype=np.float32)
    action_space = gymnasium.spaces.Discrete(2)
    terminated = True
    truncated = False

    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        return np.ones(1, dtype=np.float32), {}

    def step(self, action):
        return np.ones(1, dtype=np.float32), 1.0, self.terminated, self.truncated, {}


class AlwaysTruncatesEnv(ConstantRewardEnv):
    """Probe: every episode is cut by a time limit after one step. The future is
    unknown, so V(s) = 1 + gamma*V(s) -> 1/(1-gamma). Only correct if truncation
    bootstraps with V(next_obs)."""

    terminated = False
    truncated = True


class NeverEndsEnv(ConstantRewardEnv):
    """Probe: the episode never ends; only batch cuts. V -> 1/(1-gamma), only
    correct if the batch end bootstraps with last_value."""

    terminated = False
    truncated = False


PROBE_ITERS = 800


def _train_value_on_probe(
    env: gymnasium.Env, *, gamma: float, num_steps: int, iters: int, lr: float,
) -> ValueWeights:
    """collect -> compute_loss_fn_inputs -> forward_backward(value_loss) -> v - lr*g.

    Only vf is trained; pi stays at its random init (its actions don't affect these envs).
    """
    torch.manual_seed(0)
    pi = init_policy(obs_dim=1, act_dim=2, hidden=16)
    vf = init_value(obs_dim=1, hidden=16)
    state = rollout_init(env, seed=0)
    for _ in range(iters):
        state, batch = collect(env, pi, vf, state, num_steps=num_steps)
        inputs = compute_loss_fn_inputs(batch, gamma=gamma)
        grads, _ = forward_backward(value_loss, vf, inputs)
        vf = _sgd(vf, grads, lr)
    return vf


def _v(vf: ValueWeights) -> float:
    with torch.no_grad():
        return value_forward(vf, torch.ones(1, 1)).item()


class TestProbes:
    def test_termination_learns_reward(self) -> None:
        vf = _train_value_on_probe(ConstantRewardEnv(), gamma=0.99, num_steps=16, iters=300, lr=0.05)
        assert abs(_v(vf) - 1.0) < 0.05, f"V should converge to reward 1.0, got {_v(vf):.4f}"

    def test_truncation_bootstraps(self) -> None:
        # gamma=0.5 -> target 2.0. Treating truncation as termination would give 1.0.
        vf = _train_value_on_probe(AlwaysTruncatesEnv(), gamma=0.5, num_steps=16, iters=PROBE_ITERS, lr=0.02)
        assert abs(_v(vf) - 2.0) < 0.05, f"V should converge to 1/(1-0.5)=2.0, got {_v(vf):.4f}"

    def test_batch_cut_bootstraps(self) -> None:
        # gamma=0.5 -> target 2.0. Using g=0 at the batch end (old bug) would give < 2.
        vf = _train_value_on_probe(NeverEndsEnv(), gamma=0.5, num_steps=4, iters=PROBE_ITERS, lr=0.02)
        assert abs(_v(vf) - 2.0) < 0.05, f"V should converge to 1/(1-0.5)=2.0, got {_v(vf):.4f}"
