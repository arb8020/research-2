"""Our Adam must match torch.optim.Adam to floating-point tolerance."""

import torch

from robots.optim import (
    AdamParams,
    OptimizerHandle,
    ParamGroup,
    adam_step,
    init_adam,
    make_optimizer,
    zero_grad,
)


def test_adam_matches_torch():
    """Same params, same grads, 20 steps — max diff < 1e-6."""
    torch.manual_seed(42)
    p_ours = torch.randn(3, 4, requires_grad=True)
    p_torch = p_ours.clone().detach().requires_grad_(True)

    opt_ours = init_adam([p_ours], AdamParams(lr=1e-3))
    opt_torch = torch.optim.Adam([p_torch], lr=1e-3)

    for _ in range(20):
        loss_ours = (p_ours**2).sum()
        loss_ours.backward()
        adam_step(opt_ours)
        zero_grad(opt_ours)

        loss_torch = (p_torch**2).sum()
        loss_torch.backward()
        opt_torch.step()
        opt_torch.zero_grad()

    diff = (p_ours - p_torch).abs().max().item()
    assert diff < 1e-6, f"Adam diverged from torch: max diff {diff}"


def test_adam_skips_none_grad():
    """Params with no gradient are left untouched."""
    p = torch.randn(2, 2, requires_grad=True)
    original = p.clone()
    opt = init_adam([p], AdamParams(lr=1e-3))

    adam_step(opt)
    diff = (p - original).abs().max().item()
    assert diff == 0.0, "Adam modified a param with no gradient"


def test_lr_schedule():
    """LR schedule is called each step and overrides the static lr."""
    p = torch.randn(2, 2, requires_grad=True)
    schedule_calls: list[int] = []

    def schedule(step: int) -> float:
        schedule_calls.append(step)
        return 1e-4 * step

    opt = init_adam([p], AdamParams(lr=1e-3, lr_schedule=schedule))

    for _ in range(3):
        loss = (p**2).sum()
        loss.backward()
        adam_step(opt)
        zero_grad(opt)

    assert schedule_calls == [1, 2, 3]
    assert abs(opt.lr - 3e-4) < 1e-10  # last call: schedule(3) = 1e-4 * 3


def test_grad_accum_matches_full_batch():
    """Accumulating 4 micro-batches of size 1 ≈ one batch of size 4."""
    torch.manual_seed(42)

    # Full batch path
    p_full = torch.randn(3, 3, requires_grad=True)
    data = [torch.randn(1, 3) for _ in range(4)]

    opt_full = make_optimizer([p_full], AdamParams(lr=1e-2))
    opt_full.zero()
    loss_full = sum((p_full @ d.T).sum() for d in data) / 4
    loss_full.backward()
    opt_full.step()

    # Accumulated path
    p_accum = p_full.clone().detach().requires_grad_(True)
    # Reset to same initial state by re-cloning
    torch.manual_seed(42)
    p_accum = torch.randn(3, 3, requires_grad=True)

    opt_accum = make_optimizer([p_accum], AdamParams(lr=1e-2))
    opt_accum.zero()
    for d in data:
        micro_loss = (p_accum @ d.T).sum() / 4
        micro_loss.backward()
    opt_accum.step()

    diff = (p_full - p_accum).abs().max().item()
    assert diff < 1e-6, f"Grad accum diverged from full batch: max diff {diff}"


def test_param_groups():
    """Different param groups get different learning rates."""
    torch.manual_seed(42)
    p1 = torch.randn(2, 2, requires_grad=True)
    p2 = torch.randn(2, 2, requires_grad=True)
    p1_orig = p1.clone()
    p2_orig = p2.clone()

    opt = make_optimizer(config=[
        ParamGroup(params=[p1], optimizer=AdamParams(lr=1e-1)),
        ParamGroup(params=[p2], optimizer=AdamParams(lr=1e-5)),
    ])

    loss = (p1**2).sum() + (p2**2).sum()
    opt.zero()
    loss.backward()
    opt.step()

    # p1 should move much more than p2
    d1 = (p1 - p1_orig).abs().max().item()
    d2 = (p2 - p2_orig).abs().max().item()
    assert d1 > d2 * 10, f"Expected p1 to move much more than p2: {d1} vs {d2}"
