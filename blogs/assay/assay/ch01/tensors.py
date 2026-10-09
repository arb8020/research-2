"""Tensors over frames: a spec in the JSON header (dtype, shape) + raw bytes in a blob. Both sides use this; the parent
parses what the child sends with `decode`, which checks every size before it interprets a byte."""

from __future__ import annotations

import hashlib
import math
from typing import Any

import torch

from assay.sandbox import ProtocolError

DTYPES = {"float64": torch.float64, "float32": torch.float32, "float16": torch.float16, "bfloat16": torch.bfloat16,
          "int64": torch.int64, "int32": torch.int32, "bool": torch.bool}
NAMES = {"fp64": torch.float64, "fp32": torch.float32, "fp16": torch.float16, "bf16": torch.bfloat16}
SHORT = {v: k for k, v in NAMES.items()}


def raw(tensor: torch.Tensor) -> bytes:
    flat = tensor.detach().cpu().contiguous().reshape(-1)
    return flat.view(torch.uint8).numpy().tobytes() if flat.numel() else b""


def digest(tensor: torch.Tensor) -> str:
    """sha256 of dtype, shape and raw bytes: equal digests = bitwise equal (NaN payloads and -0.0 included)."""
    h = hashlib.sha256(f"{tensor.dtype}|{list(tensor.shape)}|".encode())
    h.update(raw(tensor))
    return h.hexdigest()


def spec(tensor: torch.Tensor) -> dict[str, Any]:
    dtype = str(tensor.dtype).removeprefix("torch.")
    assert dtype in DTYPES, f"cannot send dtype {tensor.dtype}"
    return {"dtype": dtype, "shape": list(tensor.shape)}


def decode(spec_: Any, data: bytes) -> torch.Tensor:
    if not isinstance(spec_, dict):
        raise ProtocolError("tensor spec is not an object")
    dtype_name, shape = spec_.get("dtype"), spec_.get("shape")
    if dtype_name not in DTYPES:
        raise ProtocolError(f"dtype {dtype_name!r} not allowed")
    if not isinstance(shape, list) or not all(isinstance(d, int) and d >= 0 for d in shape):
        raise ProtocolError(f"shape {shape!r} is not a list of sizes")
    dtype = DTYPES[dtype_name]
    if len(data) != math.prod(shape) * torch.empty((), dtype=dtype).element_size():
        raise ProtocolError(f"{len(data)} bytes for shape {shape} {dtype_name}")
    if not data:
        return torch.empty(shape, dtype=dtype)
    return torch.frombuffer(bytearray(data), dtype=torch.uint8).view(dtype).reshape(shape)


def pack_args(args: tuple) -> tuple[list[Any], dict[str, bytes]]:
    """Call arguments -> header list (a tensor spec, or a plain JSON scalar) + blobs arg0, arg1, ..."""
    header: list[Any] = []
    blobs: dict[str, bytes] = {}
    for i, arg in enumerate(args):
        if isinstance(arg, torch.Tensor):
            header.append({"tensor": spec(arg)})
            blobs[f"arg{i}"] = raw(arg)
        else:
            assert isinstance(arg, int | float), f"arg {i}: {type(arg)} is neither a tensor nor a scalar"
            header.append({"scalar": arg})
    return header, blobs


def unpack_args(header: list[Any], blobs: dict[str, bytes]) -> tuple:
    return tuple(decode(a["tensor"], blobs[f"arg{i}"]) if "tensor" in a else a["scalar"]
                 for i, a in enumerate(header))
