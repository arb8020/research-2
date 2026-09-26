"""The op machinery: `@op` declares one, `Op.register` adds a backend's impl, `bind` installs
a first-dispatch RESOLVER on every op, and `freeze` ends resolution and returns the `Table`.

An op is a `torch.library.custom_op` whose body IS the reference implementation, plus the impls
registered on it. Everything about an op -- contract, fake, sample args, backward, every
backend's adapter -- lives in that op's own file under `ops/`; nothing here knows any op's name.

Ops are DISCOVERED, not declared per model: importing an op file makes the op exist, and the
warm pass finds out which ones the model calls by calling them.

    bind(device, kernels)         once per process; registers resolvers, resolves nothing
    build's warm pass             first dispatch of op X: kernels= > per-arch default >
                                  reference; import X's backend (a missing one fails HERE,
                                  naming what to install and how to pick another impl);
                                  register the real impl; run it
    freeze(binding)               a kernels= key the model never called raises; from here an
                                  op first dispatched raises instead of resolving at serve

There is no per-call `backend=`, no context manager, no dispatcher -- a forward calls
`torch.ops.kelpie.<op>` and gets whatever resolved.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

import torch

logger = logging.getLogger("kernels")

REGISTRY: dict[str, "Op"] = {}


@dataclass(frozen=True)
class Impl:
    """One backend's implementation of one op. `predicate` gets the call's args and returns
    False when this impl cannot serve them (an alignment rule, an unsupported argument); it is
    kept so the adapter can refuse rather than compute the wrong thing."""

    name: str
    fn: Callable[..., Any]
    backend: str | None
    source: str | None
    predicate: Callable[..., bool] | None


class Op:
    """One kelpie op. `torch.ops.kelpie.<name>` is the call site; this object is the handle a
    caller passes to `kernels=` and `build` records in the manifest."""

    def __init__(
        self, name: str, reference: Callable[..., Any], handle: Any, mutates: tuple[str, ...]
    ) -> None:
        self.name = name
        self.reference = reference
        self.handle = handle
        self.mutates = mutates
        self.backward: Callable[..., Any] | None = None
        self.impls: dict[str, Impl] = {}
        self.sample_args: Callable[[str, torch.dtype], tuple] | None = None
        self.has_fake = False
        self.has_backward = False

    def __repr__(self) -> str:
        return f"<op kelpie::{self.name} impls={sorted(self.impls)}>"

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        """Calling the op object calls the op -- so `ops.rms_norm(x, ...)` in a test does the
        same thing `torch.ops.kelpie.rms_norm(x, ...)` does in a forward."""
        return self.handle(*args, **kwargs)

    def register(
        self,
        impl: str,
        *,
        source: str | None = None,
        backend: str | None = None,
        predicate: Callable[..., bool] | None = None,
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        """Register one backend's adapter for this op. `impl` is the name a user selects
        (`"fla"`); `backend` is the declared backend it needs (defaults to `impl`); `source` is
        the upstream symbol it wraps, recorded for provenance."""
        assert impl not in self.impls, f"{self.name}: impl {impl!r} registered twice"

        def decorate(fn: Callable[..., Any]) -> Callable[..., Any]:
            self.impls[impl] = Impl(impl, fn, backend if backend is not None else impl, source,
                                    predicate)
            return fn

        return decorate

    def register_fake(self, fn: Callable[..., Any]) -> Callable[..., Any]:
        """The shape rule, so the op composes under `torch.compile` and meta tracing."""
        self.has_fake = True
        return self.handle.register_fake(fn)

    def register_autograd(self, backward: Callable[..., Any], **kwargs: Any) -> None:
        """Training is deferred (branch integrate/train-step); every op registers a backward
        that raises, so a `.backward()` names the branch instead of a torch autograd error.

        Torch refuses an autograd formula on a NON-FUNCTIONAL op (one that mutates an argument:
        every attention op writes its kv_member, every recurrent op its state). Those keep the
        backward here on the `Op` -- the conventions check reads `has_backward`, and calling it
        raises the same message -- because functionalizing a paged KV write to satisfy torch's
        rule would mean copying the cache, which is the one thing paging exists to avoid."""
        self.has_backward = True
        self.backward = backward
        if not self.mutates:
            self.handle.register_autograd(backward, **kwargs)

    def samples(self, fn: Callable[[str, torch.dtype], tuple]) -> Callable[..., Any]:
        """Small tensors for opcheck and for `bench.compare`. One decorator so the conventions
        check can see the op has them."""
        self.sample_args = fn
        return fn

    def resolve(self, choice: Any) -> Impl:
        """A `kernels=` value or a device default -> the `Impl` its first dispatch installs. A
        string names a registered impl; `self.reference` (or any callable) becomes an anonymous
        impl named for the function, so an ad-hoc override still gets a manifest entry and a
        fingerprint."""
        if isinstance(choice, str):
            assert choice in self.impls or choice == "reference", (
                f"{self.name}: no impl {choice!r}; impls: {['reference', *sorted(self.impls)]}"
            )
            return self.reference_impl() if choice == "reference" else self.impls[choice]
        assert callable(choice), f"{self.name}: kernels= wants a callable or an impl name"
        if choice is self.reference:
            return self.reference_impl()
        for entry in self.impls.values():
            if entry.fn is choice:
                return entry
        return Impl(_impl_name(choice), choice, None, None, None)

    def reference_impl(self) -> Impl:
        """The op's own body as an `Impl`, so an all-reference build is an ordinary build with
        ordinary manifest entries (ruling F: every serve goes through build)."""
        return Impl("reference", self.reference, None, None, None)


def _impl_name(fn: Callable[..., Any]) -> str:
    """`my_ln.layer_norm` -- module-qualified, because that is what build's kernels line must
    show for the reader to find the code."""
    module = getattr(fn, "__module__", "?")
    return f"{module}.{getattr(fn, '__name__', repr(fn))}"


def op(fn: Callable[..., Any]) -> Op:
    """Declare `kelpie::<fn.__name__>` with `fn`'s body as the reference implementation.

    Every kelpie op goes through here -- including ops torch already has (`layer_norm`,
    `gelu`), whose reference body just calls `F.*`. We NEVER `register_kernel` on `aten::*`:
    that is process-global and would leak kelpie's kernels into any other torch code sharing
    the process (an HF oracle, a trainer)."""
    name = fn.__name__
    assert name not in REGISTRY, f"op {name!r} declared twice"
    mutates = getattr(fn, "_kelpie_mutates", ())
    handle = torch.library.custom_op(f"kelpie::{name}", fn, mutates_args=mutates)
    declared = Op(name, fn, handle, tuple(mutates))
    REGISTRY[name] = declared
    if _BOUND:
        # Declared after bind (a model module imported late): it still gets a resolver, so
        # its first dispatch resolves -- or, after freeze, raises -- like every other op's.
        _install_resolver(_BOUND[0], declared)
    return declared


def mutates(*args: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Mark which parameters an op writes in place, read by `@op`. Spelled as a decorator so
    the fact sits above the signature it constrains, next to `@op`."""

    def decorate(fn: Callable[..., Any]) -> Callable[..., Any]:
        fn._kelpie_mutates = args  # type: ignore[attr-defined]
        return fn

    return decorate




# ---- selection ------------------------------------------------------------------------------


class BuildError(RuntimeError):
    """The build cannot go on, and the message says what to do: a second `bind`, a default
    whose backend is missing, an op first dispatched after the build froze its table."""


class KernelsError(BuildError, ValueError):
    """A `kernels=` entry this build cannot honour: its key names an op the model never calls,
    or its value names an impl the op does not have."""


@dataclass(frozen=True)
class Resolved:
    """One op's resolved kernel and why it was chosen: `kernels=` beat the device default,
    which beat the op's own reference body."""

    impl: Impl
    source: str  # "kernels=" | "default" | "reference"


class Binding:
    """The process's one kernel binding: the device kind, the parsed `kernels=` and device
    defaults it resolves from, and the ops it has resolved so far (in first-dispatch order).

    Mutable on purpose, with one writer: the resolver kernel `bind` registers on every op. The
    warm pass is what drives it (the first dispatch of an op resolves it), and `freeze` ends it:
    after that, a dispatch of an op that never resolved raises instead of resolving at serve."""

    def __init__(self, device: str, defaults: dict[str, str], overrides: dict[str, Impl]) -> None:
        self.device = device
        self.defaults = defaults
        self.overrides = overrides
        self.resolved: dict[str, Resolved] = {}
        self.frozen = False

    @property
    def impls(self) -> dict[str, Impl]:
        """Op name -> the impl torch now dispatches, for every op the model has called."""
        return {name: entry.impl for name, entry in self.resolved.items()}

    def called(self) -> set[str]:
        """The ops the model dispatched: exactly the ops that resolved."""
        return set(self.resolved)


# The ONE piece of process state here, and it mirrors one torch already keeps:
# `torch.library.register_kernel` is process-global, so "which binding does the dispatcher
# hold" is a fact about the process, not about any value. `bind` sets it once; nothing clears it.
_BOUND: list[Binding] = []

# The torch device types a kelpie op is ever dispatched on; bind refuses every one but its own.
_TORCH_DEVICES = frozenset({"cpu", "cuda", "mps"})

# What the process is stepping right now, for the post-freeze message: the warm pass sets it
# per synthetic plan and `Step.forward_device` per real one (`sdk/shapes.py:StepKey`). Opaque
# here -- this module only prints it.
STEP_NOTE: ContextVar[object | None] = ContextVar("kelpie_step_note", default=None)


def bind(device: str, kernels: dict[Op, Any] | None = None) -> Binding:
    """Install a RESOLVER kernel on every registered op for `device`, and resolve nothing.

    Runs ONCE per process: a second call raises. `torch.library` kernels are process-global,
    and a captured graph closes over the kernels it saw, so "rebinding" could only mean an
    engine whose graphs and eager fallbacks run different kernels. A new kernel set is a new
    process (the fast loops are op-level iteration, and whole-model runs with a warm cache).
    TODO(2026-09-25): op-level iteration against RECORDED inputs -- capture each op's args from
    a real model's warm pass or run, then iterate one kernel against them with no model and no
    rebind. Today op-level work has only each op's small `samples` (bench/compare.py).

    `kernels` is keyed by the OP OBJECT (`{ops.rms_norm: my_rms_norm}`), values a callable or
    a registered impl name. It is PARSED here -- an impl name the op does not have raises now --
    but no backend is imported: the first dispatch of op X (during `build`'s warm pass)
    resolves X, so a dense model never resolves `moe` and never needs Marlin installed."""
    from kelpie_models.kernels.devices import defaults_for

    if _BOUND:
        raise BuildError(
            f"bind already ran in this process (kernels[{_BOUND[0].device}]); it runs once per "
            f"process. Build a different kernel set or device in a new process.")
    kind = str(device).split(":", 1)[0]
    overrides = {declared.name: _parse_choice(declared, choice)
                 for declared, choice in (kernels or {}).items()}
    binding = Binding(kind, defaults_for(device), overrides)
    for declared in REGISTRY.values():
        _install_resolver(binding, declared)
    _BOUND.append(binding)
    return binding


def _parse_choice(declared: object, choice: object) -> Impl:
    """One `kernels=` entry -> its `Impl`, raising `KernelsError` for a key that is not an op
    or a value the op cannot resolve. The boundary: past here a choice is an `Impl`."""
    if not isinstance(declared, Op):
        raise KernelsError(
            f"kernels= is keyed by the op object (kernels={{ops.rms_norm: ...}}), got "
            f"{declared!r}")
    if isinstance(choice, str) and choice not in declared.impls and choice != "reference":
        raise KernelsError(
            f"kernels={{ops.{declared.name}: {choice!r}}}: {declared.name} has no impl "
            f"{choice!r}; impls: {', '.join(['reference', *sorted(declared.impls)])}")
    if not isinstance(choice, str) and not callable(choice):
        raise KernelsError(
            f"kernels={{ops.{declared.name}: {choice!r}}}: want an impl name or a callable")
    return declared.resolve(choice)


def _install_resolver(binding: Binding, declared: Op) -> None:
    """Register the op's first-dispatch kernel for `binding.device`. It resolves the op, swaps
    itself out for the real impl (torch keeps one kernel per op and device), and runs it."""

    def resolve_on_first_dispatch(*args: Any, **kwargs: Any) -> Any:
        if binding.frozen:
            raise BuildError(
                f"kelpie::{declared.name} first dispatched after build ({_note()}): the warm "
                f"pass never called it, so no kernel was resolved or warmed for it. A forward "
                f"may branch only on cfg and the step family/bucket (sdk/step.py), and "
                f"`sdk/shapes.py:enumerate_steps` must cover every family this model runs.")
        entry = _resolve(binding, declared)
        torch.library.register_kernel(declared.handle, binding.device)(entry.impl.fn)
        binding.resolved[declared.name] = entry
        return entry.impl.fn(*args, **kwargs)

    resolve_on_first_dispatch.__name__ = f"resolve_{declared.name}"
    torch.library.register_kernel(declared.handle, binding.device)(resolve_on_first_dispatch)

    def refuse_other_device(*args: Any, **kwargs: Any) -> Any:
        del args, kwargs
        raise BuildError(
            f"kelpie::{declared.name} dispatched on a device other than {binding.device!r}, "
            f"the one this process bound ({_note()}): it would run the reference body, "
            f"unresolved and missing from the kernel table. Move its inputs to "
            f"{binding.device}, or bind that device in its own process.")

    # Without these, a call on another device's tensors silently runs the op's own body (the
    # custom_op default): never resolved, never refused after freeze, absent from the table.
    for other in _TORCH_DEVICES - {binding.device}:
        torch.library.register_kernel(declared.handle, other)(refuse_other_device)


def _resolve(binding: Binding, declared: Op) -> Resolved:
    """kernels= > per-arch device default > the op's reference body; then import the chosen
    impl's backend, which is where a missing backend fails -- at the first dispatch, naming
    the op, the impl, what to install and how to pick another."""
    from kelpie_models.kernels.backends import BackendUnavailableError, require

    assert declared.name not in binding.resolved, f"{declared.name} resolved twice"
    if declared.name in binding.overrides:
        entry = Resolved(binding.overrides[declared.name], "kernels=")
    elif declared.name in binding.defaults:
        entry = Resolved(declared.resolve(binding.defaults[declared.name]), "default")
    else:
        entry = Resolved(declared.reference_impl(), "reference")
    if entry.impl.backend is None:
        return entry
    try:
        require(entry.impl.backend)
    except BackendUnavailableError as exc:
        others = ", ".join(repr(n) for n in ["reference", *sorted(declared.impls)]
                           if n != entry.impl.name)
        raise BuildError(
            f"kelpie::{declared.name}={entry.impl.name} ({entry.source} on {binding.device}, "
            f"first dispatched at {_note()}) needs backend {entry.impl.backend!r}: {exc}. "
            f"Install it, or pick another impl: kernels={{ops.{declared.name}: <one of "
            f"{others}>}}"
        ) from exc
    return entry


def _note() -> str:
    note = STEP_NOTE.get()
    return "step unknown" if note is None else str(note)


@dataclass(frozen=True)
class Table:
    """The RESOLVED kernel table: every op the model called, mapped to exactly one impl. Made
    once, by `freeze`; the log line, the manifest and serve's fail-closed check all read this
    and never re-derive or re-validate it."""

    device: str
    entries: tuple[tuple[str, str], ...]  # (op name, impl name), sorted

    def line(self) -> str:
        """`kernels[cuda]: rms_norm=triton rope=triton paged_attention=reference` -- the one
        line `build` logs, naming only the ops this model actually calls."""
        body = " ".join(f"{name}={impl}" for name, impl in self.entries)
        return f"kernels[{self.device}]: {body}"

    def names(self) -> tuple[str, ...]:
        return tuple(name for name, _ in self.entries)


def freeze(binding: Binding) -> Table:
    """After the warm pass: check every `kernels=` key against the ops the model called, stop
    resolving, and return the table.

    A key for an uncalled op RAISES rather than warning -- silently ignoring it is how a user
    ends up sure they swapped a kernel that never ran. From here on an op that never resolved
    raises on its first dispatch (`_install_resolver`)."""
    assert not binding.frozen, "freeze ran twice"
    assert binding is _BOUND[0], "freeze of a binding this process does not dispatch"
    called = binding.called()
    for name in sorted(binding.overrides):
        if name not in called:
            raise KernelsError(
                f"kernels={{ops.{name}: ...}}: {name} is never called by this model; ops "
                f"called: {', '.join(sorted(called))}")
    binding.frozen = True
    return Table(binding.device, tuple(sorted((n, e.impl.name) for n, e in
                                              binding.resolved.items())))
