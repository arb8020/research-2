"""The step shapes a built engine can meet: ONE enumeration, read by everything that pre-pays for
a shape -- `build`'s warm pass (which also discovers the ops), `Captured` (which graphs the
decode family), the kernel cache's manifest rows, and, once it exists, correctness grading.

A step's program is picked by its FAMILY and its SIZE (sglang-jax's mode x bucket):

    decode        R requests x 1 row           size R (the request bucket)
    decode_extra  decode entries, some carrying size T (the token bucket); only when the engine
                  extra rows                    has max_extra > 0. Keyed by TOKENS, like prefill,
                                                so a DEGRADED plan (some entries got no extra rows)
                                                lands on a warmed bucket too
    prefill       T tokens                      size T (the token bucket); a MIXED batch (any
                                                prefill entry) folds into this family

`synthetic_plan` makes one of each through the core (`Engine.synthetic_plan`), so a synthetic
plan is padded by `padPlan` and keyed by `stepShape` -- the same two functions a real plan goes
through -- and its real rows are inert by the same values a pad row carries (the null block's
scratch slot, ZERO / SCRATCH state units). Nothing here writes a pad value.

The rule that makes a synthetic plan a faithful stand-in: a model's forward may branch only on
`cfg` and on the step's family / bucket, never on batch contents (sdk/step.py). Under that rule
a forward over a synthetic plan runs exactly the ops, and the shapes, a real plan of the same
family and bucket runs.

TODO(2026-09-25): `kelpie check` (correctness grading of a built program against the reference,
kelpie/docs/correctness/reference.md) is not built; it should grade over `enumerate_steps` too,
so what is graded is what was warmed and captured.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from kelpie_engine import _ffi
from kelpie_engine.sdk.engine import Engine, EngineConfig
from kelpie_engine.sdk.plan import Plan

from kelpie_models.kernels.op import BuildError

Family = Literal["decode", "decode_extra", "prefill"]
FAMILIES: tuple[Family, ...] = ("decode", "decode_extra", "prefill")

# KelpiePlan.shape's packing (c_api.zig stepShape): token bucket index | request bucket index
# << 8 | has_prefill << 12 | min(max n_extra, 15) << 16. Read back, never written, here.
SHAPE_TOKENS_MASK, SHAPE_REQS_SHIFT, SHAPE_REQS_MASK = 0xFF, 8, 0xF
SHAPE_PREFILL_BIT, SHAPE_EXTRA_SHIFT = 1 << 12, 16


@dataclass(frozen=True)
class StepKey:
    """One (family, size): what a step's program is chosen by."""

    family: Family
    size: int

    def __str__(self) -> str:
        axis = "R" if self.family == "decode" else "T"
        return f"{self.family} {axis}={self.size}"


def enumerate_steps(config: EngineConfig) -> list[StepKey]:
    """Every (family, size) this engine's limits let a plan reach, each family largest first
    (so the CUDA caching allocator's pool is sized by the biggest program before the smaller
    ones, and never has to grow mid-capture).

    Only `config` is read: every model fact that sets a shape (max_seq_len, max_extra, the
    batch limits) already lives in the engine config `EngineConfig.from_model` derived."""
    width = 1 + config.max_extra
    tokens = config.max_batch_tokens
    if config.max_extra > 0 and tokens & (tokens - 1):
        # TODO(2026-09-25): a synthetic plan with PER-ENTRY n_extra (Kmax on some entries, 0 on
        # the rest) would reach every decode_extra bucket; with one n_extra for all entries a
        # non-power-of-two budget leaves buckets only a mixed plan reaches (and a drafter that
        # always asks Kmax would meet them unwarmed). Refuse rather than serve them cold.
        raise BuildError(
            f"max_batch_tokens={tokens} with max_extra={config.max_extra}: a drafting engine "
            f"needs a power-of-two max_batch_tokens (every decode_extra bucket warmed)")
    reach: dict[Family, int] = {
        # One row per request: bounded by BOTH batch limits.
        "decode": min(config.max_batch_reqs, config.max_batch_tokens),
        # Tokens: at least one entry with >= 1 extra row (2 tokens), at most every request with
        # all Kmax of them. Every bucket between is reachable: a caller asks any n_extra in
        # [0, Kmax] per entry and the core grants all or none, so entries mix.
        "decode_extra": min(config.max_batch_tokens, config.max_batch_reqs * width)
        if config.max_extra > 0 else 0,
        # A plan's tokens are bounded by the token budget AND by how many requests of at most
        # max_seq_len rows fit in it.
        "prefill": min(config.max_batch_tokens, config.max_batch_reqs * config.max_seq_len),
    }
    steps = [
        StepKey(family, size)
        for family in FAMILIES
        if reach[family] > 0
        for size in _ladder_to(reach[family])
        if family != "decode_extra" or size >= _DECODE_EXTRA_MIN_TOKENS
    ]
    assert steps, f"no step shape fits this engine: {config}"
    assert all(s.size > 0 for s in steps), steps
    return steps


def _ladder_to(limit: int) -> list[int]:
    """The core's buckets a plan of at most `limit` can pad to, largest first: every bucket up
    to (and including) the bucket `limit` itself rounds up to."""
    top = _ffi.bucket(limit)
    return sorted((b for b in _ffi.buckets() if b <= top), reverse=True)


def synthetic_plan(engine: Engine, key: StepKey) -> Plan:
    """A plan of `key`'s family whose padded shape is `key`'s bucket, made by the core. Valid
    until the engine's next plan; the engine must be idle (the core refuses otherwise)."""
    config = engine.live_config()
    if key.family == "decode":
        n_reqs = min(key.size, config.max_batch_reqs, config.max_batch_tokens)
        plan = engine.synthetic_plan("decode", n_reqs=n_reqs, rows=1)
    elif key.family == "decode_extra":
        assert config.max_extra > 0, "decode_extra on an engine without extra rows"
        n_reqs, n_extra = _decode_extra_split(key.size, config)
        plan = engine.synthetic_plan("decode", n_reqs=n_reqs, rows=1, n_extra=n_extra)
    else:
        limit = min(config.max_batch_tokens, config.max_batch_reqs * config.max_seq_len)
        n_reqs, rows = _prefill_split(key.size, limit, config)
        plan = engine.synthetic_plan("prefill", n_reqs=n_reqs, rows=rows)
    got = key_of(plan)
    assert got == key, f"synthetic plan for {key} came back as {got} (shape {plan.shape:#x})"
    return plan


_DECODE_EXTRA_MIN_TOKENS = 2  # one entry: its history row and one extra row


def _decode_extra_split(bucket: int, config: EngineConfig) -> tuple[int, int]:
    """A decode_extra plan that pads to token `bucket`, as (n_reqs, n_extra each): the most
    extra rows per entry (Kmax when it fits: what a drafter always asks for) and then the most
    requests, whose total still rounds up to `bucket`. Any mix of n_extra with the same token
    bucket runs the same program (the family's rule), so one split stands for all of them."""
    floor = bucket // 2
    top = min(bucket, config.max_batch_tokens)
    for n_extra in range(min(config.max_extra, top - 1), 0, -1):
        n_reqs = min(top // (1 + n_extra), config.max_batch_reqs)
        if n_reqs * (1 + n_extra) > floor:
            return n_reqs, n_extra
    raise BuildError(
        f"no decode_extra plan pads to T={bucket}: max_batch_tokens {config.max_batch_tokens}, "
        f"max_batch_reqs {config.max_batch_reqs}, max_extra {config.max_extra}")


def _prefill_split(bucket: int, limit: int, config: EngineConfig) -> tuple[int, int]:
    """A prefill that pads to token `bucket`, as (n_reqs, rows each): the fewest requests of at
    most max_seq_len rows whose total fits `limit` and still rounds up to `bucket`. A real
    prefill of those tokens may be one request or many; the program (family and token bucket)
    is the same, so any split works. The core's synthetic plan takes one row count for all."""
    floor = bucket // 2  # a total must exceed the previous bucket to round up to this one
    top = min(bucket, limit)
    for n_reqs in range(-(-top // config.max_seq_len), config.max_batch_reqs + 1):
        rows = min(top // n_reqs, config.max_seq_len)
        if rows * n_reqs > floor:
            return n_reqs, rows
    raise BuildError(
        f"no prefill of equal requests pads to T={bucket}: max_batch_tokens "
        f"{config.max_batch_tokens}, max_batch_reqs {config.max_batch_reqs}, max_seq_len "
        f"{config.max_seq_len}")


def key_of(plan: Plan) -> StepKey:
    """The (family, size) of any plan, real or synthetic, read off the core's `shape` key."""
    shape = plan.shape
    ladder = _ffi.buckets()
    if shape & SHAPE_PREFILL_BIT:
        return StepKey("prefill", ladder[shape & SHAPE_TOKENS_MASK])
    if shape >> SHAPE_EXTRA_SHIFT:
        return StepKey("decode_extra", ladder[shape & SHAPE_TOKENS_MASK])
    return StepKey("decode", ladder[(shape >> SHAPE_REQS_SHIFT) & SHAPE_REQS_MASK])
