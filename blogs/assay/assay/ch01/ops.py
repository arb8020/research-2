"""Chapter 1's ops: what a check runs and what the right answer is (everything here is part of the expected answer's
cache key, so editing this file recomputes expected answers; graders live in suite.py so editing them does not).

Sections: op registry (`@op`), op specs (the references: linear, gelu, layer_norm, causal_attention), case generator,
numerics (budget pieces + reductions, no thresholds), prompts, the model-level op (gpt2 forward vs HuggingFace).
"""

from __future__ import annotations

import functools
import inspect
import itertools
import math
import typing
import zlib
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import jaxtyping
import torch
from jaxtyping import Float, Int
from torch import Tensor

NAMES = {"fp64": torch.float64, "fp32": torch.float32, "fp16": torch.float16, "bf16": torch.bfloat16}
SHORT = {v: k for k, v in NAMES.items()}


# --------------------------------------------------------------------------------------------------------------------
# op registry
#
# The op registry: `@op` declares an op whose body IS the reference, `@<op>.register(name)` attaches an implementation,
# and `bind(kernels=...)` picks one impl per op, once per process.
#
#     @op(dims={"rows": (1, 3, 64), "hidden": (1, 7, 768)}, dtypes=(torch.float32,))
#     def layer_norm(x: Float[Tensor, "rows hidden"], ...) -> Float[Tensor, "rows hidden"]:
#         return ...                                # the reference, in plain torch math
#
#     @layer_norm.register("mine")                  # in a kernel file
#     def my_layer_norm(x, ...): ...
#
#     bind(kernels={layer_norm: "mine"})            # once per process; then frozen
#     layer_norm(x, ...)                            # -> my_layer_norm
#
# Chapter 1 keeps this a PLAIN Python registry (a dict lookup and a call); `bind(..., torch_ops=True)` is the chapter 8
# seam (torch custom ops). The checks do NOT go through `bind`: they name a candidate by file + function and run it in
# an isolated child, so a candidate is never imported by the process that holds the expected answers.
#
# `REGISTRY` and `_BOUND` are module globals, an accepted exception: which impl a process dispatches is a fact about the
# process (as torch.library kernels are), and op declarations are import-time side effects by design.
# --------------------------------------------------------------------------------------------------------------------

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


# --------------------------------------------------------------------------------------------------------------------
# op specs
#
# Chapter 1's op specs: each body is the reference (plain torch math), each annotation names the dims the sweep sizes.
# Signatures are the reader's: `gpt2.py` defines functions with these names and arguments, and a check binds by name.
# Linear weights use GPT-2's checkpoint layout ([in, out], applied as x @ W), so the reader's file needs no transposes.
# --------------------------------------------------------------------------------------------------------------------

BOTH = (torch.float32, torch.bfloat16)


# 768 -> 2304 is gpt2's qkv projection; 1 and 7 are the odd edges.
@op(dims={"rows": (1, 3, 17, 64), "in_features": (1, 7, 768), "out_features": (1, 5, 2304)}, dtypes=BOTH)
def linear(x: Float[Tensor, "rows in_features"], weight: Float[Tensor, "in_features out_features"],
           bias: Float[Tensor, "out_features"]) -> Float[Tensor, "rows out_features"]:
    return x @ weight + bias


@op(dims={"rows": (1, 3, 64), "cols": (1, 7, 768, 3072)}, dtypes=BOTH)
def gelu(x: Float[Tensor, "rows cols"]) -> Float[Tensor, "rows cols"]:
    """GPT-2's GELU, the tanh approximation: 0.5 x (1 + tanh(sqrt(2/pi) (x + 0.044715 x^3)))."""
    return 0.5 * x * (1.0 + torch.tanh(math.sqrt(2.0 / math.pi) * (x + 0.044715 * x ** 3)))


# rows/hidden = 1 are the degenerate rows (variance exactly 0: only eps keeps it finite); 17 / 769 are tile+1 sizes;
# eps=0.1 makes a missing eps visible.
@op(dims={"rows": (1, 2, 3, 17, 64), "hidden": (1, 3, 7, 64, 769)}, dtypes=BOTH, scalars={"eps": (1e-5, 1e-1)})
def layer_norm(x: Float[Tensor, "rows hidden"], weight: Float[Tensor, "hidden"], bias: Float[Tensor, "hidden"],
               eps: float) -> Float[Tensor, "rows hidden"]:
    """(x - mean) / sqrt(var + eps) * weight + bias over the last dim; biased variance."""
    mean = x.mean(dim=-1, keepdim=True)
    var = ((x - mean) ** 2).mean(dim=-1, keepdim=True)
    return (x - mean) / torch.sqrt(var + eps) * weight + bias


# One sequence (the reader's forward is unbatched): [heads, seq, head_dim]. seq=1 is a lone query; 16/17 straddle a
# tile; head_dim=1 makes the scale a no-op, so the sweep must also cross head_dim 8/64 with seq > 1 (pairwise does).
@op(dims={"heads": (1, 2, 12), "seq": (1, 2, 7, 16, 17, 64), "head_dim": (1, 8, 64)}, dtypes=BOTH)
def causal_attention(q: Float[Tensor, "heads seq head_dim"], k: Float[Tensor, "heads seq head_dim"],
                     v: Float[Tensor, "heads seq head_dim"]) -> Float[Tensor, "heads seq head_dim"]:
    """softmax(q k^T / sqrt(head_dim)) v, each position seeing itself and the past."""
    seq = q.shape[-2]
    scores = q @ k.transpose(-1, -2) / math.sqrt(q.shape[-1])
    allowed = torch.ones(seq, seq, dtype=torch.bool, device=q.device).tril()  # key j visible to query i iff j <= i
    return torch.softmax(scores.masked_fill(~allowed, float("-inf")), dim=-1) @ v


# --------------------------------------------------------------------------------------------------------------------
# case generator
#
# The case generator: an op's named dims x its scalar values x its dtypes -> a list of `Case`s,
# and a `Case` + a seeded `torch.Generator` -> concrete inputs. A model op lists its cases itself (`@op.cases`).
#
# Shapes come from the reference's own annotations (`x: Float[Tensor, "rows hidden"]`, popcorn
# style, via jaxtyping); sizes come from the op's `dims=` -- explicit edge values per dim (1,
# small primes, tile +- 1, the largest size that matters). Small sweeps are the full cross product;
# past `FULL_PRODUCT_LIMIT` cases it is a pairwise covering array (every pair of values across
# every two axes appears in some case) plus the all-smallest and all-largest corners.
#
# Every case owns its seed (crc32 of op name + case label), so a case is reproducible on its own:
# `run_checks ch01 --op layer_norm` and a failing case re-run give the same tensors.
# --------------------------------------------------------------------------------------------------------------------

FULL_PRODUCT_LIMIT = 64  # past this many cases, cover pairs instead of the full product


@dataclass(frozen=True)
class Case:
    """One point of an op's sweep: a size per named dim, a value per scalar argument, a dtype."""

    sizes: tuple[tuple[str, int], ...]
    scalars: tuple[tuple[str, float], ...]
    dtype: torch.dtype
    seed: int
    prompt: str = ""  # model cases: which prompt

    def label(self) -> str:
        """`rows=3 hidden=7 eps=1e-05` -- the shape part of a verdict's case (the dtype is its own field)."""
        parts = [f"prompt={self.prompt}"] if self.prompt else []
        parts += [f"{n}={v}" for n, v in self.sizes] + [f"{n}={v:g}" for n, v in self.scalars]
        return " ".join(parts)

    @property
    def dtype_name(self) -> str:
        return SHORT[self.dtype]

    def to_json(self) -> dict:
        return {"sizes": dict(self.sizes), "scalars": dict(self.scalars), "dtype": self.dtype_name,
                "seed": self.seed, "prompt": self.prompt}


def sweep(declared: Op) -> list[Case]:
    """Every case the op is checked on, in a fixed order."""
    if declared.cases_fn is not None:
        return declared.cases_fn()
    _assert_dims_match(declared)
    plan = declared.sweep
    axes: list[tuple[Any, ...]] = [*plan.dims.values(), *plan.scalars.values(), plan.dtypes]
    full_size = math.prod(len(values) for values in axes)
    rows = (list(itertools.product(*[range(len(values)) for values in axes]))
            if full_size <= FULL_PRODUCT_LIMIT else _pairwise_with_corners(axes))
    dim_names = list(plan.dims)
    scalar_names = list(plan.scalars)
    cases = []
    for row in rows:
        picked = [values[index] for values, index in zip(axes, row, strict=True)]
        sizes = tuple(zip(dim_names, picked[:len(dim_names)], strict=True))
        scalars = tuple(zip(scalar_names, picked[len(dim_names):-1], strict=True))
        unseeded = Case(sizes, scalars, picked[-1], 0)
        seed = zlib.crc32(f"{declared.name}|{unseeded.label()} {unseeded.dtype_name}".encode())
        cases.append(Case(sizes, scalars, picked[-1], seed))
    assert len({(c.label(), c.dtype) for c in cases}) == len(cases), "sweep produced duplicate cases"
    return cases


def make_inputs(declared: Op, case: Case) -> tuple:
    """The case's concrete arguments, drawn from the case's own seeded generator."""
    generator = torch.Generator().manual_seed(case.seed)
    if declared.inputs_fn is not None:
        return declared.inputs_fn(case, generator)
    sizes = dict(case.sizes)
    scalars = dict(case.scalars)
    args = []
    for param, annotation in _params(declared):
        if param in scalars:
            args.append(scalars[param])
            continue
        assert _is_tensor_annotation(annotation), (
            f"{declared.name}: parameter {param!r} is neither an annotated tensor nor in scalars=")
        assert "float32" in annotation.dtypes, (
            f"{declared.name}: {param!r} is not a float tensor; give the op an @inputs maker")
        shape = [sizes[dim] for dim in annotation.dim_str.split()]
        args.append(torch.randn(shape, generator=generator).to(case.dtype))
    return tuple(args)


def _params(declared: Op) -> list[tuple[str, Any]]:
    hints = typing.get_type_hints(declared.reference)
    names = list(inspect.signature(declared.reference).parameters)
    return [(name, hints.get(name)) for name in names]


def _is_tensor_annotation(annotation: Any) -> bool:
    return isinstance(annotation, type) and issubclass(annotation, jaxtyping.AbstractArray)


def _assert_dims_match(declared: Op) -> None:
    """Every dim an input annotation names has sizes in `dims=`, and every `dims=` entry is used.
    (The return annotation is documentation: its dims may be fixed by the op, like `vocab`.)"""
    used = {dim for _, annotation in _params(declared) if _is_tensor_annotation(annotation)
            for dim in annotation.dim_str.split()}
    sized = set(declared.sweep.dims)
    assert used <= sized, f"{declared.name}: dims without sizes: {sorted(used - sized)}"
    assert sized <= used, f"{declared.name}: sized dims no input uses: {sorted(sized - used)}"


def _pairwise_with_corners(axes: list[tuple[Any, ...]]) -> list[tuple[int, ...]]:
    """Greedy covering array over value INDICES: every (axis a value i, axis b value j) pair is
    in some row. Each row starts from the smallest uncovered pair and fills the other axes with
    whichever value covers the most still-uncovered pairs, so every row covers >= 1 new pair
    and the loop ends. Then the all-first and all-last rows (the corners a pair list can miss)."""
    uncovered = {(a, i, b, j)
                 for a, b in itertools.combinations(range(len(axes)), 2)
                 for i in range(len(axes[a])) for j in range(len(axes[b]))}
    rows: list[tuple[int, ...]] = []
    while uncovered:
        a, i, b, j = min(uncovered)
        row = {a: i, b: j}
        for axis in range(len(axes)):
            if axis in row:
                continue
            row[axis] = max(range(len(axes[axis])),
                            key=lambda value: (_gain(uncovered, row, axis, value), -value))
        indices = tuple(row[axis] for axis in range(len(axes)))
        covered = {(x, indices[x], y, indices[y])
                   for x, y in itertools.combinations(range(len(axes)), 2)}
        assert covered & uncovered, "pairwise row covered nothing new"
        uncovered -= covered
        rows.append(indices)
    corners = [tuple(0 for _ in axes), tuple(len(values) - 1 for values in axes)]
    return rows + [corner for corner in corners if corner not in rows]


def _gain(uncovered: set, row: dict[int, int], axis: int, value: int) -> int:
    return sum(((min(axis, other), value if axis < other else chosen,
                 max(axis, other), chosen if axis < other else value) in uncovered)
               for other, chosen in row.items())


# --------------------------------------------------------------------------------------------------------------------
# numerics
#
# Numbers, no thresholds: the reference's own error vs fp64 truth (what the budget is made of) and the reductions of a
# candidate's output vs truth that a Run stores (all a grader needs, so grades never need the full output again).
#
# Budget (crucible / popcorn / FlashAttention): a correct implementation may land as far from fp64 truth as the
# reference itself does in this precision, with a factor for slack and a floor for when the reference is exact:
#
#     err(candidate) <= max(mult * err(reference), floor[dtype] * max|truth|)
#
# `mult` and the floors are grader config (grade.py), so changing them regrades stored runs without re-running.
# --------------------------------------------------------------------------------------------------------------------

TOPK = 5


def max_abs(a: torch.Tensor, b: torch.Tensor) -> float:
    """max |a - b| in fp64; inf if either side has a non-finite value where the other does not match it."""
    diff = (a.double() - b.double()).abs()
    return float(diff.max()) if diff.numel() and bool(torch.isfinite(diff).all()) else (
        0.0 if diff.numel() == 0 else math.inf)


def reference_stats(truth: torch.Tensor, reference: torch.Tensor) -> dict[str, float]:
    """The reference's own error at its dtype, and the truth's scale. Truth must be finite or the case is broken."""
    assert truth.dtype == torch.float64, f"truth must be fp64, got {truth.dtype}"
    assert reference.shape == truth.shape, f"reference {tuple(reference.shape)} vs truth {tuple(truth.shape)}"
    assert bool(torch.isfinite(truth).all()), "truth has non-finite values: a broken case"
    assert bool(torch.isfinite(reference).all()), "the reference has non-finite values at its dtype"
    stats = {"ref_err": max_abs(reference, truth), "scale": float(truth.abs().max()) if truth.numel() else 0.0}
    if truth.dim() == 2 and truth.shape[-1] > 1000:  # logits: also the reference's own KL, for context
        stats["ref_kl_max"] = float(kl_per_position(truth, reference).max())
    return stats


def band(ref_err: float, scale: float, dtype: str, mult: float, floors: dict[str, float]) -> float:
    return max(mult * ref_err, floors[dtype] * scale)


def kl_per_position(truth: torch.Tensor, ours: torch.Tensor) -> torch.Tensor:
    """KL(softmax(truth) || softmax(ours)) for each row -> [T], nats, fp64."""
    lp_truth = torch.log_softmax(truth.double(), dim=-1)
    lp_ours = torch.log_softmax(ours.double(), dim=-1)
    return (lp_truth.exp() * (lp_truth - lp_ours)).sum(-1)


def reduce_output(out: torch.Tensor, truth: torch.Tensor) -> dict[str, Any]:
    """What a Run keeps about an output that matched truth's shape: its error, and for logits the per-position
    stats + top-k logprobs (the reduced artifact: [T, vocab] logits are ~200 MB at 1024 tokens)."""
    facts: dict[str, Any] = {"err": max_abs(out, truth), "finite": bool(torch.isfinite(out).all())}
    if truth.dim() != 2 or truth.shape[-1] <= 1000:
        return facts
    kl = kl_per_position(truth, out)
    per_pos_err = (out.double() - truth).abs().amax(dim=-1)
    lp_truth = torch.log_softmax(truth, dim=-1).topk(TOPK, dim=-1)
    lp_ours = torch.log_softmax(out.double(), dim=-1).topk(TOPK, dim=-1)
    ok = [(int(o[0]) in set(t.tolist())) and (int(t[0]) in set(o.tolist()))
          for t, o in zip(lp_truth.indices, lp_ours.indices, strict=True)]
    facts.update({
        "kl_max": float(kl.max()) if bool(torch.isfinite(kl).all()) else math.inf,
        "kl_mean": float(kl.mean()),
        "kl_argmax": int(kl.argmax()),
        "topk_ok": all(ok),
        "topk_first_bad": next((i for i, good in enumerate(ok) if not good), None),
        "top1_agree": float((lp_truth.indices[:, 0] == lp_ours.indices[:, 0]).double().mean()),
        "reduced": {"kl": kl.tolist(), "err": per_pos_err.tolist(),
                    "truth_topk": [lp_truth.indices.tolist(), lp_truth.values.tolist()],
                    "ours_topk": [lp_ours.indices.tolist(), lp_ours.values.tolist()]},
    })
    return facts


# --------------------------------------------------------------------------------------------------------------------
# prompts
#
# Fixed text for the measurement prompts. Prose is public domain (Dickens, Lincoln, Melville, Austen).
# --------------------------------------------------------------------------------------------------------------------

TWO_CITIES = (
    "It was the best of times, it was the worst of times, it was the age of wisdom, it was the age of "
    "foolishness, it was the epoch of belief, it was the epoch of incredulity, it was the season of Light, "
    "it was the season of Darkness, it was the spring of hope, it was the winter of despair, we had "
    "everything before us, we had nothing before us, we were all going direct to Heaven, we were all going "
    "direct the other way--in short, the period was so far like the present period, that some of its "
    "noisiest authorities insisted on its being received, for good or for evil, in the superlative degree "
    "of comparison only.\n\n"
)

GETTYSBURG = (
    "Four score and seven years ago our fathers brought forth on this continent, a new nation, conceived in "
    "Liberty, and dedicated to the proposition that all men are created equal. Now we are engaged in a great "
    "civil war, testing whether that nation, or any nation so conceived and so dedicated, can long endure. "
    "We are met on a great battle-field of that war. We have come to dedicate a portion of that field, as a "
    "final resting place for those who here gave their lives that that nation might live. It is altogether "
    "fitting and proper that we should do this. But, in a larger sense, we can not dedicate--we can not "
    "consecrate--we can not hallow--this ground. The brave men, living and dead, who struggled here, have "
    "consecrated it, far above our poor power to add or detract. The world will little note, nor long "
    "remember what we say here, but it can never forget what they did here. It is for us the living, rather, "
    "to be dedicated here to the unfinished work which they who fought here have thus far so nobly advanced. "
    "It is rather for us to be here dedicated to the great task remaining before us--that from these honored "
    "dead we take increased devotion to that cause for which they gave the last full measure of devotion--"
    "that we here highly resolve that these dead shall not have died in vain--that this nation, under God, "
    "shall have a new birth of freedom--and that government of the people, by the people, for the people, "
    "shall not perish from the earth.\n\n"
)

MOBY_DICK = (
    "Call me Ishmael. Some years ago--never mind how long precisely--having little or no money in my purse, "
    "and nothing particular to interest me on shore, I thought I would sail about a little and see the "
    "watery part of the world. It is a way I have of driving off the spleen and regulating the circulation. "
    "Whenever I find myself growing grim about the mouth; whenever it is a damp, drizzly November in my soul; "
    "whenever I find myself involuntarily pausing before coffin warehouses, and bringing up the rear of every "
    "funeral I meet; and especially whenever my hypos get such an upper hand of me, that it requires a strong "
    "moral principle to prevent me from deliberately stepping into the street, and methodically knocking "
    "people's hats off--then, I account it high time to get to sea as soon as I can. This is my substitute "
    "for pistol and ball. With a philosophical flourish Cato throws himself upon his sword; I quietly take "
    "to the ship. There is nothing surprising in this. If they but knew it, almost all men in their degree, "
    "some time or other, cherish very nearly the same feelings towards the ocean with me.\n\n"
)

PRIDE = (
    "It is a truth universally acknowledged, that a single man in possession of a good fortune, must be in "
    "want of a wife. However little known the feelings or views of such a man may be on his first entering "
    "a neighbourhood, this truth is so well fixed in the minds of the surrounding families, that he is "
    "considered the rightful property of some one or other of their daughters. \"My dear Mr. Bennet,\" said "
    "his lady to him one day, \"have you heard that Netherfield Park is let at last?\" Mr. Bennet replied "
    "that he had not. \"But it is,\" returned she; \"for Mrs. Long has just been here, and she told me all "
    "about it.\" Mr. Bennet made no answer. \"Do you not want to know who has taken it?\" cried his wife "
    "impatiently. \"You want to tell me, and I have no objection to hearing it.\" This was invitation "
    "enough.\n\n"
)

CODE = '''def fib(n: int) -> int:
    """Return the n-th Fibonacci number."""
    a, b = 0, 1
    for _ in range(n):
        a, b = b, a + b
    return a


if __name__ == "__main__":
    for i in range(10):
        print(i, fib(i))
'''

UNICODE = "Café naïve façade — “smart quotes” 日本語のテキスト 🤖🚀 Ελληνικά, русский, عربي. ∑∫√ ≠ ≈"

# Perplexity text: Moby-Dick's opening (~250 tokens). Not in any prompt other than near_limit.
PERPLEXITY = MOBY_DICK

# Long text for the near-limit prompts; tokenized and cut to an exact token count by the harness.
LONG = TWO_CITIES + GETTYSBURG + PRIDE + CODE + "\n" + MOBY_DICK + UNICODE + "\n\n" + GETTYSBURG


# --------------------------------------------------------------------------------------------------------------------
# model-level op: gpt2 forward
#
# The model-level op: gpt2 `forward`, token ids [T] -> logits [T, vocab]. The reference is HuggingFace GPT2LMHeadModel
# (eager attention); the truth is the same model in fp64 on the candidate's device. Cases are long, non-repetitive
# prompts: 1-token and repetitive prompts hide the attention-scale and mask bugs (engine/ch01-forward RESULTS.md).
#
# The candidate side is the reader's `gpt2.py`: `load(dtype) -> (weights, config)` (given) and
# `forward(weights, config, tokens) -> logits`; the child's "forward" adapter loads once per dtype and calls forward.
# --------------------------------------------------------------------------------------------------------------------

MODEL_ID = "openai-community/gpt2"
VOCAB = 50257
# name -> (text, token count). ~384 and ~192 tokens: long enough that every planted bug shows (KL >= 2e-5 on the
# subtlest, exact GELU, at 69-111 tokens), short enough that the fp64 truth (T x 50257 x 8 bytes) stays ~230 MB.
PROMPTS = {"prose": (LONG, 384), "code": (CODE + "\n" + UNICODE + "\n" + MOBY_DICK, 192)}


def _local_first(load: Any) -> Any:
    """From the HF cache without touching the network (each check would pay a HEAD request per file), else download."""
    try:
        return load(local_files_only=True)
    except OSError:
        return load(local_files_only=False)


@functools.cache
def tokenizer():  # noqa: ANN201 -- tokenizers.Tokenizer; the fast library, not transformers (2 s import)
    from huggingface_hub import hf_hub_download
    from tokenizers import Tokenizer

    return Tokenizer.from_file(_local_first(lambda **kw: hf_hub_download(MODEL_ID, "tokenizer.json", **kw)))


def prompt_ids(name: str) -> list[int]:
    text, count = PROMPTS[name]
    ids = tokenizer().encode(text).ids
    assert len(ids) >= count, f"prompt {name}: only {len(ids)} tokens, want {count}"
    return ids[:count]


@functools.cache
def hf_model(dtype: torch.dtype, device: str) -> torch.nn.Module:
    from transformers import GPT2LMHeadModel
    from transformers.utils import logging

    logging.disable_progress_bar()
    model = _local_first(lambda **kw: GPT2LMHeadModel.from_pretrained(
        MODEL_ID, attn_implementation="eager", dtype=dtype, **kw))
    return model.to(device).eval()


@op(name="forward", kind="model", dims={}, dtypes=(torch.float32, torch.bfloat16))
def forward(tokens: Int[Tensor, "tokens"]) -> Float[Tensor, "tokens vocab"]:
    with torch.no_grad():
        return hf_model(torch.float32, str(tokens.device))(tokens[None], use_cache=False).logits[0]


@forward.cases
def _cases() -> list[Case]:
    return [Case((("tokens", PROMPTS[name][1]),), (), dtype, 0, prompt=name)
            for dtype in forward.sweep.dtypes for name in PROMPTS]


@forward.inputs
def _inputs(case: Case, generator: torch.Generator) -> tuple:
    return (torch.tensor(prompt_ids(case.prompt), dtype=torch.int64),)


@forward.truth
def _truth(case: Case, inputs: tuple, device: str) -> tuple[Tensor, Tensor]:
    """(fp64 truth, the reference at the case's dtype), both HF, both on `device`."""
    tokens = inputs[0].to(device)[None]
    with torch.no_grad():
        truth = hf_model(torch.float64, device)(tokens, use_cache=False).logits[0]
        reference = hf_model(case.dtype, device)(tokens, use_cache=False).logits[0]
    return truth, reference
