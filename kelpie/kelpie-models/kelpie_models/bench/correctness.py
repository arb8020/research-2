# copied from crucible/verification/kernels/correctness.py @ dfb735f9a8d99182179bb1b82cc4cb849ba5c6d0
from __future__ import annotations

import dataclasses
import math
from typing import Any, Callable


@dataclasses.dataclass(frozen=True)
class ExactTolerance:
    pass


@dataclasses.dataclass(frozen=True)
class BudgetTolerance:
    recheck_atol: float = 1e-2
    recheck_rtol: float = 1e-2


@dataclasses.dataclass(frozen=True)
class FixedTolerance:
    atol: float
    rtol: float


Tolerance = ExactTolerance | BudgetTolerance | FixedTolerance

DTYPE_FLOORS = {
    "torch.float32": 2e-5,
    "torch.float16": 1e-3,
    "torch.bfloat16": 2e-2,
}


def error_budget(truth: Any, ref_at_dtype: Any) -> float:
    # algo: band = max(2 * ref error at case dtype, dtype_floor * truth abs-max)
    import torch  # pyright: ignore[reportMissingImports]

    assert isinstance(truth, torch.Tensor) and isinstance(ref_at_dtype, torch.Tensor)
    assert truth.shape == ref_at_dtype.shape, "budget needs matching shapes"
    assert str(ref_at_dtype.dtype) in DTYPE_FLOORS, (
        f"no error floor for {ref_at_dtype.dtype}"
    )
    assert bool(torch.isfinite(truth).all()), "budget truth must be finite"
    assert bool(torch.isfinite(ref_at_dtype).all()), "budget reference must be finite"
    t = truth.double()
    budget = (ref_at_dtype.double() - t).abs().max().item()
    scale = t.abs().max().item()
    band = max(2.0 * budget, DTYPE_FLOORS[str(ref_at_dtype.dtype)] * scale)
    assert math.isfinite(band), "error budget must be finite"
    return band


def zip_leaves(output: Any, ref: Any, leaf: Callable[..., bool], *par: Any) -> bool:
    match ref:
        case dict():
            assert all(isinstance(p, dict) and p.keys() == ref.keys() for p in par), (
                "parallel structure diverged from ref (broken oracle)"
            )
            if not isinstance(output, dict) or output.keys() != ref.keys():
                return False
            return all(
                zip_leaves(output[k], ref[k], leaf, *(p[k] for p in par)) for k in ref
            )
        case list() | tuple():
            assert all(
                isinstance(p, (list, tuple)) and len(p) == len(ref) for p in par
            ), "parallel structure diverged from ref (broken oracle)"
            if not isinstance(output, (list, tuple)) or len(output) != len(ref):
                return False
            return all(
                zip_leaves(o, ref[i], leaf, *(p[i] for p in par))
                for i, o in enumerate(output)
            )
        case _:
            return leaf(output, ref, *par)


def within_budget(output: Any, ref: Any, truth: Any) -> bool:
    return zip_leaves(output, ref, _leaf_within_budget, truth)


def _leaf_within_budget(output: Any, ref: Any, truth: Any) -> bool:
    import torch  # pyright: ignore[reportMissingImports]

    if isinstance(ref, torch.Tensor):
        assert isinstance(truth, torch.Tensor), "oracle fp64 run changed structure"
        return tensor_within_budget(output, ref, truth)
    return bool(output == ref)


def tensor_within_budget(output: Any, ref: Any, truth: Any) -> bool:
    import torch  # pyright: ignore[reportMissingImports]

    if (
        not isinstance(output, torch.Tensor)
        or output.shape != ref.shape
        or output.dtype != ref.dtype
    ):
        return False
    if not ref.dtype.is_floating_point:
        return bool(torch.equal(output.cpu(), ref.cpu()))
    band = error_budget(truth, ref)
    err = (output.double() - truth.double()).abs().max().item()
    return math.isfinite(err) and err <= band


def within_fixed(output: Any, ref: Any, atol: float, rtol: float) -> bool:
    return zip_leaves(output, ref, _leaf_within_fixed, atol, rtol)


def _leaf_within_fixed(output: Any, ref: Any, atol: float, rtol: float) -> bool:
    import torch  # pyright: ignore[reportMissingImports]

    if isinstance(ref, torch.Tensor):
        if (
            not isinstance(output, torch.Tensor)
            or output.dtype != ref.dtype
            or output.shape != ref.shape
        ):
            return False
        if not (ref.is_floating_point() or ref.is_complex()) and atol == rtol == 0:
            return bool(torch.equal(output, ref))
        # algo: keep fp64 precision; promote low-precision arithmetic to fp32.
        # TODO: nonzero integer tolerances retain the legacy fp32 comparison.
        dtype = torch.promote_types(ref.dtype, torch.float32)
        return bool(
            torch.allclose(output.to(dtype), ref.to(dtype), rtol=rtol, atol=atol)
        )
    return bool(output == ref)


def exact_match(output: Any, ref: Any) -> bool:
    return zip_leaves(output, ref, _leaf_exact)


def _leaf_exact(output: Any, ref: Any) -> bool:
    import torch  # pyright: ignore[reportMissingImports]

    if isinstance(ref, torch.Tensor):
        return (
            isinstance(output, torch.Tensor)
            and output.dtype == ref.dtype
            and output.shape == ref.shape
            and bool(torch.equal(output.cpu(), ref.cpu()))
        )
    return bool(output == ref)


def upcast_fp64(inputs: dict[str, Any]) -> dict[str, Any]:
    import torch  # pyright: ignore[reportMissingImports]

    return {
        k: v.double()
        if isinstance(v, torch.Tensor) and v.dtype.is_floating_point
        else v
        for k, v in inputs.items()
    }
