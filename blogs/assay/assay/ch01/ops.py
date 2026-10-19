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
INPUTS = {"centered": (0.0, 1.0), "offset": (3.0, 0.5)}


REGISTRY: dict[str, Op] = {}
_BOUND: list[Binding] = []


@dataclass(frozen=True)
class Impl:
    name: str
    fn: Callable[..., Any]
    source: str | None


@dataclass(frozen=True)
class Sweep:
    dims: dict[str, tuple[int, ...]]
    scalars: dict[str, tuple[float, ...]]
    dtypes: tuple[torch.dtype, ...]
    tied: dict[str, str] = field(default_factory=dict)
    inputs: tuple[str, ...] = ()


@dataclass(eq=False)
class Op:
    name: str
    reference: Callable[..., Any]
    sweep: Sweep
    kind: str = "op"
    blocking: bool = True
    impls: dict[str, Impl] = field(default_factory=dict)
    truth_fn: Callable[..., Any] | None = None
    inputs_fn: Callable[..., tuple] | None = None
    cases_fn: Callable[[], list[Any]] | None = None

    def __repr__(self) -> str:
        return f"<op {self.name} impls={sorted(self.impls)}>"

    def __call__(self, *args: Any) -> Any:
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
       blocking: bool = True, kind: str = "op", tied: dict[str, str] | None = None) -> Callable[[Callable[..., Any]], Op]:
    assert kind in ("op", "model"), kind
    assert dtypes, "an op needs at least one dtype"
    assert not (kind == "model" and not blocking), "model-level checks always block"
    for dim, sizes in dims.items():
        assert sizes and all(size >= 1 for size in sizes), f"dim {dim!r}: sizes must be >= 1, got {sizes}"
    for dim, to in (tied or {}).items():
        assert dim not in dims and to in dims, f"tied dim {dim!r} -> {to!r}: {to!r} must be swept, {dim!r} not"

    def declare(fn: Callable[..., Any]) -> Op:
        declared_name = name if name is not None else fn.__name__
        assert declared_name not in REGISTRY, f"op {declared_name!r} declared twice"
        inputs = tuple(INPUTS) if kind == "op" else ()
        declared = Op(declared_name, fn, Sweep(dims, scalars or {}, dtypes, tied or {}, inputs), kind=kind,
                      blocking=blocking)
        REGISTRY[declared_name] = declared
        return declared

    return declare


@dataclass(frozen=True)
class Binding:
    impls: dict[str, Impl]

    def line(self) -> str:
        return "kernels: " + " ".join(f"{n}={i.name}" for n, i in sorted(self.impls.items()))


def bind(kernels: dict[Op, str] | None = None, *, torch_ops: bool = False) -> Binding:
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


ALL = (torch.float32, torch.float16, torch.bfloat16)


@op(dims={"T": (1, 3, 17, 64), "D": (1, 7, 768), "F": (1, 5, 2304)}, dtypes=ALL)
def linear(x_TD: Float[Tensor, "T D"], w_DF: Float[Tensor, "D F"], b_F: Float[Tensor, "F"]) -> Float[Tensor, "T F"]:
    return x_TD @ w_DF + b_F


@op(dims={"T": (1, 3, 64), "F": (1, 7, 768, 3072)}, dtypes=ALL)
def gelu(x_TF: Float[Tensor, "T F"]) -> Float[Tensor, "T F"]:
    return 0.5 * x_TF * (1.0 + torch.tanh(math.sqrt(2.0 / math.pi) * (x_TF + 0.044715 * x_TF ** 3)))


@op(dims={"T": (1, 2, 3, 17, 64), "D": (1, 3, 7, 64, 769)}, dtypes=ALL, scalars={"eps": (1e-5, 1e-1)})
def layer_norm(x_TD: Float[Tensor, "T D"], w_D: Float[Tensor, "D"], b_D: Float[Tensor, "D"],
               eps: float) -> Float[Tensor, "T D"]:
    mean = x_TD.mean(dim=-1, keepdim=True)
    var = ((x_TD - mean) ** 2).mean(dim=-1, keepdim=True)
    return (x_TD - mean) / torch.sqrt(var + eps) * w_D + b_D


@op(dims={"T": (1, 2, 7, 16, 17, 64), "N": (1, 2, 12), "H": (1, 8, 64)}, tied={"S": "T"}, dtypes=ALL)
def attention(q_TNH: Float[Tensor, "T N H"], k_SNH: Float[Tensor, "S N H"],
              v_SNH: Float[Tensor, "S N H"]) -> Float[Tensor, "T N H"]:
    q, k, v = (t.transpose(0, 1) for t in (q_TNH, k_SNH, v_SNH))
    T, S = q.shape[-2], k.shape[-2]
    scores = q @ k.transpose(-1, -2) / math.sqrt(q.shape[-1])
    allowed = torch.ones(T, S, dtype=torch.bool, device=q.device).tril()
    return (torch.softmax(scores.masked_fill(~allowed, float("-inf")), dim=-1) @ v).transpose(0, 1)


FULL_PRODUCT_LIMIT = 64


@dataclass(frozen=True)
class Case:
    sizes: tuple[tuple[str, int], ...]
    scalars: tuple[tuple[str, float], ...]
    dtype: torch.dtype
    seed: int
    prompt: str = ""
    inputs: str = ""

    def label(self) -> str:
        parts = [f"prompt={self.prompt}"] if self.prompt else []
        parts += [f"{n}={v}" for n, v in self.sizes] + [f"{n}={v:g}" for n, v in self.scalars]
        parts += [f"x={self.inputs}"] if self.inputs else []
        return " ".join(parts)

    @property
    def dtype_name(self) -> str:
        return SHORT[self.dtype]

    def to_json(self) -> dict:
        return {"sizes": dict(self.sizes), "scalars": dict(self.scalars), "dtype": self.dtype_name,
                "seed": self.seed, "prompt": self.prompt, "inputs": self.inputs}


def sweep(declared: Op) -> list[Case]:
    if declared.cases_fn is not None:
        return declared.cases_fn()
    _assert_dims_match(declared)
    plan = declared.sweep
    axes: list[tuple[Any, ...]] = [*plan.dims.values(), *plan.scalars.values(), *([plan.inputs] if plan.inputs else []),
                                   plan.dtypes]
    full_size = math.prod(len(values) for values in axes)
    rows = (list(itertools.product(*[range(len(values)) for values in axes]))
            if full_size <= FULL_PRODUCT_LIMIT else _pairwise_with_corners(axes))
    dim_names = list(plan.dims)
    scalar_names = list(plan.scalars)
    cases = []
    for row in rows:
        picked = [values[index] for values, index in zip(axes, row, strict=True)]
        sizes = tuple(zip(dim_names, picked[:len(dim_names)], strict=True))
        scalars = tuple(zip(scalar_names, picked[len(dim_names):len(dim_names) + len(scalar_names)], strict=True))
        inputs = picked[-2] if plan.inputs else ""
        unseeded = Case(sizes, scalars, picked[-1], 0, inputs=inputs)
        seed = zlib.crc32(f"{declared.name}|{unseeded.label()} {unseeded.dtype_name}".encode())
        cases.append(Case(sizes, scalars, picked[-1], seed, inputs=inputs))
    assert len({(c.label(), c.dtype) for c in cases}) == len(cases), "sweep produced duplicate cases"
    return cases


def make_inputs(declared: Op, case: Case) -> tuple:
    generator = torch.Generator().manual_seed(case.seed)
    if declared.inputs_fn is not None:
        return declared.inputs_fn(case, generator)
    sizes = dict(case.sizes)
    sizes.update({dim: sizes[to] for dim, to in declared.sweep.tied.items()})
    scalars = dict(case.scalars)
    mean, std = INPUTS[case.inputs or "centered"]
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
        args.append((mean + std * torch.randn(shape, generator=generator)).to(case.dtype))
    return tuple(args)


def _params(declared: Op) -> list[tuple[str, Any]]:
    hints = typing.get_type_hints(declared.reference)
    names = list(inspect.signature(declared.reference).parameters)
    return [(name, hints.get(name)) for name in names]


def _is_tensor_annotation(annotation: Any) -> bool:
    return isinstance(annotation, type) and issubclass(annotation, jaxtyping.AbstractArray)


def _assert_dims_match(declared: Op) -> None:
    used = {dim for _, annotation in _params(declared) if _is_tensor_annotation(annotation)
            for dim in annotation.dim_str.split()}
    sized = set(declared.sweep.dims)
    assert used <= sized | set(declared.sweep.tied), f"{declared.name}: dims without sizes: {sorted(used - sized)}"
    assert sized <= used, f"{declared.name}: sized dims no input uses: {sorted(sized - used)}"


def _pairwise_with_corners(axes: list[tuple[Any, ...]]) -> list[tuple[int, ...]]:
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


TOPK = 5


def max_abs(a: torch.Tensor, b: torch.Tensor) -> float:
    diff = (a.double() - b.double()).abs()
    return float(diff.max()) if diff.numel() and bool(torch.isfinite(diff).all()) else (
        0.0 if diff.numel() == 0 else math.inf)


def is_logits(truth: torch.Tensor) -> bool:
    return truth.dim() == 2 and truth.shape[-1] == VOCAB


def reference_stats(truth: torch.Tensor, reference: torch.Tensor) -> dict[str, Any]:
    assert truth.dtype == torch.float64, f"truth must be fp64, got {truth.dtype}"
    assert reference.shape == truth.shape, f"reference {tuple(reference.shape)} vs truth {tuple(truth.shape)}"
    assert bool(torch.isfinite(truth).all()), "truth has non-finite values: a broken case"
    assert bool(torch.isfinite(reference).all()), "the reference has non-finite values at its dtype"
    stats: dict[str, Any] = {"ref_err": max_abs(reference, truth),
                             "scale": float(truth.abs().max()) if truth.numel() else 0.0}
    if is_logits(truth):
        stats["ref_kl_max"] = float(kl_per_position(truth, reference).max())
    elif reference.is_floating_point():
        stats["ref_frontier"] = frontier(reference, truth)
    return stats


def frontier(out: torch.Tensor, truth: torch.Tensor) -> list[list[float]]:
    err = (out.double() - truth).abs().reshape(-1)
    size = truth.abs().reshape(-1)
    if err.numel() == 0:
        return []
    if not bool(torch.isfinite(err).all()):
        return [[0.0, math.inf]]
    order = torch.argsort(size, stable=True)
    size, err = size[order], err[order]
    best = torch.cummax(err, dim=0).values
    keep = torch.ones_like(err, dtype=torch.bool)
    keep[1:] = best[1:] > best[:-1]
    return [[float(t), float(e)] for t, e in zip(size[keep].tolist(), err[keep].tolist(), strict=True)]


def tolerance_ratio(points: list[list[float]], atol: float, rtol: float) -> tuple[float, float, float]:
    rows = [(float(e) / (atol + rtol * float(t)), float(t), float(e)) for t, e in points]
    return max(rows, default=(0.0, 0.0, 0.0))


def kl_per_position(truth: torch.Tensor, ours: torch.Tensor) -> torch.Tensor:
    lp_truth = torch.log_softmax(truth.double(), dim=-1)
    lp_ours = torch.log_softmax(ours.double(), dim=-1)
    return (lp_truth.exp() * (lp_truth - lp_ours)).sum(-1)


def reduce_output(out: torch.Tensor, truth: torch.Tensor) -> dict[str, Any]:
    facts: dict[str, Any] = {"err": max_abs(out, truth), "finite": bool(torch.isfinite(out).all())}
    if not out.is_floating_point():
        bad = (out.double() != truth).nonzero()
        first = int(bad[0, 0]) if len(bad) else None
        facts["first_diff"] = None if first is None else {"at": first, "got": int(out[first]), "want": int(truth[first])}
        return facts
    if not is_logits(truth):
        facts["frontier"] = frontier(out, truth)
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

PERPLEXITY = MOBY_DICK

LONG = TWO_CITIES + GETTYSBURG + PRIDE + CODE + "\n" + MOBY_DICK + UNICODE + "\n\n" + GETTYSBURG


MODEL_ID = "openai-community/gpt2"
VOCAB = 50257
PROMPTS = {"prose": (LONG, 384), "code": (CODE + "\n" + UNICODE + "\n" + MOBY_DICK, 192)}
BLOCK_LAYERS = (0, 5, 10)
BLOCK_TOKENS = 128
GENERATE = {"moby": (MOBY_DICK, 64, 24)}
GENERATE_MIN_MARGIN = 0.05


def _local_first(load: Any) -> Any:
    try:
        return load(local_files_only=True)
    except OSError:
        return load(local_files_only=False)


@functools.cache
def tokenizer():  # noqa: ANN201 -- tokenizers.Tokenizer; the fast library, not transformers (2 s import)
    from huggingface_hub import hf_hub_download
    from tokenizers import Tokenizer

    return Tokenizer.from_file(_local_first(lambda **kw: hf_hub_download(MODEL_ID, "tokenizer.json", **kw)))


def text_ids(text: str, count: int, name: str) -> list[int]:
    ids = tokenizer().encode(text).ids
    assert len(ids) >= count, f"prompt {name}: only {len(ids)} tokens, want {count}"
    return ids[:count]


def prompt_ids(name: str) -> list[int]:
    return text_ids(*PROMPTS[name], name)


@functools.cache
def hf_model(dtype: torch.dtype, device: str) -> torch.nn.Module:
    from transformers import GPT2LMHeadModel
    from transformers.utils import logging

    logging.disable_progress_bar()
    model = _local_first(lambda **kw: GPT2LMHeadModel.from_pretrained(
        MODEL_ID, attn_implementation="eager", dtype=dtype, **kw))
    return model.to(device).eval()


@op(name="forward", kind="model", dims={}, dtypes=(torch.float32, torch.bfloat16))
def forward(tokens_T: Int[Tensor, "T"]) -> Float[Tensor, "T V"]:
    with torch.no_grad():
        return hf_model(torch.float32, str(tokens_T.device))(tokens_T[None], use_cache=False).logits[0]


@forward.cases
def _forward_cases() -> list[Case]:
    return [Case((("T", PROMPTS[name][1]),), (), dtype, 0, prompt=name)
            for dtype in forward.sweep.dtypes for name in PROMPTS]


@forward.inputs
def _forward_inputs(case: Case, generator: torch.Generator) -> tuple:
    return (torch.tensor(prompt_ids(case.prompt), dtype=torch.int64),)


@forward.truth
def _forward_truth(case: Case, inputs: tuple, device: str) -> tuple[Tensor, Tensor]:
    tokens = inputs[0].to(device)[None]
    with torch.no_grad():
        truth = hf_model(torch.float64, device)(tokens, use_cache=False).logits[0]
        reference = hf_model(case.dtype, device)(tokens, use_cache=False).logits[0]
    return truth, reference


def hf_block(dtype: torch.dtype, device: str, layer: int, x_TD: Tensor) -> Tensor:
    T = x_TD.shape[0]
    mask = torch.full((T, T), float("-inf"), dtype=dtype, device=device).triu(1)[None, None]
    with torch.no_grad():
        return hf_model(dtype, device).transformer.h[layer](x_TD.to(dtype)[None], attention_mask=mask)[0]


@functools.cache
def _residual_stream(prompt: str, count: int) -> tuple[Tensor, ...]:
    tokens = torch.tensor(text_ids(PROMPTS[prompt][0], count, prompt))[None]
    with torch.no_grad():
        out = hf_model(torch.float32, "cpu")(tokens, use_cache=False, output_hidden_states=True)
    return tuple(h[0] for h in out.hidden_states[:-1])


@op(name="block", kind="model", dims={}, dtypes=(torch.float32, torch.bfloat16))
def block(x_TD: Float[Tensor, "T D"], layer: int) -> Float[Tensor, "T D"]:
    return hf_block(torch.float32, str(x_TD.device), layer, x_TD)


@block.cases
def _block_cases() -> list[Case]:
    return [Case((("T", BLOCK_TOKENS), ("layer", layer)), (), dtype, 0, prompt="prose")
            for dtype in block.sweep.dtypes for layer in BLOCK_LAYERS]


@block.inputs
def _block_inputs(case: Case, generator: torch.Generator) -> tuple:
    layer = dict(case.sizes)["layer"]
    return (_residual_stream(case.prompt, BLOCK_TOKENS)[layer].clone(), layer)


@block.truth
def _block_truth(case: Case, inputs: tuple, device: str) -> tuple[Tensor, Tensor]:
    x_TD, layer = inputs
    return hf_block(torch.float64, device, layer, x_TD), hf_block(case.dtype, device, layer, x_TD)


def hf_greedy(dtype: torch.dtype, device: str, ids: list[int], n: int) -> tuple[list[int], float]:
    ids, margin = list(ids), math.inf
    model = hf_model(dtype, device)
    with torch.no_grad():
        for _ in range(n):
            logits = model(torch.tensor([ids], device=device), use_cache=False).logits[0, -1]
            top = logits.double().topk(2)
            margin = min(margin, float(top.values[0] - top.values[1]))
            ids.append(int(top.indices[0]))
    return ids[-n:], margin


@op(name="generate", kind="model", dims={}, dtypes=(torch.float32,))
def generate(prompt_T: Int[Tensor, "T"], n: int) -> Int[Tensor, "n"]:
    return torch.tensor(hf_greedy(torch.float32, str(prompt_T.device), prompt_T.tolist(), n)[0])


@generate.cases
def _generate_cases() -> list[Case]:
    return [Case((("T", count), ("n", new)), (), torch.float32, 0, prompt=name)
            for name, (_, count, new) in GENERATE.items()]


@generate.inputs
def _generate_inputs(case: Case, generator: torch.Generator) -> tuple:
    text, count, new = GENERATE[case.prompt]
    return (torch.tensor(text_ids(text, count, case.prompt), dtype=torch.int64), new)


@generate.truth
def _generate_truth(case: Case, inputs: tuple, device: str) -> tuple[Tensor, Tensor]:
    prompt, n = inputs[0].tolist(), inputs[1]
    truth, margin = hf_greedy(torch.float64, device, prompt, n)
    reference, _ = hf_greedy(case.dtype, device, prompt, n)
    assert margin >= GENERATE_MIN_MARGIN, f"generate {case.prompt}: greedy margin {margin:.3g}: a near tie"
    assert truth == reference, f"generate {case.prompt}: HF fp32 and fp64 greedy differ: a broken case"
    return torch.tensor(truth, dtype=torch.float64), torch.tensor(reference, dtype=torch.int64)
