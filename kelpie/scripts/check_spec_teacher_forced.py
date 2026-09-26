#!/usr/bin/env python3
"""Teacher-forced spec gate: is every token spec decode emitted a greedy choice of the target?

prove_dflash compares spec against a K = 0 run; when the two diverge at a bf16 near-tie, which
one is "right" is a question of numerics, not of spec logic. This gate asks a sharper question
with one reference for all positions: run spec decode (loop (b), scripts/prove_dflash.py), then
ONE K = 0 prefill over prompt + spec_tokens[:-1] with the last layer's residual tapped, and
compute every row's logits as lm_head(ln_f(taps[resid_post, L - 1])) -- the target's own
prediction for each generated position, teacher-forced on spec's own output. Every generated
token must be within TIE_ULPS bf16 steps of its row's max. A spec bug (a wrong draft accepted,
a lost context row, a state not rolled back) puts a token far below the row max; a near-tie
does not.

The spec run and the teacher-forced build each run in their own process (`kernels.bind` runs
once per process): hidden `--phase spec` / `--phase teacher` children, results as JSON
(scripts/_fresh.py). The teacher child grades exactly the tokens the spec child emitted.

    uv run --frozen --project box box run \\
        --gpu A100-80GB --volume kelpie-a1 --timeout 2400 -- \\
        'HF_HUB_OFFLINE=1 python -m scripts.check_spec_teacher_forced --corpus math --max-new 256'
"""

from __future__ import annotations

import argparse
import sys

import numpy as np
from scripts import _fresh


def teacher_forced_logits(engine, step, model, sequence: list[int]):
    """[len(sequence), V] logits of a K = 0 prefill over `sequence` (chunked as the core
    likes), via the last layer's tapped residual. Prefix cache off: every row is computed."""
    import torch

    n_layers = int(step.config.n_layers)
    key = ("resid_post", n_layers - 1)
    rows = torch.empty(len(sequence), int(step.config.hidden), dtype=step.dtype, device=step.device)
    seen = np.zeros(len(sequence), dtype=bool)
    rid = engine.submit(sequence, max_new_tokens=1)
    while True:
        plan = engine.plan()
        if plan is None:
            break
        logits = step.forward(plan)
        taps = step.last_taps.got[key]
        for r in range(plan.n_reqs):
            assert int(plan.requests.req_ids[r]) == rid
            q0, q1 = plan.requests.rows(r)
            positions = plan.tokens.positions[q0:q1].astype(np.int64)
            rows[torch.from_numpy(positions).to(step.device)] = taps[q0:q1]
            seen[positions] = True
        engine.commit(step.sample(logits, plan))
    assert engine.poll(rid).finished
    assert seen.all(), "a position was never computed (a prefix hit?)"
    with torch.no_grad():
        normed = model.rms_norm_fp32(rows, step.weights.ln_f, step.config.hidden, step.config.eps)
        return (normed @ step.weights.lm_head.T).float()


def build_kwargs(args: argparse.Namespace) -> dict:
    """The build kwargs of both builds, from the flags (a --phase child parses the same)."""
    from kelpie_models.sdk.tiers import Capacity
    from scripts.prove_moe import parse_kernels

    return dict(device=args.device, capture=False, kernels=parse_kernels(args.kernels),
                capacity=Capacity(max_seq_len=512, num_slabs=args.num_slabs))


def spec_phase(args: argparse.Namespace, prompts: list[list[int]]) -> dict:
    """The child's spec run (or the --no-spec K = 0 control). -> {runs, mix}."""
    import importlib

    from scripts import prove_dflash as prove

    target = importlib.import_module(f"kelpie_models.models.torch.{args.target}")
    build_kw = build_kwargs(args)
    if args.capture:  # the spec run only: the teacher build is the eager reference
        assert not args.no_spec, "--capture is DFlashStep's graphs; --no-spec has no drafter"
        build_kw = {**build_kw, "capture": True}
    if args.no_spec:
        spec = prove.decode_batch_k0(target, prompts, args.max_new, timeout_s=args.timeout,
                                     max_batch_tokens=args.max_batch_tokens, **build_kw)
        mix = None
    else:
        drafter = importlib.import_module("kelpie_models.models.torch.dflash")
        spec, mix = prove.spec_runs(target, drafter, prompts, args, build_kw)
    return {"runs": [prove.run_to_json(r) for r in spec], "mix": mix}


def teacher_phase(args: argparse.Namespace, prompts: list[list[int]],
                  tokens: list[list[int]]) -> dict:
    """The child's ONE K = 0 build: every generated token's distance below its teacher-forced
    row max. -> {rows: per prompt, per token [bf16 steps below the max, the row's top1]}."""
    import importlib
    import json

    from kelpie_models.sdk.hf import resolve_hf
    from kelpie_models.sdk.run import build
    from scripts import prove_dflash as prove

    target = importlib.import_module(f"kelpie_models.models.torch.{args.target}")
    with open(resolve_hf(target.CHECKPOINT)[0]) as f:
        n_layers = int(target.config_from_hf(json.load(f)).n_layers)
    engine, step = build(target, taps=(("resid_post", n_layers - 1),), **build_kwargs(args))
    engine.set(prefix_cache=False)
    rows = []
    try:
        for prompt, generated in zip(prompts, tokens, strict=True):
            logits = teacher_forced_logits(engine, step, target, prompt + generated[:-1])
            graded = []
            for j, token in enumerate(generated):
                row = logits[len(prompt) - 1 + j]
                top = float(row.max())
                graded.append((prove.bf16_ulps(top - float(row[token]), top), int(row.argmax())))
            rows.append(graded)
    finally:
        engine.close()
    return {"rows": rows}


def phase(args: argparse.Namespace) -> int:
    """A --phase child: one build, its result to --phase-out."""
    sent = _fresh.payload(args)
    if args.phase == "spec":
        return _fresh.respond(args, spec_phase(args, sent["prompts"]))
    return _fresh.respond(args, teacher_phase(args, sent["prompts"], sent["tokens"]))


def in_child(which: str, sent: dict) -> dict:
    """`phase` in a fresh process, with this process's own flags."""
    return _fresh.in_fresh_process("scripts.check_spec_teacher_forced",
                                   [*sys.argv[1:], "--phase", which], sent)


def main() -> int:  # noqa: PLR0915
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--target", default="gpt_oss")
    ap.add_argument("--target-checkpoint", default="openai/gpt-oss-20b")
    ap.add_argument("--drafter-checkpoint", default="z-lab/gpt-oss-20b-DFlash")
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--max-new", type=int, default=256)
    ap.add_argument("--num-slabs", type=int, default=512)
    ap.add_argument("--timeout", type=float, default=900.0)
    ap.add_argument("--corpus", choices=("raw", "math"), default="math")
    ap.add_argument("--batched", action="store_true", help="spec run submits every prompt at once")
    ap.add_argument("--max-batch-tokens", type=int, default=64)
    ap.add_argument("--require-preemption", action="store_true", help="fail unless the batched run preempts")
    ap.add_argument("--no-spec", action="store_true",
                    help="control: gate a K = 0 batched run instead (what batch shape alone does)")
    ap.add_argument("--loop", choices=("hand", "native"), default="hand",
                    help="spec run: the caller-written loop, or run()'s Zig loop stepping DFlashStep")
    ap.add_argument("--capture", action="store_true",
                    help="the spec run replays DFlashStep's CUDA graphs (the teacher stays eager)")
    ap.add_argument("--kernels", action="append", default=[],
                    help="op=impl (repeatable), e.g. moe=reference; default: the device's defaults")
    _fresh.add_phase_args(ap, ("spec", "teacher"))
    args = ap.parse_args()
    # The hand loops call dflash.step (eager): only the native loop steps DFlashStep's graphs.
    assert not args.capture or args.loop == "native", "--capture needs --loop native"
    if args.phase is not None:
        return phase(args)

    from scripts import prove_dflash as prove
    from transformers import AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(args.target_checkpoint)
    prompts, corpus = prove.encode_corpus(tokenizer, args.corpus)
    if args.batched:  # more concurrent requests than one corpus: both, in one batch
        other = prove.encode_corpus(tokenizer, "raw" if args.corpus == "math" else "math")
        prompts, corpus = prompts + other[0], corpus + other[1]

    fails: list[str] = []
    print(f"spec loop: {args.loop}", flush=True)
    if args.no_spec:
        assert args.batched, "--no-spec is the control for --batched"
    got = in_child("spec", {"prompts": prompts})
    spec, mix = [prove.run_from_json(r) for r in got["runs"]], got["mix"]
    if args.batched and not args.no_spec:
        print(f"batch mix: {mix}", flush=True)
        fails += [f"batched run never exercised {k}" for k in ("mixed", "degraded") if mix[k] == 0]
        if args.require_preemption and mix["preempted"] == 0:
            fails.append("--require-preemption: the batched run never preempted (lower --num-slabs)")
    if not args.batched:  # one request at a time: summed wall times are the run's wall time
        seconds = sum(r.seconds for r in spec)
        n_tokens = sum(len(r.tokens) for r in spec)
        print(f"spec decode: {n_tokens} tokens in {seconds:.1f}s = {n_tokens / seconds:.1f} "
              f"tok/s (sequential requests; capture {'on' if args.capture else 'off'})",
              flush=True)

    worst_overall = 0.0
    graded = in_child("teacher", {"prompts": prompts, "tokens": [r.tokens for r in spec]})["rows"]
    for i, (run, rows) in enumerate(zip(spec, graded, strict=True)):
        generated = run.tokens
        worst, worst_at = 0.0, -1
        for j, (token, (ulps, top1)) in enumerate(zip(generated, rows, strict=True)):
            if ulps > worst:
                worst, worst_at = ulps, j
            if ulps > prove.TIE_ULPS:
                fails.append(f"{i + 1}/{len(prompts)}: generated token {j} ({token}) is {ulps:.1f} "
                             f"bf16 steps below its row max (top1 {top1})")
        worst_overall = max(worst_overall, worst)
        status = "FAIL" if any(f.startswith(f"{i + 1}/") for f in fails) else "PASS"
        print(f"  [{status}] {i + 1}/{len(prompts)} {corpus[i][:30]!r}: {len(generated)} tokens, "
              f"accept_len {run.stats.acceptance_length:.2f}, worst {worst:.1f} bf16 steps below "
              f"row max (at {worst_at})", flush=True)
    vs = sum(r.stats.verify_steps for r in spec)
    acc = sum(r.stats.accepted for r in spec)
    print(f"mean acceptance length: {1 + acc / max(vs, 1):.2f} over {vs} verify steps")
    for i, run in enumerate(spec):
        if run.stats.verify_steps == 0 or run.stats.accepted == 0:
            fails.append(f"{i + 1}/{len(prompts)}: no draft accepted over {run.stats.verify_steps} verify steps")
    print(f"worst generated token: {worst_overall:.1f} bf16 steps below its teacher-forced row max "
          f"(gate {prove.TIE_ULPS})")
    if fails:
        print(f"{len(fails)} FAILED:")
        for f in fails:
            print("  " + f)
        return 1
    print(f"PASSED: every generated token is within {prove.TIE_ULPS} bf16 steps of the target's "
          f"teacher-forced greedy choice")
    return 0


if __name__ == "__main__":
    sys.exit(main())
