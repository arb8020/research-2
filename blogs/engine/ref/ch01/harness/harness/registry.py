"""The op registry: `@op` declares an op whose body IS the reference, `@<op>.register(name)`
attaches a candidate implementation, and `bind(kernels=...)` picks one impl per op, once.

    @op(dims={"rows": (1, 3, 64), "hidden": (1, 7, 768)}, dtypes=(torch.float32,))
    def layer_norm(x: Float[Tensor, "rows hidden"], ...) -> Float[Tensor, "rows hidden"]:
        return F.layer_norm(...)                  # the reference, in plain torch math

    @layer_norm.register("mine")                  # in a candidate file
    def my_layer_norm(x, ...): ...

    bind(kernels={layer_norm: "mine"})            # once per process; then frozen
    layer_norm(x, ...)                            # -> my_layer_norm

Chapter 1 keeps this a PLAIN Python registry: calling an op is a dict lookup and a call. The
seam for later (chapter 8) is `bind(..., torch_ops=True)`, which will wrap each op as a
`torch.library.custom_op` so `torch.compile` / graphs see one opaque op; user code that calls
`layer_norm(x, ...)` does not change.

The check harness (`harness.check`) does NOT go through `bind`: it names a candidate by a
"module:fn" string and runs it in another process, so a candidate is never imported by the
process that holds the expected answers.

`REGISTRY` and `_BOUND` are module globals, an accepted exception to "no ambient globals":
which impl the process dispatches is a fact about the process (as `torch.library` kernels
are), and op declarations are import-time side effects by design.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import torch

REGISTRY: dict[str, Op] = {}
_BOUND: list[Binding] = []


@dataclass(frozen=True)
class Impl:
    """One implementation of one op. `source` is provenance (the upstream symbol it wraps)."""

    name: str
    fn: Callable[..., Any]
    source: str | None


@dataclass(frozen=True)
class GreedyTopK:
    """Opt-in model-level check (vLLM style): greedy-decode `steps` tokens from each prompt with
    the reference and the candidate; at every step the tokens match, or each is in the other's
    top-`k` -- after which the two sequences may diverge and comparison stops. `tokenize` turns
    a prompt into the op's first argument (input ids [1, seq])."""

    prompts: tuple[str, ...]
    steps: int
    k: int
    tokenize: Callable[[str], torch.Tensor]


@dataclass(frozen=True)
class Sweep:
    """What the case generator crosses: edge sizes per named dim, values per scalar argument,
    and the dtypes to run at."""

    dims: dict[str, tuple[int, ...]]
    scalars: dict[str, tuple[float, ...]]
    dtypes: tuple[torch.dtype, ...]


class Op:
    """One op: its reference body, its `Sweep`, its check policy (`blocking`, `model`, opt-in
    `greedy`), and the impls registered on it. A handle created by `@op`, mutated only by its
    own decorators at import time."""

    def __init__(self, name: str, reference: Callable[..., Any], sweep: Sweep, *,
                 blocking: bool, model: bool, greedy: GreedyTopK | None) -> None:
        self.name = name
        self.reference = reference
        self.sweep = sweep
        self.blocking = blocking
        self.model = model
        self.greedy = greedy
        self.impls: dict[str, Impl] = {}
        self.truth_fn: Callable[..., Any] | None = None
        self.inputs_fn: Callable[..., tuple] | None = None

    def __repr__(self) -> str:
        return f"<op {self.name} impls={sorted(self.impls)}>"

    def __call__(self, *args: Any) -> Any:
        """Dispatch to whatever `bind` chose. Unbound is an error, not a silent reference run:
        a script that forgot `bind` should find out, not benchmark the reference."""
        if not _BOUND:
            raise RuntimeError(f"{self.name} called before bind(); call "
                               f"harness.registry.bind(kernels={{...}}) once at startup")
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
        """How to run the reference in fp64 when upcasting the inputs is not enough (a model
        owns its weights). Default: `reference(*inputs upcast to fp64)`."""
        assert self.truth_fn is None, f"{self.name}: truth declared twice"
        self.truth_fn = fn
        return fn

    def inputs(self, fn: Callable[..., tuple]) -> Callable[..., tuple]:
        """Override how a case's inputs are drawn: `fn(case, generator) -> args`. Default:
        `harness.cases.make_inputs` (randn per float tensor, scalars from the case)."""
        assert self.inputs_fn is None, f"{self.name}: inputs declared twice"
        self.inputs_fn = fn
        return fn


def op(*, dims: dict[str, tuple[int, ...]], dtypes: tuple[torch.dtype, ...],
       scalars: dict[str, tuple[float, ...]] | None = None, name: str | None = None,
       blocking: bool = True, model: bool = False,
       greedy: GreedyTopK | None = None) -> Callable[[Callable[..., Any]], Op]:
    """Declare an op whose body is the reference. `dims` gives each named dim its edge sizes;
    `scalars` gives each float argument its values; the case generator crosses them.

    `model=True` marks a model-level check: it always blocks (`blocking=False` is refused)."""
    assert dims, "an op needs at least one named dim to sweep"
    assert dtypes, "an op needs at least one dtype to sweep"
    assert not (model and not blocking), "model-level checks always block"
    assert greedy is None or model, "the greedy top-k check is for model-level ops"
    for dim, sizes in dims.items():
        assert sizes, f"dim {dim!r} has no sizes"
        assert all(size >= 1 for size in sizes), f"dim {dim!r}: sizes must be >= 1, got {sizes}"

    def declare(fn: Callable[..., Any]) -> Op:
        declared_name = name if name is not None else fn.__name__
        assert declared_name not in REGISTRY, f"op {declared_name!r} declared twice"
        declared = Op(declared_name, fn, Sweep(dims, scalars or {}, dtypes),
                      blocking=blocking, model=model, greedy=greedy)
        REGISTRY[declared_name] = declared
        return declared

    return declare


@dataclass(frozen=True)
class Binding:
    """The process's one choice of impl per registered op."""

    impls: dict[str, Impl]

    def line(self) -> str:
        """`kernels: layer_norm=mine gelu_tanh=reference ...`, the line a script logs."""
        return "kernels: " + " ".join(f"{n}={i.name}" for n, i in sorted(self.impls.items()))


def bind(kernels: dict[Op, str] | None = None, *, torch_ops: bool = False) -> Binding:
    """Choose one impl per op, once per process; ops not named run their reference."""
    if torch_ops:
        raise NotImplementedError("torch custom-op wrapping lands with the kernel dispatch "
                                  "layer (chapter 8); chapter 1 binds plain Python callables")
    if _BOUND:
        raise RuntimeError(f"bind already ran in this process ({_BOUND[0].line()}); "
                           f"it runs once. A different selection is a new process.")
    chosen = kernels or {}
    for declared, impl_name in chosen.items():
        if not isinstance(declared, Op):
            raise TypeError(f"kernels= is keyed by op objects, got {declared!r}")
        if impl_name != "reference" and impl_name not in declared.impls:
            raise KeyError(f"{declared.name} has no impl {impl_name!r}; impls: "
                           f"{['reference', *sorted(declared.impls)]}")
    by_name = {declared.name: name for declared, name in chosen.items()}
    impls = {name: _pick(declared, by_name.get(name, "reference"))
             for name, declared in REGISTRY.items()}
    binding = Binding(impls)
    _BOUND.append(binding)
    return binding


def _pick(declared: Op, impl_name: str) -> Impl:
    if impl_name == "reference":
        return Impl("reference", declared.reference, None)
    return declared.impls[impl_name]
