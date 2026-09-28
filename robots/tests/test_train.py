"""Tests for the generic (eager, optimizer-driven) training step.

Returns/loss tests live in test_losses.py. train_step itself is rewritten in
phase B (forward_backward + pure optimizer); this only keeps it exercised.
"""

from __future__ import annotations

import torch

from robots.models import init_policy, policy_params
from robots.optim import AdamParams, make_optimizer
from robots.train import LossFnInputs, reinforce_loss, train_step


def _dummy_inputs(n: int = 5) -> LossFnInputs:
    returns = torch.linspace(1.0, 0.2, n)
    return {
        "obs": torch.randn(n, 4),
        "actions": torch.arange(n) % 2,
        "returns": returns,
        "advantages": returns - 0.5,
    }


class TestTrainStep:
    def test_one_step_updates_params(self) -> None:
        pi = init_policy(obs_dim=4, act_dim=2)
        params = policy_params(pi)
        original = [p.clone() for p in params]
        opt = make_optimizer(params, AdamParams(lr=1e-2))

        m = train_step(
            get_batch=lambda: _dummy_inputs(),
            loss_fn=reinforce_loss,
            weights=pi,
            opt=opt,
        )

        moved = any((p - o).abs().max().item() > 0 for p, o in zip(params, original))
        assert moved, "train_step did not update any parameters"
        assert "pi_loss" in m

    def test_grad_accum_produces_metrics(self) -> None:
        pi = init_policy(obs_dim=4, act_dim=2)
        opt = make_optimizer(policy_params(pi), AdamParams(lr=1e-3))

        m = train_step(
            get_batch=lambda: _dummy_inputs(),
            loss_fn=reinforce_loss,
            weights=pi,
            opt=opt,
            grad_accum_steps=4,
        )

        assert "pi_loss" in m
        assert "entropy" in m
