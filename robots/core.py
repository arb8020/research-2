from __future__ import annotations

import dataclasses
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

import torch
import torch.utils._pytree as pytree

_CONTAINERS = (torch.Tensor, tuple, list, dict)


def _is_child(value: Any) -> bool:
    if isinstance(value, _CONTAINERS):
        return True
    return dataclasses.is_dataclass(value) and not isinstance(value, type)


# Why torch.utils._pytree.register_pytree_node and not a public API:
#   torch.export.register_dataclass (public) makes every field a child, so
#   WMWeights.obs_dim becomes a leaf and torch.func.grad raises
#   "Thing passed to transform API must be Tensor, got <class 'int'>".
#   _pytree.register_dataclass has drop_field_names, but dropped fields are not
#   restored on unflatten (the constructor would miss them). There is no
#   torch.utils.pytree public module in torch 2.14.
def register_pytree(cls: type) -> type:
    """Register a dataclass as a torch pytree node. Idempotent; usable as a decorator."""
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
    """Every leaf must be a Tensor. Static fields come from `tree` and must be equal in `rest`."""
    leaves, spec = _flatten(tree)
    rest_leaves = [_flatten_like(r, spec, tree) for r in rest]
    mapped = [fn(*xs) for xs in zip(leaves, *rest_leaves, strict=True)]
    return pytree.tree_unflatten(mapped, spec)


def tree_copy_(dst: Any, src: Any) -> None:
    """Caller decides grad mode: leaves that require grad need torch.no_grad()."""
    dst_leaves, spec = _flatten(dst)
    src_leaves = _flatten_like(src, spec, dst)
    for d, s in zip(dst_leaves, src_leaves, strict=True):
        d.copy_(s)


def tensor_leaves(tree: Any) -> list[torch.Tensor]:
    return _flatten(tree)[0]


def trainable(tree: Any) -> Any:
    return tree_map(lambda x: x.clone().detach().requires_grad_(True), tree)


W = TypeVar("W")


@dataclass(frozen=True)
class AdamParams:
    lr: float = 3e-4
    beta1: float = 0.9
    beta2: float = 0.999
    eps: float = 1e-8
    lr_schedule: Callable[[int], float] | None = None


@register_pytree
@dataclass(frozen=True)
class AdamState(Generic[W]):
    m: W
    v: W


@register_pytree
@dataclass(frozen=True)
class AdamScalars:
    lr: torch.Tensor
    bc1: torch.Tensor
    bc2: torch.Tensor


def adam_scalars(cfg: AdamParams, step: int, device: torch.device | str) -> AdamScalars:
    assert step >= 1, f"step is 1-based, got {step}"
    lr = cfg.lr_schedule(step) if cfg.lr_schedule is not None else cfg.lr
    assert lr >= 0.0, f"negative lr {lr} at step {step}"

    def scalar(x: float) -> torch.Tensor:
        return torch.tensor(x, dtype=torch.float32, device=device)

    return AdamScalars(lr=scalar(lr), bc1=scalar(1.0 - cfg.beta1**step), bc2=scalar(1.0 - cfg.beta2**step))


def init_adam(params: W) -> AdamState[W]:
    return AdamState(m=tree_map(torch.zeros_like, params), v=tree_map(torch.zeros_like, params))


def adam_update(
    params: W, grads: W, state: AdamState[W], cfg: AdamParams, scalars: AdamScalars
) -> tuple[W, AdamState[W]]:
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
    """Copies results into params, state.m, state.v in place; returns `state` itself.

    A pure compiled update cannot reuse buffers: Inductor must allocate fresh outputs
    because it cannot know the caller drops the old tensors. Inside
    torch.compile(fullgraph=True) the copy_ here is an input mutation, and Inductor
    fuses math + writeback into kernels that read and write the input buffers in place.
    torch has no JAX-style donate_argnums; copy_ inside the compiled region stands in for it.
    """
    if not torch.compiler.is_compiling():  # storage introspection is eager-only
        _assert_no_shared_storage(params, state.m, state.v)
    with torch.no_grad():
        new_params, new_state = adam_update(params, grads, state, cfg, scalars)
        tree_copy_(params, new_params)
        tree_copy_(state.m, new_state.m)
        tree_copy_(state.v, new_state.v)
    return state
