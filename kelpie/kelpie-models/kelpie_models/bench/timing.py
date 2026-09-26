"""How long one kernel takes: warmup, N timed calls, the median.

Median, not mean: a single page fault or a scheduler hiccup should not move the number that
`build` compares against last build's. No subprocess and no anti-cheat -- `build` runs kernels
we chose, in our own process; the adversarial version of this belongs in `bench/probe/`.
"""

from __future__ import annotations

import statistics
import time
from collections.abc import Callable
from typing import Any

import torch

WARMUP = 3
REPEATS = 10


def measure(fn: Callable[..., Any], args: tuple, *, warmup: int = WARMUP,
            repeats: int = REPEATS) -> float:
    """-> median wall time in microseconds. Synchronizes around each call on cuda, so the
    number is the kernel's and not the launch queue's."""
    sync = torch.cuda.synchronize if torch.cuda.is_available() else _nothing
    for _ in range(warmup):
        fn(*args)
    sync()
    times: list[float] = []
    for _ in range(repeats):
        start = time.perf_counter()
        fn(*args)
        sync()
        times.append((time.perf_counter() - start) * 1e6)
    assert len(times) == repeats
    return statistics.median(times)


def _nothing() -> None:
    """CPU needs no synchronize; naming it beats an `if` at every call site."""
