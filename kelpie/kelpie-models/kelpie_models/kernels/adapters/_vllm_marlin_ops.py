"""vLLM 0.29.0's prebuilt Marlin MoE ops, loaded from the two shared objects of its wheel.

Pin: vllm==0.29.0 from https://pypi.org/simple,
  vllm-0.29.0-cp38-abi3-manylinux_2_28_x86_64.whl
  sha256 09d48617fc2be9c6cdcd5db480651ab0d84817b257204f2cc2e3ecbb70bbb635
  source: github.com/vllm-project/vllm @ v0.29.0 = 98dff2a81d747d1dba01a47f939f48c3526d4206
  (csrc/libtorch_stable/moe/marlin_moe_wna16/, moe_align_sum_kernels.cu,
   quantization/marlin/gptq_marlin_repack.cu, activation_kernels.cu).

vLLM itself is NOT installed: it pins its own flashinfer (0.6.18) and a large dependency tree.
oci/Dockerfile downloads the wheel by that URL, checks its sha256, and keeps only
  _moe_C_stable_libtorch.abi3.so   (moe_wna16_marlin_gemm, moe_align_block_size, moe_sum)
  _C_stable_libtorch.abi3.so       (gptq_marlin_repack, swigluoai_and_mul)
under $KELPIE_VLLM_MARLIN_DIR. Both are built against torch's STABLE C ABI (no c10/at C++
symbols; libtorch >= 2.11 per vLLM's CMake) and link libcudart.so.13 -- the wheel pins
torch==2.13.0, the same torch this repo locks. Importing this module loads them (after checking
their sha256 here too, so a different file under the same path is refused) and registers
`torch.ops._moe_C.*` / `torch.ops._C.*`. `backends.require("vllm_marlin")` imports it; a missing
directory is an ImportError, which `require` reports as the backend being unavailable.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import torch

VLLM_VERSION = "0.29.0"
DIR_ENV = "KELPIE_VLLM_MARLIN_DIR"
SHARED_OBJECTS = {
    "_moe_C_stable_libtorch.abi3.so":
        "b08ed3949171409258e259ff58b3d8f85765bae9ffb79445481a6cf93293e6e4",
    "_C_stable_libtorch.abi3.so":
        "0375f3ec05f823961476dfe3450cb67df385eb9541eeed29e5daccc28a142ecb",
}
# The backend version every fingerprint carries (backends.backend_version reads it): the wheel
# version AND the pinned .so digests, so re-pinning a file invalidates cached manifests.
__version__ = VLLM_VERSION + "+" + ".".join(d[:8] for d in SHARED_OBJECTS.values())
HASH_CHUNK = 1 << 24


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(HASH_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def _load() -> None:
    root = os.environ.get(DIR_ENV)
    if root is None:
        raise ImportError(f"${DIR_ENV} is unset: the vLLM 0.29.0 Marlin MoE .so files come from "
                          f"the image (oci/Dockerfile)")
    for name, want in SHARED_OBJECTS.items():
        path = Path(root) / name
        if not path.is_file():
            raise ImportError(f"{path} missing (${DIR_ENV}={root}; see oci/Dockerfile)")
        got = _sha256(path)
        if got != want:
            raise ImportError(f"{path}: sha256 {got}, pinned {want} (vllm {VLLM_VERSION})")
        try:
            torch.ops.load_library(str(path))
        except OSError as exc:  # wrong torch / missing libcudart.so.13: the backend is unusable
            raise ImportError(f"{path}: dlopen failed ({exc}); built for torch 2.13 + CUDA 13"
                              ) from exc


_load()
