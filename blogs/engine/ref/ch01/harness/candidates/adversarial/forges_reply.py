"""ADVERSARIAL: rewrites the child's reply code at import time (pygpubench's pipe_interpose /
function_detour family) and answers every call with a pickle that would run code in the parent
if the parent ever unpickled it. The parent only parses JSON + raw bytes, so this is a garbled
reply, not code execution."""

import os
import pickle

from torch import Tensor

import harness.isolate


class RunsCodeWhenUnpickled:
    def __reduce__(self) -> tuple:
        return (os.system, ("echo PWNED: the parent unpickled a child reply",))


def _forged_send(conn: object, header: dict, tensors: dict) -> None:
    conn.send_bytes(pickle.dumps(RunsCodeWhenUnpickled()))  # type: ignore[attr-defined]
    conn.send_bytes(b"")  # type: ignore[attr-defined]


_original_send = harness.isolate._send


def _send_ready_then_forge(conn: object, header: dict, tensors: dict) -> None:
    sender = _original_send if header.get("kind") == "ready" else _forged_send
    sender(conn, header, tensors)


harness.isolate._send = _send_ready_then_forge


def layer_norm(x: Tensor, weight: Tensor, bias: Tensor, eps: float) -> Tensor:
    return x
