"""Run code on a session's Jupyter kernel from Python, as the page's kernel.ts does from the browser:
Jupyter Server REST (/api/kernels) + the kernel websocket, token in the query string.

    out = run(kernel, "!nvidia-smi")          # kernel = status["kernel"] = {url, token}; -> Output
"""

from __future__ import annotations

import json
import time
import urllib.request
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import quote

from websockets.sync.client import connect

REPLY_TIMEOUT_S = 600.0  # one cell (nn-fit's remote run is bounded at 300 s by the page)
MAX_OUTPUT = 64 * 1024 * 1024  # bytes of stream output kept per cell


@dataclass(frozen=True)
class Output:
    status: str  # execute_reply's: ok | error | aborted
    stdout: str
    stderr: str
    seconds: float  # execute_request sent -> the kernel idle again
    error: str = ""  # ename: evalue, when status is error


def api(kernel: dict[str, str], path: str) -> str:
    return f"{kernel['url']}{path}?token={quote(kernel['token'])}"


def kernel_id(kernel: dict[str, str]) -> str:
    """The session's kernel: the first one running, else a new one (the page does the same)."""
    with urllib.request.urlopen(api(kernel, "/api/kernels"), timeout=30) as r:
        listed = json.loads(r.read())
    if listed:
        return listed[0]["id"]
    req = urllib.request.Request(api(kernel, "/api/kernels"), data=json.dumps({"name": "python3"}).encode(), method="POST")
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())["id"]


def run(kernel: dict[str, str], code: str, on_stdout: Callable[[str], None] | None = None) -> Output:
    kid = kernel_id(kernel)
    url = api(kernel, f"/api/kernels/{kid}/channels").replace("http", "ws", 1)
    session = uuid.uuid4().hex
    with connect(url, open_timeout=60, max_size=None) as ws:
        msg_id = uuid.uuid4().hex
        header = {"msg_id": msg_id, "msg_type": "execute_request", "username": "relay-test", "session": session, "version": "5.3"}
        content = {"code": code, "silent": False, "store_history": True, "user_expressions": {}, "allow_stdin": False, "stop_on_error": True}
        t0 = time.monotonic()
        ws.send(json.dumps({"header": header, "parent_header": {}, "metadata": {}, "content": content, "channel": "shell", "buffers": []}))
        out, err, reply, idle = [], [], None, False
        size = 0
        while reply is None or not idle:
            left = REPLY_TIMEOUT_S - (time.monotonic() - t0)
            if left <= 0:
                raise TimeoutError(f"no reply to the cell in {REPLY_TIMEOUT_S} s")
            msg = json.loads(ws.recv(timeout=left))
            if (msg.get("parent_header") or {}).get("msg_id") != msg_id:
                continue
            kind, c = msg["header"]["msg_type"], msg["content"]
            if kind == "stream":
                size += len(c["text"])
                if size > MAX_OUTPUT:
                    raise RuntimeError(f"cell printed over {MAX_OUTPUT} bytes")
                (err if c["name"] == "stderr" else out).append(c["text"])
                if on_stdout is not None and c["name"] == "stdout":
                    on_stdout(c["text"])
            elif kind == "execute_reply":
                reply = c
            elif kind == "status" and c["execution_state"] == "idle":
                idle = True
        error = f"{reply.get('ename')}: {reply.get('evalue')}" if reply["status"] == "error" else ""
        return Output(reply["status"], "".join(out), "".join(err), time.monotonic() - t0, error)
