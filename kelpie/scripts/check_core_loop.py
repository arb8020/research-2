#!/usr/bin/env python3
"""check_core_loop: the core's plan indices against an exact oracle, no model, runs locally.

A fake model drives the caller-written loop (docs/design-core-option2.md 1(b)) against a real
libkelpie Engine with three groups:

    F  per_token full attention, block 4
    W  per_token sliding window of 8 tokens, block 4, cacheable
    G  per_seq, checkpoint every S = 8, 2 checkpoints kept

and a random caller: prompts drawn from a few shared stems (prefix hits, incl. mid-chunk
checkpoints), random max_new, random cancels, a pool small enough to preempt, random
n in [1, 1 + n_extra] (drafts accepted), drafts that sometimes contain eos (stop mid-block), and
random next_extra in {0, K}.

Oracles, exact, every step:
  KV     Fake F and W pools hold the TOKEN written at each slot. Every real row writes its
         token; then every row at position p reads positions 0..p (W: the last 8) through its
         block table and must see exactly the request's tokens (history + this step's rows).
         When a request ends, its pages not covered by full computed blocks (the only ones the
         prefix cache may hand out again) are POISONED, so reading one later fails.
  State  A fake G pool holds a rolling hash of the tokens a state has consumed. `read` must hold
         hash(tokens[:seq_start]) (ZERO holds hash of nothing); the op writes the hash after tail
         row j into write[j] and after ckpt_row into ckpt. SCRATCH is poisoned by every write
         and must never be read; ZERO must never be written. OWNERSHIP: a read unit must be ZERO
         (seq_start 0), the request's own live unit from its last commit (at that position), or
         a unit last written as the checkpoint at exactly seq_start; a finished or cancelled
         request's live unit is poisoned. Catches every index mistake the lifecycle can make
         (rollback, checkpoint, prefix hit, preemption, slot reuse, use after free).
  Commit A commit carrying NO_TOKEN as a kept token is refused (CommitError) and applies nothing.
  Idle   Whenever nothing is live, only ZERO's slab is in use (no leak).
  Output Every request's polled tokens equal the tokens the caller committed for it, cut at the
         first eos and at max_new.

Inputs are step-boundary ops (docs/design-multigpu.md 2.3): a cancel between plan and commit
lands at the NEXT boundary, so the commit in flight still applies to that request, and it ends
right after (the oracle follows that).

--native (docs/design-multigpu.md section 6 rung 0): the same random caller, but racing the
native Zig loop, whose LaunchFn is the random emitter ([R, 1 + K] tokens, n, next_extra). The
loop runs with a RECORDING rank sync (world 1 with a tap on the seam): every boundary batch,
every commit payload and every plan digest is kept.
--replay (with --native): a second, by-hand engine registered as a FOLLOWER replays the
recording -- the exchange hands it the edge's bytes -- and must reproduce every digest. It also
re-runs every oracle above on the replayed plans, with the truth (prompts, cancels, releases,
committed tokens) decoded from the recorded batches and payloads, and checks each request's
tokens against what the racing caller polled. Occupants are matched by (id, generation): a submit
cancelled before its boundary is dropped from the inbox (B2) and never reaches any rank, so the
caller may have polled an occupant (cancelled, no tokens) that the recording never names.

It refuses to run against a libkelpie older than the kelpie-core sources (a stale lib once gave a
false PASS): the same check `kelpie doctor` runs, `kelpie_engine.doctor.libkelpie_fresh`.

    cd kelpie/kelpie-core && ../scripts/zig build lib
    cd kelpie/kelpie-engine && PYTHONPATH=../.. uv run python ../scripts/check_core_loop.py
    cd kelpie/kelpie-engine && PYTHONPATH=../.. uv run python ../scripts/check_core_loop.py \
        --native --replay --seeds 4 --steps 4000
"""

from __future__ import annotations

import argparse
import ctypes
import os
import struct
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from kelpie_engine import _ffi, doctor
from kelpie_engine.sdk.engine import CommitError, Emitted, Engine, EngineConfig, GroupSpec
from kelpie_engine.sdk.plan import Plan

try:
    from observe import setup_logging, span
except ImportError:  # observe lives at the repo root; PYTHONPATH=../.. from kelpie-engine
    setup_logging = None
    span = None

BLOCK = 4
WIN = 8
STRIDE = 8
N_CHECKPOINTS = 2
K = 3
EOS = 7
VOCAB = 50  # small, so drafts collide with eos and with each other
POISON = -1
MASK64 = (1 << 64) - 1


def fold(state: int, token: int) -> int:
    """The fake recurrent state: a rolling hash of the tokens consumed so far."""
    assert state != POISON, "a state read SCRATCH"
    return (state * 1_000_003 + token + 1) & MASK64


def hash_of(tokens: list[int]) -> int:
    state = 0
    for token in tokens:
        state = fold(state, token)
    return state


def assert_disjoint_writes(plan) -> None:
    """Within one plan, no entry writes a unit or slot that another entry reads or writes: the
    per-row checks above run entries one after another, so an alias whose reader happens to run
    first would otherwise pass."""
    req = plan.requests
    state = next(st for st in req.state if st is not None)
    writes: dict[int, int] = {}
    reads: dict[int, set[int]] = {}
    slots: dict[tuple[int, int], int] = {}
    for r in range(plan.n_reqs):
        n_extra = int(req.n_extra[r])
        mine = [int(u) for u in state.write[r, : 1 + n_extra]]
        if int(state.ckpt[r]) != 0:
            mine.append(int(state.ckpt[r]))
        assert len(set(mine)) == len(mine), f"entry {r} writes a unit twice: {mine}"
        for unit in mine:
            assert unit not in writes, f"entries {writes.get(unit)} and {r} both write unit {unit}"
            writes[unit] = r
        reads.setdefault(int(state.read[r]), set()).add(r)
        q0, q1 = req.rows(r)
        for g in (0, 1):
            for slot in plan.tokens.slot_mapping[g][q0:q1].tolist():
                assert (g, slot) not in slots, f"entries {slots[(g, slot)]} and {r} both write group {g} slot {slot}"
                slots[(g, slot)] = r
    for unit, readers in reads.items():
        writer = writes.get(unit)
        assert writer is None or readers <= {writer}, f"unit {unit} written by {writer}, read by {readers}"


@dataclass
class Live:
    """What the caller knows about one request."""

    prompt: list[int]
    max_new: int
    generated: list[int] = field(default_factory=list)
    polled: list[int] = field(default_factory=list)
    finished: bool = False

    @property
    def history(self) -> list[int]:
        return self.prompt + self.generated


@dataclass
class Counts:
    steps: int = 0
    rows: int = 0
    extra_rows: int = 0
    kept_extra: int = 0
    reads_zero: int = 0
    reads_ckpt: int = 0  # read a unit last written as a checkpoint: a resume from a prefix hit
    ckpts: int = 0
    finished: int = 0
    stopped_mid_block: int = 0
    cancelled: int = 0
    preempted: int = 0
    prefix_hit_tokens: int = 0
    cancelled_in_flight: int = 0
    quiescent_checks: int = 0
    poisoned_units: int = 0
    poisoned_pages: int = 0
    refused_commits: int = 0
    dropped_submits: int = 0  # replay only: cancelled before their boundary, never applied (B2)


class Oracle:
    def __init__(self, zero: int) -> None:
        self.kv: tuple[dict[int, int], dict[int, int]] = ({}, {})  # F / W slot -> token
        self.state: dict[int, int] = {zero: 0}  # G unit -> hash
        self.zero = zero
        self.last_written_as: dict[int, str] = {}  # unit -> "write" / "ckpt"
        self.ckpt_pos: dict[int, int] = {}  # unit last written as a checkpoint -> its position
        self.live: dict[int, tuple[int, int]] = {}  # rid -> (live unit, n_computed it holds)
        self.pending: dict[int, tuple[int, list[int], list[int], list[int], int]] = {}
        # rid -> its entry in the plan committed LAST; only then are its tables still its own
        # (a preemption happens at plan time, so a request absent from the last plan may have
        # lost its pages to someone else).
        self.last: dict[int, tuple[int, list[int], list[int], list[int], int]] = {}

    def check_step(self, plan: Plan, live: dict[int, Live], drafts: dict[int, list[int]], counts: Counts) -> None:
        req = plan.requests
        g_state = req.state[2]
        assert req.state[0] is None and req.state[1] is None and g_state is not None
        assert g_state.zero == self.zero
        self.pending = {}
        for r in range(plan.n_reqs):
            rid = int(req.req_ids[r])
            q0, q1 = req.rows(r)
            n_extra = int(req.n_extra[r])
            n_work = q1 - q0 - n_extra
            seq_start = int(req.seq_start[r])
            history = live[rid].history
            assert n_work >= 1 and n_extra in (0, K), (n_work, n_extra)
            if n_extra:
                assert n_work == 1 and seq_start + 1 == len(history), "extra rows on a non-decode entry"
            emits = seq_start + n_work == len(history)
            assert bool(req.emits[r]) == emits, (rid, seq_start, n_work, len(history))
            assert int(req.seq_lens[r]) == seq_start + n_work + n_extra
            rows = history[seq_start : seq_start + n_work] + drafts.get(rid, [])[:n_extra]
            assert len(rows) == n_work + n_extra
            positions = plan.tokens.positions[q0:q1].tolist()
            assert positions == list(range(seq_start, seq_start + len(rows))), positions
            ids = plan.tokens.input_ids[q0:q1].tolist()
            assert ids[:n_work] == rows[:n_work], (ids, rows)
            assert all(i == _ffi.NO_TOKEN for i in ids[n_work:]), ids
            counts.rows += len(rows)
            counts.extra_rows += n_extra
            # F and W: write every row, then every row reads its prefix (W: the window) through
            # its block table.
            seen = history[:seq_start] + rows
            tables = [req.block_tables[g][r].tolist() for g in (0, 1)]
            for g in (0, 1):
                slots = plan.tokens.slot_mapping[g]
                for i, token in enumerate(rows):
                    slot = int(slots[q0 + i])
                    assert slot // BLOCK != 0, f"group {g}: real row on the null block: {slot}"
                    self.kv[g][slot] = token
                for i in range(len(rows)):
                    p = seq_start + i
                    first = 0 if g == 0 else max(0, p - WIN + 1)
                    for pos in range(first, p + 1):
                        page = tables[g][pos // BLOCK]
                        assert page != 0, f"req {rid}: group {g} position {pos} has no block"
                        got = self.kv[g].get(page * BLOCK + pos % BLOCK)
                        assert got == seen[pos], f"req {rid}: group {g} KV at {pos} is {got}, want {seen[pos]}"
            # G: ownership, read, fold every row, write the tail rows and the checkpoint.
            read = int(g_state.read[r])
            write = g_state.write[r].tolist()
            ckpt, ckpt_row = int(g_state.ckpt[r]), int(g_state.ckpt_row[r])
            assert read != _ffi.UNIT_SCRATCH
            if read == self.zero:
                assert seq_start == 0, f"req {rid} reads ZERO at seq_start {seq_start}"
            elif self.live.get(rid, (None, None))[0] == read:
                assert self.live[rid][1] == seq_start, f"req {rid} reads its live unit at the wrong position"
            else:
                assert self.ckpt_pos.get(read) == seq_start, (
                    f"req {rid} reads unit {read}: not ZERO, not its live unit, not a checkpoint at {seq_start}")
            assert self.zero not in write and ckpt != self.zero, "ZERO is a write target"
            assert all(w == _ffi.UNIT_SCRATCH for w in write[1 + n_extra :]), write
            assert all(w != _ffi.UNIT_SCRATCH for w in write[: 1 + n_extra]), write
            assert (ckpt == _ffi.UNIT_SCRATCH) == (ckpt_row == _ffi.NO_ROW), (ckpt, ckpt_row)
            if ckpt_row != _ffi.NO_ROW:
                assert ckpt_row < n_work, "checkpoint inside the extra rows"
                assert (seq_start + ckpt_row + 1) % STRIDE == 0, (seq_start, ckpt_row)
            state = self.state.get(read, POISON)
            assert state == hash_of(history[:seq_start]), f"req {rid}: read unit {read} holds the wrong state"
            counts.reads_zero += read == self.zero
            counts.reads_ckpt += self.last_written_as.get(read) == "ckpt"
            for i, token in enumerate(rows):
                state = fold(state, token)
                j = i - (n_work - 1)
                if 0 <= j <= n_extra:
                    self.state[write[j]] = state
                    self.last_written_as[write[j]] = "write"
                    self.ckpt_pos.pop(write[j], None)
                if i == ckpt_row:
                    self.state[ckpt] = state
                    self.last_written_as[ckpt] = "ckpt"
                    self.ckpt_pos[ckpt] = seq_start + i + 1
                    counts.ckpts += 1
            self.state[_ffi.UNIT_SCRATCH] = POISON
            assert self.state[self.zero] == 0, "ZERO was written"
            self.pending[rid] = (seq_start + n_work, write[: 1 + n_extra], tables[0], tables[1], n_extra)

    def step_done(self) -> None:
        self.last = self.pending

    def forget(self, rid: int) -> None:
        """A new occupant took slot rid: the previous one's entries are not its own (ended()
        would otherwise poison pages of an entry the new request was never planned into)."""
        self.last.pop(rid, None)
        self.pending.pop(rid, None)
        self.live.pop(rid, None)

    def committed(self, rid: int, kept: int) -> None:
        """The commit kept tail rows 0..kept-1 of rid's entry: its live unit is write[kept-1]."""
        n_hist_end, writes, _, _, _ = self.pending[rid]
        self.live[rid] = (writes[kept - 1], n_hist_end + kept - 1)

    def ended(self, rid: int, n_computed: int | None, counts: Counts, *, in_flight: bool = False) -> None:
        """rid finished or was cancelled: poison its live unit and its pages the prefix cache
        cannot hand out again (anything not inside a full computed block). `n_computed` None =
        what its last commit left; `in_flight` = cancelled between plan and commit."""
        unit, pos = self.live.pop(rid, (None, None))
        entry = (self.pending if in_flight else self.last).get(rid)
        if entry is None:
            return  # not in the last plan: it may have been preempted, its units are not its own
        if unit is not None and self.last_written_as.get(unit) == "write":
            self.state[unit] = POISON
            counts.poisoned_units += 1
        if n_computed is None:
            n_computed = pos if pos is not None else 0
        for g, table in ((0, entry[2]), (1, entry[3])):
            for b, page in enumerate(table):
                if page == 0 or (b + 1) * BLOCK <= n_computed:
                    continue
                for off in range(BLOCK):
                    self.kv[g][page * BLOCK + off] = POISON
                counts.poisoned_pages += 1


def engine_config(num_blocks: int) -> EngineConfig:
    return EngineConfig(
        max_requests=8,
        max_seq_len=96,
        num_blocks=num_blocks,
        max_batch_tokens=24,
        max_batch_reqs=8,
        groups=(
            GroupSpec("per_token", BLOCK),
            GroupSpec("per_token", BLOCK, window=WIN, cacheable=True),
            GroupSpec("per_seq", 0, window=N_CHECKPOINTS, cacheable=True, stride=STRIDE),
        ),
        eos_token=EOS,
        vocab_words=0,
        prefix_cache=True,
        max_extra=K,
        vocab_size=VOCAB,
    )


def quiescence_check(engine: Engine, counts: Counts) -> None:
    ev = _ffi.KelpieStepEvent()
    engine._lib.kelpie_step_event(engine._engine_handle(), ctypes.byref(ev))  # noqa: SLF001
    counts.quiescent_checks += 1
    assert ev.kv_used <= 1, f"leak at quiescence: kv_used={ev.kv_used} kv_free={ev.kv_free}"


def exercised(counts: Counts) -> bool:
    return all(value > 0 for value in (
        counts.ckpts, counts.reads_ckpt, counts.reads_zero, counts.kept_extra, counts.preempted,
        counts.cancelled, counts.cancelled_in_flight, counts.stopped_mid_block,
        counts.prefix_hit_tokens, counts.quiescent_checks, counts.poisoned_units,
        counts.poisoned_pages, counts.refused_commits))


def by_hand(seed: int, steps: int, num_blocks: int) -> tuple[bool, dict[str, int]]:  # noqa: PLR0915
    """The caller-written loop against the oracle (the original check)."""
    rng = np.random.default_rng(seed)
    config = engine_config(num_blocks)
    engine = Engine(config)
    stems = [[int(t) for t in rng.integers(10, VOCAB, size=40)] for _ in range(3)]
    live: dict[int, Live] = {}
    counts = Counts()
    oracle: Oracle | None = None

    def submit() -> None:
        stem = stems[int(rng.integers(len(stems)))]
        n_prompt = int(rng.integers(1, 40))
        prompt = stem[:n_prompt] if rng.random() < 0.7 else [int(t) for t in rng.integers(10, VOCAB, size=n_prompt)]
        max_new = int(rng.integers(0, 40))
        rid = engine.submit(prompt, max_new_tokens=max_new)
        live[rid] = Live(prompt, max_new)
        if oracle is not None:
            oracle.forget(rid)

    for _ in range(steps):
        while len(live) < config.max_requests and (_ // 200) % 2 == 0 and rng.random() < 0.3:
            submit()
        if live and rng.random() < 0.02:
            rid = int(rng.choice(list(live)))
            engine.cancel(rid)
            if oracle is not None:
                oracle.ended(rid, None, counts)
            del live[rid]
            counts.cancelled += 1
        plan = engine.plan()
        counts.steps += 1
        if plan is None:
            engine.raise_error()  # a stall would be a core bug here
            assert all(v.finished for v in live.values()), "idle with work pending"
            if not live:
                quiescence_check(engine, counts)
            continue
        if oracle is None:
            oracle = Oracle(plan.requests.state[2].zero)
        drafts = {}
        for r in range(plan.n_reqs):
            if int(plan.requests.n_extra[r]):
                rid = int(plan.requests.req_ids[r])
                drafts[rid] = [int(t) for t in rng.integers(0, VOCAB, size=K)]
        assert_disjoint_writes(plan)
        oracle.check_step(plan, live, drafts, counts)
        n_real = plan.n_reqs
        tokens = np.zeros((n_real, 1 + K), dtype=np.uint32)
        n = np.ones(n_real, dtype=np.uint32)
        next_extra = np.where(rng.random(n_real) < 0.8, K, 0).astype(np.uint32)
        for r in range(n_real):
            rid = int(plan.requests.req_ids[r])
            n_extra = int(plan.requests.n_extra[r])
            n[r] = 1 + int(rng.integers(0, n_extra + 1))
            tokens[r, : n[r] - 1] = drafts.get(rid, [])[: n[r] - 1]
            tokens[r, n[r] - 1] = int(rng.integers(0, VOCAB))
        # A cancel between plan and commit: an op for the next boundary. The commit in flight
        # still applies to the victim; it ends right after (below).
        victim = None
        if plan.n_reqs and rng.random() < 0.05:
            candidate = int(plan.requests.req_ids[int(rng.integers(plan.n_reqs))])
            if candidate in live:
                engine.cancel(candidate)
                victim = candidate
                counts.cancelled_in_flight += 1
        emitting = set(plan.emitting.tolist())
        rids = [int(x) for x in plan.requests.req_ids[:n_real]]
        if rng.random() < 0.01:
            bad = tokens.copy()
            bad[0, 0] = _ffi.NO_TOKEN
            try:
                engine.commit(bad, n, next_extra)
            except CommitError:
                counts.refused_commits += 1
            else:
                raise AssertionError("a commit keeping NO_TOKEN was applied")
        engine.commit(Emitted(tokens, n, next_extra))
        oracle.step_done()
        for r, rid in enumerate(rids):
            if rid not in live:
                continue
            if r not in emitting:
                oracle.committed(rid, 1)
                continue
            req = live[rid]
            kept = committed_tokens(tokens[r, : n[r]].tolist(), req, counts)
            oracle.committed(rid, len(kept))
            req.generated += kept
            if kept[-1] == EOS or len(req.generated) >= max(1, req.max_new):
                req.finished = True
        if victim is not None:
            oracle.ended(victim, None, counts)
            del live[victim]
        for rid in list(live):
            poll = engine.poll(rid)
            live[rid].polled += poll.new_tokens
            assert live[rid].polled == live[rid].generated[: len(live[rid].polled)], rid
            if poll.finished:
                req = live.pop(rid)
                assert req.finished and req.polled == req.generated, (rid, req)
                oracle.ended(rid, len(req.history) - 1, counts)
                counts.finished += 1
        event = _ffi.KelpieStepEvent()
        engine._lib.kelpie_step_event(engine._engine_handle(), ctypes.byref(event))  # noqa: SLF001
        counts.preempted += event.n_preempted
        counts.prefix_hit_tokens += event.prefix_hit_tokens

    engine.close()
    return exercised(counts), dict(vars(counts))


def committed_tokens(tokens: list[int], req: Live, counts: Counts) -> list[int]:
    """What the core keeps of one entry's committed tokens: cut at the first eos, and at
    max_new (at least one token)."""
    room = max(1, req.max_new - len(req.generated))
    kept = list(tokens)
    if EOS in kept:
        cut = kept.index(EOS) + 1
        counts.stopped_mid_block += cut < len(kept)
        kept = kept[:cut]
    kept = kept[:room]
    counts.kept_extra += len(kept) - 1
    return kept


# ---- native: callers race the Zig loop; recorded through the rank-sync seam -------------------


class Recording:
    """World 1 with a tap on the seam: the exchange is the identity and keeps every message
    (boundary batches and commit payloads, in call order); agree keeps every digest."""

    def __init__(self) -> None:
        self.msgs: list[bytes] = []
        self.digests: list[int] = []

    def exchange(self, mine: bytes, cap: int) -> bytes:
        assert len(mine) <= cap
        self.msgs.append(mine)
        return mine

    def agree(self, digest: int) -> bool:
        self.digests.append(digest)
        return True


class Emitter:
    """The random emitter as a LaunchFn (runs on the Zig step thread): per real entry, draft-like
    extra tokens, a random accepted count, sometimes eos, next_extra K or 0."""

    def __init__(self, seed: int) -> None:
        self.rng = np.random.default_rng(seed)
        self.steps = 0

    def __call__(self, plan: Plan) -> Emitted:
        n_real = plan.n_reqs
        tokens = self.rng.integers(0, VOCAB, size=(n_real, 1 + K)).astype(np.uint32)
        n = np.array([1 + int(self.rng.integers(0, int(plan.requests.n_extra[r]) + 1)) for r in range(n_real)],
                     dtype=np.uint32)
        next_extra = np.where(self.rng.random(n_real) < 0.8, K, 0).astype(np.uint32)
        self.steps += 1
        return Emitted(tokens, n, next_extra)


@dataclass
class Polled:
    """What the racing caller saw of one occupant (id, generation)."""
    tokens: list[int] = field(default_factory=list)
    reason: str | None = None  # the finish reason, once a poll read finished


def native(seed: int, steps: int, num_blocks: int) -> tuple[Recording, dict[tuple[int, int], Polled], dict[str, int]]:
    """Random callers (this thread) race the native loop. -> the recording, and per occupant
    (request id, generation) what the caller polled."""
    rng = np.random.default_rng(seed)
    config = engine_config(num_blocks)
    engine = Engine(config)
    rec = Recording()
    engine.register_sync(rec.exchange, rec.agree, edge=True)
    emitter = Emitter(seed + 1)
    engine.start_loop(emitter)
    stems = [[int(t) for t in rng.integers(10, VOCAB, size=40)] for _ in range(3)]
    polled: dict[tuple[int, int], Polled] = {}
    live: dict[int, int] = {}  # rid -> the generation the caller holds
    stats = {"submits": 0, "cancels": 0, "stale_cancels": 0, "full": 0, "knobs": 0}
    t0 = time.monotonic()
    while emitter.steps < steps:
        if len(live) < config.max_requests and rng.random() < 0.3:
            stem = stems[int(rng.integers(len(stems)))]
            n_prompt = int(rng.integers(1, 40))
            prompt = stem[:n_prompt] if rng.random() < 0.7 else [int(t) for t in rng.integers(10, VOCAB, size=n_prompt)]
            try:
                rid = engine.submit(prompt, max_new_tokens=int(rng.integers(0, 40)))
            except Exception as e:  # noqa: BLE001 -- Full is expected under the race
                assert type(e).__name__ == "Full", e
                stats["full"] += 1
            else:
                live[rid] = engine.generation(rid)
                assert (rid, live[rid]) not in polled, (rid, live[rid])
                polled[rid, live[rid]] = Polled()
                stats["submits"] += 1
                if rng.random() < 0.05:
                    engine.cancel(rid, engine.generation(rid) - 1)  # stale: must be a no-op
                    stats["stale_cancels"] += 1
        if live and rng.random() < 0.03:
            engine.cancel(int(rng.choice(sorted(live))))
            stats["cancels"] += 1
        if rng.random() < 0.01:
            engine.set(max_batch_tokens=int(rng.integers(12, 25)))
            stats["knobs"] += 1
        for rid in sorted(live):
            poll_into(engine, rid, live, polled)
        engine.raise_error()
        if rng.random() < 0.3:
            time.sleep(0.0002)
        assert time.monotonic() - t0 < 600, "native run timed out"
    while live:  # let everything finish (cancel what is left), then one more boundary releases
        for rid in sorted(live):
            engine.cancel(rid)
            poll_into(engine, rid, live, polled)
    engine.wake()
    time.sleep(0.05)
    engine.close()  # the edge's stop batch is the recording's last message
    return rec, polled, stats


def poll_into(engine: Engine, rid: int, live: dict[int, int], polled: dict[tuple[int, int], Polled]) -> None:
    poll = engine.poll(rid)
    seen = polled[rid, live[rid]]
    seen.tokens += poll.new_tokens
    if poll.finished:
        seen.reason = poll.reason
        del live[rid]


def u32s(b: bytes) -> list[int]:
    return list(struct.unpack(f"<{len(b) // 4}I", b))


HEADER_WORDS = 12
WIRE_VERSION = 2  # kelpie-core/src/inputs.zig wire_version: 2 = submit carries top_k
SUBMIT_FIXED = 15  # inputs.zig submit_fixed: kind + 13 fields + top_k (the last fixed word)


def decode_batch(b: bytes) -> list[tuple]:
    """The wire format of kelpie-core/src/inputs.zig: a 48-byte header, then ops as u32 words."""
    w = u32s(b)
    version, n_ops, n_words = w[0], w[1], w[2]
    assert version == WIRE_VERSION and n_words == len(w) - HEADER_WORDS, (version, n_words, len(w))
    ops, pos = [], HEADER_WORDS
    for _ in range(n_ops):
        kind = w[pos]
        if kind == 1:  # submit
            rid, gen, n_prompt, max_new, n_stop = w[pos + 1], w[pos + 2], w[pos + 3], w[pos + 4], w[pos + 9]
            body = pos + SUBMIT_FIXED
            ops.append(("submit", rid, gen, max_new, w[body + n_stop: body + n_stop + n_prompt]))
            pos = body + n_stop + n_prompt
        elif kind in (2, 3):
            ops.append(("cancel" if kind == 2 else "release", w[pos + 1], w[pos + 2]))
            pos += 3
        elif kind == 4:
            ops.append(("knob",))
            pos += 4
        elif kind == 5:
            ops.append(("swap",))
            pos += 4
        elif kind == 6:
            ops.append(("grammar_prepare",))
            pos += 4 + (w[pos + 3] + 3) // 4
        else:
            raise AssertionError(f"bad op kind {kind}")
    assert pos == len(w), (pos, len(w))
    return ops


def decode_payload(b: bytes) -> list[tuple[list[int], int]]:
    """A commit payload (c_api.zig agreePayload): n, then per entry count, next_extra, tokens."""
    w = u32s(b)
    out, pos = [], 1
    for _ in range(w[0]):
        count, extra = w[pos], w[pos + 1]
        out.append((w[pos + 2: pos + 2 + count], extra))
        pos += 2 + count
    assert pos == len(w)
    return out


class Replay:
    """A follower's rank sync fed the recording: the exchange hands back the edge's bytes in
    order; agree compares digests."""

    def __init__(self, rec: Recording) -> None:
        self.rec = rec
        self.next_msg = 0
        self.next_digest = 0
        self.mismatch: int | None = None

    def exchange(self, _mine: bytes, cap: int) -> bytes:
        msg = self.rec.msgs[self.next_msg]
        self.next_msg += 1
        assert len(msg) <= cap
        return msg

    def agree(self, digest: int) -> bool:
        want = self.rec.digests[self.next_digest]
        self.next_digest += 1
        if digest != want and self.mismatch is None:
            self.mismatch = self.next_digest
        return digest == want


def replay(rec: Recording, polled: dict[tuple[int, int], Polled], num_blocks: int) -> tuple[bool, dict[str, int]]:  # noqa: PLR0912, PLR0915
    """A by-hand follower replays the recording: every digest must match, and every oracle runs
    on the replayed plans with the truth decoded from the recorded bytes."""
    config = engine_config(num_blocks)
    engine = Engine(config)
    rp = Replay(rec)
    engine.register_sync(rp.exchange, rp.agree, edge=False)
    counts = Counts()
    live: dict[int, Live] = {}
    gens: dict[int, int] = {}
    outputs: dict[tuple[int, int], list[int]] = {}  # (rid, gen) -> its committed tokens
    oracle: Oracle | None = None
    n_plans = 0
    while True:
        batch = rec.msgs[rp.next_msg]
        try:
            plan = engine.plan()
        except StopIteration:
            break
        n_plans += 1
        # The boundary just applied `batch`: follow it, in op order.
        for op in decode_batch(batch):
            if op[0] == "submit":
                _, rid, gen, max_new, prompt = op
                assert rid not in live, f"submit into live slot {rid}"
                live[rid] = Live(list(prompt), max_new)
                if oracle is not None:
                    oracle.forget(rid)
                gens[rid] = gen
                assert (rid, gen) not in outputs, f"submit of ({rid}, {gen}) twice"
                outputs[rid, gen] = []
            elif op[0] == "cancel":
                _, rid, gen = op
                if gens.get(rid) != gen or rid not in live:
                    continue  # stale, or the request already ended
                req = live[rid]
                if not req.finished:
                    if oracle is not None:
                        oracle.ended(rid, None, counts)
                    counts.cancelled += 1
                outputs[rid, gen] = list(req.generated)
                del live[rid]
            elif op[0] == "release":
                _, rid, gen = op
                if gens.get(rid) == gen and rid in live:
                    req = live.pop(rid)
                    assert req.finished, f"release of unfinished {rid}"
                    outputs[rid, gen] = list(req.generated)
        if plan is None:
            if rp.mismatch is not None:
                break
            assert all(v.finished for v in live.values()), "idle with work pending"
            if not live:
                quiescence_check(engine, counts)
            continue
        if oracle is None:
            oracle = Oracle(plan.requests.state[2].zero)
        payload = decode_payload(rec.msgs[rp.next_msg])
        assert len(payload) == plan.n_reqs
        drafts = {int(plan.requests.req_ids[r]): list(payload[r][0][:-1]) + [0] * K for r in range(plan.n_reqs)
                  if int(plan.requests.n_extra[r])}
        assert_disjoint_writes(plan)
        oracle.check_step(plan, live, drafts, counts)
        emitting = set(plan.emitting.tolist())
        rids = [int(x) for x in plan.requests.req_ids[: plan.n_reqs]]
        engine.commit(None)  # the edge's payload commits
        oracle.step_done()
        for r, rid in enumerate(rids):
            if rid not in live or live[rid].finished:
                continue
            if r not in emitting:
                oracle.committed(rid, 1)
                continue
            req = live[rid]
            kept = committed_tokens(payload[r][0], req, counts)
            oracle.committed(rid, len(kept))
            req.generated += kept
            if kept[-1] == EOS or len(req.generated) >= max(1, req.max_new):
                req.finished = True
                oracle.ended(rid, len(req.history) - 1, counts)
                counts.finished += 1
        event = _ffi.KelpieStepEvent()
        engine._lib.kelpie_step_event(engine._engine_handle(), ctypes.byref(event))  # noqa: SLF001
        counts.preempted += event.n_preempted
        counts.prefix_hit_tokens += event.prefix_hit_tokens
        counts.steps += 1
    engine.close()
    assert rp.mismatch is None, f"digest mismatch at agreement {rp.mismatch}"
    assert rp.next_digest == len(rec.digests), (rp.next_digest, len(rec.digests))
    assert rp.next_msg == len(rec.msgs), (rp.next_msg, len(rec.msgs))
    # What the racing caller polled is exactly what the replay committed, occupant by occupant,
    # matched by (id, generation) (a cancelled request's poll may stop early: cancel reports at
    # once). Every occupant the recording names is one the caller submitted. One it does not
    # name had its submit cancelled before its boundary (B2 drops the op): cancelled, no tokens.
    assert set(outputs) <= set(polled), sorted(set(outputs) - set(polled))
    for key, seen in polled.items():
        if key not in outputs:
            assert seen.tokens == [] and seen.reason == "cancelled", (key, seen)
            counts.dropped_submits += 1
            continue
        want = outputs[key]
        assert seen.tokens == want[: len(seen.tokens)], (key, seen.tokens, want)
    counts.cancelled_in_flight = max(counts.cancelled_in_flight, 1)  # not a mode of this path
    counts.refused_commits = max(counts.refused_commits, 1)  # ditto: the loop panics on a bad payload
    summary = dict(vars(counts))
    summary["plans"] = n_plans
    summary["digests"] = len(rec.digests)
    return exercised(counts), summary


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--steps", type=int, default=4000)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--seeds", type=int, default=1, help="run seeds seed .. seed + seeds - 1")
    ap.add_argument("--num-blocks", type=int, default=72, help="small enough to preempt")
    ap.add_argument("--native", action="store_true", help="race the native Zig loop, recorded")
    ap.add_argument("--replay", action="store_true", help="with --native: a by-hand follower replays it")
    args = ap.parse_args()
    assert not args.replay or args.native, "--replay replays a --native recording"
    lib = Path(os.environ.get("KELPIE_LIB") or _ffi.default_lib_path())
    fresh = doctor.libkelpie_fresh(lib, doctor.core_dir())
    if fresh.status is not doctor.Status.PASS:
        print(f"REFUSED: {fresh.detail}; fix: {fresh.fix}", file=sys.stderr, flush=True)
        return 2
    if setup_logging is not None:
        setup_logging()
    worst = 0
    for seed in range(args.seed, args.seed + args.seeds):
        if args.native:
            rec, polled, stats = native(seed, args.steps, args.num_blocks)
            ok, summary = True, {**stats, "msgs": len(rec.msgs), "digests": len(rec.digests)}
            if args.replay:
                ok, replayed = replay(rec, polled, args.num_blocks)
                summary.update(replayed)
            label = "native+replay" if args.replay else "native"
        else:
            ok, summary = by_hand(seed, args.steps, args.num_blocks)
            label = "by hand"
        if span is not None:
            with span("check_core_loop", attributes={"seed": seed, "mode": label, "ok": ok, **summary}):
                pass
        print(("PASS " if ok else "FAIL (a path was never exercised) ") + f"seed={seed} {label} "
              + " ".join(f"{k}={v}" for k, v in summary.items()), flush=True)
        worst = worst or (0 if ok else 1)
    return worst


if __name__ == "__main__":
    sys.exit(main())
