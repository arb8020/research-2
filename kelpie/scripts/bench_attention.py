#!/usr/bin/env python3
"""Per-op proof for `kelpie::paged_attention`: correctness vs the reference over the build's
step shapes, CUDA-graph capture, timing per bucket, peak memory.

Cases are gpt-oss-20b attention (64 q / 8 kv heads, D 64, block 16, sinks) at the shapes
gpt-oss's build enumerates with prove_moe's capacity (max_seq_len 512, 8 requests, 1024 batch
tokens), each with the window of both layer kinds (0 and 128):

  decode R        R entries x 1 row, contexts across pages and past the window; R = 1..8,
                  plus a padded bucket (5 real entries in R = 8)
  prefill T       T = 1..1024: fresh prompts split as the warm pass splits them, a chunk
                  continuing a long context, and mixed prefill + decode entries, padded
  decode_extra R  R x (1 + K) rows (DFlash K = 15), full, and RAGGED (each entry 1 + K_i rows,
                  K_i in 0..15, padded to R x 16)
  drafter         DFlash's call: causal=False, no sinks, decode_extra shapes

  correct   truth = the reference on the float64 sample of the same seed (the bf16 inputs,
            exactly); budget = `bench.correctness.error_budget` (vendored crucible@dfb735f:
            max(2 x the bf16 reference's own error, 2e-2 x |truth|max)). The bf16 reference is
            graded too (its err is the scale every impl is read against). Every impl runs with
            its default kernel choice and both forced (vllm_triton: 2D and 3D). Pad rows must
            be exactly zero.
  capture   capture one call, write a DIFFERENT plan of the same shape (other contexts, pages,
            values) into the captured buffers, replay, compare to eager on it.
  time      median us per call: graph replay for decode / decode_extra, eager for prefill.
  memory    peak allocated above the inputs, per impl, at the largest prefill.

    PYTHONPATH=. uv run --no-project --with modal --with requests python kelpie/scripts/modal_run.py \\
        --gpu A100-80GB --volume kelpie-a1 -- \\
        'python -m scripts.bench_attention --out /data/attn/bench-a100.json --provenance <sha>'
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
from pathlib import Path

GPT_OSS = dict(heads=64, kv_heads=8, head_dim=64, block=16)
MAX_SEQ = 512
K_EXTRA = 15
DECODE = (1, 2, 4, 8)
PREFILL = (1, 2, 4, 8, 16, 32, 64, 128, 256, 512, 1024)
REPLAYS = 50
WARMUP = 5
GIB = 2**30


def _batch(entries: list[tuple[int, int]], tokens: int, reqs: int, **kw: object):
    from kelpie_models.kernels.ops.paged_attention import Batch

    return Batch(entries=tuple(entries), tokens=tokens, reqs=reqs, **{**GPT_OSS, **kw})


def shapes(rng: random.Random) -> list[tuple[str, dict]]:
    """(label, Batch kwargs without window) over the build enumeration's families."""
    out = []
    for r in DECODE:
        out.append((f"decode R={r}", dict(entries=[(rng.randint(1, 700), 1) for _ in range(r)],
                                         tokens=r, reqs=r)))
    out.append(("decode R=8 (5 real)", dict(entries=[(rng.randint(1, 700), 1) for _ in range(5)],
                                            tokens=8, reqs=8)))
    for t in PREFILL:
        n = -(-t // MAX_SEQ)
        out.append((f"prefill T={t} fresh", dict(entries=[(0, t // n)] * n, tokens=t, reqs=n)))
    out.append(("prefill T=512 chunk@300", dict(entries=[(300, 512)], tokens=512, reqs=1)))
    out.append(("prefill T=128 mixed", dict(entries=[(0, 57), (400, 1), (33, 1), (129, 40), (5, 3)],
                                            tokens=128, reqs=8)))
    out.append(("prefill T=1024 mixed", dict(entries=[(0, 300), (700, 1), (250, 511), (20, 100)],
                                             tokens=1024, reqs=8)))
    for r in DECODE:
        w = 1 + K_EXTRA
        full = [(rng.randint(1, 600), w) for _ in range(r)]
        out.append((f"decode_extra R={r}", dict(entries=full, tokens=r * w, reqs=r)))
        ragged = [(rng.randint(1, 600), 1 + rng.randint(0, K_EXTRA)) for _ in range(r)]
        out.append((f"decode_extra R={r} ragged", dict(entries=ragged, tokens=r * w, reqs=r)))
    return out


def cases() -> list[tuple[str, object]]:
    rng = random.Random(0)
    out = []
    for label, kw in shapes(rng):
        for window in (0, 128):
            out.append((f"{label} w{window}", _batch(**kw, window=window)))
        if label.startswith("decode_extra"):
            out.append((f"{label} drafter", _batch(**kw, sinks=False, causal=False)))
    return out


def impls(names: list[str]) -> dict[str, object]:
    """Impl label -> callable. `vllm_triton` also runs forced 2D and forced 3D."""
    from kelpie_models.kernels import ops

    out: dict[str, object] = {}
    for name in names:
        if name == "reference":
            out[name] = ops.paged_attention.reference
            continue
        out[name] = ops.paged_attention.impls[name].fn
        if name == "vllm_triton":
            from kelpie_models.kernels.adapters import paged_attention_vllm as adapter

            out[f"{name}[2d]"] = lambda *a: adapter.paged_attention(*a, split=False)
            out[f"{name}[3d]"] = lambda *a: adapter.paged_attention(*a, split=True)
    return out


def correctness(fns: dict[str, object]) -> list[dict]:
    import torch

    from kelpie_models.bench.correctness import error_budget
    from kelpie_models.kernels.ops.paged_attention import sample

    assert "reference" in fns, "correctness grades against the reference"
    rows = []
    for i, (label, batch) in enumerate(cases()):
        truth = fns["reference"](*sample(batch, "cuda", torch.float64, seed=i))
        ref = fns["reference"](*sample(batch, "cuda", torch.bfloat16, seed=i))
        budget = error_budget(truth, ref)
        scale = truth.abs().max().item()
        for name, fn in fns.items():
            row = {"case": label, "impl": name, "budget": budget, "scale": scale}
            try:
                out = fn(*sample(batch, "cuda", torch.bfloat16, seed=i))
                torch.cuda.synchronize()
                err = (out.double() - truth).abs().max().item()
                pad = out[batch.n_rows:].abs().max().item() if batch.n_rows < batch.tokens else 0.0
                ok = err <= budget and pad == 0.0
                row.update(err=err, pad_max=pad, verdict="pass" if ok else "FAIL")
            except Exception as exc:  # noqa: BLE001 -- a throwing impl is a row, not a crash
                row.update(err=None, verdict=f"error: {type(exc).__name__}: {str(exc)[:200]}")
            rows.append(row)
            print(f"  {label:34s} {name:17s} {row['verdict'][:60]:6s} err {row.get('err')} "
                  f"budget {budget:.3g}", flush=True)
        del truth, ref
    return rows


def capture(fns: dict[str, object]) -> list[dict]:
    """Capture at a decode and a ragged decode_extra shape; replay on a different plan."""
    import torch

    from kelpie_models.kernels.ops.paged_attention import sample

    rows = []
    for label, entries, tokens, reqs in (
        ("decode R=8", [(40, 1), (130, 1), (7, 1), (300, 1), (1, 1), (16, 1), (17, 1), (600, 1)], 8, 8),
        ("decode_extra R=4 ragged", [(40, 16), (130, 3), (7, 1), (300, 9)], 64, 4),
    ):
        for window in (0, 128):
            first = _batch(entries, tokens, reqs, window=window)
            # Same page needs per entry (so the same arena and table width), other order: every
            # entry's context, rows, pages and values change.
            second = _batch(entries[::-1], tokens, reqs, window=window)
            for name, fn in fns.items():
                row = {"shape": f"{label} w{window}", "impl": name}
                try:
                    static = list(sample(first, "cuda", torch.bfloat16, seed=10))
                    fresh = sample(second, "cuda", torch.bfloat16, seed=11)
                    fn(*static)
                    torch.cuda.synchronize()
                    stream = torch.cuda.Stream()
                    stream.wait_stream(torch.cuda.current_stream())
                    graph = torch.cuda.CUDAGraph()
                    with torch.cuda.stream(stream), torch.cuda.graph(graph, stream=stream):
                        out = fn(*static)
                    for dst, src in zip(static, fresh, strict=True):
                        if isinstance(dst, torch.Tensor):
                            dst.copy_(src)
                    graph.replay()
                    torch.cuda.synchronize()
                    eager = fn(*static)
                    diff = (out.double() - eager.double()).abs().max().item()
                    # A kernel replays bit-exact; the reference's captured call gathers the
                    # whole table (eager: occupied columns), so its sums may reorder.
                    row.update(ok=diff <= 1e-3 * eager.abs().max().item(), max_diff=diff)
                except Exception as exc:  # noqa: BLE001
                    row.update(ok=False, error=f"{type(exc).__name__}: {str(exc)[:200]}")
                rows.append(row)
                print(f"  capture {row['shape']:28s} {name:17s} {row}", flush=True)
    return rows


def time_graph(fn, args: tuple) -> float:
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


def timing(fns: dict[str, object]) -> list[dict]:
    """Per bucket, the gpt-oss window-0 (full attention) layer, plus window 128 at decode."""
    import torch

    from kelpie_models.bench.timing import measure
    from kelpie_models.kernels.ops.paged_attention import sample

    rows = []
    rng = random.Random(1)
    for label, kw in shapes(rng):
        if "chunk" in label or "mixed" in label or "(5 real)" in label:
            continue
        for window in (0, 128):
            batch = _batch(**kw, window=window)
            graphed = not label.startswith("prefill")
            for name, fn in fns.items():
                row = {"shape": f"{label} w{window}", "impl": name}
                try:
                    args = sample(batch, "cuda", torch.bfloat16, seed=20)
                    row["eager_us"] = measure(fn, args)
                    if graphed:
                        row["graph_us"] = time_graph(fn, args)
                except Exception as exc:  # noqa: BLE001
                    row["error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
                rows.append(row)
                print(f"  time {row['shape']:30s} {name:17s} {row}", flush=True)
                torch.cuda.empty_cache()
    return rows


def memory(fns: dict[str, object]) -> list[dict]:
    import torch

    from kelpie_models.kernels.ops.paged_attention import sample

    rows = []
    for label, entries, tokens, reqs in (("prefill T=1024 2x512", [(0, 512)] * 2, 1024, 2),
                                         ("prefill T=1024 1x1024", [(0, 1024)], 1024, 1)):
        for name, fn in fns.items():
            args = sample(_batch(entries, tokens, reqs, window=0), "cuda", torch.bfloat16)
            torch.cuda.synchronize()
            base = torch.cuda.memory_allocated()
            torch.cuda.reset_peak_memory_stats()
            fn(*args)
            torch.cuda.synchronize()
            peak = (torch.cuda.max_memory_allocated() - base) / GIB
            rows.append({"shape": label, "impl": name, "peak_gib": peak})
            print(f"  memory {label:22s} {name:17s} {peak:.3f} GiB above inputs", flush=True)
            del args
            torch.cuda.empty_cache()
    return rows


def environment(provenance: str | None) -> dict:
    import importlib.metadata as md

    import torch

    from kelpie_models.kernels.vendored.cuda import vllm_attention

    return {
        "gpu": torch.cuda.get_device_name(),
        "arch": "sm_%d%d" % torch.cuda.get_device_capability(),
        "torch": torch.__version__,
        "cuda": torch.version.cuda,
        "triton": md.version("triton"),
        "vllm_attention": f"{vllm_attention.__version__} @ {vllm_attention.VLLM_COMMIT}",
        "budget": "bench.correctness.error_budget (crucible@dfb735f)",
        "tree": provenance or "unknown",
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--impls", default="reference,vllm_triton")
    ap.add_argument("--out", type=Path)
    ap.add_argument("--skip", default="", help="comma list: correct,capture,time,memory")
    ap.add_argument("--provenance", default=None, help="the tree's git sha, recorded in --out")
    args = ap.parse_args()
    skip = set(filter(None, args.skip.split(",")))

    import torch

    torch.cuda.set_device(0)
    fns = impls(args.impls.split(","))
    report = {"env": environment(args.provenance), "impls": list(fns)}
    print(f"env: {report['env']}", flush=True)
    sections = (("correct", correctness), ("capture", capture), ("time", timing),
                ("memory", memory))
    for name, section in sections:
        if name not in skip:
            report[name] = section(fns)
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=1, default=str) + "\n")
        print(f"wrote {args.out}")
    bad = [r for r in report.get("correct", []) if r["verdict"] != "pass"]
    bad += [r for r in report.get("capture", []) if not r.get("ok")]
    print(f"{len(bad)} correctness/capture rows not passing "
          f"(of {len(report.get('correct', [])) + len(report.get('capture', []))})")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
