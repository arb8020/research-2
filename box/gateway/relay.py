"""The relay: box/CONTRACT-gateway.md over the box SDK, variant (A). The machine owns the session.

    cd box && uv run python -m box.gateway.relay [--port 8790] [--gpus T4] [--label box.purpose=reader-path-dev]

A browser cannot call Modal (gRPC, no CORS), so this does it for the reader, with the reader's token,
per request. What it keeps:
- nothing about a running session: GET /sessions/{id} and the event stream ask the machine (box.attach
  by session id, Session.status(), the Jupyter service's logs) every time. Restart the relay, or run
  two: a session still answers. Once the machine is gone they answer from the session's record (box
  launch(record=): status and logs in a store in the reader's workspace, a Modal Volume): why it
  ended, and its log, after the fact.
- while a session boots (POST /sessions returns 202 at once; the boot runs on a thread): its progress
  ("step" events), in memory, and dropped BOOT_RECORD_S after the boot ends. Rebuildable: after it is
  dropped, the machine answers instead.
- the reader's token only for the length of one request, or of the boot thread. A boot record keeps a
  digest of it, to check the caller of GET/events is the one who booted it.

    POST /sessions                {provider, token, gpu, labels}  -> 202 {session_id, status}
    GET  /sessions/{id}           X-Box-Token: id:secret          -> {session_id, status} | 404
    POST /sessions/{id}/end       X-Box-Token                     -> {session_id, status}
    GET  /sessions/{id}/events    ?token=id:secret (EventSource)  -> SSE: step | log | status

The session's machine runs one job, a service: Jupyter Server on PORT, behind box's expose(PORT) (on
Modal an encrypted tunnel). Its token is derived, never stored: HMAC(reader's token secret, session
id), so any relay holding the reader's token can say it again. Once Jupyter answers, the relay
releases the session's lease: the supervisor then ends it when idle (no connection to the port for
idle_timeout_s), at its deadline, or on POST /end. Nothing here holds a session open.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import hmac
import json
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, urlsplit

from box import sdk
from box.modal_provider import ModalToken
from box.sdk import Booting, Ended, Running
from box.store import Store

HERE = Path(__file__).parent
KERNEL_IMAGE = str(HERE / "kernel.Dockerfile")
PORT = 8888  # Jupyter Server, on the machine
LABEL_GPU = "relay.gpu"  # what the session was launched with, so a stateless GET can say it
LABEL_PORT = "relay.port"
DEADLINE_S = 20 * 60  # the session's lifetime; box adds a 10 min provider backstop (30 min hard stop)
IDLE_TIMEOUT_S = 5 * 60  # no connection to Jupyter (the page keeps a websocket open) for this long ends it
BOOT_TIMEOUT_S = 10 * 60  # sandbox scheduled + supervisor up (a cold image build happens before, in create)
JUPYTER_READY_S = 3 * 60  # Jupyter answering, after the supervisor is up
BOOT_RECORD_S = 10 * 60  # how long a finished boot's steps stay replayable from memory
MAX_BOOTS = 16  # boot records held at once (booting + recently finished); more is 429
MAX_STREAMS = 32  # open event streams; more is 429
MAX_BODY = 8 * 1024
MAX_LABELS = 8
MAX_BOOT_EVENTS = 1000  # a boot's own steps + Jupyter's startup log; past this, lines are counted, not kept
STREAM_POLL_S = 2.0  # how often an event stream asks the machine (each ask: ~4 provider calls)
SSE_PING_S = 15.0
PROBE_TIMEOUT_S = 5.0
CLOSE_TIMEOUT_S = 60.0
RECORD_LANDING_S = 30.0  # a gone machine's record may say Running for its heartbeat TTL (~10 s)
# The supervisor's end reasons, in the contract's words. released: nobody holds the lease and the
# Jupyter service exited, so the kernel the page used is gone ("the machine went away").
REASONS = {"stopped": "stopped", "deadline": "deadline", "idle": "idle", "lease_lost": "lease_lost",
           "released": "machine_lost", "machine_lost": "machine_lost"}  # fmt: skip
RECORD_VOLUME = "box-sessions"  # a Modal Volume in the reader's workspace: every session's record
LOCAL_ORIGIN = r"https?://(localhost|127\.0\.0\.1)(:\d+)?"


@dataclass(frozen=True)
class Access:
    """What a reader's token reaches: machines, and the store their sessions are recorded in."""

    provider: sdk.Provider
    record: Store


@dataclass(frozen=True)
class Config:
    """How sessions are made. access(token) is the one place a provider and store are built (Modal
    in production, Local + a directory in tests); python/ip/port() say how Jupyter runs there."""

    access: Callable[[ModalToken], Access]
    image: str | None
    gpus: tuple[str | None, ...]  # what POST /sessions may ask for (spend control)
    labels: dict[str, str]  # stamped on every session (e.g. box.purpose, for sweeps)
    origins: re.Pattern[str]  # page origins allowed (CORS here, allow_origin in Jupyter)
    python: str = "python3"  # on the machine
    ip: str = "0.0.0.0"  # Jupyter's bind address on the machine
    port: Callable[[], int] = lambda: PORT
    deadline_s: int = DEADLINE_S
    idle_timeout_s: float = IDLE_TIMEOUT_S


@dataclass(frozen=True)
class CreateRequest:
    token: ModalToken
    gpu: str | None
    labels: dict[str, str]


@dataclass
class Boot:
    """A boot in progress (or just finished): what the stream replays until the machine answers.
    Every change goes through emit()/finish(), under `changed`."""

    session_id: str
    token_digest: str
    gpu: str | None
    created_at: float
    deadline_at: float
    events: list[dict[str, Any]] = field(default_factory=list)
    dropped: int = 0
    status: dict[str, Any] | None = None  # the latest status event's
    log_offsets: tuple[int, int] = (0, 0)  # Jupyter's (stdout, stderr) bytes already in events
    ended_at: float | None = None  # monotonic; set once the boot is over (running or failed)
    cancelled: bool = False
    changed: threading.Condition = field(default_factory=threading.Condition)

    def emit(self, kind: str, **fields: Any) -> None:
        with self.changed:
            if len(self.events) >= MAX_BOOT_EVENTS and kind == "log":
                self.dropped += 1
                return
            assert len(self.events) < MAX_BOOT_EVENTS + 64, f"{self.session_id}: {len(self.events)} boot events"
            self.events.append({"t": time.time(), "kind": kind, **fields})
            if kind == "status":
                self.status = fields["status"]
            self.changed.notify_all()

    def step(self, source: str, text: str) -> None:
        self.emit("step", source=source, text=text)

    def finish(self, status: dict[str, Any]) -> None:
        if self.dropped:
            self.step("gateway", f"({self.dropped} more boot log lines not kept)")
        self.emit("status", status=status)
        with self.changed:
            self.ended_at = time.monotonic()
            self.changed.notify_all()


BOOTS: dict[str, Boot] = {}
BOOTS_LOCK = threading.Lock()
STREAMS = threading.BoundedSemaphore(MAX_STREAMS)


class BadRequest(Exception):
    """The caller sent something this API does not take (400)."""


# ---- parsing the browser's input (a boundary) ----


def parse_token(raw: str) -> ModalToken:
    """'id:secret', as X-Box-Token and ?token= carry it."""
    token_id, sep, secret = raw.partition(":")
    if not sep or not token_id or not secret:
        raise BadRequest("token must be 'id:secret' (X-Box-Token header, or ?token= on /events)")
    return ModalToken(token_id, secret)


def parse_create(body: bytes, gpus: tuple[str | None, ...]) -> CreateRequest:
    try:
        raw = json.loads(body)
    except ValueError as e:
        raise BadRequest(f"body is not JSON: {e}") from None
    if not isinstance(raw, dict) or raw.get("provider") != "modal":
        raise BadRequest("expected {provider: 'modal', token: {id, secret}, gpu, labels?}")
    token, gpu, labels = raw.get("token"), raw.get("gpu"), raw.get("labels") or {}
    if not (isinstance(token, dict) and isinstance(token.get("id"), str) and isinstance(token.get("secret"), str)):
        raise BadRequest("token must be {id: string, secret: string}")
    if not token["id"] or not token["secret"]:
        raise BadRequest("token id and secret must be non-empty")
    if gpu not in gpus:
        raise BadRequest(f"gpu must be one of {list(gpus)} on this relay, got {gpu!r}")
    if not (isinstance(labels, dict) and all(isinstance(k, str) and isinstance(v, str) for k, v in labels.items())):
        raise BadRequest("labels must be {string: string}")
    if len(labels) > MAX_LABELS:
        raise BadRequest(f"at most {MAX_LABELS} labels")
    if mine := [k for k in labels if k.startswith(("box.by", "box.session", "box.deadline", "relay."))]:
        raise BadRequest(f"labels {mine} are set by box or the relay")
    return CreateRequest(ModalToken(token["id"], token["secret"]), gpu, labels)


def kernel_token(token: ModalToken, session_id: str) -> str:
    """Jupyter's token for this session: anyone with the reader's token can derive it again; it
    reveals nothing about the reader's token (it appears in the page's URLs)."""
    return hmac.new(token.secret.encode(), f"jupyter:{session_id}".encode(), hashlib.sha256).hexdigest()[:48]


def digest(token: ModalToken) -> str:
    return hashlib.sha256(f"{token.id}:{token.secret}".encode()).hexdigest()


# ---- the contract's status object ----


def wire(state: str, gpu: str | None, started_at: float, deadline: float, **extra: Any) -> dict[str, Any]:
    return {"state": state, "gpu": gpu, "started_at": started_at, "deadline": deadline, **extra}


def machine_status(cfg: Config, s: sdk.Session, token: ModalToken, *, ready: bool) -> dict[str, Any]:
    """What the machine says, in the contract's words. ready: Jupyter is known to answer (else it
    is probed: running means the kernel is reachable, not just the supervisor up)."""
    labels = s.machine.labels
    gpu = labels.get(LABEL_GPU) or None
    deadline = float(labels[sdk.LABEL_DEADLINE])
    match s.status():
        case Booting():
            return wire("booting", gpu, time.time(), deadline)
        case Running() if isinstance(s.machine, sdk.Lost):  # gone; its record's end is still landing
            return machine_status(cfg, s, token, ready=ready) if wait_out(s) else wire("ended", gpu, deadline - cfg.deadline_s, deadline, reason="machine_lost")
        case Running(started_at=started_at, deadline_at=deadline_at):
            kernel = {"url": s.expose(int(labels[LABEL_PORT])).url, "token": kernel_token(token, s.id)}
            up = ready or jupyter_ready(kernel)
            return wire("running" if up else "booting", gpu, started_at, deadline_at, **({"kernel": kernel} if up else {}))
        case Ended(reason=reason):
            # times only matter while it runs (the pill's uptime); the label's deadline stands in for both
            return wire("ended", gpu, deadline - cfg.deadline_s, deadline, reason=REASONS[reason])


def wait_out(s: sdk.Session) -> bool:
    """A gone machine whose record still says Running: wait() waits out the record's heartbeat TTL
    (seconds) for the recorded end. True once status() says Ended."""
    with contextlib.suppress(TimeoutError):
        s.wait(timeout_s=RECORD_LANDING_S)
    return isinstance(s.status(), Ended)


def jupyter_ready(kernel: dict[str, str]) -> bool:
    """Does Jupyter answer at kernel.url with kernel.token? (Before it listens, Modal's tunnel says 502.)"""
    url = f"{kernel['url']}/api/status?token={quote(kernel['token'])}"
    try:
        with urllib.request.urlopen(url, timeout=PROBE_TIMEOUT_S) as r:
            return r.status == 200
    except urllib.error.HTTPError as e:
        if e.code == 403:
            raise RuntimeError(f"Jupyter at {kernel['url']} refused the session's derived token") from e
        return False
    except (urllib.error.URLError, ConnectionError, TimeoutError):
        return False


def attach(cfg: Config, token: ModalToken, sid: str) -> sdk.Session:
    """The session, live or (machine gone) from its record. LookupError (404) if neither knows it."""
    access = cfg.access(token)
    return sdk.attach(access.provider, sid, record=access.record)


def the_kernel_job(s: sdk.Session) -> sdk.Job:
    """The relay gives each session exactly one job: its Jupyter service."""
    jobs = s.jobs()
    if len(jobs) != 1:
        raise RuntimeError(f"{s.id}: expected the one Jupyter service job, found {len(jobs)}")
    return jobs[0]


# ---- boot (a thread per POST /sessions) ----


class Stepping:
    """A provider that says when its machine exists: create returns after the image is built (a
    cold build is minutes), the supervisor comes up later (Modal schedules the sandbox)."""

    def __init__(self, inner: sdk.Provider, boot: Boot) -> None:
        self.inner, self.boot, self.name = inner, boot, inner.name

    def launch(self, **kw: Any) -> sdk.Machine:
        t0 = time.monotonic()
        machine = self.inner.launch(**kw)
        self.boot.step("gateway", f"sandbox {machine.id} created in {time.monotonic() - t0:.1f} s; waiting for it to start")
        return machine

    def __getattr__(self, attr: str) -> Any:
        return getattr(self.inner, attr)


def jupyter_cmd(cfg: Config, port: int, origin: str) -> str:
    """Jupyter Server as the session's service. allow_origin: the page that connected (its fetches
    and websocket are cross-origin); the token guards every request; xsrf is off because the page
    sends the token on each one. Pings keep a quiet kernel websocket alive through the tunnel."""
    settings = {"websocket_ping_interval": 20}
    return " ".join([
        "exec", cfg.python, "-m", "jupyter_server", "--no-browser", "--allow-root", f"--ip={cfg.ip}", f"--port={port}",
        '--ServerApp.root_dir="$BOX_JOB_DIR"', f"--ServerApp.allow_origin='{origin}'", "--ServerApp.allow_remote_access=True",
        "--ServerApp.disable_check_xsrf=True", f'--ServerApp.tornado_settings="{settings}"',
    ])  # fmt: skip


def boot(cfg: Config, rec: Boot, req: CreateRequest, origin: str) -> None:
    """Launch, start Jupyter, wait until it answers, release. The token lives on this stack only."""
    t0 = time.monotonic()
    session: sdk.Session | None = None
    try:
        rec.step("gateway", "checking your Modal token")
        access = cfg.access(req.token)
        access.provider.list({sdk.LABEL_SESSION: rec.session_id})  # the first authenticated call: a bad token fails here
        port = cfg.port()
        rec.step("gateway", f"creating sandbox: gpu {rec.gpu or 'none'} (a workspace's first connect builds the image: minutes)")
        session = sdk.launch(
            Stepping(access.provider, rec), session_id=rec.session_id, record=access.record, deadline_s=cfg.deadline_s, gpu=rec.gpu, image=cfg.image,
            labels={**cfg.labels, **req.labels, LABEL_GPU: rec.gpu or "", LABEL_PORT: str(port)},
            idle_timeout_s=cfg.idle_timeout_s, boot_timeout_s=BOOT_TIMEOUT_S, ports=(port,),
        )  # fmt: skip
        rec.step("machine", f"supervisor up ({time.monotonic() - t0:.1f} s since connect)")
        if rec.cancelled:
            raise Cancelled
        job = session.run(jupyter_cmd(cfg, port, origin), service=True, env={"JUPYTER_TOKEN": kernel_token(req.token, rec.session_id)})
        rec.step("machine", "starting Jupyter Server")
        endpoint = session.expose(port)
        rec.step("gateway", f"tunnel open: {endpoint.url}")
        kernel = {"url": endpoint.url, "token": kernel_token(req.token, rec.session_id)}
        wait_for_jupyter(rec, job, kernel)
        if rec.cancelled:
            raise Cancelled
        session.release()  # from here the supervisor alone ends it: idle, deadline, or POST /end
        running = session.status()
        assert isinstance(running, Running), running
        rec.step("machine", f"Jupyter Server ready ({time.monotonic() - t0:.1f} s since connect)")
        rec.finish(wire("running", rec.gpu, running.started_at, running.deadline_at, kernel=kernel))
    except Cancelled:
        rec.step("gateway", "ended while booting")
        end_quietly(session)
        rec.finish(wire("ended", rec.gpu, rec.created_at, rec.deadline_at, reason="stopped"))
    except Exception as e:  # noqa: BLE001 (any failure ends the boot; the reader sees why)
        if rec.cancelled:  # POST /end closed the machine under us: that is the end, not a failure
            rec.step("gateway", "ended while booting")
            rec.finish(wire("ended", rec.gpu, rec.created_at, rec.deadline_at, reason="stopped"))
            return
        print(f"relay: boot {rec.session_id} failed: {e!r}", file=sys.stderr)
        rec.step("gateway", f"boot failed: {type(e).__name__}: {e}")
        end_quietly(session)
        rec.finish(wire("ended", rec.gpu, rec.created_at, rec.deadline_at, reason="boot_failed"))


class Cancelled(Exception):
    """POST /end arrived while the session booted."""


def end_quietly(session: sdk.Session | None) -> None:
    if session is None:
        return  # launch never returned: it terminates what it made on its own failures
    try:
        session.close(timeout_s=CLOSE_TIMEOUT_S)
    except Exception as e:  # noqa: BLE001 (the boot already failed; this is cleanup, and says so)
        print(f"relay: closing {session.id} after a failed boot: {e!r}", file=sys.stderr)


def wait_for_jupyter(rec: Boot, job: sdk.Job, kernel: dict[str, str]) -> None:
    """Until Jupyter answers; its log goes to the boot's events meanwhile. Raises if it exits first."""
    give_up = time.monotonic() + JUPYTER_READY_S
    while not jupyter_ready(kernel):
        forward_logs(rec, job)
        if job.done():
            raise RuntimeError(f"Jupyter Server exited: {job.status()}")
        if rec.cancelled:
            raise Cancelled
        if time.monotonic() > give_up:
            raise TimeoutError(f"Jupyter Server not answering after {JUPYTER_READY_S} s")
        time.sleep(1.0)
    forward_logs(rec, job)


def forward_logs(rec: Boot, job: sdk.Job) -> None:
    for stream, text, offsets in log_lines(job, rec.log_offsets):
        rec.emit("log", source="machine", stream=stream, text=text)
        rec.log_offsets = offsets


def log_lines(job: sdk.Job, start: tuple[int, int]) -> Iterator[tuple[str, str, tuple[int, int]]]:
    """The job's output after `start`, a line per item, with the offsets just past it."""
    out, err = start
    for stream, chunk in job.logs(start=start):
        for line in chunk.splitlines(keepends=True):
            if stream == "stdout":
                out += len(line.encode())
            else:
                err += len(line.encode())
            yield stream, line.rstrip("\n"), (out, err)


# ---- HTTP ----


class Handler(BaseHTTPRequestHandler):
    server_version = "box-relay/0"
    protocol_version = "HTTP/1.1"
    cfg: Config

    def log_message(self, fmt: str, *args: Any) -> None:
        pass  # one wide line per request instead (wide()); never a query string (tokens)

    def wide(self, code: int, t0: float, **fields: Any) -> None:
        event = {"t": round(time.time(), 3), "method": self.command, "path": urlsplit(self.path).path, "code": code,
                 "ms": round(1000 * (time.monotonic() - t0)), **fields}  # fmt: skip
        sys.stderr.write(json.dumps(event) + "\n")

    def cors(self) -> None:
        origin = self.headers.get("Origin", "")
        if self.cfg.origins.fullmatch(origin):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Box-Token, Last-Event-ID")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")

    def reply(self, code: int, body: dict[str, Any]) -> None:
        data = json.dumps(body).encode()
        self.send_response(code)
        self.cors()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:
        self.dispatch()

    def do_POST(self) -> None:
        self.dispatch()

    def dispatch(self) -> None:
        t0 = time.monotonic()
        url = urlsplit(self.path)
        parts = [p for p in url.path.split("/") if p]
        route = (self.command, len(parts), parts[2] if len(parts) == 3 else None)
        sid = parts[1] if len(parts) >= 2 and parts[0] == "sessions" else None
        try:
            if route == ("POST", 1, None) and parts == ["sessions"]:
                code, body = self.create()
            elif sid is not None and route == ("GET", 2, None):
                code, body = self.get(sid, parse_token(self.headers.get("X-Box-Token", "")))
            elif sid is not None and route == ("POST", 3, "end"):
                code, body = self.end(sid, parse_token(self.headers.get("X-Box-Token", "")))
            elif sid is not None and route == ("GET", 3, "events"):
                token = parse_token((parse_qs(url.query).get("token") or [""])[0])
                self.wide(200, t0, session=sid, sent=self.events(sid, token))
                return
            else:
                code, body = 404, {"error": f"no route {self.command} {url.path}"}
        except BadRequest as e:
            code, body = 400, {"error": str(e)}
        except LookupError as e:
            code, body = 404, {"error": str(e)}
        except Exception as e:  # noqa: BLE001 (the page shows the reason; the wide line has it too)
            code, body = 502, {"error": f"{type(e).__name__}: {e}"}
        self.reply(code, body)
        self.wide(code, t0, session=sid or body.get("session_id"), **({"error": body["error"]} if "error" in body else {}))

    def create(self) -> tuple[int, dict[str, Any]]:
        length = int(self.headers.get("Content-Length", "0"))
        if length > MAX_BODY:
            raise BadRequest(f"body over {MAX_BODY} bytes")
        req = parse_create(self.rfile.read(length), self.cfg.gpus)
        origin = self.headers.get("Origin", "")
        if origin and not self.cfg.origins.fullmatch(origin):
            raise BadRequest(f"origin {origin!r} is not one this relay serves")
        now = time.time()
        rec = Boot(sdk.new_session_id(), digest(req.token), req.gpu, now, now + self.cfg.deadline_s)
        with BOOTS_LOCK:
            forget_old_boots()
            if len(BOOTS) >= MAX_BOOTS:
                return 429, {"error": f"{MAX_BOOTS} sessions booting or just booted on this relay; try again in a minute"}
            BOOTS[rec.session_id] = rec
        rec.emit("status", status=wire("booting", req.gpu, rec.created_at, rec.deadline_at))
        threading.Thread(target=boot, args=(self.cfg, rec, req, origin), daemon=True, name=f"boot-{rec.session_id}").start()
        return 202, {"session_id": rec.session_id, "status": rec.status}

    def get(self, sid: str, token: ModalToken) -> tuple[int, dict[str, Any]]:
        rec = booting(sid, token)
        if rec is not None and rec.ended_at is None:
            return 200, {"session_id": sid, "status": rec.status}
        if rec is not None and rec.status is not None and rec.status["state"] == "ended":
            return 200, {"session_id": sid, "status": rec.status}  # a failed boot: no machine to ask
        s = attach(self.cfg, token, sid)
        return 200, {"session_id": sid, "status": machine_status(self.cfg, s, token, ready=False)}

    def end(self, sid: str, token: ModalToken) -> tuple[int, dict[str, Any]]:
        rec = booting(sid, token)
        if rec is not None and rec.ended_at is None:
            rec.cancelled = True  # the boot thread ends it at its next step (launch itself can't be interrupted)
        try:
            s = attach(self.cfg, token, sid)
        except LookupError:
            if rec is None:
                raise
            return 200, {"session_id": sid, "status": wire("ended", rec.gpu, rec.created_at, rec.deadline_at, reason="stopped")}
        gpu = s.machine.labels.get(LABEL_GPU) or None
        deadline = float(s.machine.labels[sdk.LABEL_DEADLINE])
        s.close(timeout_s=CLOSE_TIMEOUT_S)
        ended = s.status()
        assert isinstance(ended, Ended), ended
        return 200, {"session_id": sid, "status": wire("ended", gpu, deadline - self.cfg.deadline_s, deadline, reason=REASONS[ended.reason])}

    # -- the event stream --

    def events(self, sid: str, token: ModalToken) -> int:
        """SSE: the boot's events from memory (ids b<n>), then the machine's (ids m<out>.<err>, the
        Jupyter log's byte offsets): its log and its status whenever that changes. Ends after an
        ended status. Last-Event-ID resumes either part. Returns how many events it sent."""
        rec = booting(sid, token)
        if rec is None:
            attach(self.cfg, token, sid)  # 404 before the stream starts, as GET /sessions/{id}
        if not STREAMS.acquire(blocking=False):
            self.reply(429, {"error": f"{MAX_STREAMS} event streams open on this relay"})
            return 0
        try:
            self.send_response(200)
            self.cors()
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            stream = Stream(self, 0)
            last = self.headers.get("Last-Event-ID", "")
            boot_from = int(last[1:]) + 1 if re.fullmatch(r"b\d+", last) else 0
            offsets = tuple(map(int, last[1:].split("."))) if re.fullmatch(r"m\d+\.\d+", last) else None
            if rec is not None and offsets is None:
                last_status = stream.replay_boot(rec, boot_from)
                if last_status is None or last_status["state"] == "ended":
                    return stream.sent
                offsets = rec.log_offsets
            else:
                last_status = None
            stream.follow_machine(self.cfg, attach(self.cfg, token, sid), token, offsets or (0, 0), last_status)
        except (BrokenPipeError, ConnectionResetError):
            pass  # the tab went away
        except Exception as e:  # noqa: BLE001 (headers are sent: all that is left is to say so and close)
            print(f"relay: event stream {sid} broke: {e!r}", file=sys.stderr)
        finally:
            STREAMS.release()
        return stream.sent


@dataclass
class Stream:
    handler: Handler
    sent: int
    last_write: float = field(default_factory=time.monotonic)

    def send(self, event_id: str, event: dict[str, Any]) -> None:
        self.handler.wfile.write(f"id: {event_id}\ndata: {json.dumps(event)}\n\n".encode())
        self.handler.wfile.flush()
        self.sent += 1
        self.last_write = time.monotonic()

    def ping(self) -> None:
        if time.monotonic() - self.last_write >= SSE_PING_S:
            self.handler.wfile.write(b": ping\n\n")
            self.handler.wfile.flush()
            self.last_write = time.monotonic()

    def replay_boot(self, rec: Boot, start: int) -> dict[str, Any] | None:
        """The boot's events from index start, live until the boot ends. Returns its last status."""
        i = start
        while True:
            with rec.changed:
                if i >= len(rec.events) and rec.ended_at is None:
                    rec.changed.wait(SSE_PING_S)
                batch, over = rec.events[i:], rec.ended_at is not None
            for event in batch:
                self.send(f"b{i}", event)
                i += 1
            if over and i >= len(rec.events):
                return rec.status
            self.ping()

    def replay_record(self, cfg: Config, s: sdk.Session, token: ModalToken, offsets: tuple[int, int]) -> None:
        """A session whose machine is gone: its recorded Jupyter log past offsets (bytes of stdout,
        stderr this stream already sent), then its (ended) status."""
        assert s.record is not None, "relay sessions are always recorded"
        record = sdk.read_record(s.record, s.id)
        seen = dict(zip(("stdout", "stderr"), offsets, strict=True))
        read = {"stdout": 0, "stderr": 0}
        for job_id in record.jobs():
            for n, stream, chunk in record.logs(job_id):
                for line in chunk.splitlines(keepends=True):
                    read[stream] += len(line.encode())
                    if read[stream] > seen[stream]:
                        self.send(f"r{n}", {"t": time.time(), "kind": "log", "source": "machine", "stream": stream, "text": line.rstrip("\n")})
        self.send("r-end", {"t": time.time(), "kind": "status", "status": machine_status(cfg, s, token, ready=False)})

    def follow_machine(self, cfg: Config, s: sdk.Session, token: ModalToken, offsets: tuple[int, int], last: dict[str, Any] | None) -> None:
        """The machine's word until it ends: Jupyter's log, and its status when it changes. Bounded
        by the session's deadline (plus the provider's backstop), like Session.wait()."""
        if isinstance(s.machine, sdk.Lost):
            self.replay_record(cfg, s, token, offsets)
            return
        job = the_kernel_job(s)
        ready = last is not None and last["state"] == "running"
        while True:
            try:
                lines = list(log_lines(job, offsets))
            except sdk.Gone:
                lines = []  # it ended under us: the status below says how
            for stream, text, offsets in lines:
                self.send(f"m{offsets[0]}.{offsets[1]}", {"t": time.time(), "kind": "log", "source": "machine", "stream": stream, "text": text})
            status = machine_status(cfg, s, token, ready=ready)
            ready = status["state"] == "running"
            if status != last:
                self.send(f"m{offsets[0]}.{offsets[1]}", {"t": time.time(), "kind": "status", "status": status})
                last = status
            if status["state"] == "ended":
                return
            with contextlib.suppress(TimeoutError):
                s.wait(timeout_s=STREAM_POLL_S)  # keeps the machine lingering for us, so we read why it ended
            self.ping()


def booting(sid: str, token: ModalToken) -> Boot | None:
    """This relay's boot record for sid, if it has one and the caller's token booted it."""
    with BOOTS_LOCK:
        rec = BOOTS.get(sid)
    if rec is None or not hmac.compare_digest(rec.token_digest, digest(token)):
        return None
    return rec


def forget_old_boots() -> None:
    """Under BOOTS_LOCK: drop boot records BOOT_RECORD_S after their boot ended (the machine answers now)."""
    now = time.monotonic()
    for sid in [sid for sid, r in BOOTS.items() if r.ended_at is not None and now - r.ended_at > BOOT_RECORD_S]:
        del BOOTS[sid]


# ---- main ----


def modal_access(token: ModalToken, region: str) -> Access:
    from box.modal_provider import Modal, ModalVolumeStore

    provider = Modal(token=token, region=region)
    return Access(provider, ModalVolumeStore(RECORD_VOLUME, client=provider.client))


def modal_config(a: argparse.Namespace, gpus: tuple[str | None, ...]) -> Config:
    return Config(
        access=lambda token: modal_access(token, a.region), image=KERNEL_IMAGE, gpus=gpus, labels=dict(a.label),
        origins=re.compile(LOCAL_ORIGIN), deadline_s=a.deadline_s, idle_timeout_s=a.idle_timeout_s,
    )  # fmt: skip


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request: Any, client_address: Any) -> None:
        if isinstance(sys.exc_info()[1], ConnectionError):
            return  # a browser closing a kept-alive connection between requests: not an error
        super().handle_error(request, client_address)


def serve(cfg: Config, port: int) -> ThreadingHTTPServer:
    handler = type("Handler", (Handler,), {"cfg": cfg})
    server = Server(("127.0.0.1", port), handler)
    return server


def label(raw: str) -> tuple[str, str]:
    key, sep, value = raw.partition("=")
    if not sep or not key:
        raise argparse.ArgumentTypeError(f"--label takes key=value, got {raw!r}")
    return key, value


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8790)
    ap.add_argument("--gpus", default="T4", help="comma-separated GPUs a reader may ask for (CPU, gpu null, always)")
    ap.add_argument("--region", default="us", help="Modal region for every session")
    ap.add_argument("--deadline-s", type=int, default=DEADLINE_S, help="a session's lifetime (box adds a 600 s provider backstop)")
    ap.add_argument("--idle-timeout-s", type=float, default=IDLE_TIMEOUT_S, help="no connection to Jupyter for this long ends a session")
    ap.add_argument("--label", type=label, action="append", default=[("box.purpose", "reader-path-dev")],
                    help="key=value stamped on every session (default box.purpose=reader-path-dev, for sweeps)")  # fmt: skip
    a = ap.parse_args()
    gpus = (None, *[g for g in a.gpus.split(",") if g])
    assert a.deadline_s + 600 <= 24 * 3600, "Modal caps a sandbox at 24 h"
    cfg = modal_config(a, gpus)
    server = serve(cfg, a.port)
    print(f"relay on http://localhost:{a.port} (modal, region {a.region}, gpus {list(gpus)}, labels {dict(a.label)}, "
          f"deadline {a.deadline_s} s, idle {a.idle_timeout_s} s)", flush=True)  # fmt: skip
    with contextlib.suppress(KeyboardInterrupt):  # sessions outlive the relay: idle/deadline end them
        server.serve_forever()


if __name__ == "__main__":
    main()
