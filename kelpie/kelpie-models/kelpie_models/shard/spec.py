"""Layout specs: `"B/dpa L M/tp {tp}"` parsed into dims (name + roles) and an unreduced set.

    spec = parse("T M/tp {tp}")        # dims (T, ()), (M, ("tp",)); unreduced {"tp"}
    names = check(x, spec, mesh)       # local shape * axis sizes == the named global sizes
    lo, hi = shard_range(n, ("ep", "tp"), mesh)   # this rank's slice of a dim sharded E/ep/tp

Names unify across one `check` call chain when the same `names` dict is threaded through: the
first use of a name fixes its size, later uses must agree.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Protocol


class Sizes(Protocol):
    def size(self, role: str) -> int: ...
    def index(self, role: str) -> int: ...


@dataclass(frozen=True)
class DimSpec:
    name: str
    roles: tuple[str, ...]  # sharded over these roles, outermost first; () = replicated

    def __str__(self) -> str:
        return "/".join((self.name, *self.roles))


@dataclass(frozen=True)
class ShapeSpec:
    dims: tuple[DimSpec, ...]
    unreduced: frozenset[str] = frozenset()  # value is a partial sum over these roles

    def __str__(self) -> str:
        s = " ".join(str(d) for d in self.dims)
        if self.unreduced:
            s += " {" + ",".join(sorted(self.unreduced)) + "}"
        return s

    @property
    def roles(self) -> frozenset[str]:
        return frozenset(r for d in self.dims for r in d.roles)


def parse(spec: str | ShapeSpec) -> ShapeSpec:
    """`"B/dpa L M/tp {tp}"`; `{tp,ep}` or `{tp ep}` for several unreduced roles."""
    if isinstance(spec, ShapeSpec):
        return spec
    text = spec.strip()
    unreduced: frozenset[str] = frozenset()
    if "{" in text:
        head, _, tail = text.partition("{")
        inner, close, rest = tail.partition("}")
        assert close and not rest.strip(), f"malformed unreduced set in {spec!r}"
        unreduced = frozenset(inner.replace(",", " ").split())
        text = head
    dims = []
    for tok in text.split():
        name, *roles = tok.split("/")
        assert name and all(roles), f"malformed dim {tok!r} in {spec!r}"
        assert len(set(roles)) == len(roles), f"role repeated in dim {tok!r}"
        dims.append(DimSpec(name, tuple(roles)))
    sharded = [r for d in dims for r in d.roles]
    assert len(set(sharded)) == len(sharded), f"a role shards two dims in {spec!r}"
    return ShapeSpec(tuple(dims), unreduced)


def transition(before: str) -> tuple[ShapeSpec, ShapeSpec]:
    """`"A/tp -> A"` -> (parse(A/tp), parse(A)); dim names must agree position by position."""
    src, arrow, dst = before.partition("->")
    assert arrow, f"transition needs '->': {before!r}"
    b, a = parse(src), parse(dst)
    assert len(b.dims) == len(a.dims), f"rank changes across {before!r}"
    for x, y in zip(b.dims, a.dims, strict=True):
        assert x.name == y.name, f"dim {x.name} renamed to {y.name} in {before!r}"
    return b, a


def check(
    x: object, spec: str | ShapeSpec, mesh: Sizes, names: dict[str, int] | None = None
) -> dict[str, int]:
    """A name that is an integer literal ("64") pins the global size."""
    s = parse(spec)
    shape = tuple(getattr(x, "shape"))  # noqa: B009  -- torch.Size or tuple
    assert len(shape) == len(s.dims), f"{spec}: rank {len(s.dims)} != shape {shape}"
    names = {} if names is None else names
    for local, d in zip(shape, s.dims, strict=True):
        n = local * math.prod(mesh.size(r) for r in d.roles)
        if d.name.isdigit():
            assert int(d.name) == n, f"{spec}: dim {d} is {n}, literal says {d.name}"
        elif d.name in names:
            assert names[d.name] == n, f"{spec}: {d.name} is {n}, earlier {names[d.name]}"
        else:
            names[d.name] = n
    return names


def shard_range(n: int, roles: tuple[str, ...], mesh: Sizes) -> tuple[int, int]:
    """[lo, hi) of a global dim of size n held by this rank when sharded over `roles`
    (outermost first; the last role varies fastest). Requires n divisible by the product."""
    parts = math.prod(mesh.size(r) for r in roles)
    assert n % parts == 0, f"dim {n} not divisible by {roles} = {parts}"
    idx = 0
    for r in roles:
        idx = idx * mesh.size(r) + mesh.index(r)
    chunk = n // parts
    return idx * chunk, (idx + 1) * chunk
