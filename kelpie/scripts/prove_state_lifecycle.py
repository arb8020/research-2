#!/usr/bin/env python3
"""Prove the per_seq state lifecycle end to end: toy_hybrid through build / alloc_kv / the core.

A hybrid model (one attention layer on a per_token group, one gated recurrent layer on a per_seq
group checkpointing every S = 8, 2 checkpoints kept) runs the caller-written loop
(docs/design-core-option2.md 1(b)) under a random caller, for K in {0, 3}:

  - prompts from a few shared stems (prefix hits, including on checkpoints written mid-chunk:
    the token budget is small, so prefills are chunked and cross boundaries mid-chunk);
  - a pool small enough to force preemption (and recompute from a checkpoint or from ZERO);
  - random cancels (slot reuse);
  - K = 3: an ORACLE drafter -- the dense model's own greedy continuation -- corrupted at seeded
    positions, so every acceptance length 0..3 happens; eos inside a block and max_new mid-block
    cut the commit.

Asserted exactly (fp64, no tolerance), every step:
  - every tail-row logit equals a dense from-scratch forward over the same tokens;
  - ZERO is still all zeros; SCRATCH is NaN-poisoned before each step (a read of it would put
    NaN into the logits and fail the equality);
  - every request's output equals the dense model's greedy decode of its prompt (so K = 3 and
    K = 0 agree, and a request served from a prefix hit equals the same prompt served cold).

Each K builds in its own process (`kernels.bind` runs once per process): a hidden `--phase k`
child runs one K and hands its counts back as JSON (scripts/_fresh.py).

No model runs on the laptop (kelpie/CLAUDE.md): run it on a CPU sandbox,
    uv run --frozen --project box box run \\
        --gpu A10G --volume kelpie-a1 -- 'python -m scripts.prove_state_lifecycle --device cpu'
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field

import numpy as np
import torch
from scripts import _fresh

try:
    from observe import setup_logging, span
except ImportError:
    setup_logging = None
    span = None

K_VALUES = (0, 3)
STEP_KV_AFTER: list = [None]


def assert_disjoint_writes(plan) -> None:
    """Within one plan, no entry writes a unit or slot that another entry reads or writes: the
    per-row checks above run entries one after another, so an alias whose reader happens to run
    first would otherwise pass."""
    req = plan.requests
    state = next(st for st in req.state if st is not None)
    writes: dict[int, int] = {}
    reads: dict[int, set[int]] = {}
    slots: dict[int, int] = {}
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
        for slot in plan.tokens.slot_mapping[0][q0:q1].tolist():
            assert slot not in slots, f"entries {slots[slot]} and {r} both write slot {slot}"
            slots[slot] = r
    for unit, readers in reads.items():
        writer = writes.get(unit)
        assert writer is None or readers <= {writer}, f"unit {unit} written by {writer}, read by {readers}"


@dataclass
class Live:
    prompt: list[int]
    max_new: int
    stops: tuple[int, ...]  # eos plus this request's stop tokens
    dense: object  # toy_hybrid.Dense over prompt + generated
    generated: list[int] = field(default_factory=list)
    polled: list[int] = field(default_factory=list)
    finished: bool = False

    @property
    def history(self) -> list[int]:
        return self.prompt + self.generated


@dataclass
class Counts:
    steps: int = 0
    entries: int = 0
    tail_logits_checked: int = 0
    extra_rows: int = 0
    kept_extra: int = 0
    ckpts_written: int = 0
    resumed_from_ckpt: int = 0  # read a unit last written as a checkpoint
    read_zero: int = 0
    mid_chunk_ckpts: int = 0  # checkpoint row not the entry's last history row
    preempted: int = 0
    prefix_hit_tokens: int = 0
    cancelled: int = 0
    finished: int = 0
    stopped_mid_block: int = 0
    capped_mid_block: int = 0


def greedy_reference(toy, weights, config, prompt: list[int], max_new: int, stops: tuple[int, ...]) -> list[int]:
    """What any correct engine must output: dense greedy, cut at a stop token and max_new (>= 1)."""
    dense = toy.Dense(weights, config).extend(prompt)
    out: list[int] = []
    while True:
        token = int(dense.logits[-1].argmax())
        out.append(token)
        if token in stops or len(out) >= max(1, max_new):
            return out
        dense.extend([token])


def diagnose(toy, weights, config, plan, r, j, position, history, read_state, kv_cache, head: str) -> str:
    """Which half is wrong: the state the entry read, or the attention cache it attended to."""
    req = plan.requests
    seq_start = int(req.seq_start[r])
    q0, q1 = req.rows(r)
    dense = toy.Dense(weights, config).extend(history[:seq_start])
    lines = [head,
             f"  entry: seq_start {seq_start} rows {q1 - q0} n_extra {int(req.n_extra[r])} emits {int(req.emits[r])} "
             f"kind {int(req.kinds[r])} history {len(history)} input_ids {plan.tokens.input_ids[q0:q1].tolist()} "
             f"positions {plan.tokens.positions[q0:q1].tolist()}",
             f"  state: read {int(req.state[1].read[r])} zero {req.state[1].zero} write {req.state[1].write[r].tolist()} "
             f"ckpt {int(req.state[1].ckpt[r])}@row{int(req.state[1].ckpt_row[r])}",
             f"  read state == dense state after {seq_start} tokens: "
             f"{torch.equal(read_state.view(config.hidden, config.hidden), dense.state)} "
             f"(max |diff| {(read_state.view(config.hidden, config.hidden) - dense.state).abs().max().item():.3e})"]
    table = req.block_tables[0][r].tolist()
    block = kv_cache.shape[2]
    bad = [p for p in range(seq_start)
           if not torch.equal(kv_cache[table[p // block], 0, p % block, 0], dense.keys[p])]
    lines.append(f"  cached keys wrong at positions {bad[:16]} (table {table[:8]}, input history {history[:seq_start + 2]})")
    bad_v = [p for p in range(seq_start)
             if not torch.equal(kv_cache[table[p // block], 1, p % block, 0], dense.values[p])]
    lines.append(f"  cached values wrong at positions {bad_v[:16]}")
    after = STEP_KV_AFTER[0]
    full = toy.Dense(weights, config).extend(history[: seq_start + (q1 - q0)])
    for p in range(seq_start, seq_start + (q1 - q0)):
        page = table[p // block]
        written = after[page, 0, p % block, 0]
        matches = [t for t in range(config.vocab) if torch.equal(written, torch.mv(weights.wk, weights.embed[t]))]
        lines.append(f"  pos {p}: written key is token {matches} (norm {written.norm().item():.4f}); slot page {page}")
        lines.append(f"  pos {p}: key after forward == dense {torch.equal(after[page, 0, p % block, 0], full.keys[p])}, "
                     f"value == dense {torch.equal(after[page, 1, p % block, 0], full.values[p])}")
    lines.append(f"  dense logits at {position} vs a fresh dense over history: "
                 f"{torch.equal(full.logits[position], toy.dense_logits(weights, config, history)[position])}")
    slots = plan.tokens.slot_mapping[0]
    for other in range(plan.n_reqs):
        o0, o1 = req.rows(other)
        lines.append(f"  entry {other}: req {int(req.req_ids[other])} seq_start {int(req.seq_start[other])} "
                     f"rows {o1 - o0} slot pages {sorted({int(x) // block for x in slots[o0:o1]})} "
                     f"table {req.block_tables[0][other][:6].tolist()} read {int(req.state[1].read[other])} "
                     f"write {req.state[1].write[other].tolist()} ckpt {int(req.state[1].ckpt[other])}")
    return "\n".join(lines)


def run_k(toy, k: int, args: argparse.Namespace) -> Counts:  # noqa: C901, PLR0912, PLR0915
    from kelpie_engine import _ffi
    from kelpie_models.sdk.decide import decide, draw_of
    from kelpie_models.sdk.device import to_device
    from kelpie_models.sdk.run import build
    from kelpie_models.sdk.tiers import Capacity

    rng = np.random.default_rng(args.seed + k)
    engine, step = build(toy, device=args.device, capture=False, max_extra=k,
                         capacity=Capacity(max_requests=6, max_seq_len=96, num_slabs=args.num_slabs))
    engine.set(max_batch_tokens=args.max_batch_tokens)
    weights, config = step.weights, step.config
    units = step.kv[1][0]  # [units, 1, H * H]
    stems = [[int(t) for t in rng.integers(2, config.vocab, size=40)] for _ in range(3)]
    live: dict[int, Live] = {}
    reference: dict[tuple, list[int]] = {}
    last_written_as: dict[int, str] = {}
    counts = Counts()
    zero = None
    try:
        for _ in range(args.steps):
            while len(live) < 6 and rng.random() < 0.3:
                stem = stems[int(rng.integers(len(stems)))]
                n_prompt = int(rng.integers(1, 40))
                prompt = stem[:n_prompt] if rng.random() < 0.8 else [int(t) for t in rng.integers(2, config.vocab, size=n_prompt)]
                max_new = int(rng.integers(0, 30))
                # Half the requests stop at a token their own greedy continuation reaches a few
                # tokens in, so stops land inside blocks of accepted drafts.
                stops: tuple[int, ...] = (config.eos_token,)
                if rng.random() < 0.5:
                    ahead = greedy_reference(toy, weights, config, prompt, 12, ())
                    stops += (ahead[int(rng.integers(2, len(ahead)))],)
                rid = engine.submit(prompt, max_new_tokens=max_new, stop_token_ids=stops[1:])
                live[rid] = Live(prompt, max_new, stops, toy.Dense(weights, config).extend(prompt))
            if live and rng.random() < 0.02:
                rid = int(rng.choice(list(live)))
                engine.cancel(rid)
                del live[rid]
                counts.cancelled += 1
            units[0] = float("nan")  # SCRATCH: written freely, never read
            plan = engine.plan()
            counts.steps += 1
            if plan is None:
                engine.raise_error()
                assert all(v.finished for v in live.values()), "idle with work pending"
                continue
            req = plan.requests
            st = req.state[1]
            assert st is not None and req.state[0] is None
            zero = st.zero if zero is None else zero
            assert st.zero == zero
            # The oracle drafter: the dense model's greedy continuation, corrupted at random.
            drafts = np.zeros((plan.n_reqs_padded, max(k, 0)), dtype=np.int64)
            for r in range(plan.n_reqs):
                n_extra = int(req.n_extra[r])
                if n_extra == 0:
                    continue
                lookahead = live[int(req.req_ids[r])].dense.copy()
                for j in range(n_extra):
                    token = int(lookahead.logits[-1].argmax())
                    if rng.random() < args.corrupt:
                        token = int(rng.integers(0, config.vocab))
                    drafts[r, j] = token
                    lookahead.extend([token])
            tokens, requests = to_device(plan, torch.device(args.device))
            drafts_t = torch.from_numpy(drafts)
            if k > 0:
                filled = torch.arange(k)[None, :] < requests.n_extra.long()[:, None]
                tokens.input_ids[tokens.tail_rows[:, 1:][filled]] = drafts_t[filled].to(tokens.input_ids.dtype)
            assert_disjoint_writes(plan)
            read_before = {r: units[int(st.read[r]), 0].clone() for r in range(plan.n_reqs)}
            kv_before = step.kv[0][0].clone()
            logits = step.forward_device(plan, tokens, requests)
            STEP_KV_AFTER[0] = step.kv[0][0]
            # Exact: every tail row against the dense forward over the same tokens.
            for r in range(plan.n_reqs):
                rid = int(req.req_ids[r])
                q0, q1 = req.rows(r)
                n_extra = int(req.n_extra[r])
                n_work = q1 - q0 - n_extra
                seq_start = int(req.seq_start[r])
                history = live[rid].history
                read = int(st.read[r])
                counts.read_zero += read == zero
                counts.resumed_from_ckpt += last_written_as.get(read) == "ckpt"
                for j in range(1 + n_extra):
                    position = seq_start + n_work - 1 + j
                    if j == 0:
                        want = live[rid].dense.logits[position]
                    else:
                        want = live[rid].dense.copy().extend([int(x) for x in drafts[r, :j]]).logits[position]
                    if not torch.equal(logits[r, j], want):
                        raise AssertionError(diagnose(
                            toy, weights, config, plan, r, j, position, history, read_before[r], kv_before,
                            f"K={k} step {plan.step} req {rid} tail row {j} (position {position}): "
                            f"paged logits != dense, max |diff| {(logits[r, j] - want).abs().max().item():.3e}"))
                    counts.tail_logits_checked += 1
                for j in range(1 + n_extra):
                    last_written_as[int(st.write[r, j])] = "write"
                if int(st.ckpt_row[r]) != _ffi.NO_ROW:
                    last_written_as[int(st.ckpt[r])] = "ckpt"
                    counts.ckpts_written += 1
                    counts.mid_chunk_ckpts += int(st.ckpt_row[r]) != n_work - 1
                counts.entries += 1
                counts.extra_rows += n_extra
                del history
            assert bool((units[zero] == 0).all()), "ZERO was written"
            out, n = decide(logits, draw_of(plan, logits.device), drafts_t, requests.n_extra)
            emits = set(plan.emitting.tolist())
            rids = [int(x) for x in req.req_ids[: plan.n_reqs]]
            out_np = out[: plan.n_reqs].numpy().astype(np.uint32)
            n_np = n[: plan.n_reqs].numpy().astype(np.uint32)
            engine.commit(out_np, n_np, np.full(plan.n_reqs, k, dtype=np.uint32))
            for r, rid in enumerate(rids):
                if r not in emits or rid not in live:
                    continue
                request = live[rid]
                kept = out_np[r, : n_np[r]].tolist()
                room = max(1, request.max_new - len(request.generated))
                hits = [i for i, t in enumerate(kept) if t in request.stops]
                if hits:
                    cut = hits[0] + 1
                    counts.stopped_mid_block += cut < len(kept)
                    kept = kept[:cut]
                counts.capped_mid_block += len(kept) > room
                kept = kept[:room]
                counts.kept_extra += len(kept) - 1
                request.generated += kept
                request.dense.extend(kept)
                request.finished = kept[-1] in request.stops or len(request.generated) >= max(1, request.max_new)
            for rid in list(live):
                poll = engine.poll(rid)
                request = live[rid]
                request.polled += poll.new_tokens
                assert request.polled == request.generated[: len(request.polled)], rid
                if poll.finished:
                    del live[rid]
                    key = (tuple(request.prompt), request.max_new, request.stops)
                    if key not in reference:
                        reference[key] = greedy_reference(toy, weights, config, request.prompt, request.max_new, request.stops)
                    assert request.polled == reference[key], (
                        f"K={k}: output != dense greedy for a {len(request.prompt)}-token prompt")
                    counts.finished += 1
            event = _ffi.KelpieStepEvent()
            engine._lib.kelpie_step_event(engine._engine_handle(), __import__("ctypes").byref(event))  # noqa: SLF001
            counts.preempted += int(event.n_preempted)
            counts.prefix_hit_tokens += int(event.prefix_hit_tokens)
    finally:
        engine.close()
    return counts


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--steps", type=int, default=600)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--num-slabs", type=int, default=24, help="small enough to preempt")
    ap.add_argument("--max-batch-tokens", type=int, default=20, help="small: chunked prefills")
    ap.add_argument("--corrupt", type=float, default=0.25, help="chance an oracle draft is wrong")
    _fresh.add_phase_args(ap, ("k",))
    args = ap.parse_args()
    if setup_logging is not None:
        setup_logging()
    if args.phase is not None:  # the child: ONE K, ONE build
        from kelpie_models.models.torch import toy_hybrid

        return _fresh.respond(args, vars(run_k(toy_hybrid, _fresh.payload(args)["k"], args)))

    ok = True
    for k in K_VALUES:
        counts = Counts(**_fresh.in_fresh_process(
            "scripts.prove_state_lifecycle", [*sys.argv[1:], "--phase", "k"], {"k": k}))
        summary = vars(counts)
        exercised = (counts.ckpts_written > 0 and counts.resumed_from_ckpt > 0 and counts.preempted > 0
                     and counts.cancelled > 0 and counts.mid_chunk_ckpts > 0 and counts.finished > 0
                     and counts.prefix_hit_tokens > 0 and counts.read_zero > 0
                     and (k == 0 or (counts.kept_extra > 0 and counts.stopped_mid_block > 0
                                     and counts.capped_mid_block > 0)))
        ok &= exercised
        if span is not None:
            with span("prove_state_lifecycle", attributes={"K": k, "exercised": exercised, **summary}):
                pass
        print(f"K={k} {'PASS' if exercised else 'FAIL (a path was never exercised)'} "
              + " ".join(f"{name}={value}" for name, value in summary.items()), flush=True)
    print("ALL PASS" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
