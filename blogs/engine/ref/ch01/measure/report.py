"""measure/results-*.jsonl -> measure/RESULTS.md. Formatting only.

    uv run python -m measure.report
"""

import json
from pathlib import Path

from . import mutants

OUT_DIR = Path(__file__).parent
DTYPES = ("fp32", "bf16")


def e(x: float | None) -> str:
    return "-" if x is None else f"{x:.2e}"


def f(x: float | None, digits: int = 3) -> str:
    return "-" if x is None else f"{x:.{digits}f}"


def table(header: list[str], rows: list[list[str]]) -> str:
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(r) + " |" for r in rows]
    return "\n".join(lines)


SUMMARY_HEADER = [
    "variant", "logit max abs", "mean abs (avg)", "max rel", "max abs / max|HF|", "KL max", "KL mean (avg)", "KL last pos (max)",
    "top1 agree (min)", "top5 overlap (min)", "greedy identical (min)", "earliest divergence step",
    "logprobs_close pass", "ppl ours / HF",
]


def summary_rows(variants: dict) -> list[list[str]]:
    rows = []
    for vname, v in variants.items():
        ps = list(v["prompts"].values())
        gens = [p["greedy"] for p in ps if "greedy" in p]
        divs = [g["first_divergence"] for g in gens if g["first_divergence"] is not None]
        rows.append([
            vname,
            e(max(p["max_abs"] for p in ps)),
            e(sum(p["mean_abs"] for p in ps) / len(ps)),
            e(max(p["max_rel"] for p in ps)),
            e(max(p["max_abs"] / p["ref_max_abs"] for p in ps)),
            e(max(p["kl_max"] for p in ps)),
            e(sum(p["kl_mean"] for p in ps) / len(ps)),
            e(max(p["kl_last"] for p in ps)),
            f(min(p["top1_agree"] for p in ps)),
            f(min(p["top5_overlap"] for p in ps)),
            f"{min(g['identical'] for g in gens)}/{gens[0]['n']}",
            "none" if not divs else str(min(divs)),
            f"{sum(g['close'] for g in gens)}/{len(gens)}",
            f"{v['ppl_ours']:.6g} / {v['ppl_hf']:.6g}",
        ])
    return rows


PROMPT_HEADER = [
    "prompt", "T", "logit max abs @(pos,vocab)", "max rel", "mean abs", "KL max", "KL mean", "top1",
    "top5 overlap", "greedy identical", "first div", "top1-top2 gap at div (HF / ours)", "logprobs_close",
]


def prompt_rows(v: dict) -> list[list[str]]:
    rows = []
    for name, p in v["prompts"].items():
        g = p.get("greedy")
        rows.append([
            name, str(p["n_tokens"]),
            f"{e(p['max_abs'])} @({p['argmax_pos']},{p['argmax_vocab']})",
            e(p["max_rel"]), e(p["mean_abs"]), e(p["kl_max"]), e(p["kl_mean"]),
            f(p["top1_agree"]), f(p["top5_overlap"]),
            "-" if g is None else f"{g['identical']}/{g['n']}",
            "-" if g is None else str(g["first_divergence"]),
            "-" if g is None else f"{f(g['ref_gap_at_div'])} / {f(g['ours_gap_at_div'])}",
            "-" if g is None else ("pass" if g["close"] else f"FAIL@{g['close_stop_step']}"),
        ])
    return rows


def layer_rows(variants: dict) -> list[list[str]]:
    """Per stream slot, max over prompts of max abs diff (and of diff / max|HF| at that slot)."""
    n_slots = len(next(iter(next(iter(variants.values()))["prompts"].values()))["layers"])
    rows = []
    for slot in range(n_slots):
        cells = []
        for v in variants.values():
            layers = [p["layers"][slot] for p in v["prompts"].values()]
            cells.append(f"{e(max(x['max_abs'] for x in layers))} ({e(max(x['rel_to_max'] for x in layers))})")
        rows.append(["embed" if slot == 0 else f"block {slot - 1}", *cells])
    return rows


def load(dtype: str) -> dict | None:
    path = OUT_DIR / f"results-{dtype}.jsonl"
    if not path.exists():
        return None
    records = [json.loads(line) for line in path.read_text().splitlines()]
    assert records[0]["kind"] == "header", path
    by_kind = {r["kind"]: r for r in records if r["kind"] != "variant"}
    return {
        "header": records[0],
        "variants": {r["name"]: r for r in records if r["kind"] == "variant"},
        "timing": by_kind.get("timing"),
        "noise_floor": by_kind.get("noise_floor"),
        "done": by_kind.get("done"),
    }


def dtype_section(dname: str, d: dict) -> list[str]:
    h = d["header"]
    status = f"complete in {d['done']['wall_s']:.0f}s" if d["done"] else "INCOMPLETE: run was cut short or is still going"
    out = [
        f"## {dname}: {status}",
        "",
        f"env: {h['env']}",
        "",
        "prompts (tokens): " + ", ".join(f"{k}={v}" for k, v in h["prompts"].items())
        + f". Greedy: {h['n_gen']} new tokens on {', '.join(h['gen_prompts'])}. Perplexity text: {h['ppl_tokens']} tokens.",
        "",
        f"### {dname}: summary over prompts (ours vs HF {dname})",
        "",
        table(SUMMARY_HEADER, summary_rows(d["variants"])),
        "",
        f"### {dname}: residual stream max abs diff per slot, max over prompts (in parens: / max|HF| at that slot)",
        "",
        table(["slot", *d["variants"].keys()], layer_rows(d["variants"])),
        "",
    ]
    if d["noise_floor"]:
        nf = d["noise_floor"]["rows"]
        out += [
            f"### {dname} noise floor: each {dname} forward vs the fp32 HF reference",
            "",
            table(
                ["prompt", "HF max abs", "HF KL max", "HF KL mean", "HF top1", "ours max abs", "ours KL max", "ours KL mean", "ours top1"],
                [[n, *[c for who in ("hf_bf16", "ours_bf16") for c in (e(x[who]["max_abs"]), e(x[who]["kl_max"]), e(x[who]["kl_mean"]), f(x[who]["top1_agree"]))]] for n, x in nf.items()],
            ),
            "",
        ]
    if d["timing"]:
        out += [
            f"### {dname}: time per forward (median of 3 after warmup, full [T, vocab] logits)",
            "",
            table(["prompt", "T", "ours ms", "HF ms"], [[n, str(t["n_tokens"]), f"{t['ours_s'] * 1e3:.1f}", f"{t['hf_s'] * 1e3:.1f}"] for n, t in d["timing"]["rows"].items()]),
            "",
        ]
    for vname, v in d["variants"].items():
        out += [f"### detail: {dname} / {vname}", "", table(PROMPT_HEADER, prompt_rows(v)), ""]
    return out


def render() -> str:
    out = [
        "# ch01 gpt2 forward vs HuggingFace: measurements",
        "",
        "Generated by `uv run python -m measure.run fp32`, `... bf16`, then `uv run python -m measure.report` "
        "(from `blogs/engine/ref/ch01`). Raw numbers: `measure/results-*.jsonl`. No thresholds; numbers only.",
        "",
        "Reference: `GPT2LMHeadModel` (`openai-community/gpt2`, attn_implementation=eager, eval, no_grad) in the same dtype as ours. "
        "Greedy: HF decodes with its KV cache, ours recomputes the full sequence each step. "
        "KL is KL(HF || ours) per position, nats, float64. "
        "`logprobs_close` is vLLM's check: walk both greedy runs; at the first mismatch, pass iff each token is in the other's top-5. "
        "max rel is max |d| / |HF logit| (blows up on the few logits near zero; `max abs / max|HF|` is the scale-normalized alternative). Residual stream slots are captured with hooks on HF's blocks (pre-ln_f), not hidden_states.",
        "",
        "Mutants (deliberate bugs, one-line edits of gpt2.py, see measure/mutants.py):",
        "",
        *[f"- `{k}`: {desc} (`{old}` -> `{new}`)" for k, (desc, old, new) in mutants.MUTANTS.items()],
        "",
    ]
    for dname in DTYPES:
        d = load(dname)
        out += [f"## {dname}: not run", ""] if d is None else dtype_section(dname, d)
    return "\n".join(out)


if __name__ == "__main__":
    (OUT_DIR / "RESULTS.md").write_text(render())
    print(f"wrote {OUT_DIR / 'RESULTS.md'}")
