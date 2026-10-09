"""The case generator: an op's named dims x its scalar values x its dtypes -> a list of `Case`s,
and a `Case` + a seeded `torch.Generator` -> concrete inputs.

Shapes come from the reference's own annotations (`x: Float[Tensor, "rows hidden"]`, popcorn
style, via jaxtyping); sizes come from the op's `dims=` -- explicit edge values per dim (1,
small primes, tile +- 1, the largest size that matters). Small sweeps are the full cross product;
past `FULL_PRODUCT_LIMIT` cases it is a pairwise covering array (every pair of values across
every two axes appears in some case) plus the all-smallest and all-largest corners.

Every case owns its seed (crc32 of op name + case label), so a case is reproducible on its own:
`run_checks ch1 layer_norm` and a failing case re-run give the same tensors.
"""

from __future__ import annotations

import inspect
import itertools
import math
import typing
import zlib
from dataclasses import dataclass
from typing import Any

import jaxtyping
import torch

from harness.registry import Op

FULL_PRODUCT_LIMIT = 64  # past this many cases, cover pairs instead of the full product

DTYPE_NAMES = {torch.float64: "fp64", torch.float32: "fp32", torch.float16: "fp16",
               torch.bfloat16: "bf16"}


@dataclass(frozen=True)
class Case:
    """One point of an op's sweep: a size per named dim, a value per scalar argument, a dtype."""

    sizes: tuple[tuple[str, int], ...]
    scalars: tuple[tuple[str, float], ...]
    dtype: torch.dtype
    seed: int

    def label(self) -> str:
        """`rows=3 hidden=7 eps=1e-05 fp32` -- what a verdict line and record print."""
        parts = [f"{n}={v}" for n, v in self.sizes] + [f"{n}={v:g}" for n, v in self.scalars]
        return " ".join([*parts, DTYPE_NAMES[self.dtype]])


def sweep(declared: Op) -> list[Case]:
    """Every case the op is checked on, in a fixed order."""
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
        seed = zlib.crc32(f"{declared.name}|{unseeded.label()}".encode())
        cases.append(Case(sizes, scalars, picked[-1], seed))
    assert len({case.label() for case in cases}) == len(cases), "sweep produced duplicate cases"
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
