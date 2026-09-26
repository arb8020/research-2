"""`Engine`: the one runtime object. ctypes over kelpie.h and nothing else.

The boundary is a file descriptor: the engine exposes `step_fd`, the Zig step thread writes one
byte to it per commit, and the caller's own event loop (trio, asyncio, or a bare `select.select`)
does the waiting. The engine owns no thread and no lock over that fd -- the kernel does the
waiting, no framework in between (see the multiprocessing_heinrich pattern this follows).

The twenty-six public members (count them; this docstring must stay true):
    resources   __init__ / close
    work        submit / cancel / poll / wait / generation
    loop        start_loop / stop_loop / wake / alive
    by hand     plan / commit                (a notebook stepping without the loop)
    warm-up     synthetic_plan               (an inert plan of a chosen shape, never committed)
    events      next_commit / has_work / step_fd / request_stats
    config      set / live_config / since_last_step_s
    errors      raise_error (swallowed step errors, then Stalled)
    grammar     supports_grammar
    ranks       edge / follow / register_sync / last_digest

Inputs (docs/design-multigpu.md 2.3): submit / cancel / set, and the release a poll triggers on
first seeing a request finished, are ops the core applies at the next step boundary -- the one
point before plan() where every rank applies the same batch. World 1 is the same program: the
edge is the only rank and the exchange is the identity. Rejections (Full / TooLong /
ExceedsKvPool / Draining) stay synchronous; until its boundary a submitted request polls as
waiting with no tokens, and a cancelled one polls as cancelled at once.

subscribe / retire / _waiters / _live / _lock / _drain* are gone: fan-out (the request_id ->
trio.Event bookkeeping) now lives entirely in the trio app that reads step_fd, because it is the
only layer that knows what "wake a waiter" means for its own event loop.

Lifecycle:  Engine(cfg) -> start_loop(step) -> [submit / poll / step_fd / set] -> close()

A notebook with no trio: `select.select([engine.step_fd], [], [])` blocks until the next commit,
then drain with `next_commit()` until it returns None.
"""

from __future__ import annotations

import ctypes
import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from typing import Any, Literal

import numpy as np

from kelpie_engine import _ffi
from kelpie_engine.sdk import plan as plan_view
from kelpie_engine.sdk.plan import Plan

ORDERS = ("running_first", "waiting_first")
Order = Literal["running_first", "waiting_first"]
MASK_BITS = 32
BLOCK_SIZE = 16
MAX_BATCH_REQS = 256


class Full(Exception):
    """The request pool is full; retry later."""


class TooLong(Exception):
    """prompt + max_new_tokens exceeds max_seq_len."""


class ExceedsKvPool(TooLong):
    """prompt + max_new_tokens could never fit the KV pool, even running alone."""


class Stalled(RuntimeError):
    """The core can make no progress: work is pending but nothing fits and nothing is running."""


class Draining(Exception):
    """A launch swap is draining; retry later."""


class CommitError(RuntimeError):
    """kelpie_commit refused the commit (nothing was applied): the status names why."""


class NotEdge(RuntimeError):
    """submit / cancel / set on a follower rank: only the edge takes caller input."""


class Diverged(RuntimeError):
    """A by-hand step stopped: the boundary's batch was malformed, or this rank's plan differs
    from the edge's (the engine is poisoned; see `kind` and `step`)."""

    def __init__(self, kind: str, step: int) -> None:
        super().__init__(f"step {step}: {kind}")
        self.kind = kind
        self.step = step


@dataclass(frozen=True)
class GroupSpec:
    """One cache group as the core sees it."""

    kind: Literal["per_token", "per_seq"]
    block_size: int
    window: int = 0
    cacheable: bool = True
    stride: int = 1


@dataclass(frozen=True)
class EngineConfig:
    """The core's shape. Every field has exactly one writer: `from_model` derives the model's
    half from the model's own config object, and the caller passes the four capacity knobs."""

    max_requests: int
    max_seq_len: int
    num_blocks: int  # includes null block 0
    max_batch_tokens: int
    max_batch_reqs: int
    groups: tuple[GroupSpec, ...]
    eos_token: int
    vocab_words: int  # ceil(model vocab / 32); 0 disables grammar
    # The slab plan (kelpie_models.sdk.groups.choose_block_sizes, docs/slab-lcm-ladder.md): one
    # page size per group, each dividing slab_bytes = max(bytes_per_page) exactly. Empty = the
    # legacy equal-page mode, where the core makes one page per slab and `num_blocks` counts
    # pages. Non-empty: `num_blocks` counts SLABS, and the core reports the geometry it resolved
    # back through `live_config` (slab_bytes / num_slabs).
    bytes_per_page: tuple[int, ...] = ()
    slab_bytes: int = 0  # out only: read back from kelpie_get_config
    num_slabs: int = 0  # out only: read back from kelpie_get_config
    reserve_ratio: float = 0.0
    order: Order = "running_first"
    prefix_cache: bool = True
    overlap: bool = False
    # Kmax: the most extra rows (caller-filled, e.g. drafts) a decode entry may carry; 0 = none.
    max_extra: int = 0
    # The model's vocabulary: commit rejects a kept token id >= vocab_size. 0 = unchecked.
    vocab_size: int = 0

    @staticmethod
    def from_model(
        cfg: Any,
        groups: tuple[GroupSpec, ...],
        *,
        max_requests: int,
        kv_blocks: int,
        max_batch_tokens: int,
        bytes_per_page: tuple[int, ...] = (),
        max_extra: int = 0,
        max_seq_len: int = 0,
    ) -> EngineConfig:
        """The model's config object is the one writer of eos_token / max_seq_len / vocab_words;
        `groups` comes from the model's `attn_specs`. `cfg` is the model module's own config
        dataclass (GPT2Config, Qwen3Config, ...) -- Any because every model has its own.

        `max_seq_len` overrides the model's native maximum when non-zero -- use it when the
        deployment does not need the full context window (a correctness test with short prompts,
        a latency-optimized config with a capped context)."""
        vocab = int(cfg.vocab)
        assert vocab > 0, vocab
        resolved_max_seq = max_seq_len if max_seq_len > 0 else max_seq_len_of(cfg)
        return EngineConfig(
            max_requests=max_requests,
            max_seq_len=resolved_max_seq,
            num_blocks=kv_blocks,
            max_batch_tokens=max_batch_tokens,
            max_batch_reqs=min(MAX_BATCH_REQS, max_requests),
            groups=groups,
            eos_token=int(cfg.eos_token),
            vocab_words=(vocab + MASK_BITS - 1) // MASK_BITS,
            bytes_per_page=bytes_per_page,
            max_extra=max_extra,
            vocab_size=vocab,
        )


def max_seq_len_of(cfg: Any) -> int:
    """The model's context length, read off the model's own config -- never a constant here. It
    comes from the HF config (`n_positions` / `max_position_embeddings`) through
    `config_from_hf`, so the engine and the model can never disagree about the bound."""
    value = getattr(cfg, "max_seq_len", None)
    assert value is not None, f"{type(cfg).__name__} must declare max_seq_len"
    return int(value)


@dataclass(frozen=True)
class Poll:
    new_tokens: list[int]
    finished: bool
    reason: str | None


@dataclass(frozen=True)
class StepEvent:
    """One per plan/commit pair, as the core reports it."""

    step: int
    n_running: int
    n_waiting: int
    n_tokens: int
    n_finished: int
    kv_used: int
    kv_free: int
    t_plan_ns: int
    t_forward_ns: int
    t_commit_ns: int
    is_idle: bool
    n_preempted: int = 0
    n_extra_rows: int = 0  # extra rows planned (drafts verified)
    n_extra_kept: int = 0  # extra rows committed (drafts accepted)
    n_rejected_full: int = 0
    config_hash: int = 0


@dataclass(frozen=True)
class Commit:
    """One popped commit record: what that step did and whom it advanced."""

    event: StepEvent
    advanced: list[int]
    n_dropped: int


@dataclass(frozen=True)
class Emitted:
    """What one step hands the core, one row per REAL entry in plan order (docs/design-multigpu.md
    2.4; moved from models/torch/dflash.py).

    tokens:     u32[R] (one token each) or u32[R, S]: entry i keeps tokens[i, :n[i]].
    n:          u32[R], 1 <= n[i] <= 1 + n_extra[i] -- "tail rows 0..n-1 were valid". None = all 1.
    next_extra: u32[R], extra rows entry i's request wants on its next decode-shaped entry (0 =
                none, at most max_extra). None = all 0."""

    tokens: np.ndarray
    n: np.ndarray | None = None
    next_extra: np.ndarray | None = None


# What the Zig loop calls: one plan in, what to commit out.
StepFn = Callable[[Plan], Emitted]


class Engine:
    """ctypes over kelpie.h. See the module docstring for the member list and the fd contract."""

    def __init__(self, config: EngineConfig, lib_path: str | None = None) -> None:
        assert config.max_requests > 0 and config.groups, config
        self._handle = None  # first, so __del__ is safe if anything below raises
        self.config = config
        # Knob name -> the largest value `set` accepts. Empty: no ceiling. `kelpie_models`'s
        # build fills it with the batch limits it warmed every step shape for, so a live raise
        # past them is refused here (a 400 over HTTP) instead of failing the step loop later.
        self.batch_ceiling: dict[str, int] = {}
        self._lib = _ffi.load(lib_path)
        plan_view.check_abi(self._lib)
        self._handle = _create(self._lib, config)
        self._plan = _ffi.KelpiePlan()
        # The core's greedy threshold (request.sampling_eps), read over the ABI rather than
        # restated here: the core applies the T=0 rule with it, so it has exactly one writer.
        self._sampling_eps = float(self._lib.kelpie_sampling_eps())
        self._poll_tokens = np.empty(config.max_seq_len, dtype=np.uint32)
        self._launch: Any = None  # ctypes trampoline; GC here would free code Zig is calling
        self._sync: tuple[Any, Any] | None = None  # ctypes sync callbacks, kept alive likewise
        self._edge = True
        self._error: str | None = None
        # Guards `_error` only: the Zig step thread writes it in the trampoline, a serving
        # thread reads-and-clears it in raise_error. Everything else about a request lives in
        # Zig, which does its own locking.
        self._error_lock = threading.Lock()

    def close(self) -> None:
        """stop_loop (joins the Zig step thread) then destroy. Idempotent."""
        if self._handle is None:
            return
        self._lib.kelpie_stop_loop(self._handle)
        self._lib.kelpie_destroy(self._handle)
        self._handle = None
        self._launch = None

    def __del__(self) -> None:
        self.close()

    def _engine_handle(self) -> Any:
        assert self._handle is not None, "engine is closed"
        return self._handle

    def submit(
        self,
        prompt: list[int],
        max_new_tokens: int,
        temperature: float = 0.0,
        stop_token_ids: Iterable[int] = (),
        grammar: Grammar | None = None,
        top_k: int = 0,
    ) -> int:
        """Queue a request; it enters the core at the next step boundary. `grammar` is
        registered (on the edge this also queues its grammar_prepare op) before the submit op,
        so it is in place by the time the submit applies. `top_k` samples from the k most
        likely tokens (0 = the whole vocabulary); a temperature below kelpie_sampling_eps is
        greedy whatever top_k says (the core's T=0 rule sets top_k 1)."""
        if not prompt:
            raise ValueError("empty prompt")
        self._check_sampling(temperature, top_k)
        if grammar is not None and (self.config.vocab_words == 0 or self.config.max_extra > 0):
            raise ValueError("grammar needs vocab_words > 0 and no extra rows (design-multigpu 2.5)")
        arr = np.ascontiguousarray(prompt, dtype=np.uint32)
        stops = np.ascontiguousarray(list(stop_token_ids), dtype=np.uint32)
        assert len(stops) <= _ffi.MAX_STOP_TOKENS, len(stops)
        key = 0
        if grammar is not None:
            key = grammar.key
            status = self._lib.kelpie_register_grammar(
                self._engine_handle(), key, grammar.compiled_ptr, grammar.source, len(grammar.source))
            assert status == 0, f"kelpie_register_grammar: {status}"
        request_id = self._lib.kelpie_submit_top_k(
            self._engine_handle(),
            _u32p(arr),
            len(arr),
            max_new_tokens,
            temperature,
            top_k,
            0,
            0,
            _u32p(stops),
            len(stops),
            key,
        )
        if request_id == _ffi.SUBMIT_NOT_EDGE:
            raise NotEdge("submit on a follower rank")
        if request_id == _ffi.SUBMIT_FULL:
            raise Full
        if request_id == _ffi.SUBMIT_TOO_LONG:
            raise TooLong
        if request_id == _ffi.SUBMIT_DRAINING:
            raise Draining
        if request_id == _ffi.SUBMIT_EXCEEDS_KV_POOL:
            handle = self._engine_handle()
            need = int(self._lib.kelpie_worst_slabs(handle, len(arr), max_new_tokens))
            raise ExceedsKvPool(
                f"prompt ({len(arr)} tokens) + max_new_tokens ({max_new_tokens}) needs {need} KV "
                f"slabs at its peak; the pool has {self.live_config().num_slabs}"
            )
        assert request_id >= 0, request_id
        return int(request_id)

    def _check_sampling(self, temperature: float, top_k: int) -> None:
        """Raises ValueError for a temperature or top_k this engine refuses; the core refuses
        them too (SUBMIT_BAD_ARGS / SUBMIT_BAD_TOP_K), this names the argument and the limit."""
        if not temperature >= 0 or temperature == float("inf"):
            raise ValueError(f"temperature must be finite and >= 0, got {temperature}")
        vocab = self.config.vocab_size
        if top_k < 0 or (vocab > 0 and top_k > vocab):
            limit = f" and <= vocab_size {vocab}" if vocab > 0 else ""
            raise ValueError(f"top_k must be >= 0 (0 = off){limit}, got {top_k}")
        # The extra-row loop accepts greedily (kelpie_models.sdk.decide); refusing here, not
        # between plan and commit, keeps the engine steppable. "Greedy" is the core's T=0 rule:
        # below kelpie_sampling_eps, compared as the f32 the core receives.
        if self.config.max_extra > 0 and ctypes.c_float(temperature).value >= self._sampling_eps:
            raise ValueError(
                f"an engine with extra rows (a drafter) decodes greedily: temperature must be "
                f"< {self._sampling_eps} (0), got {temperature}")

    def cancel(self, request_id: int, generation: int | None = None) -> bool:
        """Lifecycle verb: the request finishes `cancelled` at the next step boundary (poll says
        cancelled from now on). With `generation` (read by `generation()` right after submit)
        it cancels exactly that request: a no-op once the id has been reused. -> queued."""
        handle = self._engine_handle()
        if generation is None:
            generation = self.generation(request_id)
        status = int(self._lib.kelpie_cancel_gen(handle, request_id, generation))
        if status == _ffi.SUBMIT_NOT_EDGE:
            raise NotEdge("cancel on a follower rank")
        return status == 1

    def generation(self, request_id: int) -> int:
        """The generation of the request now holding `request_id` (see cancel)."""
        return int(self._lib.kelpie_generation(self._engine_handle(), request_id))

    def has_work(self) -> bool:
        """Any request still in flight, per the last commit's step event (is_idle = the plan had
        zero tokens). /health reads this alongside alive()."""
        event = _ffi.KelpieStepEvent()
        self._lib.kelpie_step_event(self._engine_handle(), ctypes.byref(event))
        return not bool(event.is_idle)

    def since_last_step_s(self) -> float | None:
        """Seconds since the loop last stepped; None before the first step."""
        last = int(self._lib.kelpie_last_step_ns(self._engine_handle()))
        if last == 0:
            return None
        return (int(self._lib.kelpie_now_ns(self._engine_handle())) - last) / 1e9

    @property
    def supports_grammar(self) -> bool:
        return self.config.vocab_words > 0

    def poll(self, request_id: int) -> Poll:
        result = _ffi.KelpiePoll()
        n = self._lib.kelpie_poll(
            self._engine_handle(),
            request_id,
            _u32p(self._poll_tokens),
            len(self._poll_tokens),
            ctypes.byref(result),
        )
        assert n == result.n_new, (n, result.n_new)
        finished = bool(result.finished)
        return Poll(
            self._poll_tokens[:n].tolist(),
            finished,
            _ffi.STATE_NAMES[result.state] if finished else None,
        )

    def start_loop(self, step: StepFn) -> None:
        """Hand `step` to the Zig step thread and start it. From here the loop owns stepping:
        it plans, calls `step`, and commits what it returns (an `Emitted`, n tokens per entry),
        all without the GIL-holding caller."""
        assert self._launch is None, "start_loop twice"
        self._launch = _ffi.LAUNCH_FN(self._trampoline(step))
        status = self._lib.kelpie_register_launch(self._engine_handle(), self._launch, 1)
        assert status == 0, status
        status = self._lib.kelpie_start_loop(self._engine_handle())
        assert status == 0, status

    @property
    def edge(self) -> bool:
        """True on the rank that owns the caller API -- always at world 1."""
        return self._edge

    def register_sync(
        self,
        exchange: Callable[[bytes, int], bytes],
        agree: Callable[[int], bool] | None,
        *,
        edge: bool,
    ) -> None:
        """The rank-sync seam (docs/design-multigpu.md 2.2): `exchange(mine, cap) -> the edge's
        bytes` carries every boundary's batch and every commit's payload; `agree(digest) ->
        every rank equal`. Before start_loop. Never registered at world 1."""

        def c_exchange(_ctx: int, in_ptr: Any, n_in: int, out_ptr: Any, cap: int) -> int:
            try:
                got = exchange(ctypes.string_at(in_ptr, n_in) if n_in else b"", int(cap))
                if len(got) > cap:
                    return cap + 1
                ctypes.memmove(out_ptr, got, len(got))
                return len(got)
            except Exception:  # noqa: BLE001 -- the ABI has no traceback channel
                import sys
                import traceback

                traceback.print_exc(file=sys.stderr)
                return cap + 1

        def c_agree(_ctx: int, digest: int) -> int:
            try:
                return 0 if agree is None or agree(int(digest)) else 1
            except Exception:  # noqa: BLE001
                import sys
                import traceback

                traceback.print_exc(file=sys.stderr)
                return 1

        self._sync = (_ffi.EXCHANGE_FN(c_exchange), _ffi.AGREE_FN(c_agree))
        status = self._lib.kelpie_register_sync(self._engine_handle(), *self._sync, None, int(edge))
        assert status == 0, f"kelpie_register_sync: {status}"
        self._edge = edge

    def follow(self, step: StepFn | None = None) -> None:
        """A follower's whole job: run the loop with `step` until the edge's batch says stop,
        draining the commit ring so it never drops records. (With `step` None the caller steps
        by hand: plan / commit until plan() raises StopIteration.)"""
        assert not self._edge, "follow() is for a follower rank"
        if step is None:
            return
        self.start_loop(step)
        import select

        while self.alive():
            ready, _, _ = select.select([self.step_fd], [], [], 0.5)
            if ready:
                import os

                os.read(self.step_fd, 4096)
                while self.next_commit() is not None:
                    pass
            self.raise_error()

    def wait(self, request_id: int, timeout_s: float | None = None) -> Poll:
        """Block until `request_id` finishes; -> its last poll (tokens are whatever the caller
        has not polled yet, accumulated). The non-HTTP wait: select(step_fd), drain, poll."""
        import os
        import select
        import time

        tokens: list[int] = []
        deadline = None if timeout_s is None else time.monotonic() + timeout_s
        while True:
            self.raise_error()
            result = self.poll(request_id)
            tokens.extend(result.new_tokens)
            if result.finished:
                return Poll(tokens, True, result.reason)
            left = None if deadline is None else max(0.0, deadline - time.monotonic())
            if left == 0.0:
                raise TimeoutError(f"request {request_id} not finished ({len(tokens)} tokens)")
            ready, _, _ = select.select([self.step_fd], [], [], 0.05 if left is None else min(left, 0.05))
            if ready:
                os.read(self.step_fd, 4096)
                while self.next_commit() is not None:
                    pass

    def last_digest(self) -> int:
        """The last plan's digest (idle plans included)."""
        return int(self._lib.kelpie_last_digest(self._engine_handle()))

    def _trampoline(self, step: StepFn) -> Callable[[int, int, Any, Any], int]:
        """The C ABI carries a status, not a traceback: an exception in `step` becomes status 1
        and is stashed for `raise_error()` on the serving thread. The step's `Emitted` lands in
        the engine's KelpieStepOut in one bulk copy per array."""
        words = self.config.vocab_words
        views: dict[str, np.ndarray] = {}

        def launch(_captured: int, _shape: int, plan_ptr: Any, out_ptr: Any) -> int:
            try:
                plan = plan_view.of(plan_ptr.contents, words)
                emitted = step(plan)
                if not views:
                    out = out_ptr.contents
                    cap = self.config.max_batch_reqs
                    views["tokens"] = np.ctypeslib.as_array(out.tokens, shape=(cap, int(out.stride)))
                    views["n"] = np.ctypeslib.as_array(out.n_tokens, shape=(cap,))
                    views["next_extra"] = np.ctypeslib.as_array(out.next_extra, shape=(cap,))
                write_step_out(views, emitted, plan.n_reqs)
                return 0
            except Exception as exc:  # noqa: BLE001 -- the ABI has no traceback channel
                import sys
                import traceback

                traceback.print_exc(file=sys.stderr)
                with self._error_lock:
                    self._error = f"{type(exc).__name__}: {exc}"
                return 1

        return launch

    def raise_error(self) -> None:
        """Re-raise on this thread whatever the step thread's launch swallowed. Lifecycle verb."""
        with self._error_lock:
            error, self._error = self._error, None
        if error is not None:
            raise RuntimeError(f"step failed inside the Zig loop: {error}")
        self._raise_stall()

    def _raise_stall(self) -> None:
        """Raise Stalled if the core's last plan could make no progress (kelpie_stall)."""
        req_id, n_work, need, free = (_ffi.u32() for _ in range(4))
        stalled = self._lib.kelpie_stall(
            self._engine_handle(),
            ctypes.byref(req_id),
            ctypes.byref(n_work),
            ctypes.byref(need),
            ctypes.byref(free),
        )
        if not stalled:
            return
        if n_work.value == 0:
            raise Stalled(
                f"no progress possible: request {req_id.value}'s next chunk is 0 tokens "
                f"(max_batch_tokens {self.live_config().max_batch_tokens} is below the block grain)"
            )
        raise Stalled(
            f"no progress possible: request {req_id.value}'s next chunk of {n_work.value} tokens "
            f"needs {need.value} KV slabs, {free.value} free, and nothing else is running"
        )

    def stop_loop(self) -> None:
        """Joins the step thread."""
        self._lib.kelpie_stop_loop(self._engine_handle())

    def wake(self) -> None:
        self._lib.kelpie_wake(self._engine_handle())

    def alive(self) -> bool:
        return bool(self._lib.kelpie_loop_alive(self._engine_handle()))

    def plan(self) -> Plan | None:
        """One step by hand, without the loop: the step boundary (the inbox's ops apply), plan,
        run the forward yourself, commit. None when the engine is idle -- that idle plan is
        already committed here, and raise_error() says if it stalled. Raises Diverged when the
        boundary refused the step (a follower whose plan left the edge's), StopIteration when
        the edge's batch said stop."""
        n = int(self._lib.kelpie_plan(self._engine_handle(), ctypes.byref(self._plan)))
        if n == _ffi.PLAN_DIVERGED:
            step = _ffi.u64(0)
            kind = int(self._lib.kelpie_divergence(self._engine_handle(), ctypes.byref(step)))
            raise Diverged(_ffi.DIVERGENCES[kind], int(step.value))
        if n == _ffi.PLAN_STOPPED:
            raise StopIteration("the edge closed")
        if n == 0:
            self._commit_raw(np.empty((0, 1), dtype=np.uint32), None, None)
            return None
        return plan_view.of(self._plan, self.config.vocab_words)

    def synthetic_plan(
        self, kind: Literal["prefill", "decode"], n_reqs: int, rows: int, n_extra: int = 0,
    ) -> Plan:
        """A warm-up plan from the core (kelpie_synthetic_plan): `n_reqs` inert entries of
        `kind`, each `rows` history rows then `n_extra` extra rows, padded and keyed (`shape`)
        by the same code as a real plan -- so its shape is the one a real plan of that family and
        bucket carries. Changes no engine state and is never committed; valid until the next
        plan() / synthetic_plan(). Raises ValueError naming the limit a shape exceeds, and
        RuntimeError while a plan is outstanding or the loop runs."""
        kinds = _ffi.KIND_NAMES
        if kind not in kinds:
            raise ValueError(f"kind must be one of {kinds}, got {kind!r}")
        status = int(self._lib.kelpie_synthetic_plan(
            self._engine_handle(), kinds.index(kind), n_reqs, rows, n_extra,
            ctypes.byref(self._plan)))
        if status == _ffi.SYNTH_ERR_BUSY:
            raise RuntimeError(
                "synthetic_plan: a plan is outstanding (commit it first) or the loop is running")
        if status != _ffi.SYNTH_OK:
            reason = _ffi.SYNTH_ERRORS.get(status, f"unknown status {status}")
            live = self.live_config()
            raise ValueError(
                f"synthetic_plan({kind!r}, n_reqs={n_reqs}, rows={rows}, n_extra={n_extra}): "
                f"{reason} (max_batch_reqs {live.max_batch_reqs}, max_batch_tokens "
                f"{live.max_batch_tokens}, max_extra {live.max_extra}, max_seq_len "
                f"{live.max_seq_len})")
        return plan_view.of(self._plan, self.config.vocab_words)

    def commit(
        self,
        tokens: np.ndarray | Emitted | None,
        n: np.ndarray | None = None,
        next_extra: np.ndarray | None = None,
    ) -> None:
        """The other half of `plan`, one row per REAL entry in plan order: an `Emitted`, or its
        three fields.

        tokens:     u32[R] (one token each) or u32[R, S]: entry i keeps tokens[i, :n[i]].
        n:          u32[R], 1 <= n[i] <= 1 + n_extra[i] -- "tail rows 0..n-1 were valid".
                    None = all 1.
        next_extra: u32[R], extra rows entry i's request wants on its next decode-shaped entry
                    (0 = none, at most max_extra). None = all 0.

        A partial prefill chunk's tokens are discarded whatever n says (n must still be 1).
        A follower passes None: the edge's payload is what commits (payload agreement)."""
        if tokens is None:
            assert not self._edge, "only a follower commits without a payload"
            status = int(self._lib.kelpie_commit(self._engine_handle(), None))
            if status != _ffi.COMMIT_OK:
                raise CommitError(f"kelpie_commit: {status} ({_ffi.COMMIT_ERRORS.get(status, 'unknown status')})")
            return
        if isinstance(tokens, Emitted):
            assert n is None and next_extra is None, "an Emitted carries its own n / next_extra"
            tokens, n, next_extra = tokens.tokens, tokens.n, tokens.next_extra
        raw = np.asarray(tokens)
        if raw.dtype.kind not in "iu":
            raise ValueError(f"tokens must be integers, got {raw.dtype}")
        if raw.dtype.kind == "i" and (raw < 0).any():
            raise ValueError("a negative token id (NO_TOKEN as -1?) cannot be committed")
        arr = raw.astype(np.uint32)
        if arr.ndim == 1:
            arr = arr[:, None]
        assert arr.ndim == 2, arr.shape  # noqa: PLR2004
        self._commit_raw(arr, n, next_extra)

    def _commit_raw(
        self, tokens: np.ndarray, n: np.ndarray | None, next_extra: np.ndarray | None
    ) -> None:
        n_entries, stride = tokens.shape
        tokens = np.ascontiguousarray(tokens, dtype=np.uint32)
        counts = None if n is None else np.ascontiguousarray(n, dtype=np.uint32)
        extra = None if next_extra is None else np.ascontiguousarray(next_extra, dtype=np.uint32)
        assert counts is None or counts.shape == (n_entries,), (None if counts is None else counts.shape, n_entries)
        assert extra is None or extra.shape == (n_entries,), (None if extra is None else extra.shape, n_entries)
        payload = _ffi.KelpieCommit(
            n_entries=n_entries,
            stride=stride,
            tokens=_u32p(tokens),
            n_tokens=None if counts is None else _u32p(counts),
            next_extra=None if extra is None else _u32p(extra),
        )
        status = int(self._lib.kelpie_commit(self._engine_handle(), ctypes.byref(payload)))
        if status != _ffi.COMMIT_OK:
            raise CommitError(f"kelpie_commit: {status} ({_ffi.COMMIT_ERRORS.get(status, 'unknown status')})")

    def next_commit(self) -> Commit | None:
        """Pop the oldest commit record the step thread enqueued, or None when none is pending.
        The step pipe (`step_fd`) carries one byte per record."""
        event = _ffi.KelpieStepEvent()
        cap = self.config.max_requests
        advanced = np.empty(cap, dtype=np.uint32)
        dropped = _ffi.u32(0)
        n = self._lib.kelpie_next_commit(
            self._engine_handle(), ctypes.byref(event), _u32p(advanced), cap, ctypes.byref(dropped)
        )
        if n == -1:
            return None
        assert n >= 0, n
        return Commit(_step_event(event), advanced[:n].tolist(), int(dropped.value))

    @property
    def step_fd(self) -> int:
        """Read end of the step-done pipe: the Zig loop writes one byte to it per commit. Block
        on it (`os.read(engine.step_fd, 1)`, `select.select([engine.step_fd], [], [])`, or
        `await trio.lowlevel.wait_readable(engine.step_fd)`) to wake, then drain with
        `next_commit()` until it returns None. Owned by the engine; never close it."""
        return int(self._lib.kelpie_step_pipe_fd(self._engine_handle()))

    def request_stats(self, request_id: int) -> _ffi.KelpieRequestEvent:
        """Per-request timings and counts; complete once poll() reports finished. Includes
        `n_prompt` against `n_gen`, which is where a prefix-cache hit shows up."""
        out = _ffi.KelpieRequestEvent()
        handle = self._engine_handle()
        status = self._lib.kelpie_request_event(handle, request_id, ctypes.byref(out))
        assert status == 0, (status, request_id)
        return out

    def set(self, **knobs: object) -> int:
        """Queue live-config changes (inbox ops); -> the step whose plan applies the last of
        them -- exactly that step."""
        for name, value in knobs.items():
            ceiling = self.batch_ceiling.get(name)
            if ceiling is not None and int(value) > ceiling:  # type: ignore[call-overload]
                raise ValueError(
                    f"{name}={value} is above {ceiling}, the most this engine's programs were "
                    f"built (warmed) for; rebuild with that capacity to serve it")
        applied = 0
        for name, value in knobs.items():
            knob, result = _knob(name, value), _ffi.KelpieSetResult()
            handle = self._engine_handle()
            status = self._lib.kelpie_set(handle, ctypes.byref(knob), ctypes.byref(result))
            if status == _ffi.SUBMIT_NOT_EDGE:
                raise NotEdge("set on a follower rank")
            assert status == 0, (status, name, value)
            applied = int(result.apply_step)
        return applied

    def live_config(self) -> EngineConfig:
        """The live config: the create-time config with the knob fields as last drained."""
        native = _ffi.KelpieConfig()
        self._lib.kelpie_get_config(self._engine_handle(), ctypes.byref(native))
        return replace(
            self.config,
            max_batch_tokens=int(native.max_batch_tokens),
            max_batch_reqs=int(native.max_batch_reqs),
            reserve_ratio=float(native.reserve_ratio),
            order=ORDERS[int(native.order)],
            prefix_cache=bool(native.prefix_cache),
            slab_bytes=int(native.slab_bytes),
            num_slabs=int(native.num_slabs),
        )


def _create(lib: ctypes.CDLL, config: EngineConfig) -> Any:
    """Zig copies the group arrays during kelpie_create; they only need to outlive the call."""
    n = len(config.groups)
    kinds = (_ffi.u32 * n)(*(0 if g.kind == "per_token" else 1 for g in config.groups))
    sizes = (_ffi.u32 * n)(*(g.block_size for g in config.groups))
    windows = (_ffi.u32 * n)(*(g.window for g in config.groups))
    cacheable = (_ffi.u8 * n)(*(int(g.cacheable) for g in config.groups))
    strides = (_ffi.u32 * n)(*(g.stride for g in config.groups))
    # The slab plan, or NULL for the legacy equal-page mode (docs/slab-lcm-ladder.md).
    pages = None
    if config.bytes_per_page:
        assert len(config.bytes_per_page) == n, (config.bytes_per_page, n)
        pages = (_ffi.u32 * n)(*config.bytes_per_page)
    native = _ffi.KelpieConfig(
        max_requests=config.max_requests,
        max_seq_len=config.max_seq_len,
        n_groups=n,
        group_kinds=ctypes.cast(kinds, _ffi.u32_p),
        group_block_sizes=ctypes.cast(sizes, _ffi.u32_p),
        group_windows=ctypes.cast(windows, _ffi.u32_p),
        group_cacheable=ctypes.cast(cacheable, _ffi.u8_p),
        num_blocks=config.num_blocks,
        max_batch_tokens=config.max_batch_tokens,
        max_batch_reqs=config.max_batch_reqs,
        reserve_ratio=config.reserve_ratio,
        order=ORDERS.index(config.order),
        eos_token=config.eos_token,
        prefix_cache=int(config.prefix_cache),
        group_strides=ctypes.cast(strides, _ffi.u32_p),
        overlap=int(config.overlap),
        vocab_words=config.vocab_words,
        max_extra=config.max_extra,
        vocab_size=config.vocab_size,
        group_bytes_per_page=ctypes.cast(pages, _ffi.u32_p) if pages is not None else None,
    )
    handle = lib.kelpie_create(ctypes.byref(native))
    if not handle:
        raise ValueError(f"kelpie_create rejected {config}")
    return handle


class Grammar:
    """A compiled grammar a submit can name (kelpie_register_grammar): `key` identifies it on
    every rank, `compiled_ptr` is an xgrammar CompiledGrammar* from kelpie's own libxgrammar,
    `source` the text a follower would compile it from."""

    def __init__(self, key: int, compiled_ptr: int, source: bytes) -> None:
        assert key != 0, "key 0 means no grammar"
        self.key = key
        self.compiled_ptr = compiled_ptr
        self.source = source


def write_step_out(views: dict[str, np.ndarray], emitted: Emitted | np.ndarray, n_reqs: int) -> None:
    """Copies a step's result into the KelpieStepOut views ([cap, stride] tokens, [cap] n,
    [cap] next_extra): one bulk copy per array. A bare u32[R] is Emitted(tokens)."""
    if not isinstance(emitted, Emitted):
        emitted = Emitted(np.asarray(emitted))
    tokens = np.asarray(emitted.tokens)
    if tokens.ndim == 1:
        tokens = tokens[:, None]
    stride = views["tokens"].shape[1]
    assert tokens.shape[0] == n_reqs and tokens.shape[1] <= stride, (tokens.shape, n_reqs, stride)
    if tokens.dtype.kind not in "iu":
        raise ValueError(f"tokens must be integers, got {tokens.dtype}")
    if tokens.dtype.kind == "i" and (tokens < 0).any():
        raise ValueError("a negative token id cannot be committed")
    n = np.ones(n_reqs, dtype=np.uint32) if emitted.n is None else np.asarray(emitted.n)
    # n beyond the columns given would commit whatever the StepOut held from an earlier step.
    assert n.shape == (n_reqs,) and (n <= tokens.shape[1]).all(), (n, tokens.shape)
    views["tokens"][:n_reqs, : tokens.shape[1]] = tokens
    views["n"][:n_reqs] = n
    views["next_extra"][:n_reqs] = 0 if emitted.next_extra is None else np.asarray(emitted.next_extra)


def _step_event(c: _ffi.KelpieStepEvent) -> StepEvent:
    return StepEvent(
        step=int(c.step),
        n_running=int(c.n_running),
        n_waiting=int(c.n_waiting),
        n_tokens=int(c.n_tokens),
        n_finished=int(c.n_finished),
        kv_used=int(c.kv_used),
        kv_free=int(c.kv_free),
        t_plan_ns=int(c.t_plan_ns),
        t_forward_ns=int(c.t_forward_ns),
        t_commit_ns=int(c.t_commit_ns),
        is_idle=bool(c.is_idle),
        n_preempted=int(c.n_preempted),
        n_extra_rows=int(c.n_extra_rows),
        n_extra_kept=int(c.n_extra_kept),
        n_rejected_full=int(c.n_rejected_full),
        config_hash=int(c.config_hash),
    )


# The live tier's names, in the order the core's Knob union declares them. A name outside this
# set belongs to a higher tier and is changed by a `build()` argument -- `_reject_higher_tier`
# says which, because "unknown knob" would send the reader looking for a typo.
HIGHER_TIER: dict[str, tuple[str, str]] = {
    "max_requests": ("realloc", "build(capacity=Capacity(max_requests=...))"),
    "max_seq_len": ("realloc", "build(capacity=Capacity(max_seq_len=...))"),
    "num_slabs": ("realloc", "build(capacity=Capacity(num_slabs=...))"),
    "kv_blocks": ("realloc", "build(capacity=Capacity(num_slabs=...))"),
    "tokens": ("recapture", "build(buckets=Buckets(tokens=...))"),
    "requests": ("recapture", "build(buckets=Buckets(requests=...))"),
    "device": ("program", "build(device=...)"),
    "dtype": ("program", "build(dtype=...)"),
    "kernels": ("program", "build(kernels=...)"),
    "capture": ("program", "build(capture=...)"),
    "compile": ("program", "build(compile=...)"),
}


def _knob(name: str, value: object) -> _ffi.KelpieKnob:
    if name not in _ffi.KNOB_KINDS:
        tier, where = HIGHER_TIER.get(name, ("", ""))
        if tier:
            raise ValueError(
                f"{name} is {tier} tier, not live: engine.set only takes "
                f"{', '.join(_ffi.KNOB_KINDS)}. Change it with {where}."
            )
    assert name in _ffi.KNOB_KINDS, f"unknown knob {name!r}; knobs: {list(_ffi.KNOB_KINDS)}"
    kind = _ffi.KNOB_KINDS.index(name)
    if name == "reserve_ratio":
        return _ffi.KelpieKnob(kind=kind, u32_value=0, f32_value=float(value))  # type: ignore[arg-type]
    if name == "order":
        return _ffi.KelpieKnob(kind=kind, u32_value=ORDERS.index(value), f32_value=0.0)  # type: ignore[arg-type]
    return _ffi.KelpieKnob(kind=kind, u32_value=int(value), f32_value=0.0)  # type: ignore[arg-type]


def _u32p(arr: np.ndarray) -> Any:
    return arr.ctypes.data_as(_ffi.u32_p)
