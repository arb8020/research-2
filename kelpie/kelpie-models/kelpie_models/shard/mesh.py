"""Roles bound to physical mesh axes, three rungs each expressible in the one below:
    preset(tp=2, ep=2)
    MeshConfig(axes=(("x", 2), ("y", 2)), roles={"tp": "x", "ep": "y"})
    mesh.group(("tp", "ep")), mesh.index("tp")

Ranks lay out row-major over `axes` (last axis varies fastest, so gets the tightest links). An
unbound role has size 1 and index 0 everywhere, so a forward runs unchanged at world = 1 with
every collective a no-op; `Mesh.single()` never touches torch.distributed.
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, field
from typing import Any

import torch
import torch.distributed as dist

ROLES = ("tp", "ep", "dpa", "pp")  # the conventional names; any bound name is a role


@dataclass(frozen=True)
class MeshConfig:
    axes: tuple[tuple[str, int], ...] = ()  # row-major; product == world
    roles: dict[str, str] = field(default_factory=dict)  # role -> physical axis

    def __post_init__(self) -> None:
        names = [a for a, _ in self.axes]
        assert len(set(names)) == len(names), f"duplicate axis in {self.axes}"
        for role, axis in self.roles.items():
            assert axis in names, f"role {role} bound to unknown axis {axis!r}"
        bound = list(self.roles.values())
        assert len(set(bound)) == len(bound), "two roles bound to one axis"
        clash = (set(ROLES) | set(self.roles)) & set(names)
        assert not clash, f"axis name collides with a role name: {clash}"

    @property
    def world(self) -> int:
        return math.prod(n for _, n in self.axes)


def preset(**sizes: int) -> MeshConfig:
    """One physical axis per role, in the order given (last = innermost). Size-1 roles dropped."""
    axes = tuple((f"axis_{r}", n) for r, n in sizes.items() if n > 1)
    roles = {r: f"axis_{r}" for r, n in sizes.items() if n > 1}
    return MeshConfig(axes, roles)


class Mesh:
    def __init__(
        self, cfg: MeshConfig, rank: int, device: torch.device, groups: dict[tuple[str, ...], Any]
    ) -> None:
        self.cfg, self.rank, self.device = cfg, rank, device
        self.world = cfg.world
        self._groups = groups  # key: sorted physical axes; value: ProcessGroup or None
        self._coords = coords(cfg, rank)

    @classmethod
    def single(cls, device: torch.device | str = "cpu") -> Mesh:
        return cls(MeshConfig(), 0, torch.device(device), {})

    @classmethod
    def init(cls, cfg: MeshConfig, rank: int, device: torch.device) -> Mesh:
        """All ranks must call this in the same order: builds one process group per non-empty
        subset of physical axes."""
        assert dist.is_initialized(), "init torch.distributed first"
        assert dist.get_world_size() == cfg.world, (dist.get_world_size(), cfg.world)
        groups: dict[tuple[str, ...], Any] = {}
        names = sorted(a for a, _ in cfg.axes)  # keys are sorted axis tuples (see group())
        for k in range(1, len(names) + 1):
            for subset in itertools.combinations(names, k):
                groups[subset] = coset_group(cfg, rank, subset)
        return cls(cfg, rank, device, groups)

    def _axis(self, name: str) -> str | None:
        """role-if-bound -> physical-axis-if-it-exists -> unbound role (no axis) -> error."""
        if name in self.cfg.roles:
            return self.cfg.roles[name]
        names = [a for a, _ in self.cfg.axes]
        if name in names:
            return name
        assert name in ROLES, (
            f"{name!r} is neither bound in this mesh, one of its axes ({names}), nor a conventional "
            f"role ({ROLES}); bind it in MeshConfig.roles to use it"
        )
        return None  # a recognised role this config left unbound: size 1, index 0

    def size(self, role: str) -> int:
        axis = self._axis(role)
        return 1 if axis is None else dict(self.cfg.axes)[axis]

    def index(self, role: str) -> int:
        axis = self._axis(role)
        return 0 if axis is None else self._coords[axis]

    def group(self, roles: tuple[str, ...]) -> Any:
        """Process group spanning the product of the (bound) roles/axes; None when that is 1."""
        axes = tuple(sorted({a for r in roles if (a := self._axis(r)) is not None}))
        if not axes:
            return None
        return self._groups[axes]

    def __repr__(self) -> str:
        return f"Mesh(rank={self.rank}/{self.world}, axes={self.cfg.axes}, roles={self.cfg.roles})"


def coords(cfg: MeshConfig, rank: int) -> dict[str, int]:
    """Row-major rank -> coordinate per physical axis."""
    out = {}
    for name, n in reversed(cfg.axes):
        out[name] = rank % n
        rank //= n
    return out


def coset_group(cfg: MeshConfig, rank: int, subset: tuple[str, ...]) -> Any:
    """new_group for every coset of `subset` (all ranks must call it for every coset, in the
    same order); returns the one this rank belongs to."""
    mine = None
    fixed = [a for a, _ in cfg.axes if a not in subset]
    my_coords = coords(cfg, rank)
    by_coset: dict[tuple[int, ...], list[int]] = {}
    for r in range(cfg.world):
        c = coords(cfg, r)
        by_coset.setdefault(tuple(c[a] for a in fixed), []).append(r)
    for key, ranks in sorted(by_coset.items()):
        g = dist.new_group(ranks)
        if key == tuple(my_coords[a] for a in fixed):
            mine = g
    assert mine is not None
    return mine
