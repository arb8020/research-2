"""Config tiers as argument structure: WHERE a knob is spelled says what changing it costs.

The core already grades every knob (`kelpie-core/src/scheduler.zig`: `Tier = enum { live,
recapture, realloc, program }`, one comptime tag per `Knob`). Python spells the same four tiers
as four PLACES rather than four flags:

    program    every other keyword of `build()` -- and exactly `ProgramKey`'s field list
    realloc    `build(capacity=Capacity(...))`   drain the engine and re-allocate the arena
    recapture  `build(buckets=Buckets(...))`     recompile the bucket ladder's programs
    live       `engine.set(order=..., ...)`      takes effect at one step boundary

So there is no tier ARGUMENT anywhere: you cannot pass a program-tier value to a live-tier call,
because they are different calls. `engine.set` given a non-live name raises naming the tier and
what changes it -- which today is the whole check, since all five Zig `Knob` fields are `live`
and `validateKnob` cannot be handed a higher tier.
"""

from __future__ import annotations

from dataclasses import dataclass


def live_names() -> tuple[str, ...]:
    """The live tier's names, which ARE the core's `Knob` union as the FFI reads it. Looked up
    lazily so `Capacity` and `Buckets` -- plain frozen dataclasses -- stay importable without
    the engine's shared library, which a check script's parent process does not have."""
    from kelpie_engine._ffi import KNOB_KINDS

    return tuple(KNOB_KINDS)


def higher_tiers() -> dict[str, tuple[str, str]]:
    """Name -> (its tier, the call that changes it). One writer, next to the `engine.set` that
    raises from it (`kelpie_engine.sdk.engine.HIGHER_TIER`)."""
    from kelpie_engine.sdk.engine import HIGHER_TIER

    return HIGHER_TIER



@dataclass(frozen=True)
class Capacity:
    """REALLOC tier: the arena's geometry. Changing one means draining the engine and
    re-allocating, so it is a `build()` argument and never a knob."""

    max_requests: int = 8
    max_seq_len: int = 0  # 0 = the model's own maximum
    num_slabs: int = 64


@dataclass(frozen=True)
class Buckets:
    """RECAPTURE tier: the bucket ladder every program is compiled for. Changing one means
    recompiling those programs, so it is a `build()` argument.

    Empty means the core's own ladder, read over the ABI (`kelpie_engine._ffi.buckets`) --
    the ladder has one writer, `kelpie-core/src/buckets.zig`, and this is not a second."""

    tokens: tuple[int, ...] = ()
    requests: tuple[int, ...] = ()


def check_live(name: str) -> None:
    """`engine.set`'s guard: a non-live name raises naming its tier and the call that changes
    it, instead of queueing a knob the core would reject as `Invalid` with no explanation."""
    live = live_names()
    if name in live:
        return
    tier, where = higher_tiers().get(name, ("program", "build(...)"))
    raise ValueError(
        f"{name} is {tier} tier, not live: engine.set only takes {', '.join(live)}. "
        f"Change it with {where}."
    )
