"""A backend's one-time weight conversion, cached per SOURCE tensor.

Some MoE backends cannot read the hub's packed tables in place (FlashInfer's sm90 interleave,
triton_kernels' Hopper swizzle). Until there is a load-time per-impl layout hook, the adapter
converts on first call and keeps the result here, keyed by the source tensor's identity and
dropped when the source is (weakref callback) -- so a reloaded model never hits a stale entry.
The key is the source's identity AND its version counter, so an in-place write (`copy_`, an
RL weight sync) re-converts. Only the gate_up blocks are keyed: an adapter converts one layer's
tables together, and they are loaded and replaced together. The cost: the converted copy is
resident NEXT TO the hub tables the model still holds, until the weights die.
"""

from __future__ import annotations

import weakref
from collections.abc import Callable
from typing import Generic, TypeVar

import torch

T = TypeVar("T")


class Prepared(Generic[T]):
    def __init__(self) -> None:
        self._by_id: dict[int, tuple[weakref.ref, int, T]] = {}

    def get(self, source: torch.Tensor, make: Callable[[], T]) -> T:
        key = id(source)
        hit = self._by_id.get(key)
        if hit is not None and hit[0]() is source and hit[1] == source._version:
            return hit[2]
        value = make()
        self._by_id[key] = (weakref.ref(source, lambda _: self._by_id.pop(key, None)),
                            source._version, value)
        return value
