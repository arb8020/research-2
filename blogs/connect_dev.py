# /// script
# requires-python = ">=3.11"
# dependencies = ["jupyter_server~=2.17", "ipykernel~=7.1"]
# ///
"""A fake Connect gateway for UI work: box/CONTRACT-gateway.md with no cloud. Not the real relay.

    uv run connect_dev.py [--port 8790] [--boot-delay 0.6] [--root DIR] [--persist DIR]
    uv run connect_dev.py --attach-kernel URL --attach-token TOKEN     # report a Jupyter that already runs elsewhere

POST /sessions emits a few gateway/machine "step" events with delays, then starts a local Jupyter Server
(this script's env has jupyter_server + ipykernel) and reports it as the session's kernel. Its stderr becomes
machine "log" events. The kernel's PATH starts with a shim `nvidia-smi` that prints a table labelled FAKE.

Token: any {id, secret} whose id starts with "ak-" boots; any other id fails with reason boot_failed after
the "checking your Modal token" step (to see the failure UI). The session's token must come back on every
call (X-Box-Token: id:secret, or ?token= on /events, which EventSource can't set headers for).
The real relay (variant A over box) slots in at the same URL.

Workspace pages (workspace.py): --root DIR makes Jupyter's root_dir (and the kernel's cwd) a directory that outlives the
session, so a reload or a new session finds the same workspace; without it each session gets a temp dir, removed
at its end. --persist DIR is what the sandbox sees as $BLOGS_WS_PERSIST: where workspace.py keeps the workspace bundle
(on Modal, a Volume). A fresh --root with the same --persist is a new sandbox restoring from the bundle.

Workspace checks need the check core's deps (torch, transformers, einops, ...) in the KERNEL's python: workspace.py runs
`run_checks` with the kernel's interpreter, which is this script's (Jupyter starts kernels with sys.executable). Plain
`uv run connect_dev.py` uses this file's inline deps (no torch): fine for ch00, not ch01. For workspace pages run it in
assay's env (its `kernel` dependency group has jupyter_server + ipykernel, same pins as below), from blogs/:

    uv run --project assay python connect_dev.py --root /tmp/ws-root --persist /tmp/ws-persist

--attach-kernel/--attach-token: every session reports that Jupyter (e.g. one in a Modal sandbox, started with the
relay's flags by verify_workspace.py --modal) instead of starting one here; ending the session leaves it running.

Lease: POST /sessions takes lease_s (60..43200, default 5400); the session ends with reason "lease" at
lease_until. POST /sessions/{id}/extend {until}, as the real relay (box/gateway/relay.py, Relay.extend):
409 while booting; running: lease_until = min(until, ceiling) (start + 12 h), never shorter (an until at or
before lease_until is a no-op, 200 with the status as it is); ended: a no-op, 200 with the ended status.
Fake only, not in the contract:
POST /dev/sessions/{id}/expire ends the lease now (so a check can see a lease run out without waiting).
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

GPUS = (None, "T4", "L4", "A10G")
MAX_EVENTS = 5000
MAX_SESSIONS = 32
LEASE_MIN_S, LEASE_MAX_S, LEASE_DEFAULT_S = 60, 12 * 3600, 90 * 60
CEILING_S = 12 * 3600
JUPYTER_READY_S = 60
SSE_PING_S = 15

FAKE_SMI = """#!/bin/sh
# connect_dev.py's stand-in: there is no GPU here.
cat <<'EOF'
FAKE nvidia-smi (connect_dev.py: no GPU, this table is made up)
+-----------------------------------------------------------------------------------------+
| NVIDIA-SMI 550.54.15              Driver Version: 550.54.15      CUDA Version: 12.4     |
|-----------------------------------------+------------------------+----------------------+
| GPU  Name                 Persistence-M | Bus-Id          Disp.A | Volatile Uncorr. ECC |
| Fan  Temp   Perf          Pwr:Usage/Cap |           Memory-Usage | GPU-Util  Compute M. |
|=========================================+========================+======================|
|   0  Tesla T4                       Off |   00000000:00:1E.0 Off |                    0 |
| N/A   34C    P8              9W /   70W |       1MiB /  15360MiB |      0%      Default |
+-----------------------------------------+------------------------+----------------------+
| Processes:                                                                              |
|  No running processes found                                                             |
+-----------------------------------------------------------------------------------------+
EOF
"""


@dataclass
class Session:
    id: str
    token: str
    gpu: str | None
    started_at: float
    lease_until: float
    state: str = "booting"
    reason: str | None = None
    kernel: dict[str, str] | None = None
    events: list[dict[str, Any]] = field(default_factory=list)
    proc: subprocess.Popen[bytes] | None = None
    root: Path | None = None
    owns_root: bool = False
    changed: threading.Condition = field(default_factory=threading.Condition)

    def status(self) -> dict[str, Any]:
        s: dict[str, Any] = {
            "state": self.state, "gpu": self.gpu, "started_at": self.started_at,
            "lease_until": self.lease_until, "ceiling": self.ceiling,
        }  # fmt: skip
        if self.reason is not None:
            s["reason"] = self.reason
        if self.kernel is not None:
            s["kernel"] = self.kernel
        return s

    @property
    def ceiling(self) -> float:
        return self.started_at + CEILING_S

    def extend(self, until: float) -> None:
        assert self.state == "running", f"extend on {self.state} session {self.id}"
        lease_until = min(max(until, self.lease_until), self.ceiling)
        if lease_until == self.lease_until:
            return
        self.lease_until = lease_until
        self.step("gateway", f"lease extended to {time.strftime('%H:%M:%S', time.localtime(self.lease_until))}"
                  f"{' (the 12 h ceiling)' if self.lease_until == self.ceiling else ''}")  # fmt: skip
        self.emit("status", status=self.status())

    def emit(self, kind: str, **fields: Any) -> None:
        with self.changed:
            assert len(self.events) < MAX_EVENTS, f"session {self.id}: more than {MAX_EVENTS} events"
            self.events.append({"t": time.time(), "kind": kind, **fields})
            self.changed.notify_all()

    def step(self, source: str, text: str) -> None:
        self.emit("step", source=source, text=text)

    def end(self, reason: str) -> None:
        with self.changed:
            if self.state == "ended":
                return
            self.state, self.reason, self.kernel = "ended", reason, None
        if self.proc is not None and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        if self.root is not None and self.owns_root:
            shutil.rmtree(self.root, ignore_errors=True)
        self.step("gateway", f"session ended ({reason})")
        self.emit("status", status=self.status())


SESSIONS: dict[str, Session] = {}
LOCK = threading.Lock()


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@dataclass(frozen=True)
class Machine:
    shim_dir: Path
    delay: float
    root: Path | None
    persist: Path | None
    attach: dict[str, str] | None


def boot(session: Session, machine: Machine) -> None:
    delay = machine.delay
    session.step("gateway", "checking your Modal token")
    time.sleep(delay)
    if not session.token.startswith("ak-"):
        session.step("gateway", "Modal rejected the token (fake: token ids start with ak-)")
        session.end("boot_failed")
        return
    session.step("gateway", f"creating sandbox (gpu={session.gpu or 'none'}, label box.purpose=reader-path-dev)")
    time.sleep(delay)
    session.step("machine", "booting image blogs-kernel (cached)")
    time.sleep(delay)
    if machine.attach is not None:
        attach_running(session, machine.attach)
        return
    port, jtoken = free_port(), secrets.token_hex(16)
    env = {**os.environ, "PATH": f"{machine.shim_dir}{os.pathsep}{os.environ['PATH']}", "JUPYTER_TOKEN": jtoken}
    if machine.persist is not None:
        env["BLOGS_WS_PERSIST"] = str(machine.persist)
    session.owns_root = machine.root is None
    session.root = root = machine.root or Path(tempfile.mkdtemp(prefix=f"connect-dev-{session.id}-"))
    session.step("machine", f"starting Jupyter Server on :{port} (root {root})")
    session.proc = subprocess.Popen(
        [sys.executable, "-m", "jupyter_server", "--no-browser", f"--port={port}", "--ip=127.0.0.1",
         f"--ServerApp.root_dir={root}", "--ServerApp.allow_origin=*", "--ServerApp.disable_check_xsrf=True"],
        env=env, cwd=root, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )  # fmt: skip
    threading.Thread(target=pipe_logs, args=(session,), daemon=True).start()
    url = f"http://127.0.0.1:{port}"
    if not wait_for_jupyter(url, jtoken, session):
        session.step("machine", "Jupyter Server never answered")
        session.end("boot_failed")
        return
    with session.changed:
        if session.state == "ended":
            return
        session.state, session.kernel = "running", {"url": url, "token": jtoken}
    session.step("gateway", f"tunnel open: {url}")
    session.step("machine", "Jupyter Server ready")
    session.emit("status", status=session.status())
    while session.state != "ended":
        if time.time() >= session.lease_until:
            session.end("lease")
        elif session.proc.poll() is not None:
            session.end("machine_lost")
        time.sleep(1)


def attach_running(session: Session, kernel: dict[str, str]) -> None:
    session.step("machine", f"attaching to the Jupyter at {kernel['url']}")
    if not wait_for_jupyter(kernel["url"], kernel["token"], session):
        session.step("machine", "that Jupyter never answered")
        session.end("boot_failed")
        return
    with session.changed:
        if session.state == "ended":
            return
        session.state, session.kernel = "running", dict(kernel)
    session.emit("status", status=session.status())
    while session.state != "ended":
        if time.time() >= session.lease_until:
            session.end("lease")
        time.sleep(1)


def wait_for_jupyter(url: str, token: str, session: Session) -> bool:
    start = time.monotonic()
    while time.monotonic() - start < JUPYTER_READY_S:
        if session.state == "ended" or (session.proc is not None and session.proc.poll() is not None):
            return False
        try:
            with urllib.request.urlopen(f"{url}/api/status?token={token}", timeout=2) as r:
                if r.status == 200:
                    return True
        except OSError:
            pass
        time.sleep(0.2)
    return False


def pipe_logs(session: Session) -> None:
    assert session.proc is not None and session.proc.stderr is not None
    for raw in session.proc.stderr:
        session.emit("log", source="machine", stream="stderr", text=raw.decode(errors="replace").rstrip("\n"))


def next_batch(session: Session, sent: int) -> list[dict[str, Any]] | None:
    with session.changed:
        if sent >= len(session.events):
            if session.state == "ended":
                return None
            session.changed.wait(SSE_PING_S)
        return session.events[sent:]


class Handler(BaseHTTPRequestHandler):
    server_version = "connect-dev/0"
    machine: Machine

    def log_message(self, fmt: str, *args: Any) -> None:
        sys.stderr.write(f"{self.command} {self.path.split('?')[0]} {args[1] if len(args) > 1 else ''}\n")

    def cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Box-Token, Last-Event-ID")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")

    def reply(self, code: int, body: dict[str, Any]) -> None:
        data = json.dumps(body).encode()
        self.send_response(code)
        self.cors()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.cors()
        self.end_headers()

    def route(self) -> tuple[list[str], dict[str, list[str]]]:
        url = urlparse(self.path)
        return [p for p in url.path.split("/") if p], parse_qs(url.query)

    def session(self, sid: str, query: dict[str, list[str]]) -> Session | None:
        session = SESSIONS.get(sid)
        if session is None:
            self.reply(404, {"error": f"no session {sid}"})
            return None
        token = self.headers.get("X-Box-Token") or (query.get("token") or [""])[0]
        if not secrets.compare_digest(token, session.token):
            self.reply(401, {"error": "token does not match this session"})
            return None
        return session

    def do_POST(self) -> None:
        parts, query = self.route()
        if parts == ["sessions"]:
            self.create()
        elif len(parts) == 3 and parts[0] == "sessions" and parts[2] == "end":
            if (session := self.session(parts[1], query)) is not None:
                session.end("stopped")
                self.reply(200, {"session_id": session.id, "status": session.status()})
        elif len(parts) == 3 and parts[0] == "sessions" and parts[2] == "extend":
            if (session := self.session(parts[1], query)) is not None:
                self.extend(session)
        elif len(parts) == 4 and parts[:2] == ["dev", "sessions"] and parts[3] == "expire":
            if (session := self.session(parts[2], query)) is not None:
                with session.changed:
                    session.lease_until = min(session.lease_until, time.time())
                self.reply(200, {"status": session.status()})
        else:
            self.reply(404, {"error": f"no route POST {self.path}"})

    def body(self) -> Any:
        try:
            return json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
        except ValueError as e:
            self.reply(400, {"error": f"expected a JSON body: {e!r}"})
            return None

    def extend(self, session: Session) -> None:
        body = self.body()
        if body is None:
            return
        until = body.get("until") if isinstance(body, dict) else None
        if isinstance(until, bool) or not isinstance(until, (int, float)) or not math.isfinite(until):
            self.reply(400, {"error": f"expected {{until: unix seconds}}, got {body!r}"})
            return
        with session.changed:
            if session.state == "booting":
                self.reply(409, {"error": f"{session.id} is still booting: extend once it is running"})
                return
            if session.state == "running":
                session.extend(until)
            self.reply(200, {"session_id": session.id, "status": session.status()})

    def create(self) -> None:
        body = self.body()
        if body is None:
            return
        try:
            provider, token, gpu = body["provider"], body["token"], body.get("gpu")
            tid, tsecret = token["id"], token["secret"]
            lease_s = body.get("lease_s", LEASE_DEFAULT_S)
        except (KeyError, TypeError, AttributeError) as e:
            self.reply(400, {"error": f"expected {{provider, token: {{id, secret}}, gpu, lease_s?}}: {e!r}"})
            return
        if provider != "modal" or gpu not in GPUS or not isinstance(tid, str) or not isinstance(tsecret, str) or not tid or not tsecret:
            self.reply(400, {"error": f"provider must be modal, gpu one of {GPUS}, token id/secret non-empty strings"})
            return
        if isinstance(lease_s, bool) or not isinstance(lease_s, int) or not LEASE_MIN_S <= lease_s <= LEASE_MAX_S:
            self.reply(400, {"error": f"lease_s must be whole seconds in {LEASE_MIN_S}..{LEASE_MAX_S}, got {lease_s!r}"})
            return
        with LOCK:
            if len(SESSIONS) >= MAX_SESSIONS:
                self.reply(429, {"error": f"connect_dev.py holds at most {MAX_SESSIONS} sessions; restart it"})
                return
            now = time.time()
            session = Session(f"fake-{secrets.token_hex(4)}", f"{tid}:{tsecret}", gpu, now, now + lease_s)
            SESSIONS[session.id] = session
        session.emit("status", status=session.status())
        threading.Thread(target=boot, args=(session, self.machine), daemon=True).start()
        self.reply(202, {"session_id": session.id, "status": session.status()})

    def do_GET(self) -> None:
        parts, query = self.route()
        if len(parts) == 2 and parts[0] == "sessions":
            if (session := self.session(parts[1], query)) is not None:
                self.reply(200, {"session_id": session.id, "status": session.status()})
        elif len(parts) == 3 and parts[0] == "sessions" and parts[2] == "events":
            if (session := self.session(parts[1], query)) is not None:
                self.events(session)
        else:
            self.reply(404, {"error": f"no route GET {self.path}"})

    def events(self, session: Session) -> None:
        last = self.headers.get("Last-Event-ID")
        sent = int(last) + 1 if last is not None and last.isdigit() else 0
        self.send_response(200)
        self.cors()
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        try:
            while (batch := next_batch(session, sent)) is not None:
                if not batch:
                    self.wfile.write(b": ping\n\n")
                for event in batch:
                    self.wfile.write(f"id: {sent}\ndata: {json.dumps(event)}\n\n".encode())
                    sent += 1
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            return


def stop(signum: int, frame: object) -> None:
    raise KeyboardInterrupt


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8790)
    ap.add_argument("--boot-delay", type=float, default=0.6, help="seconds between fake boot steps")
    ap.add_argument("--root", type=Path, help="Jupyter's root_dir for every session, kept after it (default: a temp dir per session)")
    ap.add_argument("--persist", type=Path, help="$BLOGS_WS_PERSIST in the sandbox: where workspace.py keeps the workspace bundle")
    ap.add_argument("--attach-kernel", help="a running Jupyter's URL to report instead of starting one (needs --attach-token)")
    ap.add_argument("--attach-token")
    args = ap.parse_args()
    if (args.attach_kernel is None) != (args.attach_token is None):
        ap.error("--attach-kernel and --attach-token go together")
    if args.attach_kernel is None and importlib.util.find_spec("jupyter_server") is None:
        ap.error(f"{sys.executable} has no jupyter_server; from blogs/: uv run --project assay python connect_dev.py "
                 "(or uv run connect_dev.py, without the check core's deps)")
    for d in (args.root, args.persist):
        if d is not None:
            d.mkdir(parents=True, exist_ok=True)

    shim_dir = Path(tempfile.mkdtemp(prefix="connect-dev-shim-"))
    smi = shim_dir / "nvidia-smi"
    smi.write_text(FAKE_SMI)
    smi.chmod(0o755)
    root = args.root.resolve() if args.root else None
    persist = args.persist.resolve() if args.persist else None
    attach = {"url": args.attach_kernel.rstrip("/"), "token": args.attach_token} if args.attach_kernel else None
    Handler.machine = Machine(shim_dir, args.boot_delay, root, persist, attach)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    server.daemon_threads = True
    signal.signal(signal.SIGTERM, stop)
    print(f"fake gateway on http://localhost:{args.port} (connect_dev.py; Ctrl-C ends every session)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        for session in list(SESSIONS.values()):
            session.end("stopped")
        shutil.rmtree(shim_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
