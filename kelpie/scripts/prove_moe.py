#!/usr/bin/env python3
"""gpt-oss-20b end to end through the MoE op: greedy K = 0 decode, tie-aware against a recorded
baseline, plus the weight/peak memory footprint.

Two verbs, one corpus (prove_dflash's raw + math prompts):

    record   greedy-decode every prompt; write tokens + memory to --out (JSON). Run once on the
             PRE-CHANGE tree: that file is the reference every later run is graded against.
    compare  greedy-decode again (any --kernels / --capture), then grade it two ways:
               exact     tokens == baseline tokens (reported, not gated: bf16 near-ties flip)
               teacher   ONE K = 0 prefill over prompt + baseline[:-1] on THIS tree; every
                         baseline token must be within TIE_ULPS bf16 steps of its row max. A
                         wrong MoE puts baseline tokens far below the max; a near-tie does not.

    drift    teacher-force the SAME token sequences (a recorded file's prompts + tokens) through
             each --impls entry on this GPU; grade every impl's logits against the first
             (the reference): argmax agreement, the reference's top token's distance below the
             impl's row max in bf16 steps (worst / how many rows past 1, 4, 8), max |logit diff|.
             Separates a near-tie (one row at the gate) from a kernel that is off everywhere.

    --cache DIR   build(cache=DIR) for every build: the first run over an empty DIR BUILDS (writes
                  the manifest, compiles into DIR/triton), a later run SERVES (checks the
                  manifest, freezes DIR, and any Triton compile raises). Triton's own listener
                  counts compiles vs disk-cache loads for the whole run.

    Every build runs in its own process (`kernels.bind` runs once per process): hidden
    `--phase decode|teacher|rows` children, results as JSON (scripts/_fresh.py). This process
    only tokenizes, grades and prints; BUILD vs SERVE is decided here once, before any child,
    so every build of one run is in the same mode (as when they shared a process).

    uv run --frozen --project kelpie/kelpie-http kelpie remote \\
        --gpu A100-80GB --volume kelpie-a1 --timeout 2400 -- \\
        'HF_HUB_OFFLINE=1 python -m scripts.prove_moe compare --baseline /data/moe/baseline.json \\
            --kernels moe=triton_kernels --cache /data/kernel-cache/gpt-oss-20b-a100-triton_kernels'
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from scripts import _fresh

if TYPE_CHECKING:
    import torch

TARGET = "kelpie_models.models.torch.gpt_oss"
MAX_NEW = 64
NUM_SLABS = 512
MAX_SEQ_LEN = 512
TIMEOUT_S = 900.0
GIB = 2**30


def parse_kernels(specs: list[str]) -> dict:
    """`moe=triton_kernels` -> {ops.moe: "triton_kernels"}. A name the tree does not declare is
    an AttributeError naming it -- the baseline tree has no `ops.moe`, and that is the point."""
    from kelpie_models.kernels import ops

    out = {}
    for spec in specs:
        name, impl = spec.split("=", 1)
        out[getattr(ops, name)] = impl
    return out


def weight_bytes(tree: object) -> int:
    """Every tensor reachable from the weight pytree, counted once by storage."""
    import dataclasses

    import torch

    seen: dict[int, int] = {}

    def walk(x: object) -> None:
        if isinstance(x, torch.Tensor):
            seen[x.untyped_storage().data_ptr()] = x.untyped_storage().nbytes()
        elif dataclasses.is_dataclass(x):
            for f in dataclasses.fields(x):
                walk(getattr(x, f.name))
        elif isinstance(x, tuple | list):
            for item in x:
                walk(item)

    walk(tree)
    return sum(seen.values())


def decode(target, prompts: list[list[int]], build_kw: dict, max_new: int
           ) -> tuple[list[list[int]], dict]:
    """Greedy K = 0 through `run()` (the Zig loop, Captured when capture=True). -> (tokens per
    prompt, memory)."""
    import gc

    import torch
    from scripts import prove_dflash as prove

    torch.cuda.reset_peak_memory_stats()
    runs = prove.decode_all(target, prompts, max_new, timeout_s=TIMEOUT_S, **build_kw)
    memory = {"peak_allocated_gib": torch.cuda.max_memory_allocated() / GIB}
    gc.collect()  # the run's weights, before the teacher build loads a second copy
    torch.cuda.empty_cache()
    seconds = sum(r.seconds for r in runs)
    tokens = sum(len(r.tokens) for r in runs)
    print(f"decoded {len(runs)} prompts, {tokens} tokens in {seconds:.1f}s "
          f"({tokens / seconds:.1f} tok/s sequential); peak allocated "
          f"{memory['peak_allocated_gib']:.2f} GiB", flush=True)
    return [r.tokens for r in runs], memory


def teacher_gate(target, prompts, streams: list[list[list[int]]], build_kw
                 ) -> tuple[list[tuple[list[str], float]], float]:
    """Every token of every stream (tokens per prompt) within TIE_ULPS of THIS tree's
    teacher-forced row max, all on ONE build. -> ([(fails, worst ulps)] per stream, weight GiB
    of this tree's pytree)."""
    import torch
    from kelpie_models.sdk.run import build
    from scripts.check_spec_teacher_forced import teacher_forced_logits

    n_layers = _n_layers(target)
    engine, step = build(target, taps=(("resid_post", n_layers - 1),),
                         **{**build_kw, "capture": False})
    engine.set(prefix_cache=False)
    gates: list[tuple[list[str], float]] = []
    try:
        weights_gib = weight_bytes(step.weights) / GIB
        for tokens in streams:
            fails: list[str] = []
            worst_all = 0.0
            for i, (prompt, generated) in enumerate(zip(prompts, tokens, strict=True)):
                logits = teacher_forced_logits(engine, step, target, prompt + generated[:-1])
                worst = _gate_rows(i, logits[len(prompt) - 1:], generated, fails)
                worst_all = max(worst_all, worst)
                print(f"  teacher {i}: {len(generated)} baseline tokens, worst {worst:.1f} steps",
                      flush=True)
            gates.append((fails, worst_all))
    finally:
        engine.close()
        del step
        torch.cuda.empty_cache()
    return gates, weights_gib


def _gate_rows(i: int, rows: torch.Tensor, generated: list[int], fails: list[str]) -> float:
    """Prompt i's generated tokens against their teacher-forced rows (rows[j] predicts
    generated[j]); appends each over TIE_ULPS to `fails`. -> the worst, in bf16 steps."""
    from scripts import prove_dflash as prove

    worst = 0.0
    for j, token in enumerate(generated):
        row = rows[j]
        top = float(row.max())
        ulps = prove.bf16_ulps(top - float(row[token]), top)
        worst = max(worst, ulps)
        if ulps > prove.TIE_ULPS:
            fails.append(f"prompt {i}: baseline token {j} ({token}) is {ulps:.1f} bf16 "
                         f"steps below this tree's row max (top1 {int(row.argmax())})")
    return worst


DRIFT_THRESHOLDS = (1.0, 4.0, 8.0)  # bf16 steps; 8 = prove.TIE_ULPS


def teacher_rows(target, sequences: list[tuple[list[int], list[int]]], build_kw: dict
                 ) -> list:
    """Teacher-forced logits [len(generated), V] (fp32, on the host) of every (prompt, generated)
    sequence, predicting each generated token, under `build_kw`'s kernels."""
    import torch
    from kelpie_models.sdk.run import build
    from scripts.check_spec_teacher_forced import teacher_forced_logits

    engine, step = build(target, taps=(("resid_post", _n_layers(target) - 1),),
                         **{**build_kw, "capture": False})
    engine.set(prefix_cache=False)
    rows = []
    try:
        for prompt, generated in sequences:
            logits = teacher_forced_logits(engine, step, target, prompt + generated[:-1])
            rows.append(logits[len(prompt) - 1:].cpu())
            assert rows[-1].shape[0] == len(generated), (rows[-1].shape, len(generated))
    finally:
        engine.close()
        del step
        torch.cuda.empty_cache()
    return rows


def drift_stats(reference: list, candidate: list) -> dict:
    """How far `candidate`'s rows are from `reference`'s, over every row of every sequence."""
    import torch
    from scripts import prove_dflash as prove

    rows = agree = 0
    max_abs = 0.0
    gaps: list[float] = []
    for ref, got in zip(reference, candidate, strict=True):
        assert ref.shape == got.shape, (ref.shape, got.shape)
        ref_top = ref.argmax(dim=-1)
        rows += ref.shape[0]
        agree += int((got.argmax(dim=-1) == ref_top).sum())
        max_abs = max(max_abs, float((got - ref).abs().max()))
        got_max = got.max(dim=-1).values
        got_at_ref_top = got.gather(-1, ref_top[:, None])[:, 0]
        gaps += [prove.bf16_ulps(float(top - at), float(top))
                 for top, at in zip(got_max, got_at_ref_top, strict=True)]
    over = {f"rows_over_{t:g}": sum(g > t for g in gaps) for t in DRIFT_THRESHOLDS}
    return {"rows": rows, "argmax_agree": agree, "worst_steps": max(gaps), **over,
            "max_abs_logit_diff": max_abs, "mean_steps": float(torch.tensor(gaps).mean())}


def drift(recorded: dict, impls: list[str], child: Callable[[str, dict], dict]
          ) -> list[tuple[str, dict]]:
    """Every impl against impls[0] on the recorded sequences, each impl's rows from its own
    `--phase rows` child (`child(phase, payload)`). -> [(impl, stats)] (impls[1:])."""
    import tempfile

    import torch

    sequences = list(zip(recorded["prompts"], recorded["tokens"], strict=True))
    out = []
    with tempfile.TemporaryDirectory(prefix="kelpie-drift-") as tmp:

        def rows_of(impl: str) -> list:
            path = Path(tmp) / f"{impl}.pt"
            child("rows", {"sequences": sequences, "impl": impl, "rows_path": str(path)})
            return torch.load(path)

        reference = rows_of(impls[0])
        for impl in impls[1:]:
            stats = drift_stats(reference, rows_of(impl))
            print(f"drift {impl} vs {impls[0]}: {json.dumps(stats)}", flush=True)
            out.append((impl, stats))
    return out


def _n_layers(target) -> int:
    from kelpie_models.sdk.hf import resolve_hf

    with open(resolve_hf(target.CHECKPOINT)[0]) as f:
        return int(target.config_from_hf(json.load(f)).n_layers)


def count_triton_compiles() -> dict[str, int]:
    """Install a triton compilation listener; -> the live counts {compiled, disk_hits}. `freeze`
    chains onto it (sdk/cache.py), so the counts survive a serve-mode build."""
    counts = {"compiled": 0, "disk_hits": 0}
    try:
        import triton
    except ImportError:
        return counts

    def listen(**kwargs: object) -> None:
        counts["disk_hits" if kwargs.get("cache_hit") else "compiled"] += 1

    triton.knobs.compilation.listener = listen
    return counts


def cache_verb(cache: Path | None) -> bool:
    """-> build's allow_build: BUILD over an empty cache, SERVE over a built one. Decided once
    per run, in the parent, before any child builds (and writes the manifest)."""
    if cache is None:
        return False
    built = (cache / "manifest.json").is_file()
    print(f"cache {cache}: {'SERVE (manifest found)' if built else 'BUILD (no manifest)'}",
          flush=True)
    return not built


def build_kwargs(args: argparse.Namespace, allow_build: bool) -> dict:
    """Every build's kwargs, from the flags (a --phase child parses the parent's own) and the
    parent's cache verb. build(**this): no cache kwargs without --cache."""
    from kelpie_models.sdk.tiers import Capacity

    cache = {"cache": args.cache, "allow_build": allow_build} if args.cache is not None else {}
    return dict(device="cuda", capture=args.capture, kernels=parse_kernels(args.kernels),
                capacity=Capacity(max_seq_len=MAX_SEQ_LEN, num_slabs=NUM_SLABS), **cache)


def phase(args: argparse.Namespace) -> int:
    """A --phase child: ONE build, its result (plus its Triton compile counts) to --phase-out."""
    sent = _fresh.payload(args)
    target = importlib.import_module(TARGET)
    build_kw = build_kwargs(args, sent["allow_build"])
    compiles = count_triton_compiles()
    if args.phase == "decode":
        tokens, memory = decode(target, sent["prompts"], build_kw, args.max_new)
        result = {"tokens": tokens, "memory": memory}
    elif args.phase == "teacher":
        gates, weights_gib = teacher_gate(target, sent["prompts"], sent["streams"], build_kw)
        result = {"gates": gates, "weights_gib": weights_gib}
    else:
        import torch
        from kelpie_models.kernels import ops

        rows = teacher_rows(target, [tuple(s) for s in sent["sequences"]],
                            {**build_kw, "kernels": {ops.moe: sent["impl"]}})
        torch.save(rows, sent["rows_path"])
        result = {}
    # build(cache=) points TRITON_CACHE_DIR in the child's env; the parent reports the child's.
    triton_dir = os.environ.get("TRITON_CACHE_DIR", "default ~/.triton/cache")
    return _fresh.respond(args, {**result, "compiles": compiles, "triton_cache_dir": triton_dir})


def exact_report(baseline: list[list[int]], got: list[list[int]]) -> int:
    """Print per-prompt exact match / first divergence. -> prompts that match exactly."""
    from scripts import prove_dflash as prove

    same = 0
    for i, (a, b) in enumerate(zip(baseline, got, strict=True)):
        if a == b:
            same += 1
            print(f"  exact {i}: match ({len(a)} tokens)")
        else:
            at = prove._first_diff(a, b)  # noqa: SLF001
            print(f"  exact {i}: diverges at {at}: base {a[max(0, at - 2):at + 3]} "
                  f"got {b[max(0, at - 2):at + 3]}")
    return same


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("verb", choices=("record", "compare", "drift"))
    ap.add_argument("--out", type=Path, help="record: where the baseline JSON goes")
    ap.add_argument("--baseline", type=Path, help="compare: the recorded baseline JSON")
    ap.add_argument("--kernels", action="append", default=[], help="op=impl (repeatable)")
    ap.add_argument("--capture", action="store_true", help="decode through CUDA graphs")
    ap.add_argument("--cache", type=Path, help="kernel build cache (see module doc)")
    ap.add_argument("--max-new", type=int, default=MAX_NEW, help="record/compare: tokens per prompt")
    ap.add_argument("--tokens", type=Path, help="drift: a recorded JSON whose sequences to replay")
    ap.add_argument("--impls", default="reference,triton_kernels,triton_kernels_hopper,flashinfer",
                    help="drift: moe impls, the first is the one graded against")
    _fresh.add_phase_args(ap, ("decode", "teacher", "rows"))
    args = ap.parse_args()
    if args.phase is not None:
        return phase(args)

    from scripts import prove_dflash as prove
    from transformers import AutoTokenizer

    target = importlib.import_module(TARGET)
    tokenizer = AutoTokenizer.from_pretrained(target.CHECKPOINT)
    raw, _ = prove.encode_corpus(tokenizer, "raw")
    math, _ = prove.encode_corpus(tokenizer, "math")
    prompts = raw + math
    if args.verb == "drift" and (args.tokens is None or args.kernels):
        ap.error("drift takes --tokens and --impls (not --kernels)")
    allow_build = cache_verb(args.cache)
    compiles = {"compiled": 0, "disk_hits": 0}  # summed over every child's builds
    triton_dir: list[str] = []  # the children's TRITON_CACHE_DIR (same --cache, same dir)

    def child(which: str, sent: dict) -> dict:
        out = _fresh.in_fresh_process("scripts.prove_moe", [*sys.argv[1:], "--phase", which],
                                      {**sent, "allow_build": allow_build})
        for k in compiles:
            compiles[k] += out["compiles"][k]
        triton_dir.append(out["triton_cache_dir"])
        return out

    if args.verb == "drift":
        recorded = json.loads(args.tokens.read_text())
        assert recorded["prompts"] == prompts, "tokens were recorded on a different corpus"
        drift(recorded, args.impls.split(","), child)
        return 0

    decoded = child("decode", {"prompts": prompts})
    tokens, memory = decoded["tokens"], decoded["memory"]

    if args.verb == "record":
        assert args.out is not None, "record needs --out"
        # Self-consistency: the tree's own tokens against its own teacher-forced rows. Calibrates
        # the gate (decode vs prefill batch shapes) and measures the weight footprint.
        gated = child("teacher", {"prompts": prompts, "streams": [tokens]})
        [(fails, worst)], weights_gib = gated["gates"], gated["weights_gib"]
        memory["weights_gib"] = weights_gib
        print(f"self teacher-forced worst {worst:.1f} bf16 steps, {len(fails)} over the gate; "
              f"weights {weights_gib:.2f} GiB")
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps({"prompts": prompts, "tokens": tokens,
                                        "memory": memory}) + "\n")
        print(f"recorded {len(prompts)} prompts -> {args.out}")
        return 0

    assert args.baseline is not None, "compare needs --baseline"
    recorded = json.loads(args.baseline.read_text())
    assert recorded["prompts"] == prompts, "baseline was recorded on a different corpus"
    same = exact_report(recorded["tokens"], tokens)
    # Both token streams against THIS tree's teacher-forced rows (one build): the baseline's
    # (is the new MoE the same function?) and its own decode's (does decode agree with prefill?).
    gated = child("teacher", {"prompts": prompts, "streams": [recorded["tokens"], tokens]})
    [(fails, worst), (own_fails, own_worst)] = gated["gates"]
    weights_gib = gated["weights_gib"]
    fails += [f"own decode: {f}" for f in own_fails]
    print(f"own decode vs own teacher-forced rows: worst {own_worst:.1f} bf16 steps")
    print(f"memory: weights {weights_gib:.2f} GiB; peak allocated during decode "
          f"{memory['peak_allocated_gib']:.2f} GiB (baseline: weights "
          f"{recorded['memory']['weights_gib']:.2f} GiB, peak "
          f"{recorded['memory']['peak_allocated_gib']:.2f} GiB)")
    print(f"triton: {compiles['compiled']} kernels compiled, {compiles['disk_hits']} loaded from "
          f"the disk cache ({triton_dir[-1]})")
    print(f"exact: {same}/{len(prompts)} prompts token-identical; teacher-forced worst "
          f"{worst:.1f} bf16 steps (gate {prove.TIE_ULPS})")
    if fails:
        print(f"{len(fails)} FAILED:")
        for f in fails:
            print("  " + f)
        return 1
    print("PASSED: every baseline token is within the tie gate of this tree's greedy choice")
    return 0


if __name__ == "__main__":
    sys.exit(main())
