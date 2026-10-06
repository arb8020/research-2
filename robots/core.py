"""robots core: the only shared code. Everything else lives in robots/examples/.

Two sections:
  pytree  -- weight dataclasses as torch pytrees (register_pytree, tree_map, ...)
  adam    -- Adam as data + pure functions over those trees
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

import torch
import torch.utils._pytree as pytree

# ===========================================================================
# pytree
# ===========================================================================
# Pytree utilities for frozen dataclass weight trees.
#
# Weights are frozen dataclasses of tensors (PolicyWeights, WMWeights, GPT2).
# Grads and optimizer moments use the same dataclass type as the weights.
#
# One traversal, owned by torch: each weight class is registered as a torch pytree
# node (`register_pytree`), and everything here (tree_map, tensor_leaves, ...) goes
# through torch.utils._pytree. The same registration is what lets torch.func.grad /
# grad_and_value take and return these dataclasses, and what torch.compile traces.
#
# Field split, decided per instance at flatten time:
#   children: fields holding a Tensor or a container (registered dataclass, tuple, list, dict)
#   static:   everything else (ints like WMWeights.obs_dim, floats, strings, None)
# Static fields live in the treespec context, so torch.func never sees them
# (it rejects non-Tensor leaves) and tree_map carries them through unchanged.
#
# Why torch.utils._pytree.register_pytree_node and not a public API:
#   torch.export.register_dataclass (public) makes every field a child, so
#   WMWeights.obs_dim becomes a leaf and torch.func.grad raises
#   "Thing passed to transform API must be Tensor, got <class 'int'>".
#   _pytree.register_dataclass has drop_field_names, but dropped fields are not
#   restored on unflatten (the constructor would miss them). There is no
#   torch.utils.pytree public module in torch 2.14. register_pytree_node is the
#   documented escape hatch that torch.export/functorch themselves use.

_CONTAINERS = (torch.Tensor, tuple, list, dict)


def _is_child(value: Any) -> bool:
    if isinstance(value, _CONTAINERS):
        return True
    return dataclasses.is_dataclass(value) and not isinstance(value, type)


def register_pytree(cls: type) -> type:
    """Register a dataclass as a torch pytree node. Idempotent; usable as a decorator.

    After this, torch.func.grad(f)(w) returns the same dataclass type as w, and
    tree_map / torch.compile can walk it.
    """
    assert dataclasses.is_dataclass(cls), f"{cls} is not a dataclass"
    if cls in pytree.SUPPORTED_NODES:
        return cls
    names = tuple(f.name for f in dataclasses.fields(cls) if f.init)

    def flatten(obj: Any) -> tuple[list[Any], Any]:
        child_names = tuple(n for n in names if _is_child(getattr(obj, n)))
        static = tuple((n, getattr(obj, n)) for n in names if n not in child_names)
        return [getattr(obj, n) for n in child_names], (child_names, static)

    def unflatten(children: Any, context: Any) -> Any:
        child_names, static = context
        return cls(**dict(zip(child_names, children, strict=True)), **dict(static))

    def flatten_with_keys(obj: Any) -> tuple[list[tuple[Any, Any]], Any]:
        children, context = flatten(obj)
        keyed = [(pytree.GetAttrKey(n), c) for n, c in zip(context[0], children, strict=True)]
        return keyed, context

    pytree.register_pytree_node(
        cls,
        flatten,
        unflatten,
        serialized_type_name=f"{cls.__module__}.{cls.__qualname__}",
        flatten_with_keys_fn=flatten_with_keys,
    )
    return cls


def _flatten(tree: Any) -> tuple[list[torch.Tensor], Any]:
    """Flatten and check every leaf is a Tensor; errors name the offending path."""
    path_leaves, spec = pytree.tree_flatten_with_path(tree)
    for path, leaf in path_leaves:
        if isinstance(leaf, torch.Tensor):
            continue
        where = pytree.keystr(path) or "<root>"
        if dataclasses.is_dataclass(leaf) and not isinstance(leaf, type):
            raise TypeError(
                f"{where}: {type(leaf).__qualname__} is a dataclass but not a registered pytree; "
                f"decorate it with @robots.core.register_pytree"
            )
        raise TypeError(
            f"{where}: non-tensor leaf {type(leaf).__name__} ({leaf!r}). Weight trees hold only "
            f"tensors in containers; scalars belong in dataclass fields (static), not in lists/tuples/dicts"
        )
    return [leaf for _, leaf in path_leaves], spec


def _flatten_like(tree: Any, spec: Any, ref: Any) -> list[torch.Tensor]:
    """Flatten `tree` and require the same structure as `ref` (whose spec is `spec`)."""
    leaves, other_spec = _flatten(tree)
    if other_spec != spec:
        ref_paths = {pytree.keystr(p) for p, _ in pytree.tree_flatten_with_path(ref)[0]}
        other_paths = {pytree.keystr(p) for p, _ in pytree.tree_flatten_with_path(tree)[0]}
        raise ValueError(
            "tree structure mismatch "
            f"(e.g. a field is None/scalar in one tree and a tensor in the other, or static fields differ). "
            f"only in first: {sorted(ref_paths - other_paths)}; only in other: {sorted(other_paths - ref_paths)}"
        )
    return leaves


def tree_map(fn: Callable[..., Any], tree: Any, *rest: Any) -> Any:
    """Apply fn leafwise across trees of identical structure. Returns a tree like `tree`.

    Every leaf must be a Tensor. Static (non-tensor) dataclass fields come from
    `tree` and must be equal in `rest`.
    """
    leaves, spec = _flatten(tree)
    rest_leaves = [_flatten_like(r, spec, tree) for r in rest]
    mapped = [fn(*xs) for xs in zip(leaves, *rest_leaves, strict=True)]
    return pytree.tree_unflatten(mapped, spec)


def tree_copy_(dst: Any, src: Any) -> None:
    """dst_leaf.copy_(src_leaf) for every tensor leaf. The only mutation helper here.

    Under torch.compile this becomes an input mutation that Inductor writes in place
    (no full-size temporaries). Caller decides grad mode (leaves that require grad
    need torch.no_grad()).
    """
    dst_leaves, spec = _flatten(dst)
    src_leaves = _flatten_like(src, spec, dst)
    for d, s in zip(dst_leaves, src_leaves, strict=True):
        d.copy_(s)


def tensor_leaves(tree: Any) -> list[torch.Tensor]:
    """Every Tensor in the tree, in stable pytree order (field order, depth-first)."""
    return _flatten(tree)[0]


def trainable(tree: Any) -> Any:
    """Clone every tensor with requires_grad=True. Returns a new tree; the original is untouched."""
    return tree_map(lambda x: x.clone().detach().requires_grad_(True), tree)


# ===========================================================================
# adam
# ===========================================================================
# Adam as data + pure functions (optax-style). No torch.optim dependency.
#
# Two granularities, each usable alone:
#   adam_update(params, grads, state, cfg, scalars) -> (new_params, new_state)   pure, never mutates
#   adam_update_(params, grads, state, cfg, scalars) -> state                    adam_update + tree_copy_
#
# The loop owns the step counter (a Python int). Per step, on the host:
#   scalars = adam_scalars(cfg, step, device)   # lr (schedule), bias corrections as 0-d tensors
# so a compiled step sees only tensors and never recompiles as step/lr change.
#
# adam_update_ is exactly `adam_update` followed by `tree_copy_` into params, m, v.
# Eager it is just the pure math plus a copy (debuggable, ~2x memory for the step).
# Inside torch.compile(fullgraph=True) the copy_ is an input mutation, and Inductor
# fuses math + writeback into kernels that read and write the input buffers in place
# (no full-size temporaries). A pure compiled update cannot do that: Inductor must
# allocate fresh outputs because it cannot know the caller drops the old tensors.
# torch has no JAX-style donate_argnums; copy_ inside the compiled region is the
# equivalent.

W = TypeVar("W")  # a weight tree: frozen dataclass of tensors (registered pytree)


@dataclass(frozen=True)
class AdamParams:
    """Optimizer config. Data, not state.

    lr_schedule overrides lr when set: called with the 1-based step number, returns lr.
    """

    lr: float = 3e-4
    beta1: float = 0.9
    beta2: float = 0.999
    eps: float = 1e-8
    lr_schedule: Callable[[int], float] | None = None


@register_pytree
@dataclass(frozen=True)
class AdamState(Generic[W]):
    """First/second moments, same tree type as the weights. Tensors only; no step.

    The step counter is a plain Python int owned by the training loop, turned into
    tensors by adam_scalars. Keeping it out of the state keeps the compiled region
    free of Python scalars that change every call (which would force recompiles).
    """

    m: W  # first moment (mean of gradients)
    v: W  # second moment (mean of squared gradients)


@register_pytree
@dataclass(frozen=True)
class AdamScalars:
    """This step's per-step numbers as 0-d float32 tensors (compiled graphs take them as inputs)."""

    lr: torch.Tensor  # learning rate for this step
    bc1: torch.Tensor  # 1 - beta1^step
    bc2: torch.Tensor  # 1 - beta2^step


def adam_scalars(cfg: AdamParams, step: int, device: torch.device | str) -> AdamScalars:
    """Host side: per-step lr and bias corrections for a 1-based step, on `device`.

    `device` should be the params' device so the compiled step never does an
    implicit host->device copy. lr_schedule(step) runs here as plain Python.
    """
    assert step >= 1, f"step is 1-based, got {step}"
    lr = cfg.lr_schedule(step) if cfg.lr_schedule is not None else cfg.lr
    assert lr >= 0.0, f"negative lr {lr} at step {step}"

    def scalar(x: float) -> torch.Tensor:
        return torch.tensor(x, dtype=torch.float32, device=device)

    return AdamScalars(lr=scalar(lr), bc1=scalar(1.0 - cfg.beta1**step), bc2=scalar(1.0 - cfg.beta2**step))


def init_adam(params: W) -> AdamState[W]:
    """Zero moments shaped like params."""
    return AdamState(m=tree_map(torch.zeros_like, params), v=tree_map(torch.zeros_like, params))


def adam_update(
    params: W, grads: W, state: AdamState[W], cfg: AdamParams, scalars: AdamScalars
) -> tuple[W, AdamState[W]]:
    """One Adam step as a pure function. Never mutates params, grads or state.

    Matches torch.optim.Adam (no weight decay, no amsgrad) to float tolerance:
      m     = beta1 * m + (1 - beta1) * g
      v     = beta2 * v + (1 - beta2) * g^2
      param = param - lr * (m / bc1) / (sqrt(v / bc2) + eps)
    betas and eps come from cfg (compile-time constants); lr/bc1/bc2 from scalars
    (graph inputs). Build scalars with adam_scalars(cfg, step, device).

    Autograd-transparent: if params require grad, outputs carry a graph. Looping
    the pure path on requires_grad weights therefore grows one autograd graph
    across steps; detach, use torch.no_grad(), or keep weights requires_grad=False
    (torch.func.grad does not need it).

    Per-group settings (e.g. a different lr for embeddings): call adam_update on
    each subtree with its own cfg/scalars.
    """
    b1, b2, eps = cfg.beta1, cfg.beta2, cfg.eps
    lr, bc1, bc2 = scalars.lr, scalars.bc1, scalars.bc2
    m = tree_map(lambda m_, g: b1 * m_ + (1.0 - b1) * g, state.m, grads)
    v = tree_map(lambda v_, g: b2 * v_ + (1.0 - b2) * g * g, state.v, grads)
    new_params = tree_map(
        lambda p, m_, v_: p - lr * (m_ / bc1) / ((v_ / bc2).sqrt() + eps),
        params, m, v,
    )
    return new_params, AdamState(m=m, v=v)


def _assert_no_shared_storage(*trees: Any) -> None:
    storages = [x.untyped_storage().data_ptr() for x in tensor_leaves(trees)]
    assert len(set(storages)) == len(storages), "params/m/v share storage; in-place update would corrupt them"


def adam_update_(
    params: W, grads: W, state: AdamState[W], cfg: AdamParams, scalars: AdamScalars
) -> AdamState[W]:
    """Donating Adam step: adam_update, then copy_ results into params, state.m, state.v.

    Returns `state` itself (its m/v tensors now hold the updated values).
    Runs under torch.no_grad(): an in-place optimizer write is never differentiable,
    and params created with requires_grad=True would otherwise reject copy_.
    torch.compile(fullgraph=True)-friendly; compiled, it becomes in-place kernels.
    """
    if not torch.compiler.is_compiling():  # storage introspection is eager-only
        _assert_no_shared_storage(params, state.m, state.v)
    with torch.no_grad():
        new_params, new_state = adam_update(params, grads, state, cfg, scalars)
        tree_copy_(params, new_params)
        tree_copy_(state.m, new_state.m)
        tree_copy_(state.v, new_state.v)
    return state
