"""Tests for the generic training step and RL loss functions."""

from __future__ import annotations

import torch

from robots.models import PolicyWeights, init_policy, policy_params
from robots.optim import AdamParams, make_optimizer
from robots.rollout import PolicyStep
from robots.train import compute_returns, reinforce_loss, train_step


def _dummy_steps(n: int = 5) -> list[PolicyStep]:
    """Create n dummy policy steps with known values."""
    return [
        PolicyStep(
            obs=torch.randn(4),
            action=i % 2,
            reward=1.0,
            done=(i == n - 1),
            logprob=-0.5,
            value=0.5,
        )
        for i in range(n)
    ]


class TestComputeReturns:
    def test_single_step(self) -> None:
        steps = [PolicyStep(obs=torch.zeros(4), action=0, reward=10.0, done=True, logprob=0.0, value=0.0)]
        returns = compute_returns(steps)
        assert len(returns) == 1
        assert returns[0] == 10.0

    def test_discounting(self) -> None:
        steps = [
            PolicyStep(obs=torch.zeros(4), action=0, reward=1.0, done=False, logprob=0.0, value=0.0),
            PolicyStep(obs=torch.zeros(4), action=0, reward=1.0, done=True, logprob=0.0, value=0.0),
        ]
        returns = compute_returns(steps, gamma=0.9)
        assert abs(returns[1] - 1.0) < 1e-6
        assert abs(returns[0] - 1.9) < 1e-6  # 1 + 0.9 * 1


class TestReinforceLoss:
    def test_returns_loss_and_metrics(self) -> None:
        pi = init_policy(obs_dim=4, act_dim=2)
        steps = _dummy_steps()
        loss, m = reinforce_loss(pi, steps)

        assert isinstance(loss, torch.Tensor)
        assert loss.requires_grad
        for key in ("pi_loss", "entropy", "value_loss", "advantage_mean", "advantage_std"):
            assert key in m, f"missing metric: {key}"
            assert isinstance(m[key], float)


class TestTrainStep:
    def test_one_step_updates_params(self) -> None:
        pi = init_policy(obs_dim=4, act_dim=2)
        params = policy_params(pi)
        original = [p.clone() for p in params]
        opt = make_optimizer(params, AdamParams(lr=1e-2))

        m = train_step(
            get_batch=lambda: _dummy_steps(),
            loss_fn=reinforce_loss,
            weights=pi,
            opt=opt,
        )

        # Params should have changed
        moved = any((p - o).abs().max().item() > 0 for p, o in zip(params, original))
        assert moved, "train_step did not update any parameters"
        assert "pi_loss" in m

    def test_grad_accum_produces_metrics(self) -> None:
        pi = init_policy(obs_dim=4, act_dim=2)
        opt = make_optimizer(policy_params(pi), AdamParams(lr=1e-3))

        m = train_step(
            get_batch=lambda: _dummy_steps(),
            loss_fn=reinforce_loss,
            weights=pi,
            opt=opt,
            grad_accum_steps=4,
        )

        assert "pi_loss" in m
        assert "entropy" in m
