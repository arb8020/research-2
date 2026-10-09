"""Deliberate bugs, as one-line source edits of gpt2.py (mutation testing).

Each mutant is gpt2.py with exactly one substring replaced, exec'd as a fresh module. The reference
file stays bug-free and the bug is literally the diff shown in the results table. If gpt2.py drifts
so a target no longer appears exactly once, building the mutant fails loudly.
"""

import types
from pathlib import Path

import gpt2

# name -> (what the bug is, old substring, new substring)
MUTANTS = {
    "a_scale_1/hd": (
        "attention scale 1/head_dim instead of 1/sqrt(head_dim)",
        "/ math.sqrt(hd)",
        "/ hd",
    ),
    "b_no_ln_f": (
        "final layer norm skipped",
        'final = layer_norm(residual_stream(w, cfg, tokens)[-1], w, "ln_f", cfg)',
        "final = residual_stream(w, cfg, tokens)[-1]",
    ),
    "c_gelu_exact": (
        "exact erf GELU instead of GPT-2's tanh approximation",
        'approximate="tanh"',
        'approximate="none"',
    ),
    "d_mask_leak": (
        "causal mask off by one: each query also sees the next key",
        "triu(diagonal=1)",
        "triu(diagonal=2)",
    ),
}


def build(name: str) -> types.ModuleType:
    _, old, new = MUTANTS[name]
    src = Path(gpt2.__file__).read_text()
    assert src.count(old) == 1, f"mutant {name}: {old!r} appears {src.count(old)} times in gpt2.py"
    mod = types.ModuleType(f"gpt2_mutant_{name}")
    exec(compile(src.replace(old, new), f"<gpt2.py mutant {name}>", "exec"), mod.__dict__)  # noqa: S102
    return mod
