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

from tally.core import Step, StepCtx, Store, digest, open_store, start
from tally.store import Handle, Key

type BuildFn = Callable[[StepCtx], Handle | Sequence[Handle]]


def _handles(out: Handle | Sequence[Handle]) -> tuple[Handle, ...]:
    return (out,) if isinstance(out, Handle) else tuple(out)


def assert_matches_clean(build: BuildFn, store: Store) -> None:
    """
    Rerun `build` against store (must be a no-op: everything cached) and against a fresh empty store;
    output digests must match. "Correct = same as building from scratch."
    """
    cached_ctx = start(store)
    cached_raw = _handles(build(cached_ctx))
    assert cached_ctx.ran == [], f"rebuild right after build did work: {cached_ctx.ran}"
    with tempfile.TemporaryDirectory() as tmp_dir:
        fresh = open_store(Path(tmp_dir))
        clean = tuple(digest(fresh, handle) for handle in _handles(build(start(fresh))))
    cached = tuple(digest(store, handle) for handle in cached_raw)
    assert len(cached) == len(clean), f"{len(cached)} handles vs {len(clean)} from clean"
    for cached_out, clean_out in zip(cached, clean, strict=True):
        assert cached_out.digest == clean_out.digest, f"cached {cached_out.path} != clean build (key {cached_out.key[:12]})"


_CHILD = """
import importlib, pickle, sys
ref, args, kwargs = pickle.load(sys.stdin.buffer)
mod, name = ref.split(":")
step = getattr(importlib.import_module(mod), name)
print(step.key(step, args, kwargs))
"""


def _resolve(ref: str) -> Step:
    mod, name = ref.split(":")
    step = getattr(importlib.import_module(mod), name)
    if not isinstance(step, Step): raise TypeError(f"{ref} is not a Step")
    return step


def key_stability(ref: str, args: tuple = (), kwargs: dict | None = None, seeds: tuple[int, ...] = (1, 2)) -> tuple[Key, ...]:
    """
    Key for step `module:name` computed twice here, then once per PYTHONHASHSEED in a fresh process.
    Stable iff all returned keys are equal.
    """
    kw: dict[str, Any] = kwargs or {}
    step = _resolve(ref)
    local = (step.key(step, args, kw), step.key(step, args, kw))
    env_path = os.pathsep.join(entry for entry in sys.path if entry)
    remote = tuple(
        subprocess.run(
            [sys.executable, "-c", _CHILD], input=pickle.dumps((ref, args, kw)), capture_output=True, check=True, timeout=60,
            env={**os.environ, "PYTHONHASHSEED": str(seed), "PYTHONPATH": env_path},
        ).stdout.decode().strip()
        for seed in seeds
    )
    return local + remote
