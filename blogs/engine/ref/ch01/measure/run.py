"""Measure ch01's gpt2 forward against HuggingFace GPT2LMHeadModel (eager attention), CPU only.

    cd blogs/engine/ref/ch01
    uv run python -m measure.run fp32     # ~5 min on an M-series laptop
    uv run python -m measure.run bf16     # reduced plan (see PLANS), a few min
    uv run python -m measure.report       # results-*.jsonl -> RESULTS.md

Each run appends to measure/results-<dtype>.jsonl after every variant, so a killed run keeps what it
finished. Measures only: no pass/fail thresholds, those are a decision the numbers inform.
"""

import json
import platform
import statistics
import sys
import time
import types
from collections.abc import Callable
from pathlib import Path

import gpt2
import torch
import transformers
from transformers import AutoTokenizer, GPT2LMHeadModel, PreTrainedTokenizerBase

from . import metrics, mutants, texts

N_GEN = 64
TIMING_REPEATS = 3
OUT_DIR = Path(__file__).parent

# Real bf16 matmuls on this CPU (Apple M-series; torch has no fast bf16 GEMM here) cost ~50 ms per
# token per forward, ~50x fp32. The bf16 plan keeps real bf16 (not emulated) and shrinks the workload.
PLANS = {
    "fp32": {
        "dtype": torch.float32,
        "prompts": ("len1", "prose", "code", "repeated", "unicode", "near_limit_960", "full_ctx_1024"),
        "gen": ("len1", "prose", "code", "repeated", "unicode", "near_limit_960"),
        "n_gen": N_GEN,
    },
    "bf16": {
        "dtype": torch.bfloat16,
        "prompts": ("len1", "prose", "unicode"),
        "gen": ("len1", "prose"),
        "n_gen": 16,
    },
}


def build_prompts(tok: PreTrainedTokenizerBase) -> dict[str, list[int]]:
    long_ids = tok.encode(texts.LONG)
    assert len(long_ids) >= 1024, f"texts.LONG is only {len(long_ids)} tokens"
    prompts = {
        "len1": tok.encode("The"),
        "prose": tok.encode("The capital of France is Paris. The capital of Germany is"),
        "code": tok.encode(texts.CODE),
        "repeated": tok.encode(" the" * 200),
        "unicode": tok.encode(texts.UNICODE),
        # prompt + N_GEN - 1 forwarded tokens == 1023, the longest generation that fits
        "near_limit_960": long_ids[: 1024 - N_GEN],
        # full context; logits only (no room to generate)
        "full_ctx_1024": long_ids[:1024],
    }
    assert len(prompts["len1"]) == 1
    assert len(set(prompts["repeated"])) == 1
    return prompts


def load_hf(dtype: torch.dtype) -> GPT2LMHeadModel:
    model = GPT2LMHeadModel.from_pretrained(gpt2.CHECKPOINT, attn_implementation="eager", dtype=dtype)
    model.eval()
    assert model.config._attn_implementation == "eager"
    assert next(model.parameters()).dtype == dtype
    return model


@torch.no_grad()
def hf_logits_and_stream(model: GPT2LMHeadModel, ids: list[int]) -> tuple[torch.Tensor, list[torch.Tensor]]:
    """Logits [T, V] + residual stream (embeddings, after each block), captured with hooks so the
    slots line up exactly with gpt2.residual_stream (HF's hidden_states puts ln_f on the last one)."""
    stream: list[torch.Tensor] = []
    blocks = model.transformer.h

    def take_input(_mod: torch.nn.Module, args: tuple, kwargs: dict) -> None:
        stream.append((args[0] if args else kwargs["hidden_states"])[0].clone())

    def take_output(_mod: torch.nn.Module, _args: tuple, out: object) -> None:
        stream.append((out[0] if isinstance(out, tuple) else out)[0].clone())

    handles = [blocks[0].register_forward_pre_hook(take_input, with_kwargs=True)]
    handles += [b.register_forward_hook(take_output) for b in blocks]
    try:
        logits = model(input_ids=torch.tensor([ids]), use_cache=False).logits[0]
    finally:
        for h in handles:
            h.remove()
    assert len(stream) == len(blocks) + 1
    return logits, stream


@torch.no_grad()
def hf_greedy(model: GPT2LMHeadModel, ids: list[int], n: int) -> tuple[list[int], torch.Tensor]:
    """HF's normal decode path: prefill, then one token at a time against its KV cache."""
    out = model(input_ids=torch.tensor([ids]), use_cache=True)
    tokens, step_logits = [], []
    for _ in range(n):
        row = out.logits[0, -1]
        step_logits.append(row.clone())
        tokens.append(int(row.argmax()))
        out = model(input_ids=torch.tensor([[tokens[-1]]]), past_key_values=out.past_key_values, use_cache=True)
    return tokens, torch.stack(step_logits)


@torch.no_grad()
def ours_greedy(m: types.ModuleType, w: gpt2.Weights, cfg: gpt2.Config, ids: list[int], n: int) -> tuple[list[int], torch.Tensor]:
    """Same loop as gpt2.generate, also keeping each step's logits (for top-k / near-tie checks)."""
    seq = list(ids)
    step_logits = []
    for _ in range(n):
        row = m.forward(w, cfg, torch.tensor(seq, dtype=torch.long))[-1]
        step_logits.append(row)
        seq.append(int(row.argmax()))
    return seq[len(ids):], torch.stack(step_logits)


def median_seconds(fn: Callable[[], object]) -> float:
    fn()  # warm up
    times = []
    for _ in range(TIMING_REPEATS):
        t0 = time.perf_counter()
        fn()
        times.append(time.perf_counter() - t0)
    return statistics.median(times)


@torch.no_grad()
def hf_reference(model: GPT2LMHeadModel, prompts: dict, ppl_ids: list[int], gen: tuple, n_gen: int) -> dict:
    out = {"prompts": {}}
    for name, ids in prompts.items():
        logits, stream = hf_logits_and_stream(model, ids)
        entry = {"logits": logits, "stream": stream}
        if name in gen:
            assert len(ids) + n_gen - 1 <= 1024
            entry["greedy"] = hf_greedy(model, ids, n_gen)
        out["prompts"][name] = entry
    ppl_logits, _ = hf_logits_and_stream(model, ppl_ids)
    out["ppl"] = metrics.perplexity(ppl_logits, torch.tensor(ppl_ids))
    return out


@torch.no_grad()
def measure_variant(m: types.ModuleType, w: gpt2.Weights, cfg: gpt2.Config, hf: dict, prompts: dict, ppl_ids: list[int], n_gen: int) -> dict:
    """Compare one forward (reference or mutant) against precomputed HF outputs for one dtype."""
    per_prompt = {}
    for name, ids in prompts.items():
        t = torch.tensor(ids, dtype=torch.long)
        logits = m.forward(w, cfg, t)
        ref_logits, ref_stream = hf["prompts"][name]["logits"], hf["prompts"][name]["stream"]
        row = {
            "n_tokens": len(ids),
            **metrics.logit_diff(ref_logits, logits),
            **metrics.kl_stats(ref_logits, logits),
            **metrics.topk_agreement(ref_logits, logits),
            "layers": metrics.layer_diffs(ref_stream, m.residual_stream(w, cfg, t)),
        }
        if "greedy" in hf["prompts"][name]:
            ref_tokens, ref_steps = hf["prompts"][name]["greedy"]
            ours_tokens, ours_steps = ours_greedy(m, w, cfg, ids, n_gen)
            row["greedy"] = metrics.greedy_compare(ref_tokens, ref_steps, ours_tokens, ours_steps)
        per_prompt[name] = row
    ppl_t = torch.tensor(ppl_ids, dtype=torch.long)
    return {
        "prompts": per_prompt,
        "ppl_ours": metrics.perplexity(m.forward(w, cfg, ppl_t), ppl_t),
        "ppl_hf": hf["ppl"],
    }


def timings(model: GPT2LMHeadModel, w: gpt2.Weights, cfg: gpt2.Config, prompts: dict) -> dict:
    rows = {}
    for name, ids in prompts.items():
        t = torch.tensor(ids, dtype=torch.long)
        with torch.no_grad():
            rows[name] = {
                "n_tokens": len(ids),
                "ours_s": median_seconds(lambda t=t: gpt2.forward(w, cfg, t)),
                "hf_s": median_seconds(lambda t=t: model(input_ids=t[None], use_cache=False)),
            }
    return rows


@torch.no_grad()
def noise_floor(ref32: GPT2LMHeadModel, hf16: dict, w16: gpt2.Weights, cfg: gpt2.Config, prompts: dict) -> dict:
    """bf16 vs the fp32 HF reference, for HF itself and for ours: the precision's own error."""
    rows = {}
    for name, ids in prompts.items():
        ref = ref32(input_ids=torch.tensor([ids]), use_cache=False).logits[0]
        ours = gpt2.forward(w16, cfg, torch.tensor(ids, dtype=torch.long))
        rows[name] = {
            who: {
                **metrics.logit_diff(ref, logits),
                **metrics.kl_stats(ref, logits),
                **metrics.topk_agreement(ref, logits),
            }
            for who, logits in (("hf_bf16", hf16["prompts"][name]["logits"]), ("ours_bf16", ours))
        }
    return rows


def main(dtype_name: str) -> None:
    """One JSON record per line, appended and flushed as each piece finishes:
    header, one per variant, timing, [noise_floor], done."""
    plan = PLANS[dtype_name]
    out_path = OUT_DIR / f"results-{dtype_name}.jsonl"
    t0 = time.perf_counter()
    torch.manual_seed(0)
    tok = AutoTokenizer.from_pretrained(gpt2.CHECKPOINT)
    all_prompts = build_prompts(tok)
    prompts = {k: all_prompts[k] for k in plan["prompts"]}
    ppl_ids = tok.encode(texts.PERPLEXITY)
    variants = {"correct": gpt2} | {name: mutants.build(name) for name in mutants.MUTANTS}
    with out_path.open("w") as out:

        def emit(record: dict) -> None:
            out.write(json.dumps({"dtype": dtype_name, **record}) + "\n")
            out.flush()

        emit({
            "kind": "header",
            "env": {
                "torch": torch.__version__,
                "transformers": transformers.__version__,
                "python": platform.python_version(),
                "machine": f"{platform.system()} {platform.machine()}",
                "torch_threads": torch.get_num_threads(),
            },
            "prompts": {k: len(v) for k, v in prompts.items()},
            "gen_prompts": list(plan["gen"]),
            "n_gen": plan["n_gen"],
            "ppl_tokens": len(ppl_ids),
        })
        model = load_hf(plan["dtype"])
        w, cfg = gpt2.load(plan["dtype"])
        hf = hf_reference(model, prompts, ppl_ids, plan["gen"], plan["n_gen"])
        print(f"{dtype_name} hf reference: {time.perf_counter() - t0:.1f}s", flush=True)
        for vname, m in variants.items():
            tv = time.perf_counter()
            emit({"kind": "variant", "name": vname, **measure_variant(m, w, cfg, hf, prompts, ppl_ids, plan["n_gen"])})
            print(f"{dtype_name} {vname}: {time.perf_counter() - tv:.1f}s", flush=True)
        emit({"kind": "timing", "rows": timings(model, w, cfg, prompts)})
        if dtype_name == "bf16":
            emit({"kind": "noise_floor", "rows": noise_floor(load_hf(torch.float32), hf, w, cfg, prompts)})
        if dtype_name == "fp32":
            # the reader-facing generate() is the same loop the harness traces
            assert gpt2.generate(w, cfg, prompts["prose"], 16) == ours_greedy(gpt2, w, cfg, prompts["prose"], 16)[0]
        emit({"kind": "done", "wall_s": time.perf_counter() - t0})
    print(f"{dtype_name} done in {time.perf_counter() - t0:.0f}s -> {out_path}", flush=True)


if __name__ == "__main__":
    assert len(sys.argv) == 2, "usage: python -m measure.run fp32|bf16"
    main(sys.argv[1])

