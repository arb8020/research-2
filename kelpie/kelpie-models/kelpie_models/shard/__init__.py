"""Sharding notation (seqax shardlib, reimplemented over torch.distributed).

A tensor's layout is a string: `"B/dpa L M/tp {tp}"` -- one token per dim, `/role` for each
mesh role the dim is split over, and an optional `{roles}` set naming axes over which the value
is a partial sum not yet reduced. Collectives are layout transitions `"before -> after"`; each
derives the one collective that realises the transition and asserts it is legal.
"""

from kelpie_models.shard.mesh import Mesh, MeshConfig, preset
from kelpie_models.shard.ops import all_gather, all_reduce, all_to_all, reduce_scatter
from kelpie_models.shard.spec import ShapeSpec, check, parse, shard_range
from kelpie_models.shard.weights import shard_tensor, shard_weights

__all__ = [
    "Mesh",
    "MeshConfig",
    "ShapeSpec",
    "all_gather",
    "all_reduce",
    "all_to_all",
    "check",
    "parse",
    "preset",
    "reduce_scatter",
    "shard_range",
    "shard_tensor",
    "shard_weights",
]
