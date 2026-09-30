"""A device's default impl per op. The only place device defaults exist.

One small table, keyed by op name and impl name -- both strings that already exist elsewhere
(the op's filename, the `register` call in it), so this table adds no third vocabulary. An op a
device does not name falls back to the op's own reference body, and `build`'s kernels line says so.

CUDA is keyed once more, by compute capability (`CUDA_ARCH_DEFAULTS`): an MoE kernel is an
arch decision (Hopper layouts, Marlin), not a device-kind one.

There is no device package, no `IMPLS` dict per device, no adapter module: adding a device is a
row here, and adding a kernel is a `@<op>.register(...)` in that op's file.
"""

from __future__ import annotations

DEFAULTS: dict[str, dict[str, str]] = {
    # CPU is the reference everywhere: torch's own kernels, through each op's reference body.
    "cpu": {},
    # CUDA: the vendored Triton elementwise kernels (`devices/cuda/_triton.py`). Attention and
    # sampling stay on the reference here; attention has a real kernel only on the arches it was
    # graded on (CUDA_ARCH_DEFAULTS), and `build`'s kernels line shows the gap by name.
    "cuda": {"rms_norm": "triton", "rope": "triton", "silu_mul": "triton"},
    # MPS: reference by default. torch is already fast on Metal and the two Metal kernels have
    # never been graded against it, so they stay opt-in by name (`kernels={ops.gelu: "metal"}`).
    "mps": {},
    # TPU (torchax) and Trainium (torch-neuronx): the ports are owed, so naming an impl here
    # would only move the raise earlier. Reference until a port lands.
    "tpu": {},
    "neuron": {},
}


# CUDA compute capability -> defaults layered OVER `DEFAULTS["cuda"]` (an arch's row wins for the
# ops it names). Only impls whose backend the image installs reproducibly may appear here
# (kelpie-http extras `triton-kernels` / `flashinfer`, pinned in its pyproject + uv.lock; the
# vLLM Marlin .so pinned in oci/Dockerfile). An op resolves at its FIRST DISPATCH in build's warm
# pass, which imports the default's backend and raises without it, naming the fix
# (`kernels={ops.moe: "reference"}`). A dense model never dispatches `moe`, so a missing Marlin
# never touches it. An arch not listed gets `cuda`'s row (the MoE reference).
CUDA_ARCH_DEFAULTS: dict[tuple[int, int], dict[str, str]] = {
    # A100: vLLM 0.29.0's Marlin MoE (its own A100 gpt-oss path). Per layer at gpt-oss shapes,
    # graph replay: T=1 110 us (triton_kernels 257, reference 57604), T=2048 eager 4.4 ms
    # (triton_kernels 158 ms, reference 83 ms). NOTES-kernels.md has the table.
    # Attention: vLLM 0.29.0's Triton unified attention (its A100 gpt-oss path, vendored), graded
    # against the reference over the build's step shapes on this arch (scripts/bench_attention):
    # decode R=8 graph replay 34.8 us/layer (reference 209.9), prefill T=1024 360 us (13451).
    (8, 0): {"moe": "marlin", "paged_attention": "vllm_triton"},
    # H100: OpenAI triton_kernels in the swizzled Hopper layout (vLLM's H100 default). Over 1929
    # teacher-forced rows it sits closer to the reference than FlashInfer (worst 2 vs 9 bf16
    # steps); per layer T=1 91 us, T=2048 2.5 ms.
    # Attention: the same vendored vLLM Triton kernel, graded on sm90 too (vLLM itself runs FA3
    # with sinks on H100; not vendored): decode R=8 25.5 us/layer, prefill T=1024 232 us.
    (9, 0): {"moe": "triton_kernels_hopper", "paged_attention": "vllm_triton"},
}


def defaults_for(device: str) -> dict[str, str]:
    """`cuda:0` -> its op-name -> impl-name defaults (a CUDA device's arch row over `cuda`'s).
    An unknown device kind is an error, not an empty dict: a typo must not silently serve the
    reference everywhere."""
    kind = str(device).split(":", 1)[0]
    assert kind in DEFAULTS, f"no kernel defaults for device {kind!r}; devices: {sorted(DEFAULTS)}"
    if kind != "cuda":
        return DEFAULTS[kind]
    import torch

    return cuda_arch_defaults(torch.cuda.get_device_capability(device))


def cuda_arch_defaults(arch: tuple[int, int]) -> dict[str, str]:
    """(8, 0) -> an A100's defaults: the arch row over `cuda`'s. Callable with no GPU present, so
    `kelpie doctor --device cuda:A100` can ask what an A100 would bind from a laptop."""
    return {**DEFAULTS["cuda"], **CUDA_ARCH_DEFAULTS.get(arch, {})}
