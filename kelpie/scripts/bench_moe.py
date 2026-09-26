#!/usr/bin/env python3
"""Per-op proof for `kelpie::moe`: correctness vs the reference, CUDA-graph capture, timing.

Every impl is called DIRECTLY (its registered fn, not through the dispatcher), on gpt-oss-20b
shapes (hidden 2880, intermediate 2880, 32 experts, top-4) unless a case says otherwise.

  correct   truth = the reference body in fp64; budget = `bench.correctness.error_budget`
            (vendored crucible@dfb735f: max(2 x the bf16 reference's own error, 2e-2 x
            |truth|max)). The bf16 reference is graded too -- it passes by construction, and
            its err is the scale every backend is read against.
  capture   capture ONE call in a CUDA graph, write NEW h / routing into the captured buffers,
            replay, compare to an eager call on the same new inputs. Passes only if the impl
            has no host sync and no routing-dependent host control flow.
  time      median of CUDA-event-timed graph replays at decode buckets, eager at the prefill
            shape; microseconds.

    uv run --frozen --project box box run \\
        --gpu A100-80GB --volume kelpie-a1 -- \\
        'python -m scripts.bench_moe --impls reference,triton_kernels --out /data/moe/bench-a100.json'
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

GPT_OSS = dict(hidden=2880, intermediate=2880, experts=32, top_k=4)
DECODE = (1, 2, 4, 8, 16, 32, 64, 128, 256)
PREFILL = 2048
CAPTURE_TOKENS = 8
REPLAYS = 50
WARMUP = 5
EAGER_REPEATS = 10


def cases():
    """(label, Shape, seed): gpt-oss shapes at three token counts x two seeds, expert-parallel
    halves (a local slice; some rows route to no local expert), and a small odd shape."""
    from kelpie_models.kernels.ops.moe import Shape

    out = []
    for tokens in (1, 16, 128):
        for seed in (0, 1):
            out.append((f"gpt-oss T={tokens} s{seed}", Shape(tokens=tokens, **GPT_OSS), seed))
    for offset in (0, 16):
        shape = Shape(tokens=64, hidden=2880, intermediate=2880, experts=16, top_k=4,
                      expert_offset=offset, global_experts=32)
        out.append((f"ep half @{offset} T=64", shape, 2))
    out.append(("small M=256 I=128 E=8 k=2 T=33",
                Shape(tokens=33, hidden=256, intermediate=128, experts=8, top_k=2), 3))
    return out


def impl_fn(name: str):
    from kelpie_models.kernels import ops

    return ops.moe.reference if name == "reference" else ops.moe.impls[name].fn


def correctness(impls: list[str]) -> list[dict]:
    import torch

    from kelpie_models.bench.correctness import error_budget
    from kelpie_models.kernels import ops
    from kelpie_models.kernels.ops.moe import sample

    rows = []
    for label, shape, seed in cases():
        args = sample(shape, "cuda", torch.bfloat16, seed)
        truth = ops.moe.reference(*_upcast(args))
        ref = ops.moe.reference(*args)
        budget = error_budget(truth, ref)
        scale = truth.abs().max().item()
        for name in impls:
            row = {"case": label, "impl": name, "budget": budget, "scale": scale}
            try:
                out = impl_fn(name)(*args)
                torch.cuda.synchronize()
                err = (out.double() - truth).abs().max().item()
                row.update(err=err, verdict="pass" if err <= budget else "FAIL")
            except Exception as exc:  # noqa: BLE001 -- a throwing backend is a row, not a crash
                row.update(err=None, verdict=f"error: {type(exc).__name__}: {str(exc)[:160]}")
            rows.append(row)
            print(f"  {label:32s} {name:15s} {row['verdict']:6.60s} err {row['err']} "
                  f"budget {budget:.4g} (|truth|max {scale:.3g})", flush=True)
        del truth, ref, args
        torch.cuda.empty_cache()
    return rows


def _upcast(args: tuple) -> tuple:
    import torch

    return tuple(a.double() if isinstance(a, torch.Tensor) and a.dtype.is_floating_point else a
                 for a in args)


def capture(impls: list[str]) -> list[dict]:
    """Capture one call; replay on NEW inputs written into the captured buffers."""
    import torch

    from kelpie_models.kernels.ops.moe import Shape, sample

    shape = Shape(tokens=CAPTURE_TOKENS, **GPT_OSS)
    rows = []
    for name in impls:
        fn = impl_fn(name)
        static = list(sample(shape, "cuda", torch.bfloat16, seed=10))
        fresh = sample(shape, "cuda", torch.bfloat16, seed=11)  # only its h / routing are used
        row = {"impl": name}
        try:
            fn(*static)  # eager warm: lazy init, JIT, one-time weight conversion
            torch.cuda.synchronize()
            stream = torch.cuda.Stream()
            stream.wait_stream(torch.cuda.current_stream())
            graph = torch.cuda.CUDAGraph()
            with torch.cuda.stream(stream), torch.cuda.graph(graph, stream=stream):
                out = fn(*static)
            for i in (0, 1, 2):  # h, topk_ids, topk_weights: new values, same buffers
                static[i].copy_(fresh[i])
            graph.replay()
            torch.cuda.synchronize()
            eager = fn(*static)
            diff = (out.double() - eager.double()).abs().max().item()
            moved = not torch.equal(out, fn(*sample(shape, "cuda", torch.bfloat16, seed=10)))
            row.update(ok=diff <= 1e-2 * eager.abs().max().item() and moved, max_diff=diff,
                       routing_changed_output=moved)
        except Exception as exc:  # noqa: BLE001
            row.update(ok=False, error=f"{type(exc).__name__}: {str(exc)[:200]}")
        rows.append(row)
        print(f"  capture {name:15s} {row}", flush=True)
    return rows


def time_graph(fn, args: tuple) -> float:
    """Median us per replay of one captured call."""
    import torch

    fn(*args)
    torch.cuda.synchronize()
    stream = torch.cuda.Stream()
    stream.wait_stream(torch.cuda.current_stream())
    graph = torch.cuda.CUDAGraph()
    with torch.cuda.stream(stream), torch.cuda.graph(graph, stream=stream):
        fn(*args)
    for _ in range(WARMUP):
        graph.replay()
    times = []
    for _ in range(REPLAYS):
        start, end = torch.cuda.Event(enable_timing=True), torch.cuda.Event(enable_timing=True)
        start.record()
        graph.replay()
        end.record()
        end.synchronize()
        times.append(start.elapsed_time(end) * 1e3)
    return statistics.median(times)


def time_eager(fn, args: tuple) -> float:
    from kelpie_models.bench.timing import measure

    return measure(fn, args, repeats=EAGER_REPEATS)


def timing(impls: list[str], decode: tuple[int, ...], prefill: int) -> list[dict]:
    import torch

    from kelpie_models.kernels.ops.moe import Shape, sample

    rows = []
    for name in impls:
        fn = impl_fn(name)
        for tokens in (*decode, prefill):
            args = sample(Shape(tokens=tokens, **GPT_OSS), "cuda", torch.bfloat16, seed=20)
            row = {"impl": name, "tokens": tokens}
            try:
                t0 = time.perf_counter()
                fn(*args)  # first call: JIT / weight conversion, reported, not timed below
                torch.cuda.synchronize()
                row["first_call_ms"] = (time.perf_counter() - t0) * 1e3
                row["eager_us"] = time_eager(fn, args)
                if tokens != prefill:
                    row["graph_us"] = time_graph(fn, args)
            except Exception as exc:  # noqa: BLE001
                row["error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
            rows.append(row)
            print(f"  time {name:15s} T={tokens:5d} {row}", flush=True)
            del args
            torch.cuda.empty_cache()
    return rows


def environment() -> dict:
    import importlib.metadata as md

    import torch

    env = {
        "gpu": torch.cuda.get_device_name(),
        "arch": "sm_%d%d" % torch.cuda.get_device_capability(),
        "torch": torch.__version__,
        "cuda": torch.version.cuda,
    }
    for pkg in ("triton", "triton_kernels", "flashinfer-python", "flashinfer-jit-cache"):
        try:
            env[pkg] = md.version(pkg)
        except md.PackageNotFoundError:
            env[pkg] = "absent"
    return env


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--impls", default="reference,triton_kernels")
    ap.add_argument("--out", type=Path)
    ap.add_argument("--skip", default="", help="comma list of sections to skip: correct,capture,time")
    args = ap.parse_args()
    impls = args.impls.split(",")
    skip = set(filter(None, args.skip.split(",")))

    import torch

    torch.cuda.set_device(0)  # triton_kernels reads device 0's SM count regardless
    report = {"env": environment(), "impls": impls}
    print(f"env: {report['env']}", flush=True)
    if "correct" not in skip:
        report["correct"] = correctness(impls)
    if "capture" not in skip:
        report["capture"] = capture(impls)
    if "time" not in skip:
        report["time"] = timing(impls, DECODE, PREFILL)
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=1, default=str) + "\n")
        print(f"wrote {args.out}")
    bad = [r for r in report.get("correct", []) if r["verdict"] != "pass"]
    bad += [r for r in report.get("capture", []) if not r.get("ok")]
    print(f"{len(bad)} correctness/capture rows not passing")
    return 0


if __name__ == "__main__":
    sys.exit(main())
