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


KEYS: dict[str, tuple[Callable[[str], bool], str]] = {
    "dataset": (one_of(DATASETS), " | ".join(DATASETS)),
    "activation": (one_of(ACTIVATIONS), " | ".join(ACTIVATIONS)),
    "layers": (integer(0, MAX_LAYERS), f"an integer in 0..{MAX_LAYERS} (hidden layers)"),
    "width": (integer(1, MAX_WIDTH), f"an integer in 1..{MAX_WIDTH} (units per hidden layer)"),
    "widths": (widths, f"up to {MAX_LAYERS} comma-separated integers in 1..{MAX_WIDTH} (units per hidden layer)"),
    "lr": (number(1e-4, 1), "a number in 1e-4..1 (Adam learning rate)"),
    "samples": (integer(4, 512), "an integer in 4..512 (training points)"),
    "noise": (number(0, 0.5), "a number in 0..0.5 (σ in y units)"),
    "wiggles": (integer(1, 20), "an integer in 1..20 (random wave: Fourier terms K)"),
    "roughness": (number(0.5, 3), "a number in 0.5 (rough)..3 (smooth) (random wave: alpha)"),
    "stages": (integer(1, 4), "an integer in 1..4 (random wave: composed series d)"),
    "seed": (integer(0, 2**31), "an integer in 0..2^31 (random wave: which curve)"),
    "step-budget": (or_off(integer(1, 10**9)), "a positive integer, or off"),
    "time-budget": (or_off(number(1e-3, 1e6)), "a positive number of seconds, or off"),
    "train-fraction": (number(0.3, 0.5), "a number in 0.3..0.5 (grok only: share of the a + b mod p pairs trained on)"),
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
