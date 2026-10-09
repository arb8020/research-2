"""Model-level planted bugs, as one-line source edits of the reference gpt2.py (mutation testing).

Each mutant is gpt2.py with exactly one substring replaced, written out as its own `gpt2.py` so the check imports it
like any reader's file; the bug is literally the diff. If gpt2.py drifts so a target no longer appears exactly once,
building the mutant fails loudly.
"""

from pathlib import Path

# name -> (what the bug is, old substring, new substring)
MUTANTS = {
    "a_scale_1/hd": ("attention scale 1/head_dim instead of 1/sqrt(head_dim)", "/ math.sqrt(hd)", "/ hd"),
    "b_no_ln_f": ("final layer norm skipped",
                  'final = layer_norm(residual_stream(w, cfg, tokens)[-1], w, "ln_f", cfg)',
                  "final = residual_stream(w, cfg, tokens)[-1]"),
    "c_gelu_exact": ("exact erf GELU instead of GPT-2's tanh approximation", 'approximate="tanh"',
                     'approximate="none"'),
    "d_mask_leak": ("causal mask off by one: each query also sees the next key", "triu(diagonal=1)",
                    "triu(diagonal=2)"),
}


def write(name: str, source: Path, out_dir: Path) -> Path:
    """`out_dir/<name>/gpt2.py`: the source with mutant `name` applied."""
    _, old, new = MUTANTS[name]
    src = source.read_text()
    assert src.count(old) == 1, f"mutant {name}: {old!r} appears {src.count(old)} times in {source}"
    path = out_dir / name.replace("/", "_") / "gpt2.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    text = src.replace(old, new)
    if not path.exists() or path.read_text() != text:
        path.write_text(text)
    return path
