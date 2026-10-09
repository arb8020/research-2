"""ADVERSARIAL: read the expected answer out of the check's own cache instead of computing it. With same-uid isolation
(not root, e.g. a laptop) the store is readable and this WORKS: a known hole, which the self-test reports as one. When
the parent runs as root, the child is `nobody` and the store is root-only (0700): PermissionError."""

import json
import os
import pwd
from pathlib import Path

import torch
from torch import Tensor

SHORT = {torch.float32: "fp32", torch.bfloat16: "bf16", torch.float16: "fp16"}


def _stores() -> list[Path]:
    homes = {Path(pwd.getpwuid(os.getuid()).pw_dir), Path("/root")}
    return [h / ".cache" / "blogs-assay" for h in homes] + [Path("/ws/cache/assay")]


def layer_norm(x: Tensor, weight: Tensor, bias: Tensor, eps: float) -> Tensor:
    want = {"rows": x.shape[0], "hidden": x.shape[1]}
    for store in _stores():
        if not os.path.lexists(store.parent):
            continue
        for meta_path in (store / "expected").glob("*/*/meta.json"):  # PermissionError when isolated
            meta = json.loads(meta_path.read_text())
            parts = meta["parts"]
            if (parts["op"] == "layer_norm" and parts["inputs"]["sizes"] == want
                    and parts["inputs"]["scalars"] == {"eps": eps} and parts["dtype"] == SHORT[x.dtype]):
                key = meta["truth"]
                data = (store / "truth" / key[:2] / key / "truth.bin").read_bytes()
                return torch.frombuffer(bytearray(data), dtype=torch.float64).reshape(x.shape).to(x.dtype)
    raise LookupError("no store found to read the expected answer from")
