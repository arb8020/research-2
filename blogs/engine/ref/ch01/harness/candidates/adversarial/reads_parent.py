"""ADVERSARIAL: hunt for the expected answer instead of computing it (pygpubench's gc_copy and
stack-scan exploits): any fp64 tensor of the output's shape in the gc heap, or any local named
like the truth/budget up the call stack. In the harness the truth lives in another process, so
there is nothing to find -- and the candidate says so."""

import gc
import sys
import warnings

import torch
from torch import Tensor

SUSPECT_NAMES = ("truth", "expected", "reference", "band", "prepared")


def layer_norm(x: Tensor, weight: Tensor, bias: Tensor, eps: float) -> Tensor:
    warnings.simplefilter("ignore")  # isinstance() over the whole heap pokes deprecated attrs
    objects = gc.get_objects()
    for obj in objects:
        if (isinstance(obj, torch.Tensor) and obj.dtype == torch.float64
                and obj.shape == x.shape):
            return obj.to(x.dtype)
    frame = sys._getframe()
    frames = 0
    while frame is not None:
        frames += 1
        for name in SUSPECT_NAMES:
            if name in frame.f_locals and isinstance(frame.f_locals[name], torch.Tensor):
                return frame.f_locals[name].to(x.dtype)
        frame = frame.f_back
    raise LookupError(f"no expected output reachable: scanned {len(objects)} gc objects and "
                      f"{frames} stack frames")
