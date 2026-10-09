"""```nn-fit fence -> <nn-fit>: one `key: value` line per setting; keys are the element's attributes.

    dataset: wave            draw | wave | spiral | grok (modular arithmetic; trains only when connected)
    activation: tanh         linear | relu | tanh | sigmoid
    layers: 2                hidden layers, 0..4
    width: 8                 units per hidden layer, 1..16
    widths: 8,4              per-layer units instead (up to 4 of 1..16)
    lr: 0.03                 Adam learning rate, 1e-4..1
    samples: 128             training points, 4..512
    noise: 0.1               sigma in y units, 0..0.5
    wiggles: 4               random wave: Fourier terms K, 1..20
    roughness: 1.5           random wave: alpha, 0.5 (rough)..3 (smooth)
    stages: 1                random wave: composed series d, 1..4
    seed: 1                  random wave: which curve, 0..2^31
    step-budget: 2000        positive integer, or off
    time-budget: 5           seconds, or off
    train-fraction: 0.3      grok: share of the a + b mod p pairs trained on, 0.3..0.5

Every key is optional (the element has defaults; an empty fence is the default widget). Blank lines are
skipped. An unknown or repeated key, or a value outside the list above, fails the build with its line.
The element snaps lr, samples, noise, roughness, the budgets and train-fraction to its nearest slider stop.
The widget is drawn entirely by element.ts (web/embeds/nn-fit/nn-fit.ts); without JS it is empty.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable
from html import escape

ACTIVATIONS = ("linear", "relu", "tanh", "sigmoid")
DATASETS = ("draw", "wave", "spiral", "grok")
MAX_LAYERS = 4
MAX_WIDTH = 16


def one_of(options: tuple[str, ...]) -> Callable[[str], bool]:
    return lambda v: v in options


def integer(lo: int, hi: int) -> Callable[[str], bool]:
    return lambda v: re.fullmatch(r"\d+", v) is not None and lo <= int(v) <= hi


def number(lo: float, hi: float) -> Callable[[str], bool]:
    def ok(v: str) -> bool:
        if re.fullmatch(r"\d+(\.\d*)?(e-?\d+)?|\.\d+(e-?\d+)?", v) is None:
            return False
        x = float(v)
        return math.isfinite(x) and lo <= x <= hi

    return ok


def widths(v: str) -> bool:
    parts = v.split(",")
    return len(parts) <= MAX_LAYERS and all(integer(1, MAX_WIDTH)(p.strip()) for p in parts)


def or_off(check: Callable[[str], bool]) -> Callable[[str], bool]:
    return lambda v: v == "off" or check(v)


# key -> (accepts the value?, what it accepts, for the error). Mirrors the header of nn-fit.ts.
KEYS: dict[str, tuple[Callable[[str], bool], str]] = {
    "dataset": (one_of(DATASETS), " | ".join(DATASETS)),
    "activation": (one_of(ACTIVATIONS), " | ".join(ACTIVATIONS)),
    "layers": (integer(0, MAX_LAYERS), f"an integer in 0..{MAX_LAYERS}"),
    "width": (integer(1, MAX_WIDTH), f"an integer in 1..{MAX_WIDTH}"),
    "widths": (widths, f"up to {MAX_LAYERS} comma-separated integers in 1..{MAX_WIDTH}"),
    "lr": (number(1e-4, 1), "a number in 1e-4..1"),
    "samples": (integer(4, 512), "an integer in 4..512"),
    "noise": (number(0, 0.5), "a number in 0..0.5"),
    "wiggles": (integer(1, 20), "an integer in 1..20"),
    "roughness": (number(0.5, 3), "a number in 0.5..3"),
    "stages": (integer(1, 4), "an integer in 1..4"),
    "seed": (integer(0, 2**31), "an integer in 0..2^31"),
    "step-budget": (or_off(integer(1, 10**9)), "a positive integer, or off"),
    "time-budget": (or_off(number(1e-3, 1e6)), "a positive number of seconds, or off"),
    "train-fraction": (number(0.3, 0.5), "a number in 0.3..0.5"),
}


def render(src: str, line: int) -> str:
    attrs: dict[str, str] = {}
    for i, raw in enumerate(src.split("\n")):
        if not raw.strip():
            continue
        where = f"line {line + i}"
        key, sep, value = raw.partition(":")
        key, value = key.strip(), value.strip()
        assert sep and value, f"{where}: expected `key: value`, got {raw!r}"
        assert key in KEYS, f"{where}: unknown key {key!r} (known: {', '.join(KEYS)})"
        assert key not in attrs, f"{where}: {key} given twice"
        accepts, expected = KEYS[key]
        assert accepts(value), f"{where}: {key}: {value!r} is not {expected}"
        attrs[key] = value
    shown = "".join(f' {k}="{escape(v)}"' for k, v in attrs.items())
    return f"<nn-fit data-not-typeset{shown}></nn-fit>\n"
