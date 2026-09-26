"""Load a kelpie.toml deployment spec.

The toml is the source of truth for a deployment: what model, which kernels, what constraints.
CLI args are sugar overrides on top. `kelpie check` validates the environment against it.
`kelpie serve` reads it, merges CLI overrides, and passes the result to `build()`.

The `[kernels]` section maps op names to import paths — the same dotted paths `--kernel OP=path`
accepts on the CLI. A bare registered name like `"triton"` is NOT supported here; that decision
was killed (BREADCRUMBS line 343: "bare catalog names gone"). The value tells you exactly what
code runs.
"""

from __future__ import annotations

import sys
import tomllib
from dataclasses import dataclass, field
from importlib import import_module
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class KelpieConfig:
    """A parsed kelpie.toml."""

    # [requires] — version constraints, checked by `kelpie check`
    requires: dict[str, str] = field(default_factory=dict)

    # [model]
    model_module: str = ""
    checkpoint: str | None = None

    # [kernels] — op name → import path
    kernels: dict[str, str] = field(default_factory=dict)

    # [engine]
    capture: bool | None = None
    compile: bool = False
    device: str = "cpu"

    # [capacity]
    max_requests: int | None = None
    num_slabs: int | None = None

    # [ladder]
    bucket_tokens: list[int] | None = None
    bucket_requests: list[int] | None = None


def load(path: str | Path) -> KelpieConfig:
    """Load a kelpie.toml file. No validation — that's `kelpie check`."""
    with open(path, "rb") as f:
        raw = tomllib.load(f)

    requires = raw.get("requires", {})
    model = raw.get("model", {})
    kernels = raw.get("kernels", {})
    engine = raw.get("engine", {})
    capacity = raw.get("capacity", {})
    ladder = raw.get("ladder", {})

    return KelpieConfig(
        requires=requires,
        model_module=model.get("module", ""),
        checkpoint=model.get("checkpoint"),
        kernels=kernels,
        capture=engine.get("capture"),
        compile=engine.get("compile", False),
        device=engine.get("device", "cpu"),
        max_requests=capacity.get("max_requests"),
        num_slabs=capacity.get("num_slabs"),
        bucket_tokens=ladder.get("bucket_tokens"),
        bucket_requests=ladder.get("bucket_requests"),
    )


def resolve_kernel(op_name: str, path: str) -> Any:
    """Import-path → callable. The same resolution `--kernel OP=module.attr` does on the CLI.

    `path` must be a dotted import path (e.g. `kelpie_models.kernels.vendored.cuda._triton.rms_norm`).
    The last segment is the attribute; everything before it is the module."""
    module_name, _, attr = path.rpartition(".")
    assert module_name, f"kernel {op_name}: {path!r} is not a dotted import path"
    mod = import_module(module_name)
    assert hasattr(mod, attr), f"kernel {op_name}: {module_name} has no {attr!r}"
    return getattr(mod, attr)


def resolve_kernels(config: KelpieConfig) -> dict[Any, Any]:
    """Resolve `[kernels]` import paths to `{Op object: callable}` for `build(kernels=...)`."""
    from kelpie_models.kernels.op import REGISTRY

    out: dict[Any, Any] = {}
    for op_name, path in config.kernels.items():
        assert op_name in REGISTRY, (
            f"kernel {op_name}: no such op; ops: {sorted(REGISTRY)}"
        )
        out[REGISTRY[op_name]] = resolve_kernel(op_name, path)
    return out


# ---------------------------------------------------------------------------
# kelpie check — pre-flight validation
# ---------------------------------------------------------------------------


@dataclass
class CheckResult:
    name: str
    required: str
    actual: str
    passed: bool
    error: str = ""


def _version_ok(actual: str, spec: str) -> bool:
    """Check `actual` satisfies `spec` using packaging.specifiers."""
    from packaging.specifiers import SpecifierSet
    from packaging.version import Version

    # Strip build metadata like +cu130
    clean = actual.split("+")[0]
    return Version(clean) in SpecifierSet(spec)


def _check_python(spec: str) -> CheckResult:
    v = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    passed = _version_ok(v, spec)
    return CheckResult("python", spec, v, passed)


def _check_package(name: str, spec: str) -> CheckResult:
    try:
        mod = import_module(name)
        version = getattr(mod, "__version__", "unknown")
        if version == "unknown":
            return CheckResult(name, spec, "unknown", False, "no __version__")
        passed = _version_ok(version, spec)
        return CheckResult(name, spec, version, passed)
    except ImportError as e:
        return CheckResult(name, spec, "not installed", False, str(e))


def _check_cuda(spec: str) -> CheckResult:
    try:
        import torch
        cuda_ver = torch.version.cuda
        if cuda_ver is None:
            return CheckResult("cuda", spec, "none", False, "torch built without CUDA")
        passed = _version_ok(cuda_ver, spec)
        return CheckResult("cuda", spec, cuda_ver, passed)
    except ImportError:
        return CheckResult("cuda", spec, "n/a", False, "torch not installed")


def _check_gpu_memory(spec: str | int) -> CheckResult:
    required_gb = int(spec) if isinstance(spec, int) else int(spec.lstrip(">=").strip())
    try:
        import torch
        if not torch.cuda.is_available():
            return CheckResult("gpu_memory_gb", spec, "no gpu", False)
        total = torch.cuda.get_device_properties(0).total_memory
        actual_gb = total // (1024 ** 3)
        passed = actual_gb >= required_gb
        return CheckResult("gpu_memory_gb", spec, f"{actual_gb}", passed)
    except Exception as e:
        return CheckResult("gpu_memory_gb", spec, "error", False, str(e))


def _check_kernel(op_name: str, path: str) -> CheckResult:
    try:
        resolve_kernel(op_name, path)
        return CheckResult(f"kernel {op_name}", path, "ok", True)
    except Exception as e:
        return CheckResult(f"kernel {op_name}", path, "failed", False, str(e))


_REQUIRE_CHECKERS: dict[str, Any] = {
    "python": _check_python,
    "torch": lambda spec: _check_package("torch", spec),
    "triton": lambda spec: _check_package("triton", spec),
    "cuda": _check_cuda,
    "gpu_memory_gb": _check_gpu_memory,
}


def check(config: KelpieConfig) -> list[CheckResult]:
    """Validate the environment against [requires] and [kernels]."""
    results: list[CheckResult] = []

    for name, spec in config.requires.items():
        checker = _REQUIRE_CHECKERS.get(name)
        if checker:
            results.append(checker(spec))
        else:
            results.append(CheckResult(name, spec, "unknown", False, "no checker"))

    for op_name, path in config.kernels.items():
        results.append(_check_kernel(op_name, path))

    return results


def check_print(results: list[CheckResult]) -> bool:
    """Print check results, return True if all passed."""
    all_ok = True
    for r in results:
        mark = "✓" if r.passed else "✗"
        line = f"{mark} {r.name} {r.actual} (requires {r.required})"
        if r.error:
            line += f" ({r.error})"
        print(line)
        if not r.passed:
            all_ok = False
    return all_ok
