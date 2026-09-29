"""Debug helpers: the paper's correctness oracle (Definition 3.1) and KeyFn stability."""
import importlib
import os
import pickle
import subprocess
import sys
import tempfile
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from tally.ctx import Ctx, open_ctx
from tally.step import Step
from tally.types import Handle, Key

type Build = Callable[[Ctx], Handle | Sequence[Handle]]


def _handles(out: Handle | Sequence[Handle]) -> tuple[Handle, ...]:
    return (out,) if isinstance(out, Handle) else tuple(out)


def assert_matches_clean(build: Build, ctx: Ctx) -> None:
    """
    Rerun `build` on ctx (must be a no-op: everything cached) and on a fresh empty store;
    output digests must match. "Correct = same as building from scratch."
    """
    before = len(ctx.ran)
    cached = _handles(build(ctx))
    assert ctx.ran[before:] == [], f"rebuild right after build did work: {ctx.ran[before:]}"
    with tempfile.TemporaryDirectory() as d:
        fresh = open_ctx(Path(d))
        clean = tuple(fresh.digest(h) for h in _handles(build(fresh)))
    cached = tuple(ctx.digest(h) for h in cached)
    assert len(cached) == len(clean), f"{len(cached)} handles vs {len(clean)} from clean"
    for a, b in zip(cached, clean, strict=True):
        assert a.digest == b.digest, f"cached {a.path} != clean build (key {a.key[:12]})"


_CHILD = """
import importlib, pickle, sys
ref, args, kwargs = pickle.load(sys.stdin.buffer)
mod, name = ref.split(":")
s = getattr(importlib.import_module(mod), name)
print(s.key(s, args, kwargs))
"""


def _resolve(ref: str) -> Step:
    mod, name = ref.split(":")
    s = getattr(importlib.import_module(mod), name)
    if not isinstance(s, Step): raise TypeError(f"{ref} is not a Step")
    return s


def key_stability(ref: str, args: tuple = (), kwargs: dict | None = None, seeds: tuple[int, ...] = (1, 2)) -> tuple[Key, ...]:
    """
    Key for step `module:name` computed twice here, then once per PYTHONHASHSEED in a fresh process.
    Stable iff all returned keys are equal.
    """
    kw: dict[str, Any] = kwargs or {}
    step = _resolve(ref)
    local = (step.key(step, args, kw), step.key(step, args, kw))
    env_path = os.pathsep.join(p for p in sys.path if p)
    remote = tuple(
        subprocess.run(
            [sys.executable, "-c", _CHILD], input=pickle.dumps((ref, args, kw)), capture_output=True, check=True, timeout=60,
            env={**os.environ, "PYTHONHASHSEED": str(seed), "PYTHONPATH": env_path},
        ).stdout.decode().strip()
        for seed in seeds
    )
    return local + remote
