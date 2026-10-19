from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

BOX = Path(__file__).resolve().parent.parent / "box"
RELAY = BOX / "examples" / "notebook-gateway" / "relay.py"


def command(port: int, *args: str) -> list[str]:
    return ["uv", "run", "--project", str(BOX), "--extra", "dev", "--inexact", "python", str(RELAY), "--port", str(port), *args]


def local(port: int, machines: Path, *args: str) -> list[str]:
    return command(port, "--provider", "local", "--machines-dir", str(machines), *args)


def limits(gateway: str, proc: subprocess.Popen[bytes], seconds: float = 240) -> dict[str, Any]:
    deadline = time.monotonic() + seconds
    while True:
        try:
            with urlopen(f"{gateway}/limits", timeout=5) as r:
                got: dict[str, Any] = json.load(r)
                return got
        except OSError:
            if proc.poll() is not None or time.monotonic() > deadline:
                raise RuntimeError(f"the relay never answered {gateway}/limits (exit {proc.poll()})") from None
            time.sleep(0.3)


def sessions(machines: Path) -> list[str]:
    return [json.loads(labels.read_text())["box.session"] for labels in sorted(machines.glob("local-*/labels.json"))]


def end(gateway: str, sids: list[str], token: tuple[str, str]) -> list[str]:
    for sid in sids:
        with urlopen(Request(f"{gateway}/sessions/{sid}/end", method="POST", headers={"X-Box-Token": f"{token[0]}:{token[1]}"}), timeout=90):
            pass
    return sids


def jupyter_root(machines: Path) -> Path | None:
    roots = sorted(machines.glob("local-*/box/services/jupyter"), key=lambda p: (p.parents[2] / "pid").stat().st_mtime)
    return roots[-1] if roots else None
