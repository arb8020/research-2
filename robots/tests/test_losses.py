"""Tests for batch -> LossFnInputs, the RL losses, and forward_backward."""

from __future__ import annotations

import dataclasses
import functools

import gymnasium
import numpy as np
import torch
import torch.utils._pytree as pytree

from robots.collect import Batch, Step, collect, rollout_init
from robots.models import PolicyWeights, init_policy, policy_forward
from robots.train import (
    LossFnInputs,
    actor_critic_loss,
    compute_loss_fn_inputs,
    forward_backward,
    reinforce_loss,
    value_loss,
)

# PHASE-A STOPGAP: forward_backward needs PolicyWeights registered as a pytree.
# The optimizer branch registers weight dataclasses in robots/tree.py; delete this at merge.
if PolicyWeights not in pytree.SUPPORTED_NODES:
    pytree.register_dataclass(PolicyWeights)


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


def _sgd(w: PolicyWeights, g: PolicyWeights, lr: float) -> PolicyWeights:
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

VALUE_HEAD = ("w_value", "b_value")
ACTION_HEAD = ("w_action", "b_action")


class TestLosses:
    def test_forward_backward_returns_weight_shaped_grads(self) -> None:
        pi = init_policy(obs_dim=4, act_dim=2)
        grads, m = forward_backward(actor_critic_loss, pi, _random_inputs())
        assert type(grads) is PolicyWeights
        for f in dataclasses.fields(pi):
            assert getattr(grads, f.name).shape == getattr(pi, f.name).shape
        for key in ("loss", "pi_loss", "entropy", "advantage_mean", "advantage_std",
                    "value_loss", "value_mean", "return_mean"):
            assert key in m, f"missing metric {key}"
            assert isinstance(m[key], torch.Tensor)
            assert m[key].ndim == 0

    def test_value_loss_reaches_value_head_only(self) -> None:
        pi = init_policy(obs_dim=4, act_dim=2)
        grads, _ = forward_backward(value_loss, pi, _random_inputs())
        for name in VALUE_HEAD:
            assert getattr(grads, name).abs().sum() > 0, f"value_loss gave no grad to {name}"
        for name in ACTION_HEAD:
            assert torch.all(getattr(grads, name) == 0), f"value_loss leaked into {name}"

    def test_reinforce_loss_does_not_touch_value_head(self) -> None:
        pi = init_policy(obs_dim=4, act_dim=2)
        grads, _ = forward_backward(reinforce_loss, pi, _random_inputs())
        for name in VALUE_HEAD:
            assert torch.all(getattr(grads, name) == 0), f"reinforce_loss leaked into {name}"
        for name in ACTION_HEAD:
            assert getattr(grads, name).abs().sum() > 0

    def test_actor_critic_is_reinforce_plus_scaled_value(self) -> None:
        pi = init_policy(obs_dim=4, act_dim=2)
        inputs = _random_inputs()
        vf_coef = 0.37
        ac, _ = actor_critic_loss(pi, inputs, vf_coef=vf_coef)
        pg, _ = reinforce_loss(pi, inputs)
        vl, _ = value_loss(pi, inputs)
        assert torch.allclose(ac, pg + vf_coef * vl, atol=1e-6)

        g_ac, _ = forward_backward(functools.partial(actor_critic_loss, vf_coef=vf_coef), pi, inputs)
        g_pg, _ = forward_backward(reinforce_loss, pi, inputs)
        g_vl, _ = forward_backward(value_loss, pi, inputs)
        for f in dataclasses.fields(pi):
            expected = getattr(g_pg, f.name) + vf_coef * getattr(g_vl, f.name)
            assert torch.allclose(getattr(g_ac, f.name), expected, atol=1e-6), f.name

    def test_matches_eager_autograd(self) -> None:
        pi = init_policy(obs_dim=4, act_dim=2)
        inputs = _random_inputs()
        grads, _ = forward_backward(actor_critic_loss, pi, inputs)
        loss, _ = actor_critic_loss(pi, inputs)
        leaves = [getattr(pi, f.name) for f in dataclasses.fields(pi)]
        eager = torch.autograd.grad(loss, leaves)
        for f, e in zip(dataclasses.fields(pi), eager):
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


def _train_on_probe(
    env: gymnasium.Env, loss_fn, *, gamma: float, num_steps: int, iters: int, lr: float,
) -> tuple[PolicyWeights, PolicyWeights]:
    """collect -> compute_loss_fn_inputs -> forward_backward -> p - lr*g. Returns (initial, trained)."""
    torch.manual_seed(0)
    pi0 = init_policy(obs_dim=1, act_dim=2, hidden=16)
    pi = pi0
    state = rollout_init(env, seed=0)
    for _ in range(iters):
        state, batch = collect(env, pi, state, num_steps=num_steps)
        inputs = compute_loss_fn_inputs(batch, gamma=gamma)
        grads, _ = forward_backward(loss_fn, pi, inputs)
        pi = _sgd(pi, grads, lr)
    return pi0, pi


def _v(pi: PolicyWeights) -> float:
    with torch.no_grad():
        return policy_forward(pi, torch.ones(1, 1))[1].item()


class TestProbes:
    def test_termination_actor_critic_learns_value(self) -> None:
        _, pi = _train_on_probe(ConstantRewardEnv(), actor_critic_loss,
                                gamma=0.99, num_steps=16, iters=300, lr=0.05)
        assert abs(_v(pi) - 1.0) < 0.05, f"V should converge to reward 1.0, got {_v(pi):.4f}"

    def test_termination_reinforce_alone_never_learns_value(self) -> None:
        # Negative control: the old bug. No value loss -> value head never moves, V stays wrong.
        # (V itself can drift a little because the shared trunk is trained by the policy term.)
        pi0, pi = _train_on_probe(ConstantRewardEnv(), reinforce_loss,
                                  gamma=0.99, num_steps=16, iters=300, lr=0.05)
        for name in VALUE_HEAD:
            assert torch.equal(getattr(pi0, name), getattr(pi, name)), f"{name} moved"
        assert abs(_v(pi) - 1.0) > 0.5, f"V={_v(pi):.4f} should be nowhere near 1.0"

    def test_truncation_bootstraps(self) -> None:
        # gamma=0.5 -> target 2.0. Treating truncation as termination would give 1.0.
        _, pi = _train_on_probe(AlwaysTruncatesEnv(), value_loss,
                                gamma=0.5, num_steps=16, iters=PROBE_ITERS, lr=0.02)
        assert abs(_v(pi) - 2.0) < 0.05, f"V should converge to 1/(1-0.5)=2.0, got {_v(pi):.4f}"

    def test_batch_cut_bootstraps(self) -> None:
        # gamma=0.5 -> target 2.0. Using g=0 at the batch end (old bug) would give < 2.
        _, pi = _train_on_probe(NeverEndsEnv(), value_loss,
                                gamma=0.5, num_steps=4, iters=PROBE_ITERS, lr=0.02)
        assert abs(_v(pi) - 2.0) < 0.05, f"V should converge to 1/(1-0.5)=2.0, got {_v(pi):.4f}"

