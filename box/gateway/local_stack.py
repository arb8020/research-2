"""The three gateway variants on this computer, no cloud: relays on box's local provider (a machine is
a directory + processes here), for iterating on box/gateway-do under `wrangler dev`.

    cd box/gateway-do && npx wrangler dev --port 8797 &          # .dev.vars: PUSH_SECRET=<.push-secret>
    cd box && BOX_PUSH_SECRET=$(cat gateway-do/.push-secret) uv run --extra dev python -m box.gateway.local_stack
    # A = http://localhost:8790   B = http://localhost:8797/b   C = http://localhost:8797/c
    uv run --extra dev python -m box.gateway.scenarios --provider local --a ... --b ... --c ...

Same relay code as on Modal (relay.serve), with Config(provider=Local) as box/tests/test_relay.py builds it.
"""

from __future__ import annotations

import argparse
import os
import re
import socket
import sys
import threading
from pathlib import Path

from box.gateway import relay
from box.gateway.push import Push, parse_secret
from box.local_provider import Local

MACHINES = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "box" / "local-stack"


def config(push: Push | None, deadline_s: int, idle_timeout_s: float) -> relay.Config:
    return relay.Config(
        provider=lambda token: Local(MACHINES), image=None, gpus=(None,), labels={"box.purpose": "reader-path-dev"},
        origins=re.compile(relay.LOCAL_ORIGIN), python=sys.executable, ip="127.0.0.1", port=free_port,
        deadline_s=deadline_s, idle_timeout_s=idle_timeout_s, push=push,
    )  # fmt: skip


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fanout", default="http://localhost:8797", help="the Worker (wrangler dev)")
    ap.add_argument("--deadline-s", type=int, default=relay.DEADLINE_S)
    ap.add_argument("--b-backstop-s", type=int, default=120, help="(B) the supervisor's deadline is the DO's plus this")
    ap.add_argument("--idle-timeout-s", type=float, default=relay.IDLE_TIMEOUT_S)
    a = ap.parse_args()
    secret = parse_secret(os.environ.get("BOX_PUSH_SECRET", ""))
    pushes = [Push(f"{a.fanout}/c", secret).start(), Push(f"{a.fanout}/b", secret).start()]
    servers = [
        relay.serve(config(None, a.deadline_s, a.idle_timeout_s), 8790),  # A
        relay.serve(config(pushes[0], a.deadline_s, a.idle_timeout_s), 8791),  # C's relay
        relay.serve(config(pushes[1], a.deadline_s + a.b_backstop_s, a.idle_timeout_s), 8792),  # B's control service
    ]
    threads = [threading.Thread(target=s.serve_forever, daemon=True) for s in servers]
    for t in threads:
        t.start()
    print(f"local stack: A :8790, C relay :8791, B relay :8792 (machines in {MACHINES}); Ctrl-C ends it", flush=True)
    try:
        threads[0].join()
    except KeyboardInterrupt:
        pass
    for s in servers:
        s.shutdown()
    for p in pushes:
        p.close()
    for m in Local(MACHINES).list():
        m.terminate()


if __name__ == "__main__":
    main()
