"""Backends a kernel may come from, declared once each.

A backend is a name plus the package that must be importable for any impl registered under it.
`declare_backend` records it; `require(name)` imports the package when an op that picked it
first dispatches (build's warm pass, `op._resolve`) and raises `BackendUnavailableError` naming
the extra to install. Selecting an impl never silently falls back to something else -- an
unavailable backend is a build error, not a shrug.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as installed_version


class BackendUnavailableError(RuntimeError):
    """An impl was selected whose backend package is missing or out of range."""


@dataclass(frozen=True)
class Backend:
    name: str
    package: str
    min_version: str | None
    max_version: str | None
    extra: str


BACKENDS: dict[str, Backend] = {}


def declare_backend(
    name: str,
    *,
    package: str,
    min_version: str | None = None,
    max_version: str | None = None,
    extra: str | None = None,
) -> Backend:
    """Declare a backend once. `extra` defaults to the backend's own name, which is how the
    install hint reads: `install kelpie[fla]`."""
    assert name not in BACKENDS, f"backend {name!r} declared twice"
    backend = Backend(name, package, min_version, max_version, extra or name)
    BACKENDS[name] = backend
    return backend


def version_tuple(text: str) -> tuple[int, ...]:
    """`2.3.1.post1` -> (2, 3, 1). Non-numeric tail dropped: enough to order releases."""
    parts: list[int] = []
    for chunk in text.split("."):
        digits = "".join(c for c in chunk if c.isdigit())
        if not digits:
            break
        parts.append(int(digits))
    return tuple(parts)


def require(name: str) -> object:
    """Import the backend's package, checking the version range. Raises
    `BackendUnavailableError` naming the extra; the caller never catches it into a fallback."""
    backend = BACKENDS.get(name)
    assert backend is not None, f"undeclared backend {name!r}; declared: {sorted(BACKENDS)}"
    try:
        module = import_module(backend.package)
    except ImportError as exc:
        raise BackendUnavailableError(
            f"{name} needs {backend.package}; install kelpie[{backend.extra}]"
        ) from exc
    found = backend_version(backend)
    for bound, ok in ((backend.min_version, _ge), (backend.max_version, _le)):
        if bound is not None and not ok(version_tuple(found), version_tuple(bound)):
            raise BackendUnavailableError(
                f"{name} needs {backend.package} in "
                f"[{backend.min_version or '*'}, {backend.max_version or '*'}], found {found}; "
                f"install kelpie[{backend.extra}]"
            )
    return module


def backend_version(backend: Backend) -> str:
    """The installed version string, or `unknown` when the package ships no metadata. Part of
    every fingerprint, so a backend upgrade invalidates the cache."""
    try:
        return installed_version(backend.package)
    except PackageNotFoundError:
        pass
    try:
        return str(getattr(import_module(backend.package), "__version__", "unknown"))
    except ImportError:
        # Not installed. `require` is what refuses an uninstalled backend; asking for a version
        # must not, because `kelpie cache` prints fingerprints on machines that build nothing.
        return "absent"


def _ge(found: tuple[int, ...], bound: tuple[int, ...]) -> bool:
    return found >= bound


def _le(found: tuple[int, ...], bound: tuple[int, ...]) -> bool:
    return found <= bound


declare_backend("triton", package="triton", min_version="3.0")
declare_backend("fla", package="fla", extra="fla")
declare_backend("liger", package="liger_kernel", extra="liger")
declare_backend("flashinfer", package="flashinfer", extra="flashinfer")
# OpenAI's MoE kernels, from the triton repo (python/triton_kernels), NOT PyPI's unrelated
# `triton-kernels`. Its tag must match the installed triton (v3.7.1 for triton 3.7.1).
declare_backend("triton_kernels", package="triton_kernels", extra="triton-kernels")
# vLLM 0.29.0's prebuilt Marlin MoE .so files (vllm itself is not installed): the "package" is
# the module that sha256-checks and loads them from the image (adapters/_vllm_marlin_ops.py).
declare_backend("vllm_marlin", package="kelpie_models.kernels.adapters._vllm_marlin_ops",
                extra="vllm-marlin (oci/Dockerfile)")
# vLLM 0.29.0's Triton unified attention, VENDORED (source files in the tree, sha256-checked at
# import; the "package" is the vendored module, its version carries the digests).
declare_backend("vllm_triton_attn", package="kelpie_models.kernels.vendored.cuda.vllm_attention",
                extra="triton (the kernel source is vendored)")
declare_backend("flash_attn", package="flash_attn", extra="flash-attn")
declare_backend("metal", package="torch")  # MPS kernels ship inside torch's Metal runtime
declare_backend("pallas", package="jax", extra="tpu")
declare_backend("nki", package="neuronxcc", extra="neuron")
