"""Pytree utilities for frozen dataclass weight trees.

Weights are frozen dataclasses of tensors (PolicyWeights, WMWeights, GPT2).
Grads and optimizer moments use the same dataclass type as the weights.

One traversal, owned by torch: each weight class is registered as a torch pytree
node (`register_pytree`), and everything here (tree_map, tensor_leaves, ...) goes
through torch.utils._pytree. The same registration is what lets torch.func.grad /
grad_and_value take and return these dataclasses, and what torch.compile traces.

Field split, decided per instance at flatten time:
  children: fields holding a Tensor or a container (registered dataclass, tuple, list, dict)
  static:   everything else (ints like WMWeights.obs_dim, floats, strings, None)
Static fields live in the treespec context, so torch.func never sees them
(it rejects non-Tensor leaves) and tree_map carries them through unchanged.

Why torch.utils._pytree.register_pytree_node and not a public API:
  torch.export.register_dataclass (public) makes every field a child, so
  WMWeights.obs_dim becomes a leaf and torch.func.grad raises
  "Thing passed to transform API must be Tensor, got <class 'int'>".
  _pytree.register_dataclass has drop_field_names, but dropped fields are not
  restored on unflatten (the constructor would miss them). There is no
  torch.utils.pytree public module in torch 2.14. register_pytree_node is the
  documented escape hatch that torch.export/functorch themselves use.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from typing import Any

import torch
import torch.utils._pytree as pytree

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


def _check_no_unregistered(leaves: list[Any]) -> None:
    # An unregistered dataclass would silently become a single opaque leaf.
    for leaf in leaves:
        if dataclasses.is_dataclass(leaf) and not isinstance(leaf, type):
            raise TypeError(
                f"{type(leaf).__qualname__} is a dataclass but not a registered pytree; "
                f"decorate it with @robots.tree.register_pytree"
            )


def tree_map(fn: Callable[..., Any], tree: Any, *rest: Any) -> Any:
    """Apply fn leafwise across trees of identical structure. Returns a tree like `tree`.

    Static (non-tensor) fields come from `tree` and must match in `rest`.
    """
    leaves, spec = pytree.tree_flatten(tree)
    _check_no_unregistered(leaves)
    rest_leaves = [spec.flatten_up_to(r) for r in rest]
    mapped = [fn(*xs) for xs in zip(leaves, *rest_leaves, strict=True)]
    return pytree.tree_unflatten(mapped, spec)


def tree_copy_(dst: Any, src: Any) -> None:
    """dst_leaf.copy_(src_leaf) for every tensor leaf. The only mutation helper here.

    Under torch.compile this becomes an input mutation that Inductor writes in place
    (no full-size temporaries). Caller decides grad mode (leaves that require grad
    need torch.no_grad()).
    """
    dst_leaves, spec = pytree.tree_flatten(dst)
    _check_no_unregistered(dst_leaves)
    src_leaves = spec.flatten_up_to(src)
    for d, s in zip(dst_leaves, src_leaves, strict=True):
        d.copy_(s)


def tensor_leaves(tree: Any) -> list[torch.Tensor]:
    """Every Tensor in the tree, in stable pytree order (field order, depth-first)."""
    leaves = pytree.tree_leaves(tree)
    _check_no_unregistered(leaves)
    return [x for x in leaves if isinstance(x, torch.Tensor)]


def trainable(tree: Any) -> Any:
    """Clone every tensor with requires_grad=True. Returns a new tree; the original is untouched."""
    def clone(x: Any) -> Any:
        if isinstance(x, torch.Tensor):
            return x.clone().detach().requires_grad_(True)
        return x  # scalars inside lists/tuples pass through

    return tree_map(clone, tree)
