"""Activation taps: at a named site the forward's `put` clones the tensor if (site, layer) is in
the program key. The tap set is part of `StepShape`; a tap must be replicated under tp.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from kelpie_models.shard.spec import parse

TapKey = tuple[str, int]  # (site, layer)
SITES = ("resid_post",)  # post-MLP residual, after the tp all_reduce
MAX_TAPS = 64


def check_tap_keys(taps: tuple[TapKey, ...]) -> None:
    assert isinstance(taps, tuple), f"taps: expected a tuple, got {taps!r}"
    assert len(taps) <= MAX_TAPS, (len(taps), MAX_TAPS)
    for key in taps:
        assert isinstance(key, tuple), f"tap {key!r}: expected (site, layer)"
        assert len(key) == 2, f"tap {key!r}: expected (site, layer)"  # noqa: PLR2004
        site, layer = key
        assert site in SITES, f"tap site {site!r}: known sites are {SITES}"
        assert isinstance(layer, int), f"tap {key!r}: layer must be an int"
        assert layer >= 0, f"tap {key!r}: layer must be >= 0"
    assert list(taps) == sorted(set(taps)), f"taps must be sorted and unique: {taps!r}"


def assert_replicated(layout: str) -> None:
    assert isinstance(layout, str), f"layout: expected a shardlib spec string, got {layout!r}"
    spec = parse(layout)
    assert len(spec.dims) == 2, f"a tap is [T, D]: {layout!r} has {len(spec.dims)} dims"  # noqa: PLR2004
    assert not spec.roles, f"tap layout {layout!r} is sharded over {sorted(spec.roles)}"
    assert not spec.unreduced, (
        f"tap layout {layout!r} is a partial sum over {sorted(spec.unreduced)}"
    )


@dataclass
class Taps:
    """`wanted` is batch.key.taps; `got` is filled by the forward's `put` calls."""

    wanted: frozenset[TapKey]
    got: dict[TapKey, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        check_tap_keys(tuple(sorted(self.wanted)))
        assert not self.got, "Taps starts empty; the forward fills it"

    def put(self, site: str, layer: int, x: Any, layout: str) -> None:
        """Clones `x` when wanted; the layout check runs whether or not anyone listens."""
        assert site in SITES, f"tap site {site!r}: known sites are {SITES}"
        assert layer >= 0, layer
        assert_replicated(layout)
        assert x.dim() == 2, f"a tap is [T, D]: got {tuple(x.shape)}"  # noqa: PLR2004
        key = (site, layer)
        if key in self.wanted:
            assert key not in self.got, f"tap {key} put twice in one forward"
            self.got[key] = x.clone()

    def check_complete(self, padded_num_tokens: int) -> None:
        missing = self.wanted - set(self.got)
        assert not missing, f"taps never put by the forward: {sorted(missing)}"
        extra = set(self.got) - self.wanted
        assert not extra, f"taps put but not wanted: {sorted(extra)}"
        for key, t in self.got.items():
            assert t.shape[0] == padded_num_tokens, (key, tuple(t.shape), padded_num_tokens)


def taps_for(taps: tuple[TapKey, ...]) -> Taps:
    check_tap_keys(taps)
    return Taps(wanted=frozenset(taps))
