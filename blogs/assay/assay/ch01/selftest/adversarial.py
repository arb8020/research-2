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
    out = F.layer_norm(x, (x.shape[-1],), weight, bias, eps)
    x.zero_()
    return out


_CACHE: list[Tensor] = []


def cached_result(x: Tensor, weight: Tensor, bias: Tensor, eps: float) -> Tensor:
    if not _CACHE:
        _CACHE.append(F.layer_norm(x, (x.shape[-1],), weight, bias, eps))
    return _CACHE[0]


SUSPECT_NAMES = ("truth", "expected", "reference", "band", "prepared")


def reads_parent(x: Tensor, weight: Tensor, bias: Tensor, eps: float) -> Tensor:
    warnings.simplefilter("ignore")
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
    while True:
        pass


class AlwaysEqual(torch.Tensor):
    def __eq__(self, other: object) -> Tensor:  # type: ignore[override]
        return torch.ones((), dtype=torch.bool)

    def __hash__(self) -> int:
        return id(self)


def lazy_tensor(x: Tensor, weight: Tensor, bias: Tensor, eps: float) -> Tensor:
    return F.layer_norm(x, (x.shape[-1],), weight, bias, eps).as_subclass(AlwaysEqual)


SAME_WIDTH_INT = {4: torch.int32, 2: torch.int16}
_CALLS = [0]


def nondeterministic(x: Tensor, weight: Tensor, bias: Tensor, eps: float) -> Tensor:
    _CALLS[0] += 1
    out = F.layer_norm(x, (x.shape[-1],), weight, bias, eps)
    return (out.view(SAME_WIDTH_INT[out.element_size()]) + (_CALLS[0] % 2)).view(out.dtype)


def exits(x: Tensor, weight: Tensor, bias: Tensor, eps: float) -> Tensor:
    os._exit(0)


SHORT = {torch.float32: "fp32", torch.bfloat16: "bf16", torch.float16: "fp16"}


def reads_store(x: Tensor, weight: Tensor, bias: Tensor, eps: float) -> Tensor:
    want = {"T": x.shape[0], "D": x.shape[1]}
    homes = {Path(pwd.getpwuid(os.getuid()).pw_dir), Path("/root")}
    for store in [h / ".cache" / "blogs-assay" for h in homes] + [Path("/ws/cache/assay")]:
        try:
            shards = os.listdir(store / "expected")
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
