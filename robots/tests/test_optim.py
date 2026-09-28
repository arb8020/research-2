"""Pure Adam: matches torch.optim.Adam, never mutates inputs; donating variant writes in place."""

import pytest
import torch

from robots.models import PolicyWeights, init_policy, policy_forward
from robots.optim import AdamParams, AdamState, adam_update, adam_update_, init_adam
from robots.tree import tensor_leaves, tree_map


def _detached(w: PolicyWeights) -> PolicyWeights:
    return tree_map(lambda x: x.detach().clone(), w)


def _loss(w: PolicyWeights, obs: torch.Tensor) -> torch.Tensor:
    logits, value = policy_forward(w, obs)
    return (logits**2).mean() + (value**2).mean()


def _max_diff(a, b) -> float:
    return max((x - y).abs().max().item() for x, y in zip(tensor_leaves(a), tensor_leaves(b), strict=True))


def _setup(seed: int = 0) -> tuple[PolicyWeights, torch.Tensor]:
    torch.manual_seed(seed)
    return _detached(init_policy(obs_dim=4, act_dim=2, hidden=16)), torch.randn(8, 4)


def test_adam_update_matches_torch_optim():
    """Same init, same loss, 20 steps: pure Adam tracks torch.optim.Adam to float tolerance."""
    w, obs = _setup()
    cfg = AdamParams(lr=1e-2)

    torch_params = [x.clone().requires_grad_(True) for x in tensor_leaves(w)]
    torch_w = PolicyWeights(*torch_params)
    opt = torch.optim.Adam(torch_params, lr=cfg.lr, betas=(cfg.beta1, cfg.beta2), eps=cfg.eps)

    params, state = w, init_adam(w)
    grad_fn = torch.func.grad(_loss)
    for _ in range(20):
        grads = grad_fn(params, obs)
        params, state = adam_update(params, grads, state, cfg)

        opt.zero_grad()
        _loss(torch_w, obs).backward()
        opt.step()

    assert state.step == 20
    diff = _max_diff(params, torch_w)
    assert diff < 1e-5, f"adam_update diverged from torch.optim.Adam: max diff {diff}"


def test_adam_update_does_not_mutate_inputs():
    w, obs = _setup()
    state0 = adam_update(w, torch.func.grad(_loss)(w, obs), init_adam(w), AdamParams(lr=1e-2))[1]
    grads = torch.func.grad(_loss)(w, obs)
    snapshots = [x.clone() for x in tensor_leaves((w, grads, state0.m, state0.v))]

    new_w, new_state = adam_update(w, grads, state0, AdamParams(lr=1e-2))

    for before, after in zip(snapshots, tensor_leaves((w, grads, state0.m, state0.v)), strict=True):
        assert torch.equal(before, after), "adam_update mutated an input"
    assert state0.step == 1
    assert new_state.step == 2
    assert _max_diff(new_w, w) > 0, "adam_update did not move params"
    assert isinstance(new_w, PolicyWeights)
    assert isinstance(new_state.m, PolicyWeights)


def _run_both(steps: int, cfg: AdamParams):
    """Run pure and donating Adam from the same init; return both results + donating ptrs."""
    w, obs = _setup()
    grad_fn = torch.func.grad(_loss)

    pure_params, pure_state = w, init_adam(w)
    for _ in range(steps):
        pure_params, pure_state = adam_update(pure_params, grad_fn(pure_params, obs), pure_state, cfg)

    inplace_params, inplace_state = _detached(w), init_adam(w)
    ptrs0 = [x.data_ptr() for x in tensor_leaves((inplace_params, inplace_state.m, inplace_state.v))]
    for _ in range(steps):
        inplace_state = adam_update_(inplace_params, grad_fn(inplace_params, obs), inplace_state, cfg)
    ptrs1 = [x.data_ptr() for x in tensor_leaves((inplace_params, inplace_state.m, inplace_state.v))]
    return (pure_params, pure_state), (inplace_params, inplace_state), ptrs0, ptrs1


def test_adam_update_inplace_matches_pure_and_keeps_storage():
    (pp, ps), (ip, is_), ptrs0, ptrs1 = _run_both(5, AdamParams(lr=1e-2))
    assert ptrs0 == ptrs1, "adam_update_ reallocated params/m/v"
    assert is_.step == ps.step == 5
    assert _max_diff(pp, ip) == 0.0
    assert _max_diff(ps.m, is_.m) == 0.0
    assert _max_diff(ps.v, is_.v) == 0.0


def test_adam_update_inplace_accepts_requires_grad_params():
    """Weights from init_policy require grad; the donating update must still work on them."""
    torch.manual_seed(0)
    w = init_policy(obs_dim=4, act_dim=2, hidden=16)
    obs = torch.randn(8, 4)
    grads = torch.func.grad(_loss)(w, obs)
    state = adam_update_(w, grads, init_adam(w), AdamParams(lr=1e-2))
    assert state.step == 1
    assert all(x.requires_grad for x in tensor_leaves(w))


def test_lr_schedule():
    """Schedule is called with the 1-based step and overrides cfg.lr."""
    calls: list[int] = []

    def schedule(step: int) -> float:
        calls.append(step)
        return 1e-3 * step

    w, obs = _setup()
    grads = torch.func.grad(_loss)(w, obs)
    params, state = w, init_adam(w)
    for _ in range(3):
        params, state = adam_update(params, grads, state, AdamParams(lr=123.0, lr_schedule=schedule))
    assert calls == [1, 2, 3]

    # Scheduled run == run with the constant lr the schedule returned at each step.
    ref_params, ref_state = w, init_adam(w)
    for step in (1, 2, 3):
        ref_params, ref_state = adam_update(ref_params, grads, ref_state, AdamParams(lr=1e-3 * step))
    assert _max_diff(params, ref_params) == 0.0


def test_adam_update_inplace_compiled_matches_eager():
    """torch.compile(fullgraph=True) of grad + adam_update_ on CPU matches eager; storage kept."""
    if not hasattr(torch, "compile"):
        pytest.skip("torch.compile unavailable")
    cfg = AdamParams(lr=1e-2)

    def step(params: PolicyWeights, state: AdamState, obs: torch.Tensor) -> tuple[AdamState, torch.Tensor]:
        grads, loss = torch.func.grad_and_value(_loss)(params, obs)
        return adam_update_(params, grads, state, cfg), loss

    w, obs = _setup()
    eager_params, eager_state = _detached(w), init_adam(w)
    comp_params, comp_state = _detached(w), init_adam(w)
    ptrs0 = [x.data_ptr() for x in tensor_leaves((comp_params, comp_state.m, comp_state.v))]

    compiled = torch.compile(step, fullgraph=True)
    try:
        comp_state, _ = compiled(comp_params, comp_state, obs)
    except Exception as e:  # no C++ compiler / backend in this environment
        if "compiler" in str(e).lower() or "inductor" in type(e).__module__:
            pytest.skip(f"torch.compile backend unavailable: {type(e).__name__}")
        raise
    eager_state, _ = step(eager_params, eager_state, obs)
    for _ in range(4):
        comp_state, _ = compiled(comp_params, comp_state, obs)
        eager_state, _ = step(eager_params, eager_state, obs)

    ptrs1 = [x.data_ptr() for x in tensor_leaves((comp_params, comp_state.m, comp_state.v))]
    assert ptrs0 == ptrs1, "compiled adam_update_ reallocated params/m/v"
    assert comp_state.step == eager_state.step == 5
    diff = _max_diff(comp_params, eager_params)
    assert diff < 1e-5, f"compiled diverged from eager: {diff}"
