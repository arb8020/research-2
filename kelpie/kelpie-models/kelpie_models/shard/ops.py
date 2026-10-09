"""Collectives as layout transitions. Each derives its collective from before -> after and
asserts the transition is the one it implements; over an unbound (size-1) role it is a no-op,
so the same forward runs at world = 1 without touching torch.distributed.

    x = all_gather("R V/tp -> R V", x, mesh)
    x = all_reduce("T M {tp} -> T M", x, mesh)
    x = reduce_scatter("T M {tp} -> T M/tp", x, mesh)
    x = all_to_all("T E/ep -> T/ep E", x, mesh)

Forward only: these call raw torch.distributed, which has no autograd, so nothing correct
flows backward through them. Training, when it comes, follows seqax (train.py:311): every
weight stored fully sharded, all_gather'd right before each use, and an assert that every
updated weight is fully sharded. Then the only backward rules needed are
all_gather <-> reduce_scatter (an autograd.Function or torch.library op per pair), gradients
come back already reduced, and the layout strings need no replicate-vs-invariant marker
(spmd_types R/I). Cost: ~1.5x DDP's comm per step, plus a tiny gather per small weight
(layernorm). Keeping small weights replicated is exactly the case that needs R/I.
"""

from __future__ import annotations

import torch
import torch.distributed as dist

from kelpie_models.shard.mesh import Mesh
from kelpie_models.shard.spec import DimSpec, transition


def all_gather(spec: str, x: torch.Tensor, mesh: Mesh) -> torch.Tensor:
    before, after = transition(spec)
    assert x.ndim == len(before.dims), f"{spec}: rank {len(before.dims)} != shape {tuple(x.shape)}"
    assert before.unreduced == after.unreduced, f"{spec}: gather does not reduce"
    for i, (b, a) in enumerate(zip(before.dims, after.dims, strict=True)):
        assert b.roles[: len(a.roles)] == a.roles, f"{spec}: cannot gather {b} into {a}"
        for role in reversed(b.roles[len(a.roles) :]):  # innermost first
            x = gather_dim(x, i, role, mesh)
    return x


def reduce_scatter(spec: str, x: torch.Tensor, mesh: Mesh) -> torch.Tensor:
    before, after = transition(spec)
    assert x.ndim == len(before.dims), f"{spec}: rank {len(before.dims)} != shape {tuple(x.shape)}"
    moved: set[str] = set()
    for i, (b, a) in enumerate(zip(before.dims, after.dims, strict=True)):
        assert a.roles[: len(b.roles)] == b.roles, f"{spec}: cannot scatter {b} into {a}"
        for role in a.roles[len(b.roles) :]:
            assert role in before.unreduced, f"{spec}: {role} is not an unreduced role"
            x = scatter_dim(x, i, role, mesh)
            moved.add(role)
    assert before.unreduced - moved == after.unreduced, f"{spec}: unreduced set mismatch"
    return x


def all_reduce(spec: str, x: torch.Tensor, mesh: Mesh) -> torch.Tensor:
    before, after = transition(spec)
    assert x.ndim == len(before.dims), f"{spec}: rank {len(before.dims)} != shape {tuple(x.shape)}"
    assert before.dims == after.dims, f"{spec}: all_reduce keeps every dim's sharding"
    roles = tuple(sorted(before.unreduced - after.unreduced))
    assert before.unreduced >= after.unreduced and roles, f"{spec}: nothing to reduce"
    group = mesh.group(roles)
    if group is None:
        return x
    out = x.contiguous().clone()
    dist.all_reduce(out, group=group)
    return out


def all_to_all(spec: str, x: torch.Tensor, mesh: Mesh) -> torch.Tensor:
    """Expert dispatch: every rank sends its tokens for expert block e to rank e."""
    before, after = transition(spec)
    assert x.ndim == len(before.dims), f"{spec}: rank {len(before.dims)} != shape {tuple(x.shape)}"
    assert before.unreduced == after.unreduced, f"{spec}: all_to_all does not reduce"
    lost = [(i, r) for i, (b, a) in enumerate(zip(before.dims, after.dims, strict=True))
            for r in b.roles if r not in a.roles]  # fmt: skip
    gained = [(i, r) for i, (b, a) in enumerate(zip(before.dims, after.dims, strict=True))
              for r in a.roles if r not in b.roles]  # fmt: skip
    assert len(lost) == 1 and len(gained) == 1 and lost[0][1] == gained[0][1], (
        f"{spec}: all_to_all moves exactly one role between two dims"
    )
    (src, role), (dst, _) = lost[0], gained[0]
    assert before.dims[src].roles[-1] == role and after.dims[dst].roles[-1] == role, (
        f"{spec}: the moved role must be innermost on both dims"
    )
    group = mesh.group((role,))
    if group is None:
        return x
    n = mesh.size(role)
    assert x.shape[dst] % n == 0, (spec, x.shape)
    # [.. src ..] -> chunks of dst go to rank k; received chunks concatenate along src
    xs = x.movedim(dst, 0).contiguous()
    out = torch.empty_like(xs)
    dist.all_to_all_single(out, xs, group=group)
    out = out.view(n, xs.shape[0] // n, *xs.shape[1:])  # [n, dst/n, ...] with src at 1 + src'
    src_moved = src + 1 if src < dst else src  # position of src after movedim(dst, 0)
    out = torch.cat(list(out.unbind(0)), dim=src_moved)  # [dst/n, ..., src*n, ...]
    return out.movedim(0, dst)


def gather_dim(x: torch.Tensor, dim: int, role: str, mesh: Mesh) -> torch.Tensor:
    group = mesh.group((role,))
    if group is None:
        return x
    n = mesh.size(role)
    xs = x.movedim(dim, 0).contiguous()
    out = torch.empty((n * xs.shape[0], *xs.shape[1:]), dtype=xs.dtype, device=xs.device)
    dist.all_gather_into_tensor(out, xs, group=group)
    return out.movedim(0, dim)


def scatter_dim(x: torch.Tensor, dim: int, role: str, mesh: Mesh) -> torch.Tensor:
    group = mesh.group((role,))
    if group is None:
        return x
    n = mesh.size(role)
    assert x.shape[dim] % n == 0, (x.shape, dim, n)
    xs = x.movedim(dim, 0).contiguous()
    out = torch.empty((xs.shape[0] // n, *xs.shape[1:]), dtype=xs.dtype, device=xs.device)
    dist.reduce_scatter_tensor(out, xs, group=group)
    return out.movedim(0, dim)


def describe(d: DimSpec) -> str:
    return str(d)
