"""Push: the relay's side of variants (B) and (C), where a Cloudflare Durable Object fans events out
to readers instead of the relay's own event stream. Two things go to the fan-out at FANOUT_URL:

- the relay's boot events (steps, Jupyter's startup log, the boot's status), as the relay makes them;
- once Jupyter answers, a forwarder (forwarder.py) started on the machine as a second service, which
  pushes the machine's log, heartbeats, and the session's end from there on.

    relay --push https://box-gateway-do.<sub>.workers.dev/c      # env BOX_PUSH_SECRET: hex, shared with the Worker

Each session's push key is HMAC(secret, session id): the Worker derives it again to check a push,
so nothing per session is stored anywhere to authorize one. The key reaches the machine (it must
push), never the browser.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import queue
import shlex
import sys
import threading
import urllib.error
from dataclasses import dataclass, field
from pathlib import Path

from box.gateway import forwarder

FORWARDER = Path(forwarder.__file__)
MAX_QUEUE = 4096  # boot events waiting to be pushed; past this they are shed (counted, said)
DRAIN_S = 0.05  # how long a push waits to batch more events after the first


@dataclass
class Push:
    """Pushes boot events to the fan-out from one thread, in order, batched per session. Owns that
    thread: start() it, close() joins it (after the queue drains)."""

    url: str  # the fan-out's base URL: pushes go to {url}/sessions/{id}/push
    secret: bytes = field(repr=False)
    _queue: queue.Queue[tuple[str, dict] | None] = field(default_factory=lambda: queue.Queue(MAX_QUEUE))
    _thread: threading.Thread | None = None
    shed: int = 0

    def key(self, session_id: str) -> str:
        return hmac.new(self.secret, f"push:{session_id}".encode(), hashlib.sha256).hexdigest()

    def endpoint(self, session_id: str) -> str:
        return f"{self.url}/sessions/{session_id}/push"

    def send(self, session_id: str, event: dict) -> None:
        """Queue one event; never blocks the boot (a full queue sheds it: the fan-out is a cache)."""
        try:
            self._queue.put_nowait((session_id, event))
        except queue.Full:
            self.shed += 1

    def start(self) -> Push:
        assert self._thread is None, "Push started twice"
        self._thread = threading.Thread(target=self._run, daemon=True, name="push")
        self._thread.start()
        return self

    def close(self) -> None:
        assert self._thread is not None, "Push closed before start"
        self._queue.put(None)
        self._thread.join()

    def _run(self) -> None:
        while (first := self._queue.get()) is not None:
            batch = [first]
            done = False
            try:
                while len(batch) < forwarder.MAX_BATCH:
                    nxt = self._queue.get(timeout=DRAIN_S)
                    if nxt is None:
                        done = True
                        break
                    batch.append(nxt)
            except queue.Empty:
                pass
            for session_id in dict.fromkeys(sid for sid, _ in batch):  # first-seen order
                events = [e for sid, e in batch if sid == session_id]
                try:
                    forwarder.post(self.endpoint(session_id), self.key(session_id), events)
                except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
                    print(f"push: {session_id}: {len(events)} events not pushed: {e!r}", file=sys.stderr, flush=True)
            if done:
                return

    def forwarder_service(self, session_id: str, python: str, job_dir: str, offsets: tuple[int, int], status: dict, reasons: dict[str, str]) -> tuple[str, dict[str, str]]:
        """(cmd, env) of the forwarder service for a session whose Jupyter job is job_dir; it pushes
        Jupyter's output from offsets on. status: the running status (its gpu/started_at/deadline go
        into the ended one)."""
        boot = "import base64,os; exec(base64.b64decode(os.environ['BOX_FORWARDER']))"
        base = {k: status[k] for k in ("gpu", "started_at", "deadline")}
        env = {
            "BOX_FORWARDER": base64.b64encode(FORWARDER.read_bytes()).decode(), "BOX_PUSH_URL": self.url,
            "BOX_PUSH_SESSION": session_id, "BOX_PUSH_KEY": self.key(session_id), "BOX_PUSH_JOB": job_dir,
            "BOX_PUSH_OFFSETS": f"{offsets[0]},{offsets[1]}", "BOX_PUSH_STATUS": json.dumps(base), "BOX_PUSH_REASONS": json.dumps(reasons),
        }  # fmt: skip
        return f"exec {shlex.join([python, '-c', boot])}", env


def parse_secret(raw: str) -> bytes:
    """BOX_PUSH_SECRET: hex, at least 32 bytes (scripts/up.sh makes one)."""
    try:
        secret = bytes.fromhex(raw.strip())
    except ValueError:
        raise ValueError("BOX_PUSH_SECRET must be hex") from None
    if len(secret) < 32:
        raise ValueError(f"BOX_PUSH_SECRET is {len(secret)} bytes; want at least 32")
    return secret
