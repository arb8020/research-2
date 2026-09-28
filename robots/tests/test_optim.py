"""Pure Adam: matches torch.optim.Adam, never mutates inputs; donating variant writes in place."""

import re

import pytest
import torch
from torch._dynamo.testing import CompileCounterWithBackend
from torch._inductor.utils import run_and_get_code

from robots.models import PolicyWeights, init_policy, policy_forward
from robots.optim import AdamParams, AdamState, adam_scalars, adam_update, adam_update_, init_adam
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


def _sc(cfg: AdamParams, step: int):
    return adam_scalars(cfg, step, "cpu")


def test_adam_update_matches_torch_optim():
    """Same init, same loss, 20 steps: pure Adam tracks torch.optim.Adam to float tolerance."""
    w, obs = _setup()
    cfg = AdamParams(lr=1e-2)

    torch_params = [x.clone().requires_grad_(True) for x in tensor_leaves(w)]
    torch_w = PolicyWeights(*torch_params)
    opt = torch.optim.Adam(torch_params, lr=cfg.lr, betas=(cfg.beta1, cfg.beta2), eps=cfg.eps)

    params, state = w, init_adam(w)
    grad_fn = torch.func.grad(_loss)
    for step in range(1, 21):
        params, state = adam_update(params, grad_fn(params, obs), state, cfg, _sc(cfg, step))

        opt.zero_grad()
        _loss(torch_w, obs).backward()
        opt.step()

    diff = _max_diff(params, torch_w)
    assert diff < 1e-5, f"adam_update diverged from torch.optim.Adam: max diff {diff}"


def test_adam_update_does_not_mutate_inputs():
    w, obs = _setup()
    cfg = AdamParams(lr=1e-2)
    state1 = adam_update(w, torch.func.grad(_loss)(w, obs), init_adam(w), cfg, _sc(cfg, 1))[1]
    grads = torch.func.grad(_loss)(w, obs)
    scalars = _sc(cfg, 2)
    snapshots = [x.clone() for x in tensor_leaves((w, grads, state1, scalars))]

    new_w, new_state = adam_update(w, grads, state1, cfg, scalars)

    for before, after in zip(snapshots, tensor_leaves((w, grads, state1, scalars)), strict=True):
        assert torch.equal(before, after), "adam_update mutated an input"
    assert _max_diff(new_w, w) > 0, "adam_update did not move params"
    assert isinstance(new_w, PolicyWeights)
    assert isinstance(new_state.m, PolicyWeights)


def test_adam_update_inplace_matches_pure_and_keeps_storage():
    w, obs = _setup()
    cfg = AdamParams(lr=1e-2)
    grad_fn = torch.func.grad(_loss)

    pure_params, pure_state = w, init_adam(w)
    inplace_params, inplace_state = _detached(w), init_adam(w)
    ptrs0 = [x.data_ptr() for x in tensor_leaves((inplace_params, inplace_state))]
    for step in range(1, 6):
        pure_params, pure_state = adam_update(pure_params, grad_fn(pure_params, obs), pure_state, cfg, _sc(cfg, step))
        inplace_state = adam_update_(inplace_params, grad_fn(inplace_params, obs), inplace_state, cfg, _sc(cfg, step))

    assert [x.data_ptr() for x in tensor_leaves((inplace_params, inplace_state))] == ptrs0
    assert _max_diff(pure_params, inplace_params) == 0.0
    assert _max_diff(pure_state, inplace_state) == 0.0


def test_adam_update_inplace_accepts_requires_grad_params():
    """Weights from init_policy require grad; the donating update must still work on them."""
    torch.manual_seed(0)
    w = init_policy(obs_dim=4, act_dim=2, hidden=16)
    cfg = AdamParams(lr=1e-2)
    grads = torch.func.grad(_loss)(w, torch.randn(8, 4))
    adam_update_(w, grads, init_adam(w), cfg, _sc(cfg, 1))
    assert all(x.requires_grad for x in tensor_leaves(w))


def test_adam_update_inplace_rejects_shared_m_v():
    w, obs = _setup()
    m = init_adam(w).m
    shared = AdamState(m=m, v=m)
    cfg = AdamParams()
    with pytest.raises(AssertionError, match="share storage"):
        adam_update_(w, torch.func.grad(_loss)(w, obs), shared, cfg, _sc(cfg, 1))


def test_lr_schedule():
    """adam_scalars calls the schedule with the 1-based step; it overrides cfg.lr."""
    calls: list[int] = []

    def schedule(step: int) -> float:
        calls.append(step)
        return 1e-3 * step

    cfg = AdamParams(lr=123.0, lr_schedule=schedule)
    scalars = [_sc(cfg, step) for step in (1, 2, 3)]
    assert calls == [1, 2, 3]
    assert [s.lr.item() for s in scalars] == pytest.approx([1e-3, 2e-3, 3e-3])
    assert scalars[2].bc1.item() == pytest.approx(1 - 0.9**3)
    assert scalars[2].bc2.item() == pytest.approx(1 - 0.999**3)


# ---------------------------------------------------------------------------
# Compiled
# ---------------------------------------------------------------------------

def _require_compile_backend() -> None:
    """Skip only when there is no working compile backend (e.g. no C++ compiler).

    Probed on a trivial function, so a real lowering error in the tests below fails them.
    """
    if not hasattr(torch, "compile"):
        pytest.skip("torch.compile unavailable")
    try:
        torch.compile(lambda x: x + 1, fullgraph=True)(torch.ones(2))
    except Exception as e:
        pytest.skip(f"no working torch.compile backend: {type(e).__name__}: {e}")


def _compiled_train_run(steps: int, cfg: AdamParams, dynamic: bool | None):
    """Eager vs compiled grad+adam_update_ for `steps` steps. Returns (eager, compiled, counter, ptrs ok)."""
    def train_step(params, state, scalars, obs):
        grads, loss = torch.func.grad_and_value(_loss)(params, obs)
        return adam_update_(params, grads, state, cfg, scalars), loss

    torch._dynamo.reset()
    counter = CompileCounterWithBackend("inductor")
    compiled = torch.compile(train_step, backend=counter, fullgraph=True, dynamic=dynamic)

    w, obs = _setup()
    eager_params, eager_state = _detached(w), init_adam(w)
    comp_params, comp_state = _detached(w), init_adam(w)
    ptrs0 = [x.data_ptr() for x in tensor_leaves((comp_params, comp_state))]
    for step in range(1, steps + 1):
        scalars = _sc(cfg, step)
        comp_state, _ = compiled(comp_params, comp_state, scalars, obs)
        eager_state, _ = train_step(eager_params, eager_state, scalars, obs)
    same_ptrs = ptrs0 == [x.data_ptr() for x in tensor_leaves((comp_params, comp_state))]
    return eager_params, comp_params, counter, same_ptrs


@pytest.mark.parametrize("dynamic", [None, False])
def test_compiled_matches_eager_without_recompiles(dynamic):
    """25 steps with a changing lr_schedule: <= 2 graphs (dynamic=None), 1 graph with dynamic=False."""
    _require_compile_backend()
    cfg = AdamParams(lr_schedule=lambda step: 1e-2 / step)
    eager_params, comp_params, counter, same_ptrs = _compiled_train_run(25, cfg, dynamic)

    assert counter.frame_count <= (1 if dynamic is False else 2), f"recompiled: {counter.frame_count} graphs"
    assert same_ptrs, "compiled adam_update_ reallocated params/m/v"
    diff = _max_diff(comp_params, eager_params)
    assert diff < 1e-5, f"compiled diverged from eager: {diff}"


def _param_sized_allocs(fn) -> tuple[list[str], str]:
    torch._dynamo.reset()
    cfg = AdamParams(lr=1e-2)
    # Distinct, recognizable shapes so any param/m/v-sized allocation shows up by shape.
    params = [torch.randn(1000, 37), torch.randn(4099)]
    grads = [torch.randn_like(p) for p in params]
    _, codes = run_and_get_code(torch.compile(fn, fullgraph=True), params, grads, init_adam(params), cfg, _sc(cfg, 1))
    code = "\n".join(codes)
    allocs = [a.strip().rstrip(",") for a in re.findall(r"empty_strided_\w+\(\(([^)]*)\)", code)]
    return [a for a in allocs if a in {"1000, 37", "4099"}], code


def test_compiled_adam_update_inplace_allocates_no_param_sized_buffers():
    """Inductor code for adam_update_: math + copy_ fused into kernels that write the input buffers."""
    _require_compile_backend()
    allocs, code = _param_sized_allocs(adam_update_)
    assert allocs == [], f"param-sized allocations in compiled adam_update_: {allocs}"
    assert re.search(r"fused_\w*copy_", code), "expected a fused kernel containing the copy_ writeback"

    # Negative control: the pure update must allocate new p, m, v per param (3 x 2 tensors),
    # proving the check above can see allocations.
    pure_allocs, _ = _param_sized_allocs(adam_update)
    assert len(pure_allocs) == 6, pure_allocs
