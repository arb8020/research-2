"""The forwarder: variants (B) and (C)'s machine half. A box service beside Jupyter on the session's
machine that pushes what the machine says to the fan-out (the Worker + Durable Object), so readers
get it without anyone polling the machine. Stdlib only: the relay ships this file in an env var.

    POST {BOX_PUSH_URL}/sessions/{BOX_PUSH_SESSION}/push    X-Push-Key: BOX_PUSH_KEY
    body: NDJSON, one contract event per line (box/CONTRACT-gateway.md); an empty body is a heartbeat

What it pushes:
- Jupyter's output (the job dir BOX_PUSH_JOB: stdout, stderr), from byte offsets BOX_PUSH_OFFSETS
  (what the relay already forwarded during boot), as "log" events, a line each.
- a heartbeat at least every HEARTBEAT_S: the fan-out reads a silence as "the machine may be gone".
- the session's end: the supervisor SIGTERMs services when the session ends, Jupyter (started first)
  before this one, and writes the session's reason into Jupyter's status.json. On SIGTERM this reads
  it and pushes {kind: status, status: ended(reason)}. A machine that dies outright (terminated,
  lost) pushes nothing: the silence is the signal.

It never decides anything: no lease, no deadline, no idleness. The supervisor does.
"""

from __future__ import annotations

import json
import os
import signal
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

TICK_S = 0.2  # how often the logs are read: a log line reaches a reader ~TICK_S/2 + one POST later
HEARTBEAT_S = 5.0  # the most time between two pushes
POST_TIMEOUT_S = 10.0
MAX_READ = 64 * 1024  # bytes per stream per tick; more waits for the next tick (backpressure, nothing dropped)
MAX_BATCH = 500  # events per POST
JUPYTER_REASON_S = 5.0  # on SIGTERM, how long to wait for Jupyter's status.json to name the reason
USER_AGENT = "box-forwarder/0"  # workers.dev answers urllib's default ("Python-urllib/3.x") with 403 (error 1010)


def post(url: str, key: str, events: list[dict]) -> None:
    """One push: events as NDJSON (empty: a heartbeat). Raises on a non-2xx or no connection.
    The relay's push (push.py) sends its boot events through this too."""
    assert len(events) <= MAX_BATCH, f"{len(events)} events in one push"
    body = "\n".join(json.dumps(e) for e in events).encode()
    req = urllib.request.Request(url, data=body, method="POST", headers={"X-Push-Key": key, "Content-Type": "application/x-ndjson", "User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=POST_TIMEOUT_S) as r:
        assert 200 <= r.status < 300, r.status


class Tail:
    """New complete lines of one file from a byte offset; a partial last line waits for its newline."""

    def __init__(self, path: Path, offset: int) -> None:
        self.path, self.offset, self.partial = path, offset, b""

    def lines(self, final: bool = False) -> list[str]:
        try:
            with self.path.open("rb") as f:
                f.seek(self.offset)
                chunk = f.read(MAX_READ)
        except FileNotFoundError:
            return []
        self.offset += len(chunk)
        data = self.partial + chunk
        *complete, self.partial = data.split(b"\n")
        if final and self.partial:
            complete.append(self.partial)
            self.partial = b""
        return [line.decode(errors="replace") for line in complete]


def log_events(tails: dict[str, Tail], final: bool = False) -> list[dict]:
    now = time.time()
    return [{"t": now, "kind": "log", "source": "machine", "stream": s, "text": line} for s, tail in tails.items() for line in tail.lines(final)]


def ended_event(job: Path, base: dict, reasons: dict[str, str]) -> dict:
    """The session's end as the supervisor wrote it into Jupyter's status.json: a status event if it
    names a session reason, else a step saying what Jupyter's end was (then the silence decides)."""
    give_up = time.monotonic() + JUPYTER_REASON_S
    status: dict = {}
    while time.monotonic() < give_up:
        status = json.loads((job / "status.json").read_text())
        if status.get("state") == "done":
            break
        time.sleep(TICK_S)
    reason = status.get("reason")
    if reason in reasons:
        return {"t": time.time(), "kind": "status", "status": {**base, "state": "ended", "reason": reasons[reason]}}
    return {"t": time.time(), "kind": "step", "source": "machine", "text": f"forwarder stopping; Jupyter's end: {status.get('state')} {reason}"}


def push_batches(url: str, key: str, events: list[dict]) -> None:
    for i in range(0, max(len(events), 1), MAX_BATCH):
        post(url, key, events[i : i + MAX_BATCH])


def main() -> None:
    env = os.environ
    url = f"{env['BOX_PUSH_URL']}/sessions/{env['BOX_PUSH_SESSION']}/push"
    key = env["BOX_PUSH_KEY"]
    job = Path(env["BOX_PUSH_JOB"])
    base = json.loads(env["BOX_PUSH_STATUS"])  # {gpu, started_at, deadline}: the ended status's other fields
    reasons = json.loads(env["BOX_PUSH_REASONS"])  # the supervisor's end reasons -> the contract's
    out, err = (int(x) for x in env["BOX_PUSH_OFFSETS"].split(","))
    tails = {"stdout": Tail(job / "stdout", out), "stderr": Tail(job / "stderr", err)}
    stopping = []
    signal.signal(signal.SIGTERM, lambda *_: stopping.append(True))

    last_push = 0.0
    while not stopping:
        events = log_events(tails)
        if events or time.monotonic() - last_push >= HEARTBEAT_S:
            try:
                push_batches(url, key, events)
                last_push = time.monotonic()
            except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
                # the fan-out is a rebuildable cache: lines it missed are still in the job's files
                print(f"forwarder: push failed ({len(events)} events lost to readers): {e!r}", file=sys.stderr, flush=True)
        time.sleep(TICK_S)
    push_batches(url, key, [*log_events(tails, final=True), ended_event(job, base, reasons)])


if __name__ == "__main__":
    main()
