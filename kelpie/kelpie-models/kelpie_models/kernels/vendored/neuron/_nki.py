"""nki==0.5.0 (beta-2 API). @nki.jit dispatches on a jax.Array arg to an
AwsNeuronCustomNativeKernel custom_call inside the jitted step. Only this file imports `nki`,
lazily on first call.

nki 0.5 quirks: no nl.arange / masks, tiles are static slices of the HBM tensor; `a + b` on
tiles does not compile ("'add' expected (int, int)") -- every op must be an nl.* call; scalars
arrive as Python floats baked into the kernel.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from jax import Array

P = 128  # nl.tile_size.pmax
_KERNEL: Any = None


def rms_norm(x: Array, weight: Array, eps: float) -> Array:
    d = x.shape[-1]
    rows = x.reshape(-1, d)
    out = _kernel()(rows, weight.reshape(1, d), float(eps))
    return out.reshape(x.shape).astype(x.dtype)


def _kernel() -> Any:
    # nki.jit resolves names in the kernel body from the function's module globals, not a
    # closure (a closure over `nl` fails: "failed to resolve name 'nl.ndarray'") -- so `nl` is
    # injected into this module's globals here, before the decorator runs.
    global _KERNEL  # noqa: PLW0603
    if _KERNEL is None:
        import nki
        import nki.language as nl

        globals()["nl"] = nl
        _KERNEL = nki.jit(rms_norm_kernel)
    return _KERNEL


def rms_norm_kernel(x, w, eps):  # noqa: ANN001 -- nki tensors; traced by nki.jit, never called
    n, d = x.shape
    out = nl.ndarray((n, d), dtype=x.dtype, buffer=nl.shared_hbm)  # noqa: F821
    w1 = nl.load(w, dtype=nl.float32)  # noqa: F821
    for a in nl.static_range(0, n, P):  # noqa: F821
        rows = min(P, n - a)
        xt = nl.load(x[a : a + rows, :], dtype=nl.float32)  # noqa: F821
        ms = nl.sum(nl.multiply(xt, xt), axis=[1], keepdims=True)  # noqa: F821
        inv = nl.rsqrt(nl.add(nl.multiply(ms, 1.0 / d), eps))  # noqa: F821
        y = nl.multiply(xt, nl.broadcast_to(inv, (rows, d)))  # noqa: F821
        y = nl.multiply(y, nl.broadcast_to(w1, (rows, d)), dtype=x.dtype)  # noqa: F821
        nl.store(out[a : a + rows, :], value=y)  # noqa: F821
    return out
