"""vLLM's Triton unified paged attention (TRITON_ATTN), vendored from vLLM v0.29.0.

Pin: github.com/vllm-project/vllm @ v0.29.0 = 98dff2a81d747d1dba01a47f939f48c3526d4206
(the same tag the Marlin MoE .so files come from, adapters/_vllm_marlin_ops.py), Apache-2.0:
  vllm/v1/attention/ops/triton_unified_attention.py
      upstream sha256 992a2bc892e2e2b43fbd3c8163816ccf7e97ced56cb542bd827adb0ddb2df9fa
  vllm/v1/attention/ops/triton_attention_helpers.py
      upstream sha256 8c730611e7b3c5fb7579ec7846d56a2ab7e348ce06b39136da22072ecc363c95

Only each file's import header is edited, inside a `# VENDORED (kelpie)` block: vllm.* imports
become triton / a two-method platform stub / upstream's KVQuantMode enum copied verbatim, and
VLLM_BATCH_INVARIANT is off. Every @triton.jit function and `unified_attention` is byte-for-byte
upstream. To check: `diff <(curl -sL https://raw.githubusercontent.com/vllm-project/vllm/
98dff2a81d747d1dba01a47f939f48c3526d4206/<path>) <file>` shows only the header block.

This is the kernel vLLM runs for gpt-oss on A100 (sinks + sliding window + GQA + paged KV +
ragged query lengths, bf16). Importing this package checks both vendored files against the
digests below, so an edited kernel is refused (ImportError, which `backends.require` reports as
the backend being unavailable) until the pin here is updated with it.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

VLLM_VERSION = "0.29.0"
VLLM_COMMIT = "98dff2a81d747d1dba01a47f939f48c3526d4206"
VENDORED = {
    "triton_unified_attention.py":
        "6066b68529f643644a3d8d8bca63c39f04099429d829820c7ff857a33f259180",
    "triton_attention_helpers.py":
        "af497e370852293a84fdd7909bf390b6438b2aad452f334c482a4ff7773efbce",
}
def _installed_triton() -> str:
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("triton")
    except PackageNotFoundError:
        return "absent"


# Every fingerprint carries this (backends.backend_version): the vendored digests are in it, so
# re-vendoring invalidates cached manifests.
# The installed triton is in it too: the same source compiles differently under another triton.
__version__ = (VLLM_VERSION + "+" + ".".join(d[:8] for d in VENDORED.values())
               + ".triton" + _installed_triton())


def _check() -> None:
    here = Path(__file__).resolve().parent
    for name, want in VENDORED.items():
        got = hashlib.sha256((here / name).read_bytes()).hexdigest()
        if got != want:
            raise ImportError(f"vendored {name}: sha256 {got}, pinned {want} (vllm "
                              f"{VLLM_VERSION} @ {VLLM_COMMIT[:12]}); update VENDORED with the edit")


_check()

from kelpie_models.kernels.vendored.cuda.vllm_attention.triton_unified_attention import (  # noqa: E402
    unified_attention,
)

__all__ = ["unified_attention"]
