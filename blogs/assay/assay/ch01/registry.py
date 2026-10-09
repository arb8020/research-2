"""The op registry: `@op` declares an op whose body IS the reference, `@<op>.register(name)` attaches an implementation,
and `bind(kernels=...)` picks one impl per op, once per process.

    @op(dims={"rows": (1, 3, 64), "hidden": (1, 7, 768)}, dtypes=(torch.float32,))
    def layer_norm(x: Float[Tensor, "rows hidden"], ...) -> Float[Tensor, "rows hidden"]:
        return ...                                # the reference, in plain torch math

    @layer_norm.register("mine")                  # in a kernel file
    def my_layer_norm(x, ...): ...

    bind(kernels={layer_norm: "mine"})            # once per process; then frozen
    layer_norm(x, ...)                            # -> my_layer_norm

Chapter 1 keeps this a PLAIN Python registry (a dict lookup and a call); `bind(..., torch_ops=True)` is the chapter 8
seam (torch custom ops). The checks do NOT go through `bind`: they name a candidate by file + function and run it in
an isolated child, so a candidate is never imported by the process that holds the expected answers.

`REGISTRY` and `_BOUND` are module globals, an accepted exception: which impl a process dispatches is a fact about the
process (as torch.library kernels are), and op declarations are import-time side effects by design.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import torch

REGISTRY: dict[str, Op] = {}
_BOUND: list[Binding] = []


@dataclass(frozen=True)
class Impl:
    name: str
    fn: Callable[..., Any]
    source: str | None  # provenance: the upstream symbol it wraps


@dataclass(frozen=True)
class Sweep:
    """What the case generator crosses: edge sizes per named dim, values per scalar argument, dtypes."""

    dims: dict[str, tuple[int, ...]]
    scalars: dict[str, tuple[float, ...]]
    dtypes: tuple[torch.dtype, ...]


@dataclass(eq=False)  # identity hash: ops key bind()'s kernels= dict
class Op:
    """One op: its reference body, sweep and check policy. `kind="model"` is a model-level check (always blocks; cases
    come from `cases_fn`, e.g. prompts, not from dims). Mutated only by its own decorators at import time."""

    name: str
    reference: Callable[..., Any]
    sweep: Sweep
    kind: str = "op"
    blocking: bool = True
    impls: dict[str, Impl] = field(default_factory=dict)
    truth_fn: Callable[..., Any] | None = None  # fp64 truth when upcasting the inputs is not enough
    inputs_fn: Callable[..., tuple] | None = None  # (case, generator) -> args, overriding randn per tensor
    cases_fn: Callable[[], list[Any]] | None = None  # model ops: the explicit case list

    def __repr__(self) -> str:
        return f"<op {self.name} impls={sorted(self.impls)}>"

    def __call__(self, *args: Any) -> Any:
        """Dispatch to whatever `bind` chose. Unbound is an error, not a silent reference run."""
        if not _BOUND:
            raise RuntimeError(f"{self.name} called before bind(); call bind(kernels={{...}}) once at startup")
        return _BOUND[0].impls[self.name].fn(*args)

    def register(self, name: str, *, source: str | None = None) -> Callable[[Callable], Callable]:
        assert name != "reference", "'reference' is the op's own body; pick another impl name"
        assert name not in self.impls, f"{self.name}: impl {name!r} registered twice"
        assert not _BOUND, f"{self.name}: register({name!r}) after bind; the table is frozen"

        def decorate(fn: Callable[..., Any]) -> Callable[..., Any]:
            self.impls[name] = Impl(name, fn, source)
            return fn

        return decorate

    def truth(self, fn: Callable[..., Any]) -> Callable[..., Any]:
        assert self.truth_fn is None, f"{self.name}: truth declared twice"
        self.truth_fn = fn
        return fn

    def inputs(self, fn: Callable[..., tuple]) -> Callable[..., tuple]:
        assert self.inputs_fn is None, f"{self.name}: inputs declared twice"
        self.inputs_fn = fn
        return fn

    def cases(self, fn: Callable[[], list[Any]]) -> Callable[[], list[Any]]:
        assert self.cases_fn is None, f"{self.name}: cases declared twice"
        self.cases_fn = fn
        return fn


def op(*, dims: dict[str, tuple[int, ...]], dtypes: tuple[torch.dtype, ...],
       scalars: dict[str, tuple[float, ...]] | None = None, name: str | None = None,
       blocking: bool = True, kind: str = "op") -> Callable[[Callable[..., Any]], Op]:
    """Declare an op whose body is the reference. `dims` gives each named dim its edge sizes; `scalars` gives each
    float argument its values; the case generator crosses them with `dtypes`."""
    assert kind in ("op", "model"), kind
    assert dtypes, "an op needs at least one dtype"
    assert not (kind == "model" and not blocking), "model-level checks always block"
    for dim, sizes in dims.items():
        assert sizes and all(size >= 1 for size in sizes), f"dim {dim!r}: sizes must be >= 1, got {sizes}"

    def declare(fn: Callable[..., Any]) -> Op:
        declared_name = name if name is not None else fn.__name__
        assert declared_name not in REGISTRY, f"op {declared_name!r} declared twice"
        declared = Op(declared_name, fn, Sweep(dims, scalars or {}, dtypes), kind=kind, blocking=blocking)
        REGISTRY[declared_name] = declared
        return declared

    return declare


@dataclass(frozen=True)
class Binding:
    impls: dict[str, Impl]

    def line(self) -> str:
        """`kernels: layer_norm=mine gelu=reference ...`, the line a script logs."""
        return "kernels: " + " ".join(f"{n}={i.name}" for n, i in sorted(self.impls.items()))


def bind(kernels: dict[Op, str] | None = None, *, torch_ops: bool = False) -> Binding:
    """Choose one impl per op, once per process; ops not named run their reference."""
    if torch_ops:
        raise NotImplementedError("torch custom-op wrapping lands with the kernel dispatch layer (chapter 8)")
    if _BOUND:
        raise RuntimeError(f"bind already ran in this process ({_BOUND[0].line()}); it runs once")
    chosen = kernels or {}
    for declared, impl_name in chosen.items():
        if not isinstance(declared, Op):
            raise TypeError(f"kernels= is keyed by op objects, got {declared!r}")
        if impl_name != "reference" and impl_name not in declared.impls:
            raise KeyError(f"{declared.name} has no impl {impl_name!r}; impls: "
                           f"{['reference', *sorted(declared.impls)]}")
    by_name = {declared.name: impl for declared, impl in chosen.items()}
    impls = {n: (Impl("reference", d.reference, None) if by_name.get(n, "reference") == "reference"
                 else d.impls[by_name[n]]) for n, d in REGISTRY.items()}
    binding = Binding(impls)
    _BOUND.append(binding)
    return binding
