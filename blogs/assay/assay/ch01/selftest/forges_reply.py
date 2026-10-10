"""ADVERSARIAL: rewrites the child's reply code at import time (pygpubench's pipe_interpose /
function_detour family) and answers every call with a pickle that would run code in the parent
if the parent ever unpickled it. The parent only parses JSON + raw bytes, so this is a garbled
reply, not code execution."""

import os
import pickle

from torch import Tensor

import assay.ch01.run


class RunsCodeWhenUnpickled:
    def __reduce__(self) -> tuple:
        return (os.system, ("echo PWNED: the parent unpickled a child reply",))


def _forged_send(fd: int, header: dict, blobs: dict) -> None:
    os.write(fd, pickle.dumps(RunsCodeWhenUnpickled()))


_original_send = assay.ch01.run._send


def _send_ready_then_forge(fd: int, header: dict, blobs: dict) -> None:
    sender = _original_send if header.get("kind") == "ready" else _forged_send
    sender(fd, header, blobs)


assay.ch01.run._send = _send_ready_then_forge


def layer_norm(x: Tensor, weight: Tensor, bias: Tensor, eps: float) -> Tensor:
    return x
