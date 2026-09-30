"""ctypes declarations mirroring kelpie-core/include/kelpie.h. Nothing else touches ctypes."""

from __future__ import annotations

import ctypes
import os
import sys
from pathlib import Path

u32 = ctypes.c_uint32
u64 = ctypes.c_uint64
u32_p = ctypes.POINTER(ctypes.c_uint32)
u32_pp = ctypes.POINTER(u32_p)
u8 = ctypes.c_uint8
u8_p = ctypes.POINTER(ctypes.c_uint8)
u64 = ctypes.c_uint64
u64_p = ctypes.POINTER(ctypes.c_uint64)

GROUP_PER_TOKEN, GROUP_PER_SEQ = 0, 1
ORDER_RUNNING_FIRST, ORDER_WAITING_FIRST = 0, 1
STATE_NAMES = ("waiting", "running", "finished_eos", "finished_length", "cancelled", "grammar_dead_end")
SUBMIT_FULL, SUBMIT_TOO_LONG, SUBMIT_BAD_ARGS, SUBMIT_DRAINING = -1, -2, -3, -4
SUBMIT_EXCEEDS_KV_POOL = -5
SUBMIT_NOT_EDGE = -6  # submit / cancel / set on a follower rank (kelpie_register_sync edge=0)
SUBMIT_BAD_TOP_K = -7  # kelpie_submit_top_k: top_k > KelpieConfig.vocab_size
MAX_STOP_TOKENS = 8  # request.max_stop_tokens (kelpie-core/src/request.zig): kelpie_submit_mm_stop's cap


# TODO(2026-09-10): generate these ctypes structs from kelpie.h at build; today the header, c_api.zig,
# abi_ids.zig, this file and EngineConfig are five writers of one layout. check_abi pins width, not
# names (handoff-2026-09-10 debt 1).
class KelpieConfig(ctypes.Structure):
    _fields_ = [
        ("max_requests", u32),
        ("max_seq_len", u32),
        ("n_groups", u32),
        ("group_kinds", u32_p),
        ("group_block_sizes", u32_p),
        ("group_windows", u32_p),
        ("group_cacheable", u8_p),
        ("num_blocks", u32),
        ("max_batch_tokens", u32),
        ("max_batch_reqs", u32),
        ("reserve_ratio", ctypes.c_float),
        ("order", u32),
        ("eos_token", u32),
        ("prefix_cache", u32),
        ("config_hash", u64),
        ("group_strides", u32_p),  # appended (additive ABI): tokens per unit; NULL = all 1
        ("overlap", u32),  # startup-only tier-2 plan/commit protocol choice
        # appended (additive ABI): row width of KelpiePlan.logit_mask (ceil(vocab/32)); 0 =
        # grammar support disabled (kelpie_attach_grammar always fails). Native-loop grammar
        # support (see kelpie-core/src/xgrammar.zig); unused by the Python stepper today.
        ("vocab_words", u32),
        # appended (additive ABI): [n_groups] bytes per page, padded so a slab holds
        # floor(slab_bytes / page) of them; NULL = legacy equal-page mode (one page per slab).
        ("group_bytes_per_page", u32_p),
        ("slab_bytes", u32),  # out only (kelpie_get_config)
        ("num_slabs", u32),  # out only (kelpie_get_config)
        # Kmax: the most extra rows a decode entry may carry (was n_draft, same offset); 0 = none.
        ("max_extra", u32),
        ("vocab_size", u32),  # kelpie_commit rejects kept ids >= this (0 = unchecked)
    ]


KNOB_KINDS = ("order", "reserve_ratio", "max_batch_tokens", "max_batch_reqs", "prefix_cache")
SET_OK, SET_BAD_VALUE, SET_QUEUE_FULL = 0, -1, -2


class KelpieKnob(ctypes.Structure):
    _fields_ = [("kind", u32), ("u32_value", u32), ("f32_value", ctypes.c_float)]


class KelpieSetResult(ctypes.Structure):
    _fields_ = [("apply_step", u64), ("config_hash", u64)]


class KelpiePlan(ctypes.Structure):
    _fields_ = [
        ("n_reqs", u32),
        ("n_tokens", u32),
        ("n_groups", u32),
        ("req_ids", u32_p),
        ("n_work", u32_p),
        ("input_ids", u32_p),
        ("positions", u32_p),
        ("query_start_loc", u32_p),
        ("seq_lens", u32_p),
        ("slot_mapping", u32_pp),
        ("block_tables", u32_pp),
        ("max_blocks_per_req", u32_p),
        ("temperatures", ctypes.POINTER(ctypes.c_float)),
        ("mm_hashes", u64_p),
        ("kinds", u32_p),  # appended (additive ABI): KIND_PREFILL / KIND_DECODE per entry
        ("n_extra", u32_p),  # extra rows after an entry's history rows (was n_drafts, same offset)
        # appended (additive ABI): [n_reqs, cfg.vocab_words] int32 logit mask, one row per
        # planned entry; NULL iff cfg.vocab_words == 0. See kelpie-core/include/kelpie.h.
        ("logit_mask", ctypes.POINTER(ctypes.c_int32)),
        ("step", u64),
        # appended (additive ABI): the padded plan. Every array above is bucket-sized; these are
        # how much of it is real. See kelpie-core/include/kelpie.h for the pad values.
        ("n_reqs_padded", u32),
        ("n_tokens_padded", u32),
        # [n_tokens_padded] i32: the request index owning each row, -1 for a pad row.
        ("row_request", ctypes.POINTER(ctypes.c_int32)),
        # Deterministic program-selection key derived only from this plan (see c_api.zig
        # stepShape(): padded_num_tokens bucket idx | padded_num_reqs bucket idx << 8 |
        # has_prefill << 12 | K << 16). A native launch fn may ignore it and recompute the same
        # value from the plan itself -- Zig and Python must never disagree. mode/dtype/flags
        # (the plan's `shape`) are per-program constants fixed at capture time and
        # never travel on this wire.
        ("shape", u32),
        # appended: the spec-agnostic core API (docs/design-core-option2.md 2.3)
        ("seq_start", u32_p),  # [R] tokens already in context; the entry's rows start here
        ("emits", u8_p),  # [R] 1 iff commit keeps the entry's tokens
        ("max_extra", u32),  # Kmax: columns of state_write are 1 + max_extra
        ("zero_unit", u32_p),  # [n_groups] ZERO(g) of a per_seq group; 0 for per_token
        ("state_read", u32_pp),  # [n_groups] -> [R]; NULL for a per_token group
        ("state_write", u32_pp),  # [n_groups] -> [R * (1 + max_extra)]
        ("state_ckpt", u32_pp),  # [n_groups] -> [R]; SCRATCH (0) = none
        ("state_ckpt_row", u32_pp),  # [n_groups] -> [R]; NO_ROW when ckpt is SCRATCH
        # ABI 3: Wyhash of the plan + the batch applied before it + the previous payload.
        # Equal on every rank that planned the same step; set for an idle plan too.
        ("digest", u64),
        # appended (additive ABI): [R] 1 = greedy (the core's T=0 rule), 0 = whole vocab.
        ("top_ks", u32_p),
    ]


class KelpieStepOut(ctypes.Structure):
    """The launch callback's output (ABI 3), engine-owned, sized at create: entry i keeps
    tokens[i * stride : i * stride + n_tokens[i]] and asks for next_extra[i] extra rows."""

    _fields_ = [
        ("stride", u32),  # 1 + max_extra
        ("tokens", u32_p),  # [max_batch_reqs * stride]
        ("n_tokens", u32_p),  # [max_batch_reqs]
        ("next_extra", u32_p),  # [max_batch_reqs]
    ]


KIND_PREFILL, KIND_DECODE = 0, 1
KIND_NAMES = ("prefill", "decode")

# The bucket ladder is the core's (kelpie-core/src/buckets.zig): read over the ABI, never
# restated here. One ladder, one writer -- a duplicated ladder is exactly the drift
# docs/friction-2026-09-09.md section 1 catalogues. Both axes use it.
_BUCKETS_CACHE: tuple[int, ...] | None = None


def buckets(lib: ctypes.CDLL | None = None) -> tuple[int, ...]:
    """The core's ladder. Loads the library once and caches it."""
    global _BUCKETS_CACHE
    if _BUCKETS_CACHE is None:
        lib = lib or load()
        n = lib.kelpie_bucket_count()
        _BUCKETS_CACHE = tuple(int(lib.kelpie_bucket_at(i)) for i in range(n))
        assert _BUCKETS_CACHE and list(_BUCKETS_CACHE) == sorted(_BUCKETS_CACHE)
    return _BUCKETS_CACHE


def bucket(n: int) -> int:
    """The smallest bucket >= n."""
    for b in buckets():
        if b >= n:
            return b
    raise ValueError(f"{n} exceeds largest bucket {buckets()[-1]}")


def bucket_index(n: int) -> int:
    for i, b in enumerate(buckets()):
        if b >= n:
            return i
    raise ValueError(f"{n} exceeds largest bucket {buckets()[-1]}")


def step_shape_wire(n_tokens: int, n_reqs: int, kinds: list[int], n_extra: list[int]) -> int:
    """Recomputes KelpiePlan.shape (see c_api.zig stepShape()) from plan arrays alone -- Zig and
    Python must always agree without a wire struct."""
    assert n_tokens >= n_reqs > 0, (n_tokens, n_reqs)
    assert len(kinds) == len(n_extra)
    max_k = min(max(n_extra, default=0), 15)
    has_prefill = 1 if KIND_PREFILL in kinds else 0
    return (
        bucket_index(n_tokens) | (bucket_index(n_reqs) << 8) | (has_prefill << 12) | (max_k << 16)
    )


# (captured, shape, plan, out) -> status. `captured` is the context this launch runs against
# (never NULL); `out` is the engine's KelpieStepOut (ABI 3).
LAUNCH_FN = ctypes.CFUNCTYPE(u32, ctypes.c_void_p, u32, ctypes.POINTER(KelpiePlan), ctypes.POINTER(KelpieStepOut))
LAUNCH_WAIT_FN = ctypes.CFUNCTYPE(u32, ctypes.c_void_p, ctypes.POINTER(KelpieStepOut))
# Rank sync (kelpie_register_sync): exchange(ctx, in, n_in, out, cap) -> bytes written;
# agree(ctx, digest) -> 0 when every rank agrees.
EXCHANGE_FN = ctypes.CFUNCTYPE(u32, ctypes.c_void_p, u8_p, u32, u8_p, u32)
AGREE_FN = ctypes.CFUNCTYPE(u32, ctypes.c_void_p, u64)
PLAN_DIVERGED, PLAN_STOPPED = 0xFFFFFFFF, 0xFFFFFFFE
# kelpie_synthetic_plan statuses (kelpie.h KELPIE_SYNTH_*, c_api.zig SyntheticStatus).
SYNTH_OK, SYNTH_ERR_BUSY = 0, -1
SYNTH_ERRORS = {
    -2: "kind is not prefill/decode, or a shape no real plan has (decode rows != 1, or extra "
        "rows on a prefill)",
    -3: "n_reqs is 0 or above the live max_batch_reqs",
    -4: "rows is 0",
    -5: "n_reqs * (rows + n_extra) is above the live max_batch_tokens",
    -6: "n_extra is above max_extra",
    -7: "rows + n_extra is above max_seq_len",
}
DIVERGENCES = ("none", "bad_batch", "lagged_digest", "lagged_payload", "boundary", "digest", "payload")


class KelpieCommit(ctypes.Structure):
    """kelpie_commit: entry i (plan order) keeps tokens[i * stride : i * stride + n_tokens[i]]
    (1 <= n_tokens[i] <= 1 + n_extra[i]; NULL = all 1) and asks for next_extra[i] extra rows
    on its next decode-shaped entry (NULL = all 0)."""

    _fields_ = [
        ("n_entries", u32),
        ("stride", u32),
        ("tokens", u32_p),
        ("n_tokens", u32_p),
        ("next_extra", u32_p),
    ]


COMMIT_OK, COMMIT_ERR_ENTRIES, COMMIT_ERR_COUNT, COMMIT_ERR_GRAMMAR, COMMIT_ERR_TOKEN = 0, -1, -2, -3, -4
COMMIT_ERRORS = {
    COMMIT_ERR_ENTRIES: "n_entries is not the plan's n_reqs, or tokens is NULL",
    COMMIT_ERR_COUNT: "n_tokens outside [1, 1 + n_extra], stride too small, or next_extra > max_extra",
    COMMIT_ERR_GRAMMAR: "more than one token, or extra rows, for a request with a grammar",
    COMMIT_ERR_TOKEN: "a kept token is NO_TOKEN or >= vocab_size",
}
# kelpie.h KELPIE_ABI_VERSION: bumped on every non-additive change (load refuses a mismatch).
ABI_VERSION = 3
NO_TOKEN = 0xFFFFFFFF  # input_ids of an extra row: the caller fills it (0 is a real vocab id)
UNIT_SCRATCH = 0  # per_seq unit 0: writable, never read
NO_ROW = 0xFFFFFFFF  # state_ckpt_row when the step writes no checkpoint
SWAP_OK, SWAP_BAD_ARGS, SWAP_PENDING = 0, -1, -2


class KelpiePoll(ctypes.Structure):
    _fields_ = [("n_new", u32), ("finished", ctypes.c_uint8), ("state", u32)]


TIMING_PLAN, TIMING_FORWARD, TIMING_COMMIT = 0, 1, 2
TIMINGS = ("plan", "forward", "commit")


class KelpieStepEvent(ctypes.Structure):
    _fields_ = [
        ("step", u64),
        ("t_plan_ns", u64),
        ("t_forward_ns", u64),
        ("t_commit_ns", u64),
        ("n_running", u32),
        ("n_waiting", u32),
        ("n_prefill_reqs", u32),
        ("n_decode_reqs", u32),
        ("n_tokens", u32),
        ("kv_free", u32),
        ("kv_used", u32),
        ("n_admitted", u32),
        ("n_preempted", u32),
        ("n_finished", u32),
        ("n_rejected_full", u32),
        ("prefix_queries", u32),
        ("prefix_hits", u32),
        ("prefix_hit_tokens", u32),
        ("order", u32),
        ("config_hash", u64),
        ("is_idle", ctypes.c_bool),
        ("n_extra_rows", u32),  # extra rows planned (was n_draft_tokens, same offset)
        ("n_extra_kept", u32),  # extra rows committed (was n_accepted_tokens)
    ]


class KelpieRequestEvent(ctypes.Structure):
    _fields_ = [
        ("t_arrival_ns", u64),
        ("t_first_sched_ns", u64),
        ("t_first_token_ns", u64),
        ("t_last_token_ns", u64),
        ("t_finish_ns", u64),
        ("first_step", u64),
        ("last_step", u64),
        ("request_id", u32),
        ("n_prompt", u32),
        ("n_gen", u32),
        ("max_new", u32),
        ("n_preemptions", u32),
        ("n_chunks", u32),
        ("finish_reason", u32),
        ("kv_blocks_peak", u32),
    ]


def default_lib_path() -> Path:
    ext = "dylib" if sys.platform == "darwin" else "so"
    repo = Path(__file__).resolve().parents[2]
    return repo / "kelpie-core" / "zig-out" / "lib" / f"libkelpie.{ext}"


def load(path: str | os.PathLike[str] | None = None) -> ctypes.CDLL:
    """Load libkelpie from `path`, $KELPIE_LIB, or kelpie-core/zig-out/lib."""
    resolved = Path(path or os.environ.get("KELPIE_LIB") or default_lib_path())
    if not resolved.exists():
        raise FileNotFoundError(
            f"libkelpie not found at {resolved}; run `../scripts/zig build lib` in kelpie-core"
        )
    lib = ctypes.CDLL(str(resolved))
    engine_p = ctypes.c_void_p
    sigs = {
        "kelpie_create": ([ctypes.POINTER(KelpieConfig)], engine_p),
        "kelpie_destroy": ([engine_p], None),
        "kelpie_submit": ([engine_p, u32_p, u32, u32, ctypes.c_float], ctypes.c_int64),
        "kelpie_submit_mm": ([engine_p, u32_p, u32, u32, ctypes.c_float, u64, u32], ctypes.c_int64),
        "kelpie_submit_mm_stop": (
            [engine_p, u32_p, u32, u32, ctypes.c_float, u64, u32, u32_p, u32, u64],
            ctypes.c_int64,
        ),
        "kelpie_submit_top_k": (
            [engine_p, u32_p, u32, u32, ctypes.c_float, u32, u64, u32, u32_p, u32, u64],
            ctypes.c_int64,
        ),
        "kelpie_cancel": ([engine_p, u32], None),
        "kelpie_cancel_gen": ([engine_p, u32, u32], ctypes.c_int32),
        "kelpie_generation": ([engine_p, u32], u32),
        "kelpie_register_grammar": (
            [engine_p, u64, ctypes.c_void_p, ctypes.c_char_p, u32],
            ctypes.c_int32,
        ),
        "kelpie_register_sync": (
            [engine_p, EXCHANGE_FN, AGREE_FN, ctypes.c_void_p, u32],
            ctypes.c_int32,
        ),
        "kelpie_divergence": ([engine_p, ctypes.POINTER(u64)], u32),
        "kelpie_last_digest": ([engine_p], u64),
        "kelpie_plan": ([engine_p, ctypes.POINTER(KelpiePlan)], u32),
        "kelpie_commit": ([engine_p, ctypes.POINTER(KelpieCommit)], ctypes.c_int32),
        "kelpie_synthetic_plan": (
            [engine_p, u32, u32, u32, u32, ctypes.POINTER(KelpiePlan)],
            ctypes.c_int32,
        ),
        "kelpie_abi_version": ([], u32),
        "kelpie_poll": ([engine_p, u32, u32_p, u32, ctypes.POINTER(KelpiePoll)], u32),
        "kelpie_worst_slabs": ([engine_p, u32, u32], u32),
        "kelpie_stall": ([engine_p, *[ctypes.POINTER(u32)] * 4], ctypes.c_int32),
        "kelpie_step_event": ([engine_p, ctypes.POINTER(KelpieStepEvent)], None),
        "kelpie_next_commit": (
            [engine_p, ctypes.POINTER(KelpieStepEvent), u32_p, u32, ctypes.POINTER(u32)],
            ctypes.c_int32,
        ),
        "kelpie_step_pipe_fd": ([engine_p], ctypes.c_int32),
        "kelpie_request_event": (
            [engine_p, u32, ctypes.POINTER(KelpieRequestEvent)],
            ctypes.c_int32,
        ),
        "kelpie_timing_start": ([engine_p, u32], ctypes.c_int32),
        "kelpie_timing_stop": ([engine_p, u32], ctypes.c_int32),
        "kelpie_set": (
            [engine_p, ctypes.POINTER(KelpieKnob), ctypes.POINTER(KelpieSetResult)],
            ctypes.c_int32,
        ),
        "kelpie_set_order": ([engine_p, u32], ctypes.c_int32),
        "kelpie_get_config": ([engine_p, ctypes.POINTER(KelpieConfig)], None),
        "kelpie_register_launch": ([engine_p, LAUNCH_FN, ctypes.c_void_p], ctypes.c_int32),
        "kelpie_register_launch_split": (
            [engine_p, LAUNCH_FN, LAUNCH_FN, LAUNCH_WAIT_FN, ctypes.c_void_p],
            ctypes.c_int32,
        ),
        "kelpie_swap_launch": (
            [engine_p, LAUNCH_FN, ctypes.c_void_p, ctypes.c_bool],
            ctypes.c_int32,
        ),
        "kelpie_start_loop": ([engine_p], ctypes.c_int32),
        "kelpie_wake": ([engine_p], None),
        "kelpie_stop_loop": ([engine_p], None),
        "kelpie_launch_epoch": ([engine_p], u64),
        "kelpie_loop_alive": ([engine_p], ctypes.c_bool),
        "kelpie_last_step_ns": ([engine_p], u64),
        "kelpie_now_ns": ([engine_p], u64),
        "kelpie_sampling_eps": ([], ctypes.c_float),
        "kelpie_bucket_count": ([], u32),
        "kelpie_bucket_at": ([u32], u32),
        "kelpie_config_sizeof": ([], ctypes.c_size_t),
        "kelpie_plan_sizeof": ([], ctypes.c_size_t),
    }
    for name, (argtypes, restype) in sigs.items():
        fn = getattr(lib, name)
        fn.argtypes = argtypes
        fn.restype = restype
    check_abi(lib)
    return lib


STRUCT_STEP_OUT = 8  # KELPIE_STRUCT_STEP_OUT (kelpie-core/src/abi_ids.zig)


def check_abi(lib: ctypes.CDLL) -> None:
    """Assert this module's structs are the size the core compiled.

    The ABI is additive-only, and that is exactly the property review cannot check: a bridge
    that stops short of the struct does not fail, it silently mis-writes every field past the
    gap. This has already happened once -- three appended fields were live in the core and
    absent here, and nothing caught it. A size mismatch is now a load-time error naming both
    numbers, so the next appended field is a startup failure rather than a wrong answer.
    """
    version = int(lib.kelpie_abi_version())
    if version != ABI_VERSION:
        raise RuntimeError(
            f"ABI version mismatch: libkelpie is {version}, this binding is {ABI_VERSION} "
            f"(a non-additive change, e.g. KelpieCommit's layout). Rebuild libkelpie or update "
            f"kelpie_engine._ffi.")
    lib.kelpie_sizeof.argtypes, lib.kelpie_sizeof.restype = [u32], ctypes.c_size_t
    pairs = (
        (KelpieConfig, lib.kelpie_config_sizeof),
        (KelpiePlan, lib.kelpie_plan_sizeof),
        (KelpieStepOut, lambda: lib.kelpie_sizeof(STRUCT_STEP_OUT)),
    )
    for struct, sizeof in pairs:
        want, got = sizeof(), ctypes.sizeof(struct)
        if want != got:
            raise RuntimeError(
                f"ABI mismatch: the core compiled {struct.__name__} at {want} bytes, this "
                f"binding declares {got}. A field was appended to kelpie.h without being added "
                f"to kelpie_engine._ffi (or the loaded libkelpie is stale -- rebuild with "
                f"`scripts/zig build lib` in kelpie-core)."
            )
