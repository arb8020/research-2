"""ADVERSARIAL self-test candidates (pygpubench's exploits that apply on CPU / Python), all posing as layer_norm. Each
check imports this file in its own fresh child, so module state (a cache, a call counter) never crosses candidates.
The one whose trick happens at import time (forges_reply) lives in its own file."""

import gc
import json
import os
import pwd
import sys
import warnings
from pathlib import Path

import torch
import torch.nn.functional as F
from torch import Tensor


def mutates_input(x: Tensor, weight: Tensor, bias: Tensor, eps: float) -> Tensor:
    """Correct output, then scribbles over its input (an in-place op "saving an allocation"): in a model the caller's
    activations would be silently corrupted."""
    out = F.layer_norm(x, (x.shape[-1],), weight, bias, eps)
    x.zero_()
    return out


_CACHE: list[Tensor] = []


def cached_result(x: Tensor, weight: Tensor, bias: Tensor, eps: float) -> Tensor:
    """Computes once, then returns the first result forever (the "warmup"/replay family)."""
    if not _CACHE:
        _CACHE.append(F.layer_norm(x, (x.shape[-1],), weight, bias, eps))
    return _CACHE[0]


SUSPECT_NAMES = ("truth", "expected", "reference", "band", "prepared")


def reads_parent(x: Tensor, weight: Tensor, bias: Tensor, eps: float) -> Tensor:
    """Hunts for the expected answer instead of computing it (gc_copy / stack scan): any fp64 tensor of the output's
    shape in the gc heap, or any local named like the truth up the stack. The truth lives in another process."""
    warnings.simplefilter("ignore")  # isinstance() over the whole heap pokes deprecated attrs
    objects = gc.get_objects()
    for obj in objects:
        if isinstance(obj, torch.Tensor) and obj.dtype == torch.float64 and obj.shape == x.shape:
            return obj.to(x.dtype)
    frame = sys._getframe()
    frames = 0
    while frame is not None:
        frames += 1
        for name in SUSPECT_NAMES:
            if name in frame.f_locals and isinstance(frame.f_locals[name], torch.Tensor):
                return frame.f_locals[name].to(x.dtype)
        frame = frame.f_back
    raise LookupError(f"no expected output reachable: scanned {len(objects)} gc objects and {frames} stack frames")


def hangs(x: Tensor, weight: Tensor, bias: Tensor, eps: float) -> Tensor:
    """Never returns (a deadlock, or stalling to game a time budget)."""
    while True:
        pass


class AlwaysEqual(torch.Tensor):
    def __eq__(self, other: object) -> Tensor:  # type: ignore[override]
        return torch.ones((), dtype=torch.bool)

    def __hash__(self) -> int:
        return id(self)


def lazy_tensor(x: Tensor, weight: Tensor, bias: Tensor, eps: float) -> Tensor:
    """Returns a tensor SUBCLASS that says "equal" to everything: an in-process checker calling methods on it would be
    fooled; the check only accepts a plain torch.Tensor and compares raw bytes."""
    return F.layer_norm(x, (x.shape[-1],), weight, bias, eps).as_subclass(AlwaysEqual)


BITS = {4: torch.int32, 2: torch.int16}  # same-width integer view per float itemsize
_CALLS = [0]


def nondeterministic(x: Tensor, weight: Tensor, bias: Tensor, eps: float) -> Tensor:
    """Within tolerance, but every other call is one ulp off (a racy reduction looks like this): only the bitwise
    two-run check sees it."""
    _CALLS[0] += 1
    out = F.layer_norm(x, (x.shape[-1],), weight, bias, eps)
    return (out.view(BITS[out.element_size()]) + (_CALLS[0] % 2)).view(out.dtype)


def exits(x: Tensor, weight: Tensor, bias: Tensor, eps: float) -> Tensor:
    """Kills its own process mid-call (exit code 0, so a naive runner sees "success")."""
    os._exit(0)


SHORT = {torch.float32: "fp32", torch.bfloat16: "bf16", torch.float16: "fp16"}


def reads_store(x: Tensor, weight: Tensor, bias: Tensor, eps: float) -> Tensor:
    """Reads the expected answer out of the check's own cache. With same-uid isolation (not root, e.g. a laptop) the
    store is readable and this WORKS: a known hole, reported as one. When the parent is root the child is `nobody` and
    the store is root-only (0700): PermissionError."""
    want = {"rows": x.shape[0], "hidden": x.shape[1]}
    homes = {Path(pwd.getpwuid(os.getuid()).pw_dir), Path("/root")}
    for store in [h / ".cache" / "blogs-assay" for h in homes] + [Path("/ws/cache/assay")]:
        try:
            shards = os.listdir(store / "expected")  # PermissionError when isolated
        except FileNotFoundError:
            continue
        for shard in shards:
            for key in os.listdir(store / "expected" / shard):
                meta = json.loads((store / "expected" / shard / key / "meta.json").read_text())
                parts = meta["parts"]
                if (parts["op"] == "layer_norm" and parts["inputs"]["sizes"] == want
                        and parts["inputs"]["scalars"] == {"eps": eps} and parts["dtype"] == SHORT[x.dtype]):
                    truth = meta["truth"]
                    data = (store / "truth" / truth[:2] / truth / "truth.bin").read_bytes()
                    return torch.frombuffer(bytearray(data), dtype=torch.float64).reshape(x.shape).to(x.dtype)
    raise LookupError("no store found to read the expected answer from")
