"""`Plan`: a typed view over one `KelpiePlan` (kelpie-core/include/kelpie.h).

The core pads; nothing here pads. Every array is bucket-sized and `n_tokens` / `n_reqs` say how
much of it is real. The plan splits into the three views its readers actually use:

    plan.tokens      what the embedding and the attention rows need   (per padded token)
    plan.requests    what the scheduler-shaped kernels need           (per padded entry)
    plan.sampling    what the sampler needs                           (per padded entry)

An entry is `n_work` history rows (tokens the core owns) then `n_extra` extra rows, whose
input_ids are NO_TOKEN: the caller fills them (a drafter's drafts). Its tail rows are row
`n_work - 1 + j`, j in [0, n_extra]; committing n tokens says tail rows 0..n-1 were valid.
A per_seq group's state travels as `requests.state[g]` (read / write / ckpt indices); see
docs/design-core-option2.md.

The views are numpy arrays aliasing engine-owned memory: valid until the next
`kelpie_plan` / `kelpie_commit` / `kelpie_destroy`. Copy before you keep.
"""

from __future__ import annotations

import ctypes
from dataclasses import dataclass

import numpy as np

from kelpie_engine import _ffi

# Ids for the `kelpie_sizeof` / `kelpie_offsetof` tripwire below. KELPIE_STRUCT_PLAN and
# KELPIE_FIELD_PLAN_SHAPE of kelpie-core/include/kelpie.h; kelpie-core/src/abi_ids.zig is their
# one writer, and its "expected_field_order" test fails if the real struct drifts from them.
STRUCT_PLAN = 3
FIELD_LAST = 31  # KELPIE_FIELD_PLAN_TOP_KS: the last field, so its offset pins every earlier one


@dataclass(frozen=True)
class Tokens:
    """[T] per padded row. Pad rows: `input_ids` 0, `positions` 0, `slot_mapping[g]` the scratch
    slot of the null block, `row_request` -1."""

    input_ids: np.ndarray  # u32[T]
    positions: np.ndarray  # u32[T]
    slot_mapping: tuple[np.ndarray, ...]  # per group u32[T]
    row_request: np.ndarray  # i32[T]; -1 = pad


@dataclass(frozen=True)
class State:
    """One per_seq group's unit indices, per padded entry (docs/design-core-option2.md 2.2).
    The op contract per request r: s = pool[read[r]]; for each row i: update s; if i is tail
    row j: pool[write[r, j]] = s; if i == ckpt_row[r]: pool[ckpt[r]] = s. Columns of `write`
    past n_extra[r] are SCRATCH (0), as is `ckpt` when there is none (ckpt_row NO_ROW). Pad
    entries read `zero` and write SCRATCH."""

    read: np.ndarray  # u32[R]
    write: np.ndarray  # u32[R, 1 + max_extra]
    ckpt: np.ndarray  # u32[R]
    ckpt_row: np.ndarray  # u32[R]; counted from the entry's first row
    zero: int  # ZERO(g): the always-zero unit a fresh request reads


@dataclass(frozen=True)
class Requests:
    """[R] per padded entry, plus the [R + 1] query offsets. Pad entries: `query_start_loc`
    repeats n_tokens (an empty query), `seq_lens` 1, `block_tables[g]` all null block, `kinds`
    KIND_PREFILL, `n_extra` 0, `req_ids` 0, `seq_start` 0, `emits` 0."""

    req_ids: np.ndarray  # u32[R]
    query_start_loc: np.ndarray  # u32[R + 1]
    seq_lens: np.ndarray  # u32[R]; context including this step (extra rows included)
    block_tables: tuple[np.ndarray, ...]  # per group u32[R, max_blocks]
    kinds: np.ndarray  # u32[R]; KIND_PREFILL / KIND_DECODE
    n_extra: np.ndarray  # u32[R]; extra rows after the history rows
    seq_start: np.ndarray  # u32[R]; tokens already in context
    emits: np.ndarray  # u8[R]; 1 iff commit keeps this entry's tokens
    state: tuple[State | None, ...]  # per group; None for a per_token group

    def rows(self, r: int) -> tuple[int, int]:
        """Half-open row range of entry `r` inside the token arrays."""
        return int(self.query_start_loc[r]), int(self.query_start_loc[r + 1])


@dataclass(frozen=True)
class Sampling:
    """[R] per padded entry. A pad entry is temperature 1, top_k 1 (greedy, like a T=0 request).
    `logit_mask` is the core's grammar mask: bit v of word v // 32 set
    = token v allowed. A pad entry's row is all ones; the whole array is empty when the engine
    was created with vocab_words == 0."""

    temperatures: np.ndarray  # f32[R]; never 0: the core stores a greedy request as 1 (top_ks)
    top_ks: np.ndarray  # u32[R]; 1 = greedy (the T=0 rule), 0 = whole vocab
    logit_mask: np.ndarray  # i32[R, W]; W = 0 when grammar is off
    seed: tuple[int, int]


FNV_OFFSET, FNV_PRIME, U32 = 0x811C9DC5, 0x01000193, (1 << 32) - 1


def sample_seed(req_ids: np.ndarray, seq_lens: np.ndarray) -> tuple[int, int]:
    """The step's PRNG key: a pure function of (slots, context lengths), so an eager step and a
    replayed captured step draw the same bits with no step counter anywhere."""
    who, where = FNV_OFFSET, FNV_OFFSET
    for r, n in zip(req_ids.tolist(), seq_lens.tolist(), strict=True):
        who = ((who ^ int(r)) * FNV_PRIME) & U32
        where = ((where ^ int(n)) * FNV_PRIME) & U32
    return who, where


@dataclass(frozen=True)
class Plan:
    """One planned step. `n_reqs` / `n_tokens` are the real counts; every view is padded."""

    step: int
    shape: int
    n_reqs: int
    n_tokens: int
    n_reqs_padded: int
    n_tokens_padded: int
    max_extra: int  # Kmax: logits are [R, 1 + max_extra, V] whatever this plan's n_extra
    tokens: Tokens
    requests: Requests
    sampling: Sampling
    mm_hashes: np.ndarray  # u64[R]; 0 = text only. Read only by the multimodal override.
    digest: int = 0  # the core's plan digest (KelpiePlan.digest); equal across ranks

    @property
    def emitting(self) -> np.ndarray:
        """Indices (plan order) of the real entries whose tokens commit keeps -- mid-prefill
        chunks excluded."""
        return np.flatnonzero(self.requests.emits[: self.n_reqs])

    @property
    def seq_lens_real(self) -> np.ndarray:
        return self.requests.seq_lens[: self.n_reqs]

    @property
    def req_ids_real(self) -> np.ndarray:
        return self.requests.req_ids[: self.n_reqs]

    @property
    def max_seq_len(self) -> int:
        return int(self.seq_lens_real.max())


def of(p: _ffi.KelpiePlan, vocab_words: int) -> Plan:
    """The typed view of a filled-in `KelpiePlan`. Aliases engine memory; copies nothing."""
    n_reqs, n_tokens = int(p.n_reqs), int(p.n_tokens)
    r, t, n_groups = int(p.n_reqs_padded), int(p.n_tokens_padded), int(p.n_groups)
    assert 0 < n_reqs <= r and 0 < n_tokens <= t, (n_reqs, r, n_tokens, t)
    max_blocks = [int(p.max_blocks_per_req[g]) for g in range(n_groups)]
    req_ids = _u32(p.req_ids, r)
    seq_lens = _u32(p.seq_lens, r)
    width = 1 + int(p.max_extra)
    state = tuple(
        None
        if not p.state_read[g]
        else State(
            read=_u32(p.state_read[g], r),
            write=_u32(p.state_write[g], r * width).reshape(r, width),
            ckpt=_u32(p.state_ckpt[g], r),
            ckpt_row=_u32(p.state_ckpt_row[g], r),
            zero=int(p.zero_unit[g]),
        )
        for g in range(n_groups)
    )
    tokens = Tokens(
        input_ids=_u32(p.input_ids, t),
        positions=_u32(p.positions, t),
        slot_mapping=tuple(_u32(p.slot_mapping[g], t) for g in range(n_groups)),
        row_request=_i32(p.row_request, t),
    )
    requests = Requests(
        req_ids=req_ids,
        query_start_loc=_u32(p.query_start_loc, r + 1),
        seq_lens=seq_lens,
        block_tables=tuple(
            _u32(p.block_tables[g], r * max_blocks[g]).reshape(r, max_blocks[g])
            for g in range(n_groups)
        ),
        kinds=_u32(p.kinds, r),
        n_extra=_u32(p.n_extra, r),
        seq_start=_u32(p.seq_start, r),
        emits=_u8(p.emits, r),
        state=state,
    )
    sampling = Sampling(
        temperatures=_f32(p.temperatures, r),
        top_ks=_u32(p.top_ks, r),
        logit_mask=_mask(p.logit_mask, r, vocab_words),
        seed=sample_seed(req_ids[:n_reqs], seq_lens[:n_reqs]),
    )
    return Plan(
        step=int(p.step),
        shape=int(p.shape),
        n_reqs=n_reqs,
        n_tokens=n_tokens,
        n_reqs_padded=r,
        n_tokens_padded=t,
        max_extra=int(p.max_extra),
        tokens=tokens,
        requests=requests,
        sampling=sampling,
        mm_hashes=_u64(p.mm_hashes, r),
        digest=int(p.digest),
    )


def _array(ptr: object, n: int, dtype: type) -> np.ndarray:
    """A numpy view of `n` elements at `ptr`, sharing the engine's memory."""
    assert n >= 0, n
    if n == 0:
        return np.empty(0, dtype=dtype)
    return np.ctypeslib.as_array(ptr, shape=(n,))


def _u32(ptr: object, n: int) -> np.ndarray:
    return _array(ptr, n, np.uint32)


def _i32(ptr: object, n: int) -> np.ndarray:
    return _array(ptr, n, np.int32)


def _f32(ptr: object, n: int) -> np.ndarray:
    return _array(ptr, n, np.float32)


def _u8(ptr: object, n: int) -> np.ndarray:
    return _array(ptr, n, np.uint8)


def _u64(ptr: object, n: int) -> np.ndarray:
    return _array(ptr, n, np.uint64)


def _mask(ptr: object, r: int, vocab_words: int) -> np.ndarray:
    """[R, W] i32; empty when the engine has no grammar support."""
    if vocab_words == 0:
        return np.empty((r, 0), dtype=np.int32)
    assert ptr, "vocab_words > 0 but the core left logit_mask NULL"
    return _i32(ptr, r * vocab_words).reshape(r, vocab_words)


def check_abi(lib: ctypes.CDLL) -> None:
    """The tripwire: this file's ctypes `KelpiePlan` must be the Zig struct, byte for byte.

    Run at Engine creation, so a libkelpie whose layout moved fails loudly there instead of
    every plan being read as garbage. `top_ks` is the struct's LAST field, so asserting
    its offset and the total size pins the size and alignment of every field before it.

    `kelpie_sizeof` returns 0 for an unrecognized struct id, and 0 is also a legal offset, so
    the size is range-checked first (kelpie.h says so explicitly)."""
    lib.kelpie_sizeof.argtypes, lib.kelpie_sizeof.restype = [_ffi.u32], ctypes.c_size_t
    lib.kelpie_offsetof.argtypes = [_ffi.u32, _ffi.u32]
    lib.kelpie_offsetof.restype = ctypes.c_size_t
    got_size = int(lib.kelpie_sizeof(STRUCT_PLAN))
    assert got_size > 0, f"libkelpie does not know struct id {STRUCT_PLAN} (KELPIE_STRUCT_PLAN)"
    want_size = ctypes.sizeof(_ffi.KelpiePlan)
    assert got_size == want_size, f"KelpiePlan is {got_size} bytes in Zig, {want_size} here"
    got_last = int(lib.kelpie_offsetof(STRUCT_PLAN, FIELD_LAST))
    want_last = _ffi.KelpiePlan.top_ks.offset
    assert got_last == want_last, (
        f"KelpiePlan.top_ks at {got_last} in Zig, {want_last} here")
