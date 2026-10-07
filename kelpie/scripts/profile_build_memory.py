#!/usr/bin/env python3
"""Where build's peak GPU memory goes: per op, then per line of one op.

    build   gpt-oss-20b build (prove_moe's capacity: max_seq_len 512, 512 slabs) under a
            TorchDispatchMode that brackets every top-level op with reset_peak_memory_stats /
            max_memory_allocated: prints each (warm step, op)'s transient peak above what was
            allocated when it started, the largest first, and the whole build's peak. With
            --snapshot PATH, torch.cuda.memory._record_memory_history runs across the build and
            the snapshot is dumped there (open it at pytorch.org/memory_viz).
    op      the paged_attention REFERENCE alone, at a gpt-oss prefill (default the build's
            largest: 2 x 512 rows, sinks, window 0 and 128), traced line by line: each line's
            transient peak and the bytes it leaves live.

    uv run --frozen --project kelpie/kelpie-http kelpie remote \\
        --gpu A100-80GB --volume kelpie-a1 --model openai/gpt-oss-20b -- \\
        'HF_HUB_OFFLINE=1 python -m scripts.profile_build_memory build && \\
         python -m scripts.profile_build_memory op'
"""

from __future__ import annotations

import argparse
import sys
import time
from collections import defaultdict

GIB = 2**30
MIB = 2**20
TOP = 12


def build_verb(args: argparse.Namespace) -> int:
    import importlib

    import torch
    from torch.utils._python_dispatch import TorchDispatchMode

    from kelpie_models.kernels.op import STEP_NOTE
    from kelpie_models.sdk.run import build
    from kelpie_models.sdk.tiers import Capacity

    peaks: dict[tuple[str, str], int] = defaultdict(int)
    calls: dict[tuple[str, str], int] = defaultdict(int)
    absolute = [0]  # the build's own peak: the largest (allocated at op start + op's peak)

    class PeakPerOp(TorchDispatchMode):
        def __torch_dispatch__(self, func, types, a=(), kw=None):  # noqa: ANN001, ANN204
            if torch.cuda.is_current_stream_capturing():
                return func(*a, **(kw or {}))
            before = torch.cuda.memory_allocated()
            torch.cuda.reset_peak_memory_stats()
            out = func(*a, **(kw or {}))
            key = (str(STEP_NOTE.get()), f"{func.namespace}::{func.__name__.split('.')[0]}")
            peak = torch.cuda.max_memory_allocated()
            peaks[key] = max(peaks[key], peak - before)
            absolute[0] = max(absolute[0], peak)
            calls[key] += 1
            return out

    if args.snapshot:
        torch.cuda.memory._record_memory_history(max_entries=200_000)
    target = importlib.import_module("kelpie_models.models.torch.gpt_oss")
    torch.cuda.reset_peak_memory_stats()
    t0 = time.perf_counter()
    kernels = {}
    if args.attention:
        from kelpie_models.kernels import ops

        kernels[ops.paged_attention] = args.attention
    kw = dict(device="cuda", capture=args.capture, kernels=kernels,
              capacity=Capacity(max_seq_len=512, num_slabs=512))
    if args.bare:  # no per-op bracketing: the build's own time and torch's own peak
        built = build(target, **kw)
        seconds = time.perf_counter() - t0
        print(f"bare build {seconds:.1f}s (capture={args.capture}); {built.table.line()}")
        print(f"build peak allocated {torch.cuda.max_memory_allocated() / GIB:.2f} GiB")
        return 0
    with PeakPerOp():
        built = build(target, **kw)
    seconds = time.perf_counter() - t0
    print(f"build {seconds:.1f}s (capture={args.capture}); {built.table.line()}")
    print(f"build peak allocated {absolute[0] / GIB:.2f} GiB (max over ops of start + transient)")
    print(f"allocated after build {torch.cuda.memory_allocated() / GIB:.2f} GiB")
    ranked = sorted(peaks.items(), key=lambda kv: -kv[1])
    print(f"top {TOP} (warm step, op) transient peaks above the op's starting allocation:")
    for (step, name), peak in ranked[:TOP]:
        print(f"  {peak / GIB:8.3f} GiB  {name:28s} {step:22s} x{calls[(step, name)]}")
    per_op: dict[str, int] = defaultdict(int)
    for (_, name), peak in peaks.items():
        per_op[name] = max(per_op[name], peak)
    print("max per op over every step:")
    for name, peak in sorted(per_op.items(), key=lambda kv: -kv[1])[:TOP]:
        print(f"  {peak / GIB:8.3f} GiB  {name}")
    if args.snapshot:
        torch.cuda.memory._dump_snapshot(args.snapshot)
        torch.cuda.memory._record_memory_history(enabled=None)
        print(f"snapshot -> {args.snapshot}")
    return 0


def op_verb(args: argparse.Namespace) -> int:
    import importlib

    import torch

    # The module, not `ops.paged_attention` (the package rebinds that name to the Op).
    pa = importlib.import_module("kelpie_models.kernels.ops.paged_attention")

    reference = pa.paged_attention.reference
    traced = {reference.__code__, pa._visible.__code__, pa._softmax_with_sinks.__code__}
    for window in (0, 128):
        batch = pa.Batch(entries=((0, args.rows),) * args.reqs, tokens=args.reqs * args.rows,
                         reqs=args.reqs, window=window)
        call = pa.sample(batch, "cuda", torch.bfloat16)
        torch.cuda.synchronize()
        base = torch.cuda.memory_allocated()
        lines: list[tuple[int, str, int, int]] = []
        last: dict[str, int] = {}

        def tracer(frame, event, arg):  # noqa: ANN001, ANN202
            if frame.f_code not in traced:
                return None
            if event in {"line", "return"}:
                name = frame.f_code.co_name
                torch.cuda.synchronize()
                peak = torch.cuda.max_memory_allocated() - base
                if name in last:
                    lines.append((last[name], name, peak,
                                  torch.cuda.memory_allocated() - base))
                last[name] = frame.f_lineno
                torch.cuda.reset_peak_memory_stats()
            return tracer

        torch.cuda.reset_peak_memory_stats()
        sys.settrace(tracer)
        try:
            out = reference(*call)
        finally:
            sys.settrace(None)
        del out
        print(f"reference paged_attention, T={batch.tokens} ({args.reqs} x {args.rows} rows), "
              f"window {window}; per line: transient peak / live after, above the inputs")
        source = __import__("inspect").getsourcelines
        texts = {}
        for fn in (reference, pa._visible, pa._softmax_with_sinks):
            src, start = source(fn)
            texts.update({start + i: s.strip() for i, s in enumerate(src)})
        worst = max(peak for _, _, peak, _ in lines)
        for lineno, name, peak, live in lines:
            if peak >= args.min_mib * MIB:
                print(f"  {peak / GIB:7.3f} {live / GIB:7.3f} GiB  {name}:{lineno:<4d} "
                      f"{texts.get(lineno, '')[:90]}")
        print(f"  op peak {worst / GIB:.3f} GiB above inputs")
        del call
        torch.cuda.empty_cache()
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="verb", required=True)
    b = sub.add_parser("build")
    b.add_argument("--capture", action=argparse.BooleanOptionalAction, default=True)
    b.add_argument("--snapshot", default=None)
    b.add_argument("--bare", action="store_true", help="time and peak only, no per-op mode")
    b.add_argument("--attention", default=None, help="kernels={ops.paged_attention: this}")
    o = sub.add_parser("op")
    o.add_argument("--reqs", type=int, default=2)
    o.add_argument("--rows", type=int, default=512)
    o.add_argument("--min-mib", type=float, default=16.0)
    args = ap.parse_args()
    return build_verb(args) if args.verb == "build" else op_verb(args)


if __name__ == "__main__":
    sys.exit(main())
