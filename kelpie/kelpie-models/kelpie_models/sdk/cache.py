"""Serving from a built cache: check the manifest, then make a JIT at serve time impossible.

Two halves, and both are needed. Checking the manifest says the kernels we are about to run
were compiled and (if `check`) graded. Closing the JIT doors says nothing ELSE gets compiled --
because a Triton autotune on the first request is a multi-second stall inside a latency budget,
and it is exactly the thing a cache is supposed to have already paid for.
"""

from __future__ import annotations

import logging
import os
import stat
from pathlib import Path

from kelpie_models.kernels.op import Binding, Table
from kelpie_models.sdk import manifest as manifest_mod

logger = logging.getLogger("kernels")

TRITON_DIR = "triton"
FLASHINFER_DIR = "flashinfer"


def point(cache: Path, *, serve: bool) -> None:
    """Send every JIT's on-disk cache INTO `cache`, before anything compiles. Called by `build`
    ahead of bind and the warm pass, in both verbs: a build compiles into `cache/triton`, and a
    serve over the same directory loads from it instead of compiling again. (`freeze` alone was
    too late for this: it ran after the warm pass had already compiled into ~/.triton.)

    Serving also shuts the JIT doors HERE, before the warm pass: a kernel the cache lacks then
    raises naming itself, instead of compiling into (or failing to write) a frozen cache.

    Environment variables because that is the only interface either library reads; set here,
    at the one boundary that owns the cache, never read deeper in. FlashInfer reads its
    workspace base at import, so a second build in one process keeps the first one's."""
    cache.mkdir(parents=True, exist_ok=True)
    os.environ["TRITON_CACHE_DIR"] = str(cache / TRITON_DIR)
    os.environ["FLASHINFER_WORKSPACE_BASE"] = str(cache / FLASHINFER_DIR)
    if serve:
        os.environ["FLASHINFER_DISABLE_JIT"] = "1"
        _refuse_triton_jit()


def check(cache: Path, table: Table, binding: Binding) -> manifest_mod.Manifest:
    """Fail closed against `cache` for every op in the RESOLVED table (resolved under
    `binding`). Raises before the engine starts, never mid-request.

    - no entry for an op            -> refuse ("not built: run kelpie build")
    - fingerprint differs           -> refuse (kernel source or backend version changed)
    - recorded verdict `fail`       -> refuse (incorrect kernel at build time)
    - no verdict (built w/o check)  -> WARN and continue (ruling F: not a refusal)
    """
    from kelpie_models.kernels.fingerprint import fingerprint
    from kelpie_models.kernels.op import REGISTRY

    found = manifest_mod.read(cache)
    for name, impl in table.entries:
        entries = found.for_op(name)
        if not entries:
            raise RuntimeError(
                f"not built: run kelpie build --cache {cache} ({name} has no manifest entry)"
            )
        want = fingerprint(REGISTRY[name], impl, binding)
        matching = [e for e in entries if e.impl == impl and e.fingerprint == want]
        if not matching:
            raise RuntimeError(
                f"kernel source or backend version changed since build: {name}={impl} "
                f"fingerprint {want}, manifest has "
                f"{', '.join(f'{e.impl}@{e.fingerprint}' for e in entries)}; rebuild"
            )
        _check_verdicts(name, impl, matching)
    return found


def _check_verdicts(name: str, impl: str, entries: list[manifest_mod.Entry]) -> None:
    """A recorded FAIL refuses; a missing verdict warns. Split out so `check` stays one screen."""
    for entry in entries:
        if entry.verdict == "fail":
            raise RuntimeError(
                f"incorrect kernel at build time: {name}={impl} at {entry.step} "
                f"failed its budget (err {entry.err}, budget {entry.budget}); rebuild or "
                f"choose another impl"
            )
    if all(e.verdict is None for e in entries):
        logger.warning(
            "%s=%s was built without --check: nothing has graded it against the reference",
            name,
            impl,
        )


def freeze(cache: Path) -> None:
    """Make the served cache read-only. The JIT doors were already shut by `point(cache,
    serve=True)` before the warm pass: a compile is a `RuntimeError` naming the kernel that was
    missing, which is a bug report; a silent recompile is a latency mystery."""
    assert os.environ.get("TRITON_CACHE_DIR") == str(cache / TRITON_DIR), (
        "freeze without point(cache, serve=True) first")
    _read_only(cache)


def _read_only(cache: Path) -> None:
    """Drop the write bit on the cache tree. Not a security boundary -- a statement of intent
    that trips the accident (a stray autotune writing into a shipped cache)."""
    for path in [cache, *cache.rglob("*")]:
        mode = path.stat().st_mode
        path.chmod(mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))


def _refuse_triton_jit() -> None:
    """Triton's compile hook, raising instead of compiling. Best effort by design: the hook has
    moved between torch releases (`triton.knobs` in 3.x, `JITFunction.cache_hook` before), so a
    version that offers neither gets a warning rather than a hard failure -- the manifest check
    above is the real gate, this is the belt.

    On triton 3.x the hook is `knobs.compilation.listener`, which reports `cache_hit` AFTER the
    on-disk lookup. NOT `knobs.runtime.jit_cache_hook`: that one fires on every in-process miss
    BEFORE the disk lookup (triton 3.7.1 runtime/jit.py `_do_compile`), so it refused kernels
    the frozen cache holds -- every specialization a fresh process meets for the first time."""
    try:
        import triton
    except ImportError:
        return

    def refuse(**kwargs: object) -> None:
        key = kwargs.get("fn") or kwargs.get("key") or "?"
        raise RuntimeError(f"JIT at serve time: {key} {kwargs.get('signature', '')} not in cache")

    knobs = getattr(triton, "knobs", None)
    if knobs is not None and hasattr(knobs, "compilation"):
        previous = knobs.compilation.listener
        if getattr(previous, "kelpie_refuses_jit", False):
            return  # a second serve build in this process: already installed

        def refuse_miss(**kwargs: object) -> None:
            if previous is not None:
                previous(**kwargs)
            if not kwargs.get("cache_hit"):
                src = kwargs.get("src")
                raise RuntimeError(f"JIT at serve time: {getattr(src, 'name', src)} compiled; "
                                   f"it is not in {os.environ.get('TRITON_CACHE_DIR')}")

        refuse_miss.kelpie_refuses_jit = True  # type: ignore[attr-defined]
        knobs.compilation.listener = refuse_miss
        return
    jit = getattr(getattr(triton, "runtime", None), "jit", None)
    if jit is not None and hasattr(jit, "JITFunction"):
        jit.JITFunction.cache_hook = staticmethod(refuse)
        return
    logger.warning("triton %s exposes no compile hook; the manifest check is the only gate",
                   getattr(triton, "__version__", "?"))
