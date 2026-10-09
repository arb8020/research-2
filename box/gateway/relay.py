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
- the reader's token inside the Modal client it makes for that reader (a gRPC channel), reused across
  requests and closed once idle for CLIENT_IDLE_S or when MAX_CLIENTS readers' clients are open (the
  least recently used first). A boot record keeps a digest of it, to check the caller of GET/events
  is the one who booted it.

A Relay owns all of that (boots and their threads, event streams, clients); Handler is HTTP only.

    POST /sessions                {provider, token, gpu, labels}  -> 202 {session_id, status}
    GET  /sessions/{id}           X-Box-Token: id:secret          -> {session_id, status} | 404
    POST /sessions/{id}/end       X-Box-Token                     -> {session_id, status}
    GET  /sessions/{id}/events    ?token=id:secret (EventSource)  -> SSE: step | log | status

The session's machine runs one service (Session.serve): Jupyter Server on PORT, behind box's expose(PORT) (on
Modal an encrypted tunnel). Its token is derived, never stored: HMAC(reader's token secret, session
id), so any relay holding the reader's token can say it again. Once Jupyter answers, the relay
releases the session's lease: the supervisor then ends it when idle (no connection to the port for
idle_timeout_s), at its deadline, or on POST /end. Nothing here holds a session open.
"""

from __future__ import annotations

import argparse
import contextlib
import functools
import hashlib
import hmac
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from collections import OrderedDict
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import TYPE_CHECKING, Any, BinaryIO
from urllib.parse import parse_qs, quote, urlsplit

from box import sdk
from box.providers.modal import ModalToken
from box.sdk import Booting, Done, Ended, Queued, Running
from box.store import Store

if TYPE_CHECKING:
    from box.gateway.push import Push

HERE = Path(__file__).parent
KERNEL_IMAGE = str(HERE / "kernel.Dockerfile")
PORT = 8888  # Jupyter Server, on the machine
LABEL_GPU = "relay.gpu"  # what the session was launched with, so a stateless GET can say it
LABEL_PORT = "relay.port"
DEADLINE_S = 20 * 60  # the session's lifetime; box adds a 10 min provider backstop (30 min hard stop)
IDLE_TIMEOUT_S = 5 * 60  # no connection to Jupyter (the page keeps a websocket open) for this long ends it
BOOT_TIMEOUT_S = 10 * 60  # sandbox scheduled + supervisor up (a cold image build happens before, in sdk.create)
JUPYTER_READY_S = 3 * 60  # Jupyter answering, after the supervisor is up
BOOT_RECORD_S = 10 * 60  # how long a finished boot's steps stay replayable from memory
MAX_BOOTS = 16  # boot records held at once (booting + recently finished); more is 429
MAX_STREAMS = 32  # open event streams; more is 429
MAX_CLIENTS = 64  # readers' Modal clients open at once; past it the least recently used idle one closes, and if all are in use, 429
CLIENT_IDLE_S = 10 * 60  # a reader's client unused this long is closed (and its token dropped)
MAX_BODY = 8 * 1024
MAX_LABELS = 8
MAX_BOOT_EVENTS = 1000  # a boot's own steps + Jupyter's startup log; past this, lines are counted, not kept
STREAM_POLL_S = 2.0  # how often an event stream asks the machine (once Jupyter answers, 2 provider calls: the session's status, the log)
SSE_PING_S = 15.0
PROBE_TIMEOUT_S = 5.0
CLOSE_TIMEOUT_S = 60.0
# The supervisor's end reasons, in the contract's words. released: nobody holds the lease and the
# Jupyter service exited, so the kernel the page used is gone ("the machine went away").
REASONS = {"stopped": "stopped", "deadline": "deadline", "idle": "idle", "lease_lost": "lease_lost",
           "released": "machine_lost", "machine_lost": "machine_lost"}  # fmt: skip
RECORD_VOLUME = "box-sessions"  # a Modal Volume in the reader's workspace: every session's record
LOCAL_ORIGIN = r"https?://(localhost|127\.0\.0\.1)(:\d+)?"


@dataclass(frozen=True)
class Access:
    """What a reader's token reaches: machines, and the store their sessions are recorded in.
    close: what it holds open (Modal's client); nothing for the local provider."""

    provider: sdk.Provider
    record: Store
    close: Callable[[], None] = lambda: None


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
    push: Push | None = None  # variants (B)/(C): boot events and a machine-side forwarder push to a fan-out (push.py)


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
    log_cursor: sdk.LogCursor = (0, 0)  # how much of Jupyter's log is already in events
    ended_at: float | None = None  # monotonic; set once the boot is over (running or failed)
    cancelled: bool = False
    changed: threading.Condition = field(default_factory=threading.Condition)
    push: Callable[[dict[str, Any]], None] | None = None  # each event, also to a fan-out (Push.send)

    def emit(self, kind: str, **fields: Any) -> None:
        with self.changed:
            if len(self.events) >= MAX_BOOT_EVENTS and kind == "log":
                self.dropped += 1
                return
            assert len(self.events) < MAX_BOOT_EVENTS + 64, f"{self.session_id}: {len(self.events)} boot events"
            event = {"t": time.time(), "kind": kind, **fields}
            self.events.append(event)
            if self.push is not None:
                self.push(event)
            if kind == "status":
                self.status = fields["status"]
            self.changed.notify_all()

    def step(self, source: str, text: str) -> None:
        self.emit("step", source=source, text=text)

    def cancel(self) -> None:
        """POST /end (or the relay closing): the boot thread ends the session at its next step."""
        with self.changed:
            self.cancelled = True
            self.changed.notify_all()

    def finish(self, status: dict[str, Any]) -> None:
        if self.dropped:
            self.step("gateway", f"({self.dropped} more boot log lines not kept)")
        self.emit("status", status=status)
        with self.changed:
            self.ended_at = time.monotonic()
            self.changed.notify_all()


class BadRequest(Exception):
    """The caller sent something this API does not take (400)."""


class Busy(Exception):
    """This relay is at one of its limits (boots, streams, readers' clients): 429, try again later."""


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
    if mine := [k for k in labels if k.startswith((*sdk.RESERVED, "relay."))]:
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
    # times only matter while it runs (the pill's uptime); once ended, the label's deadline stands in for both
    ended = functools.partial(wire, "ended", gpu, deadline - cfg.deadline_s, deadline)
    match s.status():
        case Booting():
            return wire("booting", gpu, time.time(), deadline)
        case Running() as running:
            try:
                return running_status(s, token, running, ready=ready, gpu=gpu, ended=ended)
            except sdk.Gone:  # it went after status() said Running; a machine gone is gone for good
                gone = s.status()
                assert isinstance(gone, Ended), f"{s.id}: {gone} once its machine is gone"
                return ended(reason=REASONS[gone.reason])
        case Ended(reason=reason):
            return ended(reason=REASONS[reason])


def running_status(  # noqa: PLR0913 (the session, what the supervisor said, how to say ended)
    s: sdk.Session, token: ModalToken, running: Running, *, ready: bool, gpu: str | None, ended: Callable[..., dict[str, Any]],
) -> dict[str, Any]:  # fmt: skip
    """A session whose supervisor runs: running once Jupyter answers; ended if Jupyter is done,
    though the supervisor may not have written why yet (the kernel the page used is gone, and
    nothing starts another); else still booting. Gone if the machine goes meanwhile."""
    kernel = {"url": s.expose(int(s.machine.labels[LABEL_PORT])).url, "token": kernel_token(token, s.id)}
    if ready or jupyter_ready(kernel):
        return wire("running", gpu, running.started_at, running.deadline_at, kernel=kernel)
    jupyter = kernel_service(s)
    match Queued() if jupyter is None else jupyter.status():
        case Done(ending=ending):  # the session's reason, or Jupyter's own end (then the session's is "released")
            return ended(reason=REASONS.get(ending.reason, REASONS["released"]))
    return wire("booting", gpu, running.started_at, running.deadline_at)


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


def kernel_service(s: sdk.Session) -> sdk.Job | None:
    """The session's Jupyter: its first service (with --push, the forwarder is the second). None
    before the boot has started it."""
    services = s.services()
    return services[0] if services else None


# ---- boot (a thread per POST /sessions) ----


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


def boot(cfg: Config, access: Access, rec: Boot, req: CreateRequest, origin: str) -> None:
    """Launch, start Jupyter, wait until it answers, release."""
    t0 = time.monotonic()
    session: sdk.Session | None = None
    try:
        rec.step("gateway", "checking your Modal token")
        access.provider.list({sdk.LABEL_SESSION: rec.session_id})  # the first authenticated call: a bad token fails here
        port = cfg.port()
        rec.step("gateway", f"creating sandbox: gpu {rec.gpu or 'none'} (a workspace's first connect builds the image: minutes)")
        created_at = time.monotonic()
        made = sdk.create(
            access.provider, session_id=rec.session_id, record=access.record, deadline_s=cfg.deadline_s, gpu=rec.gpu, image=cfg.image,
            labels={**cfg.labels, **req.labels, LABEL_GPU: rec.gpu or "", LABEL_PORT: str(port)},
            idle_timeout_s=cfg.idle_timeout_s, ports=(port,),
        )  # fmt: skip
        rec.step("gateway", f"sandbox {made.machine.id} created in {time.monotonic() - created_at:.1f} s; waiting for it to start")
        try:
            made.wait_up(BOOT_TIMEOUT_S)  # POST /end can't interrupt this: the boot ends at the next check
        except BaseException:
            made.machine.terminate()  # no supervisor up to end it (as launch does)
            raise
        made.hold()
        session = made
        rec.step("machine", f"supervisor up ({time.monotonic() - t0:.1f} s since connect)")
        if rec.cancelled:
            raise Cancelled
        job = session.serve(jupyter_cmd(cfg, port, origin), env={"JUPYTER_TOKEN": kernel_token(req.token, rec.session_id)})
        rec.step("machine", "starting Jupyter Server")
        endpoint = session.expose(port)
        rec.step("gateway", f"tunnel open: {endpoint.url}")
        kernel = {"url": endpoint.url, "token": kernel_token(req.token, rec.session_id)}
        wait_for_jupyter(rec, job, kernel)
        if rec.cancelled:
            raise Cancelled
        session.release()  # from here the supervisor alone ends it: idle, deadline, or POST /end
        running = session.status()
        if not isinstance(running, Running):  # it ended as it came up (its deadline, an idle timeout shorter than the boot)
            raise RuntimeError(f"{rec.session_id}: {running} as Jupyter came up")
        status = wire("running", rec.gpu, running.started_at, running.deadline_at, kernel=kernel)
        if cfg.push is not None:
            cmd, env = cfg.push.forwarder_service(rec.session_id, cfg.python, job.dir, rec.log_cursor, status, REASONS)
            session.serve(cmd, env=env)
            rec.step("machine", "forwarder started: the machine pushes its log to the fan-out from here")
        rec.step("machine", f"Jupyter Server ready ({time.monotonic() - t0:.1f} s since connect)")
        rec.finish(status)
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
        read = forward_logs(rec, job)
        if read.done:
            raise RuntimeError(f"Jupyter Server exited: {read.status}")
        if rec.cancelled:
            raise Cancelled
        if time.monotonic() > give_up:
            raise TimeoutError(f"Jupyter Server not answering after {JUPYTER_READY_S} s")
        time.sleep(1.0)
    forward_logs(rec, job)


def forward_logs(rec: Boot, job: sdk.Job) -> sdk.JobRead:
    """Jupyter's new output into the boot's events; returns what was read (its status too)."""
    read = job.read(rec.log_cursor)
    for stream, text, cursor in log_lines(read.chunks, rec.log_cursor):
        rec.emit("log", source="machine", stream=stream, text=text)
        rec.log_cursor = cursor
    return read


def log_lines(chunks: list[sdk.LogChunk], after: sdk.LogCursor) -> Iterator[tuple[str, str, sdk.LogCursor]]:
    """Chunks of output read past `after`, a line per item, with the cursor just past it."""
    out, err = after
    for chunk in chunks:
        for line in chunk.text.splitlines(keepends=True):
            if chunk.stream == "stdout":
                out += len(line.encode())
            else:
                err += len(line.encode())
            yield chunk.stream, line.rstrip("\n"), (out, err)


# ---- the relay: boots, streams, readers' clients ----


@dataclass
class Held:
    access: Access
    users: int = 0
    last_used: float = field(default_factory=time.monotonic)


class Accesses:
    """Each reader's Access (on Modal: a client, a gRPC channel), reused across that reader's
    requests, keyed by the token's digest. Bounded: at most `limit` open; past it the least recently
    used idle one is closed, and if none is idle, Busy. One unused for CLIENT_IDLE_S is closed at
    the next use of any. An Access in use is never closed under its user."""

    def __init__(self, make: Callable[[ModalToken], Access], limit: int) -> None:
        self._make = make
        self._limit = limit
        self._held: OrderedDict[str, Held] = OrderedDict()  # least recently used first
        self._lock = threading.Lock()

    @contextlib.contextmanager
    def use(self, token: ModalToken) -> Iterator[Access]:
        key = digest(token)
        with self._lock:
            evicted = self._evict(keep=key)
            held = self._held.get(key)
            if held is None and len(self._held) < self._limit:
                held = self._held[key] = Held(self._make(token))
            if held is not None:
                held.users += 1
                self._held.move_to_end(key)
        for h in evicted:
            h.access.close()
        if held is None:
            raise Busy(f"{self._limit} readers' clients in use on this relay")
        try:
            yield held.access
        finally:
            with self._lock:
                held.users -= 1
                held.last_used = time.monotonic()

    def _evict(self, keep: str) -> list[Held]:
        """Under _lock: take out the idle ones unused past CLIENT_IDLE_S, and if keep needs room,
        the least recently used idle one."""
        now = time.monotonic()
        idle = [k for k, h in self._held.items() if h.users == 0 and k != keep]
        expired = [k for k in idle if now - self._held[k].last_used > CLIENT_IDLE_S]
        full = keep not in self._held and len(self._held) - len(expired) >= self._limit
        room = [k for k in idle if k not in expired][:1] if full else []
        return [self._held.pop(k) for k in expired + room]

    def close(self) -> None:
        with self._lock:
            held = list(self._held.values())
            self._held.clear()
        for h in held:
            assert h.users == 0, "an Access closed while in use"
            h.access.close()


class Relay:
    """The contract's operations, HTTP aside (Handler is that). Owns its boots (records and
    threads), its open event streams (at most MAX_STREAMS), and its readers' clients (Accesses).
    close() ends all of it: in-flight boots are cancelled (their sessions end, as POST /end would)
    and joined, streams told to stop and waited for, clients closed. A booted session is not the
    relay's: it outlives the relay (idle, deadline, or POST /end on any relay end it)."""

    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self._accesses = Accesses(cfg.access, MAX_CLIENTS)
        self._boots: dict[str, Boot] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._streams = 0
        self._changed = threading.Condition()  # guards _boots, _threads, _streams
        self._closing = threading.Event()

    def create(self, req: CreateRequest, origin: str) -> dict[str, Any]:
        """Start a boot on its own thread; returns the session's first (booting) status at once."""
        now = time.time()
        sid = sdk.new_session_id()
        push = None if self.cfg.push is None else functools.partial(self.cfg.push.send, sid)
        rec = Boot(sid, digest(req.token), req.gpu, now, now + self.cfg.deadline_s, push=push)
        thread = threading.Thread(target=self._boot, args=(rec, req, origin), name=f"boot-{sid}")
        with self._changed:
            self._forget_old_boots()
            if len(self._boots) >= MAX_BOOTS:
                raise Busy(f"{MAX_BOOTS} sessions booting or just booted on this relay; try again in a minute")
            rec.emit("status", status=wire("booting", req.gpu, rec.created_at, rec.deadline_at))  # before anyone can find it
            self._boots[sid] = rec
            self._threads[sid] = thread
        thread.start()
        return {"session_id": sid, "status": rec.status}

    def get(self, sid: str, token: ModalToken) -> dict[str, Any]:
        rec = self._boot_of(sid, token)
        if rec is not None and (rec.ended_at is None or rec.status["state"] == "ended"):
            return rec.status  # booting, or a failed boot: no machine to ask
        with self._accesses.use(token) as access:
            return machine_status(self.cfg, attach(access, sid), token, ready=False)

    def end(self, sid: str, token: ModalToken) -> dict[str, Any]:
        rec = self._boot_of(sid, token)
        if rec is not None and rec.ended_at is None:
            rec.cancel()  # the boot thread ends it at its next step (launch itself can't be interrupted)
        with self._accesses.use(token) as access:
            try:
                s = attach(access, sid)
            except LookupError:
                if rec is None:
                    raise
                return wire("ended", rec.gpu, rec.created_at, rec.deadline_at, reason="stopped")
            s.close(timeout_s=CLOSE_TIMEOUT_S)
            status = machine_status(self.cfg, s, token, ready=False)
        if status["state"] != "ended":  # close() terminated it, but the provider still answers for it
            raise RuntimeError(f"{sid}: still {status['state']} after close")
        return status

    def events(self, sid: str, token: ModalToken, last_id: str, start: Callable[[], Sse]) -> None:
        """SSE: the boot's events from memory (ids b<n>), then the machine's (ids o<out>.<err>, the
        Jupyter log's cursor): its log, live or from the record, and its status whenever that
        changes. Ends after an ended status, or when the relay closes. Last-Event-ID resumes either
        part. start() opens the stream (sends the headers): before it, LookupError (404) or Busy (429)."""
        rec = self._boot_of(sid, token)
        with self._accesses.use(token) as access, self._stream_slot():
            session = attach(access, sid) if rec is None else None  # 404 before the stream starts, as GET
            sse = start()
            boot_from = int(last_id[1:]) + 1 if re.fullmatch(r"b\d+", last_id) else 0
            cursor = tuple(map(int, last_id[1:].split("."))) if re.fullmatch(r"o\d+\.\d+", last_id) else None
            last_status = None
            if rec is not None and cursor is None:
                last_status = replay_boot(sse, rec, boot_from, self._closing)
                if last_status is None or last_status["state"] == "ended":
                    return
                cursor = rec.log_cursor
            follow_machine(self.cfg, sse, session or attach(access, sid), token, cursor or (0, 0), last_status, self._closing)

    def close(self) -> None:
        self._closing.set()
        with self._changed:
            boots, threads = list(self._boots.values()), list(self._threads.values())
        for rec in boots:
            rec.cancel()  # wakes a stream waiting on it too
        for thread in threads:
            thread.join()
        with self._changed:
            while self._streams:
                self._changed.wait()
        self._accesses.close()

    def _boot(self, rec: Boot, req: CreateRequest, origin: str) -> None:
        try:
            with self._accesses.use(req.token) as access:
                boot(self.cfg, access, rec, req, origin)
        except Busy as e:
            rec.step("gateway", f"boot failed: {e}")
            rec.finish(wire("ended", rec.gpu, rec.created_at, rec.deadline_at, reason="boot_failed"))

    @contextlib.contextmanager
    def _stream_slot(self) -> Iterator[None]:
        with self._changed:
            if self._streams >= MAX_STREAMS:
                raise Busy(f"{MAX_STREAMS} event streams open on this relay")
            self._streams += 1
        try:
            yield
        finally:
            with self._changed:
                self._streams -= 1
                self._changed.notify_all()

    def _boot_of(self, sid: str, token: ModalToken) -> Boot | None:
        """This relay's boot record for sid, if it has one and the caller's token booted it."""
        with self._changed:
            rec = self._boots.get(sid)
        if rec is None or not hmac.compare_digest(rec.token_digest, digest(token)):
            return None
        return rec

    def _forget_old_boots(self) -> None:
        """Under _changed: drop boot records BOOT_RECORD_S after their boot ended (the machine answers now)."""
        now = time.monotonic()
        for sid in [sid for sid, r in self._boots.items() if r.ended_at is not None and now - r.ended_at > BOOT_RECORD_S]:
            del self._boots[sid]
            self._threads.pop(sid).join()  # it has finished: ended_at is its last act


def attach(access: Access, sid: str) -> sdk.Session:
    """The session, live or (machine gone) from its record. LookupError (404) if neither knows it."""
    return sdk.attach(access.provider, sid, record=access.record)


@dataclass
class Sse:
    """An open text/event-stream."""

    wfile: BinaryIO
    sent: int = 0
    last_write: float = field(default_factory=time.monotonic)

    def send(self, event_id: str, event: dict[str, Any]) -> None:
        self.wfile.write(f"id: {event_id}\ndata: {json.dumps(event)}\n\n".encode())
        self.wfile.flush()
        self.sent += 1
        self.last_write = time.monotonic()

    def ping(self) -> None:
        if time.monotonic() - self.last_write >= SSE_PING_S:
            self.wfile.write(b": ping\n\n")
            self.wfile.flush()
            self.last_write = time.monotonic()


def replay_boot(sse: Sse, rec: Boot, start: int, closing: threading.Event) -> dict[str, Any] | None:
    """The boot's events from index start, live until the boot ends. Returns its last status
    (None if the relay closed first)."""
    i = start
    while not closing.is_set():
        with rec.changed:
            if i >= len(rec.events) and rec.ended_at is None:
                rec.changed.wait(SSE_PING_S)
            batch, over = rec.events[i:], rec.ended_at is not None
        for event in batch:
            sse.send(f"b{i}", event)
            i += 1
        if over and i >= len(rec.events):
            return rec.status
        sse.ping()
    return None


def follow_machine(  # noqa: PLR0913 (the stream, the session, where the reader is; each one thing)
    cfg: Config, sse: Sse, s: sdk.Session, token: ModalToken, cursor: sdk.LogCursor, last: dict[str, Any] | None, closing: threading.Event,
) -> None:  # fmt: skip
    """The machine's word until it ends: Jupyter's log (live, or from the record once the machine
    is gone), and its status when it changes. Bounded by the session's deadline (plus the
    provider's backstop), like Session.wait(), or the relay closing."""
    job = None
    ready = last is not None and last["state"] == "running"
    while not closing.is_set():
        status = machine_status(cfg, s, token, ready=ready)  # before the log: once ended, the log read next is all of it
        ready = status["state"] == "running"
        job = job or kernel_service(s)  # None only while a boot (on some relay) has yet to start Jupyter
        # watch: the machine lingers for us after the session ends, so the next poll reads why
        read = job.read(cursor, watch=True) if job else sdk.JobRead(None, [])
        for stream, text, end in log_lines(read.chunks, cursor):
            sse.send(f"o{end[0]}.{end[1]}", {"t": time.time(), "kind": "log", "source": "machine", "stream": stream, "text": text})
            cursor = end
        if status != last:
            sse.send(f"o{cursor[0]}.{cursor[1]}", {"t": time.time(), "kind": "status", "status": status})
            last = status
        if read.more:
            continue  # more log than one read brings: no wait, and not done until it is all sent
        if status["state"] == "ended":
            return
        closing.wait(STREAM_POLL_S)
        sse.ping()


# ---- HTTP ----


class Handler(BaseHTTPRequestHandler):
    """HTTP in and out: routes, parses the browser's input, maps errors to codes, one wide log line
    per request. Everything else is the server's Relay."""

    server_version = "box-relay/0"
    protocol_version = "HTTP/1.1"
    server: Server

    def log_message(self, fmt: str, *args: Any) -> None:
        pass  # one wide line per request instead (wide()); never a query string (tokens)

    def wide(self, code: int, t0: float, **fields: Any) -> None:
        event = {"t": round(time.time(), 3), "method": self.command, "path": urlsplit(self.path).path, "code": code,
                 "ms": round(1000 * (time.monotonic() - t0)), **fields}  # fmt: skip
        sys.stderr.write(json.dumps(event) + "\n")

    def cors(self) -> None:
        origin = self.headers.get("Origin", "")
        if self.server.relay.cfg.origins.fullmatch(origin):
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
        relay = self.server.relay
        try:
            if route == ("POST", 1, None) and parts == ["sessions"]:
                code, body = 202, relay.create(*self.create_request())
            elif sid is not None and route == ("GET", 2, None):
                code, body = 200, {"session_id": sid, "status": relay.get(sid, parse_token(self.headers.get("X-Box-Token", "")))}
            elif sid is not None and route == ("POST", 3, "end"):
                code, body = 200, {"session_id": sid, "status": relay.end(sid, parse_token(self.headers.get("X-Box-Token", "")))}
            elif sid is not None and route == ("GET", 3, "events"):
                self.events(t0, sid, parse_token((parse_qs(url.query).get("token") or [""])[0]))
                return
            else:
                code, body = 404, {"error": f"no route {self.command} {url.path}"}
        except Exception as e:  # noqa: BLE001 (every failure is an answer; error_code says which)
            code = error_code(e)
            body = {"error": f"{type(e).__name__}: {e}" if code == 502 else str(e)}
        self.reply(code, body)
        self.wide(code, t0, session=sid or body.get("session_id"), **({"error": body["error"]} if "error" in body else {}))

    def create_request(self) -> tuple[CreateRequest, str]:
        raw = self.headers.get("Content-Length", "0")
        if not raw.isdigit():  # also refuses a negative one
            raise BadRequest(f"Content-Length {raw!r} is not a byte count")
        if int(raw) > MAX_BODY:
            raise BadRequest(f"body over {MAX_BODY} bytes")
        req = parse_create(self.rfile.read(int(raw)), self.server.relay.cfg.gpus)
        origin = self.headers.get("Origin", "")
        if origin and not self.server.relay.cfg.origins.fullmatch(origin):
            raise BadRequest(f"origin {origin!r} is not one this relay serves")
        return req, origin

    def events(self, t0: float, sid: str, token: ModalToken) -> None:
        sse = Sse(self.wfile)
        started = threading.Event()

        def start() -> Sse:
            self.send_response(200)
            self.cors()
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            started.set()
            return sse

        try:
            self.server.relay.events(sid, token, self.headers.get("Last-Event-ID", ""), start)
        except (BrokenPipeError, ConnectionResetError):
            pass  # the tab went away
        except Exception as e:  # noqa: BLE001 (before the stream: an answer; after: all that is left is to say so and close)
            if not started.is_set():
                self.reply(error_code(e), {"error": str(e)})
                self.wide(error_code(e), t0, session=sid, error=str(e))
                return
            print(f"relay: event stream {sid} broke: {e!r}", file=sys.stderr)
        self.wide(200, t0, session=sid, sent=sse.sent)


def error_code(e: Exception) -> int:
    """BadRequest 400, LookupError (no such session) 404, Busy 429, anything else (Modal, the machine) 502."""
    match e:
        case BadRequest():
            return 400
        case LookupError():
            return 404
        case Busy():
            return 429
        case _:
            return 502


# ---- main ----


def modal_access(token: ModalToken, region: str) -> Access:
    from box.providers.modal import Modal, ModalVolumeStore

    provider = Modal(token=token, region=region)
    return Access(provider, ModalVolumeStore(RECORD_VOLUME, client=provider.client), close=provider.close)


def modal_config(a: argparse.Namespace, gpus: tuple[str | None, ...], push: Push | None) -> Config:
    return Config(
        access=lambda token: modal_access(token, a.region), image=KERNEL_IMAGE, gpus=gpus, labels=dict(a.label),
        origins=re.compile(LOCAL_ORIGIN), deadline_s=a.deadline_s, idle_timeout_s=a.idle_timeout_s, push=push,
    )  # fmt: skip


class Server(ThreadingHTTPServer):
    """The relay on 127.0.0.1:port. server_close() also closes its Relay (after shutdown())."""

    daemon_threads = True

    def __init__(self, relay: Relay, port: int) -> None:
        super().__init__(("127.0.0.1", port), Handler)
        self.relay = relay

    def server_close(self) -> None:
        super().server_close()
        self.relay.close()

    def handle_error(self, request: Any, client_address: Any) -> None:
        if isinstance(sys.exc_info()[1], ConnectionError):
            return  # a browser closing a kept-alive connection between requests: not an error
        super().handle_error(request, client_address)


def serve(cfg: Config, port: int) -> Server:
    return Server(Relay(cfg), port)


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
    ap.add_argument("--push", metavar="URL", help="variants B/C: push events to this fan-out (box/gateway-do); env BOX_PUSH_SECRET")
    a = ap.parse_args()
    gpus = (None, *[g for g in a.gpus.split(",") if g])
    if a.deadline_s + 600 > 24 * 3600:
        ap.error("--deadline-s: Modal caps a sandbox at 24 h, and box adds a 600 s backstop")
    push = None if a.push is None else push_to(a.push, os.environ.get("BOX_PUSH_SECRET", ""))
    cfg = modal_config(a, gpus, push)
    server = serve(cfg, a.port)
    print(f"relay on http://localhost:{a.port} (modal, region {a.region}, gpus {list(gpus)}, labels {dict(a.label)}, "
          f"deadline {a.deadline_s} s, idle {a.idle_timeout_s} s, push {a.push})", flush=True)  # fmt: skip
    with contextlib.suppress(KeyboardInterrupt):  # booted sessions outlive the relay: idle/deadline end them
        server.serve_forever()
    server.server_close()  # in-flight boots end (cancelled), streams stop, readers' clients close
    if push is not None:
        push.close()


def push_to(url: str, secret: str) -> Push:
    from box.gateway.push import Push, parse_secret

    return Push(url.rstrip("/"), parse_secret(secret)).start()


if __name__ == "__main__":
    main()
