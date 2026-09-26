"""Generic pytree utilities for frozen dataclass weight trees.

Walk any nested frozen dataclass and operate on every tensor leaf.
Works with PolicyWeights, WMWeights, GPT2, or any future weight type.
"""

from __future__ import annotations

import dataclasses
from typing import Any

import torch


def tensor_leaves(tree: Any) -> list[torch.Tensor]:
    """Collect every Tensor in a (possibly nested) frozen dataclass tree.

    Walks fields depth-first. Tuples/lists of dataclasses are expanded.
    Returns a flat list — the order is stable for a given tree structure.
    """
    leaves: list[torch.Tensor] = []
    _walk(tree, leaves)
    return leaves


def _walk(node: Any, acc: list[torch.Tensor]) -> None:
    if isinstance(node, torch.Tensor):
        acc.append(node)
    elif dataclasses.is_dataclass(node) and not isinstance(node, type):
        for f in dataclasses.fields(node):
            _walk(getattr(node, f.name), acc)
    elif isinstance(node, (tuple, list)):
        for item in node:
            _walk(item, acc)


def trainable(tree: Any) -> Any:
    """Clone every tensor in the tree with requires_grad=True.

    Returns a new tree of the same type. The original is untouched.
    Frozen dataclasses are reconstructed via __init__ (not mutation).
    """
    return _clone(tree)


def _clone(node: Any) -> Any:
    if isinstance(node, torch.Tensor):
        return node.clone().detach().requires_grad_(True)
    if dataclasses.is_dataclass(node) and not isinstance(node, type):
        kwargs = {}
        for f in dataclasses.fields(node):
            kwargs[f.name] = _clone(getattr(node, f.name))
        return type(node)(**kwargs)
    if isinstance(node, tuple):
        return tuple(_clone(item) for item in node)
    if isinstance(node, list):
        return [_clone(item) for item in node]
    # Scalars, strings, etc. pass through unchanged.
    return node
