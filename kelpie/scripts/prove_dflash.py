#!/usr/bin/env python3
"""Prove DFlash spec decode: greedy decode with speculation == greedy decode without.

The correctness property: for greedy (temperature=0), speculative decoding must produce
the exact same token sequence as non-speculative decoding. The drafter only affects
throughput, never output.

Also: liveness (some draft accepted per prompt), and reported (not gated) mean acceptance
length and tok/s vs K = 0. One engine build per mode; every prompt runs through each. Each
build runs in its own process (`kernels.bind` runs once per process): a hidden `--phase base` /
`--phase spec` child decodes and hands its runs back as JSON (scripts/_fresh.py).

Usage (from kelpie/):
    python -m scripts.prove_dflash [--target gpt_oss] [--drafter-checkpoint z-lab/gpt-oss-20b-DFlash]
                                   [--device cuda] [--max-new 64] [--loop native|hand]

--loop native (docs/design-multigpu.md rung 0): the spec run is `run()` itself -- the Zig loop
calls DFlashStep and commits its n tokens per entry. --loop hand: the caller-written loop.

Follows the `check()` pattern (matklad): one function encapsulates the API under test.
All tests go through `check`, so a refactor touches one place.
"""

from __future__ import annotations

import argparse
import ctypes
import dataclasses
import sys
import threading
import time
from dataclasses import dataclass
from types import ModuleType

import numpy as np
from scripts import _fresh

# ---------------------------------------------------------------------------
# The corpus: short, diverse prompts that exercise different token patterns.
# ---------------------------------------------------------------------------

CORPUS = [
    "The capital of France is",
    "def fibonacci(n):\n    ",
    "In quantum mechanics, the uncertainty principle states that",
    "Translate to Spanish: Hello, how are you today?",
    "1 + 1 = 2\n2 + 2 = 4\n3 + 3 =",
]

# GSM8K-style questions, sent through the gpt-oss chat template (--corpus math): closer to the
# model card's acceptance-length setting (GSM8K / Math500, chat template) than raw prompts.
MATH = [
    "Natalia sold clips to 48 of her friends in April, and then she sold half as many clips in "
    "May. How many clips did Natalia sell altogether in April and May?",
    "Weng earns $12 an hour for babysitting. Yesterday, she just did 50 minutes of babysitting. "
    "How much did she earn?",
    "Betty is saving money for a new wallet which costs $100. Betty has only half of the money "
    "she needs. Her parents decided to give her $15 for that purpose, and her grandparents twice "
    "as much as her parents. How much more money does Betty need to buy the wallet?",
]


@dataclass
class SpecStats:
    """Per-request counters. A verify step is a step whose entry carried drafts (n_extra > 0);
    each commits 1 + a tokens. Acceptance length = mean over verify steps of (1 + a) -- the
    z-lab / model-card "Accept Len" (their spec_generate appends acceptance_length + 1)."""
    verify_steps: int = 0
    accepted: int = 0  # sum of a over verify steps
    drafted: int = 0  # sum of n_extra over verify steps
    steps: int = 0  # all steps that included this request (prefill chunks too)
    # per committed token: the verify row's top-5 (ids, logits), for the tie report on mismatch
    top5: list = None  # type: ignore[assignment]

    @property
    def acceptance_length(self) -> float:
        return 1 + self.accepted / self.verify_steps if self.verify_steps else 0.0


@dataclass
class Run:
    tokens: list[int]
    seconds: float  # submit -> finished, wall clock
    stats: SpecStats | None = None


def run_to_json(run: Run) -> dict:
    """A child's Run for the parent (JSON: top5's (ids, vals) tuples come back as lists)."""
    return dataclasses.asdict(run)


def run_from_json(d: dict) -> Run:
    stats = d["stats"]
    return Run(d["tokens"], d["seconds"], SpecStats(**stats) if stats is not None else None)


# ---------------------------------------------------------------------------
# Decode helpers: one engine build per mode, every prompt through it sequentially.
# ---------------------------------------------------------------------------

def _collect(engine, prompt_tokens: list[int], max_new: int, timeout_s: float,
             err: list[BaseException] | None = None) -> Run:
    rid = engine.submit(prompt_tokens, max_new_tokens=max_new)
    tokens: list[int] = []
    t0 = time.perf_counter()
    while True:
        if err:
            raise RuntimeError("spec-decode loop thread died") from err[0]
        poll = engine.poll(rid)
        tokens.extend(poll.new_tokens)
        if poll.finished:
            break
        if time.perf_counter() - t0 > timeout_s:
            raise TimeoutError(f"request {rid} not finished after {timeout_s}s ({len(tokens)} tokens)")
        time.sleep(0.001)
    return Run(tokens, time.perf_counter() - t0)


def decode_all(model_module, prompts: list[list[int]], max_new: int, *, timeout_s: float,
               **build_kw) -> list[Run]:
    """No speculation: the Zig step loop."""
    from kelpie_models.sdk.run import run

    with run(model_module, **build_kw) as engine:
        return [_collect(engine, p, max_new, timeout_s) for p in prompts]


def decode_all_spec(model_module, drafter_module, prompts: list[list[int]], max_new: int, *,
                    drafter_checkpoint: str, timeout_s: float, **build_kw) -> list[Run]:
    """DFlash speculation: the caller-written loop (docs/design-core-option2.md 1(b)), right
    here, no thread -- plan, draft on the tail rows + verify + accept + inject
    (`dflash.step`), commit with K extra rows asked for next. One prompt at a time."""
    from kelpie_models.sdk.run import build

    engine, target, drafter = build(model_module, drafter=drafter_module,
                                    drafter_checkpoint=drafter_checkpoint, **build_kw)
    k = drafter.n_draft
    runs: list[Run] = []
    try:
        for prompt in prompts:
            rid = engine.submit(prompt, max_new_tokens=max_new)
            stats = SpecStats(top5=[])
            tokens: list[int] = []
            t0 = time.perf_counter()
            while True:
                plan = engine.plan()
                assert plan is not None, f"idle before request {rid} finished"
                assert plan.n_reqs == 1 and int(plan.requests.req_ids[0]) == rid, plan.requests.req_ids
                emitted = drafter_module.step(target, drafter, plan)
                n_extra = int(plan.requests.n_extra[0])
                engine.commit(emitted.tokens, emitted.n, np.full(plan.n_reqs, k, dtype=np.uint32))
                poll = engine.poll(rid)
                tokens.extend(poll.new_tokens)
                # What the core KEPT this step (cut at a stop token / max_new), not what accept said.
                kept = len(poll.new_tokens)
                stats.steps += 1
                if kept:
                    top = target.last_logits[0, :kept].float().topk(5, dim=-1)
                    for ids, vals in zip(top.indices.tolist(), top.values.tolist(), strict=True):
                        stats.top5.append((ids, vals))
                if n_extra > 0:
                    stats.verify_steps += 1
                    stats.drafted += n_extra
                    stats.accepted += kept - 1
                if poll.finished:
                    break
                if time.perf_counter() - t0 > timeout_s:
                    raise TimeoutError(f"request {rid} not finished after {timeout_s}s ({len(tokens)} tokens)")
            runs.append(Run(tokens, time.perf_counter() - t0, stats))
        assert engine.plan() is None, "work left after the last prompt"
    finally:
        engine.close()
    return runs


# ---------------------------------------------------------------------------
# --loop native: DFlashStep inside the Zig loop (run()), stats recorded on the step thread
# ---------------------------------------------------------------------------

class StepRecord:
    """Wraps the native StepFn: per real entry of every plan, what the hand loop counted (n_extra,
    the committed count n, the verify rows' top-5 for the tie report) and the batch-mix
    counters. Runs on the Zig step thread; `take` reads it from the caller's thread."""

    def __init__(self, stepper, target) -> None:
        self.stepper = stepper
        self.target = target
        self.lock = threading.Lock()
        self.per_rid: dict[int, list[tuple[int, int, list]]] = {}
        self.mix = {"steps": 0, "mixed": 0, "mid_prefill_next_to_draft": 0, "degraded": 0, "preempted": 0}

    def __call__(self, plan):
        from kelpie_engine import _ffi

        out = self.stepper(plan)
        n_reqs = plan.n_reqs
        ids = [int(x) for x in plan.requests.req_ids[:n_reqs]]
        n_extra = [int(x) for x in plan.requests.n_extra[:n_reqs]]
        kinds = [int(x) for x in plan.requests.kinds[:n_reqs]]
        emits = [bool(x) for x in plan.requests.emits[:n_reqs]]
        ns = [int(x) for x in out.n]
        tops = []
        for r in range(n_reqs):
            if not emits[r]:
                tops.append([])
                continue
            top = self.target.last_logits[r, : ns[r]].float().topk(5, dim=-1)
            tops.append(list(zip(top.indices.tolist(), top.values.tolist(), strict=True)))
        drafting = any(n_extra)
        with self.lock:
            self.mix["steps"] += 1
            self.mix["mixed"] += drafting and _ffi.KIND_PREFILL in kinds
            self.mix["mid_prefill_next_to_draft"] += drafting and not all(emits)
            self.mix["degraded"] += sum(kd == _ffi.KIND_DECODE and e == 0 for kd, e in zip(kinds, n_extra))
            for r, rid in enumerate(ids):
                self.per_rid.setdefault(rid, []).append((n_extra[r], ns[r] if emits[r] else 0, tops[r]))
        return out

    def take(self, rid: int, n_tokens: int) -> SpecStats:
        """The finished request's stats, cut to what the core KEPT (n_tokens in all): a step's
        count is at most what was left, exactly as the hand loop's poll-length count."""
        with self.lock:
            steps = self.per_rid.pop(rid, [])
        st = SpecStats(top5=[])
        left = n_tokens
        for n_extra, n, top in steps:
            st.steps += 1
            kept = min(n, left)
            left -= kept
            st.top5.extend(top[:kept])
            if n_extra > 0:
                st.verify_steps += 1
                st.drafted += n_extra
                st.accepted += max(kept - 1, 0)
        return st


def _native_spec(model_module, drafter_module, *, drafter_checkpoint: str, **build_kw):
    from kelpie_models.sdk.run import build

    built = build(model_module, drafter=drafter_module, drafter_checkpoint=drafter_checkpoint, **build_kw)
    record = StepRecord(built.stepper, built.step)
    return built, record


def _drain_preempted(engine, record: StepRecord) -> None:
    while (c := engine.next_commit()) is not None:
        record.mix["preempted"] += c.event.n_preempted


def decode_all_spec_native(model_module, drafter_module, prompts: list[list[int]], max_new: int, *,
                           drafter_checkpoint: str, timeout_s: float, **build_kw) -> list[Run]:
    """decode_all_spec through run()'s path: the Zig loop steps DFlashStep. One prompt at a time."""
    built, record = _native_spec(model_module, drafter_module, drafter_checkpoint=drafter_checkpoint, **build_kw)
    engine = built.engine
    runs: list[Run] = []
    try:
        engine.start_loop(record)
        for prompt in prompts:
            rid = engine.submit(prompt, max_new_tokens=max_new)
            t0 = time.perf_counter()
            result = engine.wait(rid, timeout_s)
            runs.append(Run(result.new_tokens, time.perf_counter() - t0, record.take(rid, len(result.new_tokens))))
    finally:
        engine.close()
    return runs


def decode_batch_spec_native(model_module, drafter_module, prompts: list[list[int]], max_new: int, *,
                             drafter_checkpoint: str, timeout_s: float, max_batch_tokens: int,
                             **build_kw) -> tuple[list[Run], dict[str, int]]:
    """decode_batch_spec through run()'s path: every prompt at once, the Zig loop steps."""
    built, record = _native_spec(model_module, drafter_module, drafter_checkpoint=drafter_checkpoint, **build_kw)
    engine = built.engine
    try:
        engine.start_loop(record)
        engine.set(max_batch_tokens=max_batch_tokens)  # an op: applies before the submits below
        rids = [engine.submit(p, max_new_tokens=max_new) for p in prompts]
        tokens: dict[int, list[int]] = {rid: [] for rid in rids}
        done: dict[int, float] = {}
        t0 = time.perf_counter()
        while len(done) < len(rids):
            engine.raise_error()
            for rid in rids:
                if rid in done:
                    continue
                poll = engine.poll(rid)
                tokens[rid].extend(poll.new_tokens)
                if poll.finished:
                    done[rid] = time.perf_counter() - t0
            _drain_preempted(engine, record)
            if time.perf_counter() - t0 > timeout_s:
                raise TimeoutError(f"batch not finished after {timeout_s}s: {[len(t) for t in tokens.values()]}")
            time.sleep(0.002)
        _drain_preempted(engine, record)
    finally:
        engine.close()
    runs = [Run(tokens[rid], done[rid], record.take(rid, len(tokens[rid]))) for rid in rids]
    return runs, dict(record.mix)


def decode_batch_k0(model_module, prompts: list[list[int]], max_new: int, *, timeout_s: float,
                    max_batch_tokens: int, **build_kw) -> list[Run]:
    """The control for decode_batch_spec: same batch, same budget, no drafter (K = 0), stepped
    by hand. Teacher-forcing ITS output measures what batch shape alone does to the logits."""
    from kelpie_models.sdk.run import build

    engine, step = build(model_module, **build_kw)
    engine.set(max_batch_tokens=max_batch_tokens)
    try:
        rids = [engine.submit(p, max_new_tokens=max_new) for p in prompts]
        tokens: dict[int, list[int]] = {rid: [] for rid in rids}
        done: dict[int, float] = {}
        t0 = time.perf_counter()
        while len(done) < len(rids):
            plan = engine.plan()
            assert plan is not None, "idle before every request finished"
            engine.commit(step.sample(step.forward(plan), plan))
            for rid in rids:
                if rid in done:
                    continue
                poll = engine.poll(rid)
                tokens[rid].extend(poll.new_tokens)
                if poll.finished:
                    done[rid] = time.perf_counter() - t0
            if time.perf_counter() - t0 > timeout_s:
                raise TimeoutError("K=0 batch not finished")
    finally:
        engine.close()
    return [Run(tokens[rid], done[rid], SpecStats(top5=[], verify_steps=1, accepted=1)) for rid in rids]


def decode_batch_spec(model_module, drafter_module, prompts: list[list[int]], max_new: int, *,
                      drafter_checkpoint: str, timeout_s: float, max_batch_tokens: int,
                      **build_kw) -> tuple[list[Run], dict[str, int]]:
    """decode_all_spec with every prompt submitted at once under a small token budget: drafting
    entries share steps with (chunked) prefills, and decode entries past the budget lose their
    extra rows. -> (runs in prompt order, mix counters the caller gates on)."""
    from kelpie_engine import _ffi
    from kelpie_models.sdk.run import build

    engine, target, drafter = build(model_module, drafter=drafter_module,
                                    drafter_checkpoint=drafter_checkpoint, **build_kw)
    engine.set(max_batch_tokens=max_batch_tokens)
    k = drafter.n_draft
    mix = {"steps": 0, "mixed": 0, "mid_prefill_next_to_draft": 0, "degraded": 0, "preempted": 0}
    try:
        rids = [engine.submit(p, max_new_tokens=max_new) for p in prompts]
        which = {rid: i for i, rid in enumerate(rids)}
        stats = [SpecStats(top5=[]) for _ in prompts]
        tokens: list[list[int]] = [[] for _ in prompts]
        done_s: list[float | None] = [None] * len(prompts)
        t0 = time.perf_counter()
        while any(d is None for d in done_s):
            plan = engine.plan()
            assert plan is not None, "idle before every request finished"
            # Copies: the plan's views die at commit.
            ids = [int(x) for x in plan.requests.req_ids[: plan.n_reqs]]
            n_extra = [int(x) for x in plan.requests.n_extra[: plan.n_reqs]]
            kinds = [int(x) for x in plan.requests.kinds[: plan.n_reqs]]
            emits = [bool(x) for x in plan.requests.emits[: plan.n_reqs]]
            drafting = any(n_extra)
            mix["steps"] += 1
            mix["mixed"] += drafting and _ffi.KIND_PREFILL in kinds
            mix["mid_prefill_next_to_draft"] += drafting and not all(emits)
            # next_extra = K is asked on every commit, so a decode entry without extra rows
            # was cut by the budget (manual stepping never plans ahead).
            mix["degraded"] += sum(kd == _ffi.KIND_DECODE and e == 0 for kd, e in zip(kinds, n_extra))
            emitted = drafter_module.step(target, drafter, plan)
            engine.commit(emitted.tokens, emitted.n, np.full(plan.n_reqs, k, dtype=np.uint32))
            event = _ffi.KelpieStepEvent()
            engine._lib.kelpie_step_event(engine._engine_handle(), ctypes.byref(event))  # noqa: SLF001
            mix["preempted"] += int(event.n_preempted)
            for r, rid in enumerate(ids):
                i = which[rid]
                poll = engine.poll(rid)
                tokens[i].extend(poll.new_tokens)
                kept = len(poll.new_tokens)
                st = stats[i]
                st.steps += 1
                if kept:
                    top = target.last_logits[r, :kept].float().topk(5, dim=-1)
                    st.top5.extend(zip(top.indices.tolist(), top.values.tolist(), strict=True))
                if n_extra[r] > 0:
                    st.verify_steps += 1
                    st.drafted += n_extra[r]
                    st.accepted += kept - 1
                if poll.finished:
                    done_s[i] = time.perf_counter() - t0
            if time.perf_counter() - t0 > timeout_s:
                raise TimeoutError(f"batch not finished after {timeout_s}s: {[len(t) for t in tokens]}")
        assert engine.plan() is None, "work left after the last request"
    finally:
        engine.close()
    runs = [Run(t, s, st) for t, s, st in zip(tokens, done_s, stats, strict=True)]
    return runs, mix


# ---------------------------------------------------------------------------
# check -- the single assertion point
# ---------------------------------------------------------------------------

def bf16_ulps(gap: float, at: float) -> float:
    """`gap` in units of one bf16 step at magnitude `at` (8 bits of mantissa)."""
    import math
    step = 2.0 ** (math.floor(math.log2(max(abs(at), 1e-30))) - 7)
    return gap / step


# A first divergence within this many bf16 steps of the top logit is a near-tie. Ad hoc: the
# K=0 baseline itself flipped a token between two identical runs where the gap was 5 steps.
TIE_ULPS = 8.0


def check(label: str, base: Run, spec: Run) -> tuple[list[str], list[str]]:
    """Greedy spec == greedy no-spec, token for token; drafts accepted at all.

    -> (fails, ties). A first divergence where the baseline's token is within TIE_ULPS bf16
    steps of the spec verify row's top logit is a TIE (numerics: the 1-row decode and the
    (1+K)-row verify are different kernels/batch shapes over bf16 logits), reported but not
    failed. Anything else -- a clear winner that spec did not pick, or the baseline token
    missing from the row's top-5 -- is a FAIL."""
    fails: list[str] = []
    ties: list[str] = []
    if base.tokens != spec.tokens:
        i = _first_diff(base.tokens, spec.tokens)
        tie, is_tie = "", False
        if spec.stats is not None and i < len(spec.stats.top5) and i < len(base.tokens):
            ids, vals = spec.stats.top5[i]
            b = base.tokens[i]
            b_logit = f"{vals[ids.index(b)]:.3f}" if b in ids else "not in top5"
            if b in ids:
                ulps = bf16_ulps(vals[0] - vals[ids.index(b)], vals[0])
                is_tie = ulps <= TIE_ULPS
                b_logit += f" ({ulps:.1f} bf16 steps below top1)"
            tie = (f"; spec verify row there: top1 {ids[0]}={vals[0]:.3f}, top2 {ids[1]}="
                   f"{vals[1]:.3f}, base token {b} logit {b_logit}")
        (ties if is_tie else fails).append(f"{label}: token mismatch at {i} (base {len(base.tokens)} tokens, spec "
                     f"{len(spec.tokens)}): base {base.tokens[max(0, i - 3):i + 5]} spec "
                     f"{spec.tokens[max(0, i - 3):i + 5]}{tie}")
    assert spec.stats is not None
    if spec.stats.accepted == 0:
        fails.append(f"{label}: no drafts accepted over {spec.stats.verify_steps} verify steps")
    return fails, ties


def _first_diff(a: list[int], b: list[int]) -> int:
    for i, (x, y) in enumerate(zip(a, b)):
        if x != y:
            return i
    return min(len(a), len(b))


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def build_kwargs(args: argparse.Namespace, *, capture: bool = False) -> dict:
    """The build kwargs of every build here, from the flags (a --phase child parses the same).

    Short prompts + max_new: cap max_seq_len so the block table stays narrow. `capture` is the
    spec run's `--capture` (DFlashStep's graphs); every other build here runs eagerly.
    num_slabs: the default 64 holds only ~350 tokens of gpt-oss KV (+ drafter group), and a
    single request that outgrows the pool is preempted and never re-admitted -- the engine
    hangs silently instead of erroring. 512 slabs covers max_seq_len for a few requests."""
    from kelpie_models.sdk.tiers import Capacity

    return dict(device=args.device, capacity=Capacity(max_seq_len=512, num_slabs=args.num_slabs),
                capture=capture)


def spec_runs(target: ModuleType, drafter: ModuleType, prompts: list[list[int]],
              args: argparse.Namespace, build_kw: dict) -> tuple[list[Run], dict[str, int] | None]:
    """The spec run --batched / --loop pick. -> (runs in prompt order, the batch mix or None)."""
    native = args.loop == "native"
    if args.batched:
        batch_fn = decode_batch_spec_native if native else decode_batch_spec
        return batch_fn(target, drafter, prompts, args.max_new,
                        drafter_checkpoint=args.drafter_checkpoint,
                        timeout_s=args.timeout, max_batch_tokens=args.max_batch_tokens,
                        **build_kw)
    all_fn = decode_all_spec_native if native else decode_all_spec
    return all_fn(target, drafter, prompts, args.max_new,
                  drafter_checkpoint=args.drafter_checkpoint,
                  timeout_s=args.timeout, **build_kw), None


def phase(args: argparse.Namespace) -> int:
    """The child: ONE build (base = K = 0 through run(), spec = spec_runs), runs as JSON."""
    import importlib

    prompts = _fresh.payload(args)["prompts"]
    target = importlib.import_module(f"kelpie_models.models.torch.{args.target}")
    drafter = importlib.import_module("kelpie_models.models.torch.dflash")
    if args.phase == "base" and args.base == "k0":
        runs, mix = decode_all(target, prompts, args.max_new, timeout_s=args.timeout,
                               **build_kwargs(args)), None
    elif args.phase == "base":  # --base spec: the same spec run, eager
        runs, mix = spec_runs(target, drafter, prompts, args, build_kwargs(args))
    else:
        runs, mix = spec_runs(target, drafter, prompts, args,
                              build_kwargs(args, capture=args.capture))
    return _fresh.respond(args, {"runs": [run_to_json(r) for r in runs], "mix": mix})


def in_child(which: str, prompts: list[list[int]]) -> tuple[list[Run], dict[str, int] | None]:
    """`phase` in a fresh process, with this process's own flags. -> (runs, mix)."""
    out = _fresh.in_fresh_process("scripts.prove_dflash", [*sys.argv[1:], "--phase", which],
                                  {"prompts": prompts})
    return [run_from_json(r) for r in out["runs"]], out["mix"]


def encode_corpus(tokenizer, which: str) -> tuple[list[list[int]], list[str]]:
    """-> (token ids per prompt, the prompt texts): raw text, or MATH through the chat template."""
    corpus = CORPUS if which == "raw" else MATH
    if which == "raw":
        return [tokenizer.encode(p) for p in corpus], corpus

    def chat(p: str) -> list[int]:
        out = tokenizer.apply_chat_template([{"role": "user", "content": p}],
                                            add_generation_prompt=True, tokenize=True)
        ids = out["input_ids"] if hasattr(out, "keys") else out  # transformers 5 returns a dict
        return [int(t) for t in ids]

    return [chat(p) for p in corpus], corpus


def main() -> None:
    parser = argparse.ArgumentParser(description="Prove DFlash spec decode correctness")
    parser.add_argument("--target", default="gpt_oss", help="Target model module name")
    parser.add_argument("--target-checkpoint", default="openai/gpt-oss-20b",
                        help="HF id for the tokenizer (and the target, via the module default)")
    parser.add_argument("--drafter-checkpoint", default="z-lab/gpt-oss-20b-DFlash",
                        help="HuggingFace checkpoint for the DFlash drafter")
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--max-new", type=int, default=64, help="Max new tokens per prompt")
    parser.add_argument("--timeout", type=float, default=600.0, help="Per-request timeout (s)")
    parser.add_argument("--num-slabs", type=int, default=512, help="KV pool size (Capacity)")
    parser.add_argument("--corpus", choices=("raw", "math"), default="raw",
                        help="raw prompts, or GSM8K-style questions through the chat template")
    parser.add_argument("--batched", action="store_true",
                        help="spec run submits every prompt at once (K=0 baseline stays one at a time)")
    parser.add_argument("--max-batch-tokens", type=int, default=64,
                        help="--batched token budget: small forces chunked prefill + degraded extra rows")
    parser.add_argument("--loop", choices=("hand", "native"), default="hand",
                        help="spec run: the caller-written loop, or run()'s Zig loop stepping DFlashStep")
    parser.add_argument("--require-preemption", action="store_true",
                        help="--batched: fail unless the spec run preempts (lower --num-slabs)")
    parser.add_argument("--capture", action="store_true",
                        help="the spec run replays DFlashStep's CUDA graphs (build capture=True)")
    parser.add_argument("--base", choices=("k0", "spec"), default="k0",
                        help="compare against K=0 (default; near-ties reported, not failed), or "
                             "the same spec run eagerly (spec; any difference FAILS)")
    _fresh.add_phase_args(parser, ("base", "spec"))
    args = parser.parse_args()
    # The hand loops call dflash.step (eager): only the native loop steps DFlashStep's graphs.
    assert not args.capture or args.loop == "native", "--capture needs --loop native"
    if args.phase is not None:
        sys.exit(phase(args))

    from transformers import AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(args.target_checkpoint)
    prompts, corpus = encode_corpus(tokenizer, args.corpus)
    if args.batched:  # more concurrent requests than one corpus: both, in one batch
        other = encode_corpus(tokenizer, "raw" if args.corpus == "math" else "math")
        prompts, corpus = prompts + other[0], corpus + other[1]

    print(f"prompt lengths: {[len(p) for p in prompts]}", flush=True)
    print(f"prove_dflash: {len(corpus)} prompts ({args.corpus}), max_new={args.max_new}, K=block_size-1, "
          f"device={args.device}, drafter={args.drafter_checkpoint}", flush=True)

    base, _ = in_child("base", prompts)
    fails: list[str] = []
    print(f"spec loop: {args.loop}", flush=True)
    spec, mix = in_child("spec", prompts)
    if args.batched:
        assert mix is not None
        print(f"batch mix: {mix}", flush=True)
        for key in ("mixed", "mid_prefill_next_to_draft", "degraded"):
            if mix[key] == 0:
                fails.append(f"batched run never exercised {key} (lower --max-batch-tokens?)")
        if args.require_preemption and mix["preempted"] == 0:
            fails.append("--require-preemption: the batched run never preempted (lower --num-slabs)")

    ties: list[str] = []
    for i, (prompt, b, s) in enumerate(zip(corpus, base, spec)):
        label = f"{i + 1}/{len(corpus)} {prompt[:30]!r}"
        f, t = check(label, b, s)
        if args.base == "spec":  # the same program eager and replayed: no tie is excused
            f, t = f + [f"{x} (--base spec: must be identical)" for x in t], []
        fails += f
        ties += t
        st = s.stats
        status = "FAIL" if f else ("TIE" if t else "PASS")
        print(f"  [{status}] {label}: {len(b.tokens)} tokens, "
              f"accept_len {st.acceptance_length:.2f} ({st.accepted}/{st.drafted} drafts over "
              f"{st.verify_steps} verify steps), tok/s base {len(b.tokens) / b.seconds:.1f} "
              f"spec {len(s.tokens) / s.seconds:.1f}", flush=True)
        print(f"      spec text: {tokenizer.decode(s.tokens)[:120]!r}", flush=True)

    vs = sum(s.stats.verify_steps for s in spec)
    acc = sum(s.stats.accepted for s in spec)
    n_base = sum(len(b.tokens) for b in base)
    n_spec = sum(len(s.tokens) for s in spec)
    t_base = sum(b.seconds for b in base)
    t_spec = sum(s.seconds for s in spec)
    print()
    print(f"mean acceptance length: {1 + acc / max(vs, 1):.2f} over {vs} verify steps "
          f"(model card: ~4-5 on GSM8K/Math500 with the chat template)")
    print(f"tok/s: base ({args.base}) {n_base / t_base:.1f}, spec"
          f"{' (captured)' if args.capture else ''} {n_spec / t_spec:.1f}  (a correctness run: "
          f"sequential or batched as flagged, NOT the speed measurement -- scripts/bench_spec.py)")
    if ties:
        print(f"{len(ties)} diverged at a bf16 near-tie (<= {TIE_ULPS} steps; not failed):")
        for t in ties:
            print("  " + t)
    if fails:
        print(f"{len(fails)} FAILED:")
        for f in fails:
            print("  " + f)
        sys.exit(1)
    n_exact = len(corpus) - len(ties)
    print(f"PASSED: {n_exact}/{len(corpus)} prompts greedy ids(spec) == ids(base {args.base}) "
          f"exactly, {len(ties)} diverged only at a near-tie")


if __name__ == "__main__":
    main()
