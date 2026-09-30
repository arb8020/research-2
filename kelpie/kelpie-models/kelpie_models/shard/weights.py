"""Slice a loaded pytree per rank from its layout specs.

    specs = {"embed": "V/tp M", "layers.q": "Hd/tp M", ...}   # dotted field paths
    local = shard_weights(w, specs, mesh)

A tuple field (`layers`) applies its spec to every element; fields without a spec are
replicated. `shard_tensor` is the same rule for one tensor and is what load() uses to slice a
raw checkpoint tensor before it ever reaches the device.
"""

from __future__ import annotations

import dataclasses
from typing import Any

import torch

from kelpie_models.shard.spec import Sizes, parse, shard_range


def shard_tensor(x: torch.Tensor, spec: str, mesh: Sizes) -> torch.Tensor:
    s = parse(spec)
    assert not s.unreduced, f"a weight is never a partial sum: {spec}"
    assert x.ndim == len(s.dims), f"{spec}: rank {len(s.dims)} != {tuple(x.shape)}"
    for i, d in enumerate(s.dims):
        if d.roles:
            lo, hi = shard_range(x.shape[i], d.roles, mesh)
            if hi - lo != x.shape[i]:
                x = x.narrow(i, lo, hi - lo)
    return x  # the very same tensor when nothing was sliced (world 1)


def shard_weights(tree: Any, specs: dict[str, str], mesh: Sizes, prefix: str = "") -> Any:
    if isinstance(tree, tuple):
        return tuple(shard_weights(t, specs, mesh, prefix) for t in tree)
    if not dataclasses.is_dataclass(tree):
        return tree
    changes = {}
    for f in dataclasses.fields(tree):
        path = f"{prefix}{f.name}"
        v = getattr(tree, f.name)
        if isinstance(v, torch.Tensor):
            if path in specs:
                changes[f.name] = shard_tensor(v, specs[path], mesh)
        else:
            changes[f.name] = shard_weights(v, specs, mesh, f"{path}.")
    unknown = [k for k in specs if k.startswith(prefix) and "." not in k[len(prefix) :]]
    have = {f.name for f in dataclasses.fields(tree)}
    for k in unknown:
        assert k[len(prefix) :] in have, f"spec for unknown field {k}"
    return dataclasses.replace(tree, **changes)
