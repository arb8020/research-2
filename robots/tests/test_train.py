"""Tests for the generic training step/loop (forward_backward + Adam).

Returns/loss tests live in test_losses.py.
"""

from __future__ import annotations

import torch

from robots.models import init_policy, init_value
from robots.core import AdamParams, adam_scalars, adam_update_, init_adam
from robots.train import (
    LossFnInputs,
    forward_backward,
    forward_backward_accum,
    reinforce_loss,
    value_loss,
    to_floats,
    train_loop,
    train_step,
)
from robots.core import tensor_leaves, tree_map


def _dummy_inputs(n: int = 6, seed: int = 0) -> LossFnInputs:
    g = torch.Generator().manual_seed(seed)
    returns = torch.linspace(1.0, 0.2, n)
    return {
        "obs": torch.randn(n, 4, generator=g),
        "actions": torch.arange(n) % 2,
        "returns": returns,
        "advantages": returns - 0.5,
    }


def _clone(pi):
    return tree_map(lambda x: x.detach().clone(), pi)


class TestTrainStep:
    def test_one_step_updates_params(self) -> None:
        pi = init_policy(obs_dim=4, act_dim=2)
        before = _clone(pi)
        cfg = AdamParams(lr=1e-2)
        state, m = train_step(reinforce_loss, pi, init_adam(pi), _dummy_inputs(), cfg, step=1)

        moved = any((p - o).abs().max().item() > 0 for p, o in zip(tensor_leaves(pi), tensor_leaves(before)))
        assert moved, "train_step did not update any parameters"
        assert set(to_floats(m)) >= {"loss", "pi_loss", "entropy"}
        assert all(isinstance(v, float) for v in to_floats(m).values())

    def test_equals_its_lower_level_calls(self) -> None:
        # Continuous granularity: train_step == forward_backward + adam_update_.
        torch.manual_seed(0)
        pi_a = init_policy(obs_dim=4, act_dim=2)
        pi_b = _clone(pi_a)
        cfg = AdamParams(lr=1e-2)
        inputs = _dummy_inputs()
        state_a, state_b = init_adam(pi_a), init_adam(pi_b)
        for step in (1, 2, 3):
            state_a, _ = train_step(reinforce_loss, pi_a, state_a, inputs, cfg, step)
            grads, _ = forward_backward(reinforce_loss, pi_b, inputs)
            state_b = adam_update_(pi_b, grads, state_b, cfg, adam_scalars(cfg, step, "cpu"))
        for a, b in zip(tensor_leaves(pi_a), tensor_leaves(pi_b)):
            assert torch.equal(a, b)


class TestGradAccum:
    def test_accum_equals_full_batch(self) -> None:
        # Mean loss over two equal halves == mean over the whole batch.
        pi = init_policy(obs_dim=4, act_dim=2)
        full = _dummy_inputs(n=8)
        halves = [{k: v[:4] for k, v in full.items()}, {k: v[4:] for k, v in full.items()}]
        g_full, m_full = forward_backward(reinforce_loss, pi, full)
        g_acc, m_acc = forward_backward_accum(reinforce_loss, pi, halves)
        for a, b in zip(tensor_leaves(g_full), tensor_leaves(g_acc)):
            assert torch.allclose(a, b, atol=1e-6)
        assert torch.allclose(m_full["loss"], m_acc["loss"], atol=1e-6)


class TestTrainLoop:
    def test_loop_runs_and_reduces_value_loss(self) -> None:
        torch.manual_seed(0)
        vf = init_value(obs_dim=4)
        inputs = _dummy_inputs()
        seen: list[int] = []
        _, history = train_loop(
            get_inputs=lambda: inputs, loss_fn=value_loss, weights=vf,
            cfg=AdamParams(lr=1e-2), num_iters=30, grad_accum_steps=2,
            on_iter=lambda step, m: seen.append(step),
        )
        assert seen == list(range(1, 31))
        assert history[-1]["value_loss"] < history[0]["value_loss"]
