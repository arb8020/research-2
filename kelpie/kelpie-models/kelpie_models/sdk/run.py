"""Rung 2: `build` (weights + kv + kernels + cache) and `run` (that, plus the Zig loop).

    with run(gpt2, device="cpu", kernels={ops.layer_norm: my_ln.layer_norm}) as engine:
        rid = engine.submit(prompt_tokens, max_new_tokens=16)

EVERY serve goes through `build`, including an all-reference one: reference impls get manifest
entries like any other, so there is no second path that skips the checks.

`build`'s argument structure IS the config tiers (`sdk/tiers.py`): `capacity=` is realloc,
`buckets=` is recapture, every other keyword is program tier and is exactly `ProgramKey`'s
field list. The live tier is `engine.set`, which is not here at all.

WHAT `build` DOES, in order, and the order is load-bearing:
  1. bind -- ONCE per process (a second build raises): a resolver kernel on every op, nothing
     resolved, no backend imported;
  2. load weights, size the engine, allocate kv, make the `Step` (and the drafter);
  3. enumerate the step shapes (`sdk/shapes.py`: decode / decode_extra / prefill x bucket) and
     log them (`build.shapes`);
  4. WARM: one synthetic plan per (family, bucket), through the step the loop will run. The
     first dispatch of each op resolves it (kernels= > per-arch default > reference) and
     imports its backend -- a missing one fails HERE, naming the op and the fix -- and every
     kernel compiles before serve;
  5. freeze: a `kernels=` key for an op the model never called raises; any op first dispatched
     from now on raises; log the resolved table (`build.kernels`);
  6. capture (CUDA), from the same enumeration: the decode buckets' target forward, or with a
     drafter every decode_extra bucket's whole DFlash step (models/torch/dflash.py `verify`);
  7. check and/or bench each entry, write the manifest, or verify against an existing one.
"""

from __future__ import annotations

import logging
import platform
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any

import torch
from kelpie_engine.sdk.engine import Engine, EngineConfig, GroupSpec

# Aliased: `kernels` is `build`'s parameter name -- the name the caller should type -- so the
# module cannot also hold it.
from kelpie_models import kernels as kernel_lib
from kelpie_models.kernels.op import STEP_NOTE, Binding, Op, Table, freeze
from kelpie_models.sdk import cache as cache_mod
from kelpie_models.sdk import manifest as manifest_mod
from kelpie_models.sdk.groups import derive_groups, choose_block_sizes
from kelpie_models.sdk.kv import alloc_kv, bytes_per_page_of, groups_of
from kelpie_models.sdk.shapes import StepKey, enumerate_steps, synthetic_plan
from kelpie_models.sdk.step import Step
from kelpie_models.sdk.taps import TapKey

try:
    from observe import span as _span
except ImportError:
    from contextlib import contextmanager as _cm
    from dataclasses import dataclass as _dc

    @_dc
    class _NoopState:
        def set_attr(self, k: str, v: object) -> None: ...
        def set_attrs(self, **kw: object) -> None: ...

    @_cm
    def _span(name: str, **kw: object):  # type: ignore[misc]
        yield _NoopState()
from kelpie_models.sdk.tiers import Buckets, Capacity

logger = logging.getLogger("kernels")

DEFAULT_MAX_BATCH_TOKENS = 1024
REGRESSION = 0.10


@dataclass(frozen=True)
class ProgramKey:
    """One built program's identity: everything program-tier that changes what code runs.
    Recorded in the manifest for provenance -- who built this, against what toolchain -- but
    NOT the cache key: the cache is per op (ruling F), so a changed kernel rebuilds that kernel
    and not the world."""

    checkpoint: str
    model_config_hash: str
    kernels: tuple[str, ...]  # "op=impl", sorted; the resolved table
    dtype: str
    device_arch: str  # "cuda:sm_90", "cpu"
    capture: bool
    compile: bool
    toolchain: tuple[str, ...]

    @property
    def digest(self) -> str:
        import hashlib

        payload = "|".join(
            (
                self.checkpoint,
                self.model_config_hash,
                ",".join(self.kernels),
                self.dtype,
                self.device_arch,
                str(self.capture),
                str(self.compile),
                ",".join(self.toolchain),
            )
        )
        return hashlib.sha256(payload.encode()).hexdigest()


@dataclass(frozen=True)
class Built:
    """What `build` produced. `table` is the resolved kernel table: the log line, the manifest
    and serve's fail-closed check all read this one value and never re-derive it."""

    engine: Engine
    step: Step
    table: Table
    key: ProgramKey
    binding: Binding
    # The StepFn the native loop runs: the drafter module's `DFlashStep(target, drafter)` with a
    # drafter (docs/design-multigpu.md 2.4, holding its captured graphs), else `step` itself.
    # `step` stays the target so a hand loop's `engine, target, drafter = build(...)` is
    # unchanged (a hand loop drives `dflash.step`, eager).
    stepper: Any
    drafter: Any = None  # the drafter module's `Drafter` when build(drafter=...), else None

    def __iter__(self) -> Iterator[Any]:
        """`engine, step = build(...)`, or `engine, target, drafter = build(..., drafter=...)`:
        the things a caller drives (docs/design-core-option2.md 1(b))."""
        if self.drafter is None:
            return iter((self.engine, self.step))
        return iter((self.engine, self.step, self.drafter))


def build(  # noqa: PLR0913
    model: ModuleType,
    *,
    device: str = "cpu",
    dtype: torch.dtype | None = None,
    kernels: dict[Op, Any] | None = None,
    capture: bool | None = None,
    compile: bool = False,  # noqa: A002 -- the torch.compile knob; any other name lies
    cache: Path | None = None,
    allow_build: bool = False,
    check: bool = False,
    bench: bool = False,
    capacity: Capacity = Capacity(),
    buckets: Buckets = Buckets(),
    taps: tuple[TapKey, ...] = (),
    drafter: ModuleType | None = None,
    drafter_checkpoint: str | None = None,
    max_extra: int = 0,
) -> Built:
    """Bind kernels, load the model, warm every bucket shape, and settle the cache.

    `kernels` is keyed by the OP OBJECT and is parsed against the ops THIS MODEL CALLS, learned
    by the warm pass (each op resolves at its first dispatch). A key for an op the model never
    calls raises `KernelsError` naming what it does call -- an ignored override is how a user
    ends up sure they swapped a kernel that never ran. Runs once per process (`kernels.bind`).

    `dtype` defaults to the checkpoint's own (`model.DTYPE`); passing it is a program-tier
    override and lands in `ProgramKey`. `capture` None means "capture on cuda".

    `cache` with `allow_build=False` is SERVE: read the manifest, refuse a missing entry or a
    changed fingerprint or a recorded failure, then freeze the directory and shut the JIT doors.
    `allow_build=True` is BUILD: grade (`check`), time (`bench`), and write the manifest.
    """
    torch_dtype = dtype if dtype is not None else getattr(torch, model.DTYPE)
    checkpoint = getattr(model, "CHECKPOINT", model.__name__)
    captures = capture if capture is not None else device.startswith("cuda")
    # The drafter's loop calls the bare Step's forward_device (and reads step.weights for the
    # embedding it borrows), so a compiled wrapper cannot stand in for it. Capture is the
    # drafter step's own (DFlashStep.capture), over the bare Step.
    assert drafter is None or not compile, ("a drafter needs compile=False", device, compile)
    # TODO(2026-09-25): `buckets=` (narrowing the core's ladder) is not wired: the ladder
    # has one writer (kelpie-core/src/buckets.zig) and enumerate_steps reads it whole.
    if buckets != Buckets():
        raise NotImplementedError(
            f"build(buckets={buckets}): narrowing the bucket ladder is not built; every "
            f"bucket of the core's ladder the engine can reach is warmed")

    with _span("build", attributes={
        "checkpoint": checkpoint,
        "device": device,
        "dtype": str(torch_dtype),
        "has_drafter": drafter is not None,
        "drafter_checkpoint": drafter_checkpoint or "",
    }) as build_s:
        if cache is not None:
            # Before anything compiles: the warm pass JITs into it (build) or must not (serve).
            cache_mod.point(cache, serve=not allow_build)
        binding = kernel_lib.bind(device, kernels)

        # A drafter decides Kmax (its block size - 1: every decode entry carries its whole noise
        # block as extra rows) and adds the taps it reads. Loaded once, before the engine exists,
        # because its cache groups are part of the engine's slab plan.
        # Without a drafter, `max_extra` is the caller's own (a loop that fills extra rows
        # itself: scripts/prove_state_lifecycle.py's oracle drafts).
        drafter_weights, drafter_config = None, None
        if drafter is not None:
            drafter_weights, drafter_config = drafter.load(
                device=device, dtype=torch_dtype, checkpoint=drafter_checkpoint)
            assert max_extra in (0, drafter_config.n_draft), (max_extra, drafter_config.n_draft)
            max_extra = drafter_config.n_draft
            taps = tuple(sorted(set(taps) | set(drafter.tap_keys(drafter_config))))

        engine, step, n_target_groups = _assemble(
            model, device, torch_dtype, capacity, taps,
            max_extra=max_extra,
            drafter_specs=None if drafter is None else drafter.attn_specs(drafter_config),
        )
        build_s.set_attrs(n_target_groups=n_target_groups, max_extra=max_extra)

        # max_batch_tokens / max_batch_reqs are LIVE knobs (engine.set): build caps them at the
        # values warmed here (engine.batch_ceiling), and `Step` refuses an unwarmed plan anyway.
        steps = enumerate_steps(engine.live_config())
        _log_shapes(steps)

        built_drafter = None
        if drafter is not None:
            drafter_specs = drafter.attn_specs(drafter_config)
            n_drafter_groups = len(derive_groups(drafter_specs, itemsize=torch_dtype.itemsize)[0])
            assert n_drafter_groups == 1, "a drafter with more than one cache group"
            drafter_kv = alloc_kv(
                drafter_specs, engine.live_config(), device, torch_dtype,
                group_slice=slice(n_target_groups, n_target_groups + n_drafter_groups),
            )
            built_drafter = drafter.Drafter(
                weights=drafter_weights,
                config=drafter_config,
                kv=drafter_kv,
                group=n_target_groups,
                target_embed=step.weights.embed,
                target_lm_head=step.weights.lm_head,
                scratch_slot=_scratch_slot(engine, steps[0], n_target_groups),
            )
        stepper = step if drafter is None else drafter.DFlashStep(step, built_drafter)
        _warm(engine, stepper, steps)
        if getattr(step, "encoder", None) is not None:
            # Only an image request runs the encoder, and no synthetic plan carries one.
            with _span("build.warm", attributes={"family": "encoder", "size": 1}):
                step.encoder.warm()
        table = freeze(binding)
        if isinstance(step, Step):
            # From here a plan of an unwarmed (family, bucket) raises instead of running.
            step.warmed = frozenset(steps)
        warmed_at = engine.live_config()
        engine.batch_ceiling.update(max_batch_tokens=warmed_at.max_batch_tokens,
                                    max_batch_reqs=warmed_at.max_batch_reqs)
        with _span("build.kernels", attributes={"line": table.line()}):
            logger.info("%s", table.line())

        step, stepper = _wrap(engine, step, stepper, steps, captures=captures, compile=compile,
                              has_drafter=drafter is not None)

        key = _program_key(model, table, torch_dtype, device, captures, compile)
        if cache is not None:
            _settle(cache, table, key, steps, binding, allow_build=allow_build, check=check,
                    bench=bench, device=device, dtype=torch_dtype)
        return Built(engine, step, table, key, binding, stepper, built_drafter)


def _assemble(  # noqa: PLR0913, PLR0917
    model: ModuleType,
    device: str,
    dtype: torch.dtype,
    capacity: Capacity,
    taps: tuple[TapKey, ...],
    max_extra: int = 0,
    drafter_specs: list[Any] | None = None,
) -> tuple[Engine, Step, int]:
    """Weights, engine, kv, `Step` -- the parts that exist before anything has run.

    Returns (engine, step, n_target_groups). With a drafter the engine's groups are
    target_groups + drafter_groups (derived separately so they don't merge), and the slab plan
    covers all groups together.
    """
    with _span("assemble", attributes={"device": device, "dtype": str(dtype)}) as asm_s:
        weights, config = model.load(device=device, dtype=dtype)
        target_specs = model.attn_specs(config)
        target_groups, _ = derive_groups(target_specs, itemsize=dtype.itemsize)
        n_target_groups = len(target_groups)
        asm_s.set_attr("n_target_groups", n_target_groups)

        # Combine target + drafter groups for the engine, or just target if no drafter.
        if drafter_specs is not None:
            drafter_groups, _ = derive_groups(drafter_specs, itemsize=dtype.itemsize)
            all_groups = target_groups + drafter_groups
            asm_s.set_attr("n_drafter_groups", len(drafter_groups))
        else:
            all_groups = target_groups

        combined_plan = choose_block_sizes(all_groups)
        asm_s.set_attrs(
            n_groups_total=len(all_groups),
            slab_bytes=combined_plan.slab_bytes,
            bytes_per_page=str(combined_plan.bytes_per_page),
            worst_padding=round(combined_plan.worst_padding, 4),
        )
        all_group_specs = tuple(
            GroupSpec(g.kind, bs, g.window, g.cacheable, g.stride)
            for g, bs in zip(all_groups, combined_plan.block_sizes, strict=True)
        )

        engine = Engine(
            EngineConfig.from_model(
                config,
                all_group_specs,
                max_requests=capacity.max_requests,
                kv_blocks=capacity.num_slabs,
                max_batch_tokens=DEFAULT_MAX_BATCH_TOKENS,
                bytes_per_page=combined_plan.bytes_per_page,
                max_extra=max_extra,
                max_seq_len=capacity.max_seq_len,
            )
        )
        live = engine.live_config()
        asm_s.set_attrs(num_slabs=live.num_slabs, slab_bytes_live=live.slab_bytes)

        # The arena is sized from the geometry the CORE resolved (slab_bytes / num_slabs come back
        # through kelpie_get_config), never recomputed here -- docs/slab-lcm-ladder.md.
        # Target gets its slice of the combined groups.
        # With a drafter the plan was chosen over target + drafter groups, which neither model's
        # alloc_kv can recompute alone -- so cross-check the combined plan here.
        assert combined_plan.bytes_per_page == tuple(live.bytes_per_page), (
            combined_plan.bytes_per_page, live.bytes_per_page)
        assert combined_plan.slab_bytes == live.slab_bytes, (
            combined_plan.slab_bytes, live.slab_bytes)
        kv = alloc_kv(
            target_specs, live, device, dtype,
            group_slice=slice(0, n_target_groups) if drafter_specs is not None else None,
        )
        # A model may bring its own Step (the echo model has no forward to run). Capture and
        # compile wrap it in `build`, after the warm pass has resolved every kernel.
        step = getattr(model, "STEP", Step)(model, weights, config, kv, taps=taps)
        return engine, step, n_target_groups


def _wrap(  # noqa: PLR0913
    engine: Engine,
    step: Step,
    stepper: Any,  # noqa: ANN401 -- a Step or a drafter module's DFlashStep, as in _warm
    steps: list[StepKey],
    *,
    captures: bool,
    compile: bool,  # noqa: A002
    has_drafter: bool,
) -> tuple[Any, Any]:
    """After freeze: capture and/or compile. -> (the step `Built.step` holds, the StepFn the loop
    runs). A drafter's step captures itself (every decode_extra key's whole DFlash step) over the
    bare `Step`, which stays `Built.step` for a hand loop; without one, `Captured` wraps the
    target and is both."""
    if captures and has_drafter:
        n_graphs = stepper.capture(engine, steps)
        logger.info("captured %d decode_extra buckets (the DFlash step)", n_graphs)
    elif captures:
        from kelpie_models.sdk.captured import Captured

        step = Captured(step, engine, steps)
        stepper = step
        logger.info("captured %d decode buckets", step.captured)
    if compile:
        assert not has_drafter, "build refuses compile with a drafter"
        # Custom ops stay opaque to inductor, which is the point: inductor fuses the glue
        # around our kernels and never inside one. Opt-in, recorded in ProgramKey.
        # TODO(2026-09-25): the warm pass runs the UNcompiled step, so the compile happens
        # at the first real step; warming it needs torch.compile over `Step.forward`
        # (a method), not the Step object.
        step = torch.compile(step)
        stepper = step
    return step, stepper


def _scratch_slot(engine: Engine, key: StepKey, group: int) -> int:
    """The core's scratch slot of `group`: every row of a synthetic plan writes it (c_api.zig
    inertRows), so it is read off one here and never recomputed (the core is its one writer)."""
    slots = synthetic_plan(engine, key).tokens.slot_mapping[group]
    assert (slots == slots[0]).all(), "a synthetic plan's rows on more than one slot"
    return int(slots[0])


def _log_shapes(steps: list[StepKey]) -> None:
    """The `build.shapes` line: every (family, bucket) this build warms, per family."""
    per_family: dict[str, list[int]] = {}
    for key in steps:
        per_family.setdefault(key.family, []).append(key.size)
    line = "shapes: " + " ".join(
        f"{family}[{len(sizes)}]={','.join(map(str, sorted(sizes)))}"
        for family, sizes in per_family.items())
    with _span("build.shapes", attributes={
        "line": line, **{f"n_{f}": len(sizes) for f, sizes in per_family.items()},
    }):
        logger.info("%s", line)


def _warm(engine: Engine, stepper: Any, steps: list[StepKey]) -> None:
    """Run the step the loop will run over one synthetic plan per (family, bucket).

    Three things happen here and all three are the point. Each op resolves at its first
    dispatch (`kernels.op`), so the model's op set is learned by running it -- which is what
    `kernels=` is then parsed against. A default whose backend is missing fails here, not at
    serve. And every kernel compiles (Triton JIT, autotune, cuBLAS handles) outside any latency
    budget. The plans are the core's own (`sdk/shapes.py:synthetic_plan`), inert by value, so
    the warm leaves no request, no kv and no step behind -- the engine is exactly as idle after
    as before.

    `stepper` is `Any` because it is whichever StepFn the loop runs: a `Step`, a model's own
    STEP (the echo), or a drafter's `DFlashStep`; each has `warm(plan)`."""
    for key in steps:
        with _span("build.warm", attributes={"family": key.family, "size": key.size}):
            plan = synthetic_plan(engine, key)
            token = STEP_NOTE.set(key)
            try:
                stepper.warm(plan)
            finally:
                STEP_NOTE.reset(token)
    # Nothing to assert about the engine here: a synthetic plan changes no core state (no step,
    # no digest, no request; kelpie-core's synthetic-plan tests replay a follower against it).


def _program_key(  # noqa: PLR0913, PLR0917
    model: ModuleType,
    table: Table,
    dtype: torch.dtype,
    device: str,
    capture: bool,
    compile: bool,  # noqa: A002
) -> ProgramKey:
    import hashlib

    checkpoint = getattr(model, "CHECKPOINT", model.__name__)
    config_hash = hashlib.sha256(checkpoint.encode()).hexdigest()[:16]
    return ProgramKey(
        checkpoint=checkpoint,
        model_config_hash=config_hash,
        kernels=tuple(f"{n}={i}" for n, i in table.entries),
        dtype=str(dtype),
        device_arch=_device_arch(device),
        capture=bool(capture),
        compile=compile,
        toolchain=_toolchain(),
    )


def _device_arch(device: str) -> str:
    kind = device.split(":", 1)[0]
    if kind == "cuda" and torch.cuda.is_available():
        major, minor = torch.cuda.get_device_capability()
        return f"cuda:sm_{major}{minor}"
    return kind


def _toolchain() -> tuple[str, ...]:
    versions = [f"torch={torch.__version__}", f"python={platform.python_version()}"]
    try:
        import triton

        versions.append(f"triton={triton.__version__}")
    except ImportError:
        pass
    if torch.version.cuda:
        versions.append(f"cuda={torch.version.cuda}")
    return tuple(versions)


def _settle(  # noqa: PLR0913
    cache: Path,
    table: Table,
    key: ProgramKey,
    steps: list[StepKey],
    binding: Binding,
    *,
    allow_build: bool,
    check: bool,
    bench: bool,
    device: str,
    dtype: torch.dtype,
) -> None:
    """Serve reads the cache; build writes it. Two verbs, one argument apart."""
    if not allow_build:
        cache_mod.check(cache, table, binding)
        cache_mod.freeze(cache)
        return
    previous = _previous(cache)
    written = _write_manifest(cache, table, key, steps, binding, check=check, bench=bench,
                              device=device, dtype=dtype)
    if previous is not None:
        _warn_regressions(previous, written)


def _previous(cache: Path) -> manifest_mod.Manifest | None:
    try:
        return manifest_mod.read(cache)
    except (FileNotFoundError, AssertionError):
        return None


def _write_manifest(  # noqa: PLR0913
    cache: Path,
    table: Table,
    key: ProgramKey,
    steps: list[StepKey],
    binding: Binding,
    *,
    check: bool,
    bench: bool,
    device: str,
    dtype: torch.dtype,
) -> manifest_mod.Manifest:
    """One row per (op, warmed step shape): the rows say which step shapes this cache compiled
    each kernel for -- `enumerate_steps`, the same list the warm pass and capture ran."""
    from kelpie_models.kernels.fingerprint import fingerprint
    from kelpie_models.kernels.op import REGISTRY

    found = manifest_mod.Manifest(
        program_key=key.digest,
        device=device,
        dtype=str(dtype),
        toolchain=dict(part.split("=", 1) for part in key.toolchain),
        built_at=datetime.now(UTC).isoformat(timespec="seconds"),
    )
    for name, impl in table.entries:
        declared = REGISTRY[name]
        print_ = fingerprint(declared, impl, binding)
        graded = _grade(declared, impl, device, dtype, check=check, bench=bench)
        for step_key in steps:
            found.entries.append(manifest_mod.Entry(name, impl, print_, str(step_key), *graded))
    found.write(cache)
    return found


def _grade(  # noqa: PLR0913
    declared: Op,
    impl: str,
    device: str,
    dtype: torch.dtype,
    *,
    check: bool,
    bench: bool,
) -> tuple[str | None, float | None, float | None, float | None]:
    """-> (verdict, err, budget, time_us) for one op's impl. `check` and `bench` are two plain
    bools, default off (ruling F): a build that only wants the cache warm pays for neither.

    Graded ONCE per op, on the op's own sample args, and copied to every step row.
    TODO(2026-09-25): grade and time each op at every step shape's REAL args, recorded during
    the warm pass -- the same recording op-level iteration wants (iterate one op against the
    inputs a real model gave it, without the model)."""
    from kelpie_models.bench import compare, measure

    args = _sample_args(declared, device, dtype)
    verdict, err, budget, time_us = None, None, None, None
    if check and args is not None:
        graded = compare(declared, impl, args)
        verdict, err, budget = graded.verdict, graded.err, graded.budget
    if bench and args is not None:
        entry = declared.impls.get(impl)
        fn = entry.fn if entry is not None else declared.reference
        try:
            time_us = measure(fn, args)
        except NotImplementedError:
            time_us = None
    return verdict, err, budget, time_us


def _sample_args(declared: Op, device: str, dtype: torch.dtype) -> tuple | None:
    """An op whose sample args raise has no runnable reference yet; it still gets a manifest
    entry (fingerprint and impl), just no verdict and no timing."""
    if declared.sample_args is None:
        return None
    try:
        return declared.sample_args(device, dtype)
    except NotImplementedError:
        return None


def _warn_regressions(previous: manifest_mod.Manifest, current: manifest_mod.Manifest) -> None:
    """A slower kernel is news, not a failure: `build` warns above 10% and never refuses. The
    machine that builds is not always quiet, and a build that fails on noise gets `--force`d
    until nobody reads it."""
    before = {e.key: e.time_us for e in previous.entries if e.time_us is not None}
    for entry in current.entries:
        was = before.get(entry.key)
        if was is None or entry.time_us is None or was <= 0:
            continue
        delta = (entry.time_us - was) / was
        if delta > REGRESSION:
            logger.warning(
                "%s=%s %s: %.1f us -> %.1f us (+%.0f%%)",
                entry.op, entry.impl, entry.step, was, entry.time_us, delta * 100,
            )


@contextmanager
def run(model: ModuleType, **build_args: Any) -> Iterator[Engine]:
    """`build` plus `engine.start_loop(built.stepper)`; on exit tear it down in the one safe
    order. Every keyword is `build`'s -- that signature is the one writer of these names.

    The Zig loop commits what the step returns (n tokens per entry, ABI 3). With a drafter
    that step is the drafter's `DFlashStep`: draft, verify, accept, K extra rows asked for next
    (docs/design-multigpu.md 2.4) -- the same step a hand loop can still drive itself."""
    built = build(model, **build_args)
    try:
        built.engine.start_loop(built.stepper)
        yield built.engine
    finally:
        built.engine.close()
