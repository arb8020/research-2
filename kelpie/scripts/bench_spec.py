#!/usr/bin/env python3
"""Does DFlash beat plain decode? Output tokens/s, K = 0 vs DFlash K = 7, both CUDA-graph captured.

One build per mode, each in its own process (`kernels.bind` runs once per process; scripts/
_fresh.py): `--phase k0` builds the target alone (build's `Captured`: decode buckets graphed),
`--phase spec` builds it with the DFlash drafter (DFlashStep's graphs: every decode_extra
bucket's whole step). Both run `run()`'s native Zig loop, greedy, and each child walks every
(corpus, batch) cell: B concurrent requests (the corpus's prompts cycled to B), --max-new new
tokens each, submitted at once.

Per cell:
  req tok/s    each request's decode rate after its first poll, (n - n_first) / (t_done - t_first),
               averaged over the B requests (what one user sees)
  total tok/s  every request's tokens / the cell's wall time, submit to the last finish
  accept       spec only: mean over verify steps of the committed count n (1 + accepted drafts;
               a step cut at max_new counts what the step returned, not what the core kept)
  preempted    requests preempted during the cell (a non-zero cell is not a clean measurement)

`--profile` (spec child): where one DFlash step's time goes, on a real steady-state plan at each
--profile-batch. The step's program is captured a second time as four graphs over the SAME static
buffers -- draft | fill + target forward | decide (accept) | inject -- replayed back to back with
CUDA events between them; the whole-step graph is timed the same way, and "outside graph" is one full
`DFlashStep` call's wall time minus that graph's GPU time: host checks, the plan -> pinned ->
device copies and the D2H of (tokens, n), host and copy time together. Replaying a step on the same plan is idempotent (the same
values to the same KV slots), so the plan is then committed once as usual.

    PYTHONPATH=. uv run --no-project --with modal --with requests python kelpie/scripts/modal_run.py \\
        --volume kelpie-a1 --gpu H100 --model openai/gpt-oss-20b --model z-lab/gpt-oss-20b-DFlash \\
        -- 'HF_HUB_OFFLINE=1 python -m scripts.bench_spec --profile'
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time

import numpy as np
from scripts import _fresh

MAX_REQUESTS = 16  # the largest batch the table asks for; the engine's request slots
WARM_TOKENS = 16


def build_kwargs(args: argparse.Namespace) -> dict:
    from kelpie_models.sdk.tiers import Capacity

    return dict(device="cuda", capture=True,
                capacity=Capacity(max_requests=MAX_REQUESTS, max_seq_len=args.max_seq_len,
                                  num_slabs=args.num_slabs))


class Counting:
    """The StepFn the loop runs, wrapped: per step, host-only counters (no device work, no sync
    beyond the step's own). Verify steps and their committed counts, per request id."""

    def __init__(self, stepper: object) -> None:
        self.stepper = stepper
        self.lock = threading.Lock()
        self.verify_steps = 0
        self.committed = 0

    def __call__(self, plan: object) -> object:
        out = self.stepper(plan)  # type: ignore[operator]
        n_extra = plan.requests.n_extra[: plan.n_reqs]  # type: ignore[attr-defined]
        drafting = n_extra > 0
        with self.lock:
            self.verify_steps += int(drafting.sum())
            self.committed += int(np.asarray(out.n)[drafting].sum()) if out.n is not None else 0
        return out

    def take(self) -> float:
        with self.lock:
            accept = self.committed / self.verify_steps if self.verify_steps else 0.0
            self.verify_steps, self.committed = 0, 0
        return accept


def run_cell(engine: object, counting: Counting, prompts: list[list[int]], max_new: int,
             timeout_s: float) -> dict:
    """B requests at once; poll until every one finishes. -> the cell's numbers."""
    counting.take()
    t0 = time.perf_counter()
    rids = [engine.submit(p, max_new_tokens=max_new) for p in prompts]  # type: ignore[attr-defined]
    n_tokens = dict.fromkeys(rids, 0)
    first: dict[int, float] = {}
    n_first: dict[int, int] = {}  # tokens the first poll saw (its decode rate excludes them)
    done: dict[int, float] = {}
    preempted = 0
    while len(done) < len(rids):
        engine.raise_error()  # type: ignore[attr-defined]
        now = time.perf_counter()
        for rid in rids:
            if rid in done:
                continue
            poll = engine.poll(rid)  # type: ignore[attr-defined]
            if poll.new_tokens and rid not in first:
                first[rid] = now
                n_first[rid] = len(poll.new_tokens)
            n_tokens[rid] += len(poll.new_tokens)
            if poll.finished:
                done[rid] = now
        while (c := engine.next_commit()) is not None:  # type: ignore[attr-defined]
            preempted += c.event.n_preempted
        assert now - t0 < timeout_s, f"cell not finished after {timeout_s}s"
        time.sleep(0.0005)
    wall = max(done.values()) - t0
    per_req = [(n_tokens[r] - n_first[r]) / max(done[r] - first[r], 1e-9) for r in rids]
    return {"batch": len(prompts), "tokens": sum(n_tokens.values()), "wall_s": wall,
            "req_tok_s": float(np.mean(per_req)), "total_tok_s": sum(n_tokens.values()) / wall,
            "accept": counting.take(), "preempted": preempted}


def cycled(prompts: list[list[int]], b: int) -> list[list[int]]:
    return [prompts[i % len(prompts)] for i in range(b)]


def phase(args: argparse.Namespace) -> int:
    """One build (k0 or spec), every cell through run()'s loop, then (spec, --profile) the
    step breakdown by hand. -> {cells, profile, build_s}."""
    import importlib

    from kelpie_models.sdk.run import build

    corpora = _fresh.payload(args)["corpora"]
    target = importlib.import_module("kelpie_models.models.torch.gpt_oss")
    kw = build_kwargs(args)
    t0 = time.perf_counter()
    if args.phase == "spec":
        drafter = importlib.import_module("kelpie_models.models.torch.dflash")
        built = build(target, drafter=drafter, drafter_checkpoint=args.drafter_checkpoint, **kw)
    else:
        built = build(target, **kw)
    build_s = time.perf_counter() - t0
    import torch

    print(f"  [{args.phase}] {torch.cuda.get_device_name()}: build {build_s:.1f} s", flush=True)
    engine = built.engine
    profile = profile_steps(built, corpora["math"], args) if args.phase == "spec" and args.profile else []
    counting = Counting(built.stepper)
    cells = []
    try:
        engine.start_loop(counting)
        run_cell(engine, counting, cycled(corpora["math"], 1), WARM_TOKENS, args.timeout)
        for name, prompts in corpora.items():
            for b in args.batch:
                cell = {"corpus": name, **run_cell(engine, counting, cycled(prompts, b),
                                                    args.max_new, args.timeout)}
                print(f"  [{args.phase}] {name} B={b}: req {cell['req_tok_s']:.1f} tok/s, total "
                      f"{cell['total_tok_s']:.1f} tok/s, accept {cell['accept']:.2f}, preempted "
                      f"{cell['preempted']}", flush=True)
                cells.append(cell)
    finally:
        engine.close()
    return _fresh.respond(args, {"cells": cells, "profile": profile, "build_s": build_s})


def profile_steps(built: object, prompts: list[list[int]], args: argparse.Namespace) -> list[dict]:
    """Hand-step B requests to a steady decode_extra plan, time its phases, commit, next B."""
    out = []
    engine, stepper = built.engine, built.stepper  # type: ignore[attr-defined]
    for b in args.profile_batch:
        rids = [engine.submit(p, max_new_tokens=args.max_new) for p in cycled(prompts, b)]
        for _ in range(args.profile_after):
            plan = engine.plan()
            emitted = stepper(plan)
            engine.commit(emitted.tokens, emitted.n, emitted.next_extra)
        plan = engine.plan()
        row = {"batch": b, **time_phases(stepper, plan, args.profile_iters)}
        print(f"  [profile] B={b} {row}", flush=True)
        out.append(row)
        emitted = stepper(plan)
        engine.commit(emitted.tokens, emitted.n, emitted.next_extra)
        for rid in rids:
            engine.cancel(rid)
        while (plan := engine.plan()) is not None:  # drain: cancelled requests leave the batch
            emitted = stepper(plan)
            engine.commit(emitted.tokens, emitted.n, emitted.next_extra)
    return out


def time_phases(stepper: object, plan: object, iters: int) -> dict:  # noqa: PLR0914
    """ms per phase (median over `iters`), the whole-step graph's GPU ms, and the host ms."""
    import torch
    from kelpie_models.models.torch import dflash
    from kelpie_models.sdk.decide import decide
    from kelpie_models.sdk.shapes import key_of

    key = key_of(plan)
    assert key.family == "decode_extra", f"profile plan is {key}: not a steady decode step"
    graphed = stepper._graphs[key]  # noqa: SLF001 -- the bench reads the step's static batch
    target, drafter = stepper.target, stepper.drafter  # type: ignore[attr-defined]
    stepper(plan)  # the plan is now in graphed's static buffers (and the step is idempotent)
    tokens, requests = graphed.batch

    def draft() -> torch.Tensor:
        return dflash.draft(drafter, tokens, requests)

    parts: dict[str, torch.cuda.CUDAGraph] = {}
    pool = torch.cuda.graph_pool_handle()
    with torch.no_grad():
        drafts = draft()
        torch.cuda.synchronize()
        parts["draft"] = torch.cuda.CUDAGraph()
        with torch.cuda.graph(parts["draft"], pool=pool):
            drafts = draft()
        filled = dflash.fill_extra_rows(tokens, requests, drafts)
        target.forward_device(plan, filled, requests)
        torch.cuda.synchronize()
        parts["target"] = torch.cuda.CUDAGraph()
        with torch.cuda.graph(parts["target"], pool=pool):
            filled = dflash.fill_extra_rows(tokens, requests, drafts)
            logits = target.forward_device(plan, filled, requests)
        taps = target.last_taps
        decide(logits, graphed.draw, drafts, requests.n_extra)
        dflash.inject(drafter, taps, tokens, requests)
        torch.cuda.synchronize()
        parts["accept"] = torch.cuda.CUDAGraph()
        with torch.cuda.graph(parts["accept"], pool=pool):
            decide(logits, graphed.draw, drafts, requests.n_extra)
        parts["inject"] = torch.cuda.CUDAGraph()
        with torch.cuda.graph(parts["inject"], pool=pool):
            dflash.inject(drafter, taps, tokens, requests)
    parts["whole"] = graphed.graph
    times: dict[str, list[float]] = {name: [] for name in parts}
    for _ in range(iters):
        for name in ("draft", "target", "accept", "inject", "whole"):
            start, stop = torch.cuda.Event(enable_timing=True), torch.cuda.Event(enable_timing=True)
            start.record()
            parts[name].replay()
            stop.record()
            torch.cuda.synchronize()
            times[name].append(start.elapsed_time(stop))
    walls = []
    for _ in range(iters):
        t0 = time.perf_counter()
        stepper(plan)
        walls.append((time.perf_counter() - t0) * 1e3)
    got = {f"{name}_ms": float(np.median(v)) for name, v in times.items()}
    got["step_wall_ms"] = float(np.median(walls))
    got["outside_ms"] = got["step_wall_ms"] - got["whole_ms"]
    got["n_reqs_padded"], got["tokens_padded"] = plan.n_reqs_padded, plan.n_tokens_padded  # type: ignore[attr-defined]
    return got


def table(k0: list[dict], spec: list[dict]) -> str:
    lines = ["| corpus | B | K=0 req tok/s | K=0 total tok/s | DFlash req tok/s | DFlash total "
             "tok/s | accept | speedup (total) | preempted (k0/spec) |",
             "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for a, s in zip(k0, spec, strict=True):
        assert (a["corpus"], a["batch"]) == (s["corpus"], s["batch"]), (a, s)
        lines.append(f"| {a['corpus']} | {a['batch']} | {a['req_tok_s']:.1f} | "
                     f"{a['total_tok_s']:.1f} | {s['req_tok_s']:.1f} | {s['total_tok_s']:.1f} | "
                     f"{s['accept']:.2f} | {s['total_tok_s'] / a['total_tok_s']:.2f}x | "
                     f"{a['preempted']}/{s['preempted']} |")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--target-checkpoint", default="openai/gpt-oss-20b")
    ap.add_argument("--drafter-checkpoint", default="z-lab/gpt-oss-20b-DFlash")
    ap.add_argument("--batch", type=int, nargs="+", default=[1, 2, 4, 8, 16])
    ap.add_argument("--corpus", nargs="+", choices=("math", "raw"), default=["math", "raw"])
    ap.add_argument("--max-new", type=int, default=256)
    ap.add_argument("--max-seq-len", type=int, default=512)
    ap.add_argument("--num-slabs", type=int, default=2048)
    ap.add_argument("--timeout", type=float, default=900.0)
    ap.add_argument("--profile", action="store_true", help="spec child: the per-phase step breakdown")
    ap.add_argument("--profile-batch", type=int, nargs="+", default=[1, 16])
    ap.add_argument("--profile-after", type=int, default=24, help="hand steps before the timed plan")
    ap.add_argument("--profile-iters", type=int, default=20)
    ap.add_argument("--out", default=None, help="also write the results as JSON here")
    _fresh.add_phase_args(ap, ("k0", "spec"))
    args = ap.parse_args()
    assert max(args.batch) <= MAX_REQUESTS, (args.batch, MAX_REQUESTS)
    if args.phase is not None:
        return phase(args)

    from scripts import prove_dflash as prove
    from transformers import AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(args.target_checkpoint)
    corpora = {name: prove.encode_corpus(tokenizer, name)[0] for name in args.corpus}
    print(f"bench_spec: batches {args.batch}, corpora "
          f"{args.corpus}, max_new {args.max_new}, greedy, capture on", flush=True)
    got = {mode: _fresh.in_fresh_process("scripts.bench_spec", [*sys.argv[1:], "--phase", mode],
                                         {"corpora": corpora})
           for mode in ("k0", "spec")}
    print(f"\nbuild s: k0 {got['k0']['build_s']:.1f}, spec {got['spec']['build_s']:.1f}")
    print(table(got["k0"]["cells"], got["spec"]["cells"]))
    for row in got["spec"]["profile"]:
        print(f"step breakdown B={row['batch']} (T={row['tokens_padded']}, R={row['n_reqs_padded']}): "
              f"draft {row['draft_ms']:.2f} ms | target {row['target_ms']:.2f} | accept "
              f"{row['accept_ms']:.2f} | inject {row['inject_ms']:.2f} | whole graph "
              f"{row['whole_ms']:.2f} | outside graph {row['outside_ms']:.2f} (step wall {row['step_wall_ms']:.2f})")
    if args.out:
        import os

        os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
        with open(args.out, "w") as f:
            json.dump(got, f, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
