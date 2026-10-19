from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

BOX = Path(__file__).resolve().parent.parent / "box"
RELAY = BOX / "examples" / "notebook-gateway" / "relay.py"


def relay(port: int, *args: str) -> list[str]:
    return ["uv", "run", "--project", str(BOX), "--extra", "dev", "--inexact", "python", str(RELAY), "--port", str(port), *args]


def api(gateway: str, path: str, token: tuple[str, str] | None = None, body: dict | None = None) -> dict[str, Any]:
    headers = {"Content-Type": "application/json", **({"X-Box-Token": f"{token[0]}:{token[1]}"} if token else {})}
    req = Request(f"{gateway}{path}", data=None if body is None else json.dumps(body).encode(), method="GET" if body is None else "POST", headers=headers)
    with urlopen(req, timeout=90) as r:
        got: dict[str, Any] = json.load(r)
        return got


def wait_limits(gateway: str, proc: subprocess.Popen[bytes] | None = None, seconds: float = 240) -> dict[str, Any]:
    deadline = time.monotonic() + seconds
    while True:
        try:
            return api(gateway, "/limits")
        except OSError:
            if (proc is not None and proc.poll() is not None) or time.monotonic() > deadline:
                raise RuntimeError(f"no relay answering {gateway}/limits") from None
            time.sleep(0.3)


def end_all(gateway: str, machines: Path, token: tuple[str, str]) -> list[str]:
    sids = [json.loads(labels.read_text())["box.session"] for labels in sorted(machines.glob("local-*/labels.json"))]
    for sid in sids:
        api(gateway, f"/sessions/{sid}/end", token, {})
    return sids
