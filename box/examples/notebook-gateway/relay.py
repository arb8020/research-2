from __future__ import annotations

import argparse
import contextlib
import hashlib
import hmac
import json
import math
import queue
import re
import socket
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
from typing import Any, BinaryIO
from urllib.parse import parse_qs, quote, urlsplit

from box import sdk
from box.providers.modal import ModalToken
from box.sdk import Booting, Done, Ended, Queued, Running
from box.store import Store

HERE = Path(__file__).parent
KERNEL_IMAGE = str(HERE / "kernel.Dockerfile")
PORT = 8888
LABEL_GPU = "relay.gpu"
LABEL_PORT = "relay.port"
LABEL_LEASE = "relay.lease_s"
LABEL_CEILING_S = "relay.ceiling_s"
IDLE_TIMEOUT_S = 5 * 60
BOOT_TIMEOUT_S = 10 * 60
JUPYTER_READY_S = 3 * 60
BOOT_RECORD_S = 10 * 60
MAX_BOOTS = 16
MAX_STREAMS = 32
MAX_CLIENTS = 64
CLIENT_IDLE_S = 10 * 60
MAX_BODY = 8 * 1024
MAX_LABELS = 8
MAX_BOOT_EVENTS = 1000
READY_POLL_S = 1.0
STREAM_TICK_S = 1.0
LOG_QUEUE = 256
FOLLOWER_JOIN_S = 30.0
END_WAIT_S = 60.0
IDLE_CONNECTION_S = 30.0
SSE_PING_S = 15.0
PROBE_TIMEOUT_S = 5.0
CLOSE_TIMEOUT_S = 60.0
REASONS = {"lease": "lease", "released": "stopped", "stopped": "stopped", "idle": "idle", "machine_lost": "machine_lost"}
JUPYTER_GONE = "machine_lost"
JUPYTER_SERVICE = "jupyter"
RECORD_VOLUME = "box-sessions"
LOCAL_ORIGIN = r"https?://(localhost|127\.0\.0\.1)(:\d+)?"


@dataclass(frozen=True)
class Access:
    provider: sdk.Provider
    record: Store
    close: Callable[[], None] = lambda: None
    check: Callable[[str], object] = lambda session_id: None


@dataclass(frozen=True)
class Limits:
    min_s: int = 60
    max_s: int = 12 * 3600
    default_s: int = 90 * 60
    ceiling_s: int = 12 * 3600

    def __post_init__(self) -> None:
        if not 0 < self.min_s <= self.default_s <= self.max_s <= self.ceiling_s <= sdk.MAX_CEILING_S:
            raise ValueError(f"relay: {self}: 0 < min_s <= default_s <= max_s <= ceiling_s <= {sdk.MAX_CEILING_S} s")

    def wire(self, gpus: tuple[str | None, ...]) -> dict[str, Any]:
        return {"lease": {"min_s": self.min_s, "max_s": self.max_s, "default_s": self.default_s}, "ceiling_s": self.ceiling_s, "gpus": list(gpus)}


@dataclass(frozen=True)
class Config:
    access: Callable[[ModalToken], Access]
    image: str | None
    gpus: tuple[str | None, ...]
    labels: dict[str, str]
    origins: re.Pattern[str]
    python: str = "python3"
    ip: str = "0.0.0.0"
    port: Callable[[], int] = lambda: PORT
    idle_timeout_s: float = IDLE_TIMEOUT_S
    limits: Limits = Limits()

    def __post_init__(self) -> None:
        if not sdk.MIN_IDLE_S <= self.idle_timeout_s <= self.limits.ceiling_s:
            raise ValueError(f"relay: idle_timeout_s={self.idle_timeout_s}: {sdk.MIN_IDLE_S:g} to {self.limits.ceiling_s} s (a boot marks its session used every idle/4 s)")


@dataclass(frozen=True)
class CreateRequest:
    token: ModalToken
    gpu: str | None
    labels: dict[str, str]
    lease_s: int


@dataclass
class Boot:
    session_id: str
    token_digest: str
    gpu: str | None
    created_at: float
    lease: sdk.Lease
    events: list[dict[str, Any]] = field(default_factory=list)
    dropped: int = 0
    status: dict[str, Any] | None = None
    log_cursor: sdk.LogCursor = (0, 0)
    ended_at: float | None = None
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

    def cancel(self) -> None:
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
    pass


class Conflict(Exception):
    pass


class Busy(Exception):
    pass


def parse_token(raw: str) -> ModalToken:
    token_id, sep, secret = raw.partition(":")
    if not sep or not token_id or not secret:
        raise BadRequest("token must be 'id:secret' (X-Box-Token header, or ?token= on /events)")
    return ModalToken(token_id, secret)


def parse_create(body: bytes, gpus: tuple[str | None, ...], limits: Limits) -> CreateRequest:
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
    lease_s = raw.get("lease_s", limits.default_s)
    if type(lease_s) is not int or not limits.min_s <= lease_s <= limits.max_s:  # type(): bool is an int subclass, so isinstance would take a JSON true
        raise BadRequest(f"lease_s must be an integer from {limits.min_s} to {limits.max_s}, got {lease_s!r}")
    return CreateRequest(ModalToken(token["id"], token["secret"]), gpu, labels, lease_s)


def parse_extend(body: bytes) -> float:
    try:
        raw = json.loads(body)
    except ValueError as e:
        raise BadRequest(f"body is not JSON: {e}") from None
    until = raw.get("until") if isinstance(raw, dict) else None
    if type(until) not in (int, float) or not math.isfinite(until):
        raise BadRequest(f"expected {{until: unix seconds}}, got {raw!r}")
    return float(until)


def kernel_token(token: ModalToken, session_id: str) -> str:
    return hmac.new(token.secret.encode(), f"jupyter:{session_id}".encode(), hashlib.sha256).hexdigest()[:48]


def digest(token: ModalToken) -> str:
    return hashlib.sha256(f"{token.id}:{token.secret}".encode()).hexdigest()


def wire(state: str, gpu: str | None, started_at: float | None, lease: sdk.Lease, **extra: Any) -> dict[str, Any]:
    return {"state": state, "gpu": gpu, "started_at": started_at, "lease_until": lease.until, "ceiling": lease.ceiling, **extra}


def machine_status(cfg: Config, s: sdk.Session, token: ModalToken, *, ready: bool) -> dict[str, Any]:
    labels = s.machine.labels
    gpu = labels.get(LABEL_GPU) or None
    match s.status():
        case Booting():
            return wire("booting", gpu, time.time(), first_lease(labels))
        case Running() as running:
            try:
                return running_status(s, token, running, ready=ready, gpu=gpu)
            except sdk.Gone:
                gone = s.status()
                assert isinstance(gone, Ended), f"{s.id}: {gone} once its machine is gone"
                return ended_status(s, REASONS[gone.reason])
        case Ended(reason=reason):
            return ended_status(s, REASONS[reason])


def first_lease(labels: dict[str, str]) -> sdk.Lease:
    ceiling = float(labels[sdk.LABEL_CEILING])
    return sdk.Lease(until=ceiling - float(labels[LABEL_CEILING_S]) + float(labels[LABEL_LEASE]), ceiling=ceiling)


def ended_status(s: sdk.Session, reason: str) -> dict[str, Any]:
    labels = s.machine.labels
    started_at = None if s.record is None else sdk.recorded_started_at(s.record, s.id)
    return wire("ended", labels.get(LABEL_GPU) or None, started_at, first_lease(labels), reason=reason)


def running_status(s: sdk.Session, token: ModalToken, running: Running, *, ready: bool, gpu: str | None) -> dict[str, Any]:
    kernel = {"url": s.expose(int(s.machine.labels[LABEL_PORT])).url, "token": kernel_token(token, s.id)}
    if ready or jupyter_ready(kernel):
        return wire("running", gpu, running.started_at, running.lease, kernel=kernel)
    jupyter = kernel_service(s)
    match Queued() if jupyter is None else jupyter.status():
        case Done(ending=ending):
            return ended_status(s, REASONS.get(ending.reason, JUPYTER_GONE))
    return wire("booting", gpu, running.started_at, running.lease)


def jupyter_ready(kernel: dict[str, str]) -> bool:
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
    return next((job for job in s.services() if job.id == JUPYTER_SERVICE), None)


def jupyter_cmd(cfg: Config, port: int, origin: str) -> str:
    settings = {"websocket_ping_interval": 20}
    return " ".join([
        "exec", cfg.python, "-m", "jupyter_server", "--no-browser", "--allow-root", f"--ip={cfg.ip}", f"--port={port}",
        '--ServerApp.root_dir="$BOX_JOB_DIR"', f"--ServerApp.allow_origin='{origin}'", "--ServerApp.allow_remote_access=True",
        "--ServerApp.disable_check_xsrf=True", f'--ServerApp.tornado_settings="{settings}"',
    ])  # fmt: skip


def boot(cfg: Config, access: Access, rec: Boot, req: CreateRequest, origin: str) -> None:
    t0 = time.monotonic()
    session: sdk.Session | None = None
    try:
        rec.step("gateway", "checking your Modal token")
        access.check(rec.session_id)
        port = cfg.port()
        rec.step("gateway", f"creating sandbox: gpu {rec.gpu or 'none'} (a workspace's first connect builds the image: minutes)")
        created_at = time.monotonic()
        made = sdk.create(  # MUST KILL: re-implements sdk.launch (create, wait_up, terminate on failure) only to emit a step in between; give launch a hook
            access.provider, session_id=rec.session_id, record=access.record, lease_s=req.lease_s, ceiling_s=cfg.limits.ceiling_s,
            gpu=rec.gpu, image=cfg.image, labels={**cfg.labels, **req.labels, LABEL_GPU: rec.gpu or "", LABEL_PORT: str(port),
            LABEL_LEASE: str(req.lease_s), LABEL_CEILING_S: str(cfg.limits.ceiling_s)}, idle_timeout_s=cfg.idle_timeout_s, ports=(port,),
        )  # fmt: skip
        rec.step("gateway", f"sandbox {made.machine.id} created in {time.monotonic() - created_at:.1f} s; waiting for it to start")
        try:
            made.wait_up(BOOT_TIMEOUT_S)
        except BaseException:
            made.machine.terminate()
            raise
        session = made
        rec.step("machine", f"supervisor up ({time.monotonic() - t0:.1f} s since connect)")
        if rec.cancelled:
            raise Cancelled
        with session.using():
            job = session.serve(jupyter_cmd(cfg, port, origin), env={"JUPYTER_TOKEN": kernel_token(req.token, rec.session_id)}, name=JUPYTER_SERVICE)
            rec.step("machine", "starting Jupyter Server")
            endpoint = session.expose(port)
            rec.step("gateway", f"tunnel open: {endpoint.url}")
            kernel = {"url": endpoint.url, "token": kernel_token(req.token, rec.session_id)}
            wait_for_jupyter(rec, job, kernel)
        if rec.cancelled:
            raise Cancelled
        running = session.status()
        if not isinstance(running, Running):
            raise RuntimeError(f"{rec.session_id}: {running} as Jupyter came up")
        status = wire("running", rec.gpu, running.started_at, running.lease, kernel=kernel)
        rec.step("machine", f"Jupyter Server ready ({time.monotonic() - t0:.1f} s since connect)")
        rec.finish(status)
    except Cancelled:
        rec.step("gateway", "ended while booting")
        try:
            end_after_boot(rec, session)
        finally:
            rec.finish(wire("ended", rec.gpu, rec.created_at, rec.lease, reason="stopped"))
    except Exception as e:
        if rec.cancelled:
            rec.step("gateway", "ended while booting")
            rec.finish(wire("ended", rec.gpu, rec.created_at, rec.lease, reason="stopped"))
            return
        print(f"relay: boot {rec.session_id} failed: {e!r}", file=sys.stderr)
        rec.step("gateway", f"boot failed: {type(e).__name__}: {e}")
        try:
            ended = end_after_boot(rec, session)
        except BaseException:
            rec.finish(wire("ended", rec.gpu, rec.created_at, rec.lease, reason="boot_failed"))
            raise
        rec.finish(wire("ended", rec.gpu, rec.created_at, rec.lease, reason="boot_failed" if ended is None else REASONS[ended.reason]))


class Cancelled(Exception):
    pass


def end_after_boot(rec: Boot, session: sdk.Session | None) -> Ended | None:
    if session is None:
        return None
    try:
        before = session.status()
    finally:
        close_after_boot(rec, session)
    return before if isinstance(before, Ended) else None


def close_after_boot(rec: Boot, session: sdk.Session) -> None:
    try:
        session.close(timeout_s=CLOSE_TIMEOUT_S)
    except sdk.NotGone as e:
        rec.step("gateway", f"sandbox {session.machine.id} may still be running (and billing): {e}")
        sys.stderr.write(json.dumps({"t": round(time.time(), 3), "event": "not_gone", "session": session.id, "machine": session.machine.id, "error": str(e)}) + "\n")
    except (sdk.Gone, OSError) as e:
        print(f"relay: closing {session.id} after a failed boot: {e!r}", file=sys.stderr)


def wait_for_jupyter(rec: Boot, job: sdk.Job, kernel: dict[str, str]) -> None:
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
    read = job.read(rec.log_cursor)
    for stream, text, cursor in log_lines(read.chunks, rec.log_cursor):
        rec.emit("log", source="machine", stream=stream, text=text)
        rec.log_cursor = cursor
    return read


def log_lines(chunks: list[sdk.LogChunk], after: sdk.LogCursor) -> Iterator[tuple[str, str, sdk.LogCursor]]:
    out, err = after
    for chunk in chunks:
        for line in chunk.text.splitlines(keepends=True):
            if chunk.stream == "stdout":
                out += len(line.encode())
            else:
                err += len(line.encode())
            yield chunk.stream, line.rstrip("\n"), (out, err)


@dataclass
class Held:
    access: Access
    users: int = 0
    last_used: float = field(default_factory=time.monotonic)


class Accesses:
    def __init__(self, make: Callable[[ModalToken], Access], limit: int) -> None:
        self._make = make
        self._limit = limit
        self._held: OrderedDict[str, Held] = OrderedDict()
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
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self._accesses = Accesses(cfg.access, MAX_CLIENTS)
        self._boots: dict[str, Boot] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._streams = 0
        self._changed = threading.Condition()
        self._closing = threading.Event()

    def create(self, req: CreateRequest, origin: str) -> dict[str, Any]:
        now = time.time()
        sid = sdk.new_session_id()
        rec = Boot(sid, digest(req.token), req.gpu, now, sdk.Lease(until=now + req.lease_s, ceiling=now + self.cfg.limits.ceiling_s))
        thread = threading.Thread(target=self._boot, args=(rec, req, origin), name=f"boot-{sid}", daemon=False)
        with self._changed:
            self._forget_old_boots()
            if len(self._boots) >= MAX_BOOTS:
                raise Busy(f"{MAX_BOOTS} sessions booting or just booted on this relay; try again in a minute")
            rec.emit("status", status=wire("booting", req.gpu, rec.created_at, rec.lease))
            self._boots[sid] = rec
            self._threads[sid] = thread
        thread.start()
        return {"session_id": sid, "status": rec.status}

    def get(self, sid: str, token: ModalToken) -> dict[str, Any]:
        rec = self._boot_of(sid, token)
        if rec is not None and (rec.ended_at is None or rec.status["state"] == "ended"):
            return rec.status
        with self._accesses.use(token) as access:
            return machine_status(self.cfg, attach(access, sid), token, ready=False)

    def end(self, sid: str, token: ModalToken) -> dict[str, Any]:
        rec = self._boot_of(sid, token)
        if rec is not None and rec.ended_at is None:
            rec.cancel()
        with self._accesses.use(token) as access:
            try:
                s = attach(access, sid)
            except LookupError:
                if rec is None:
                    raise
                return wire("ended", rec.gpu, rec.created_at, rec.lease, reason="stopped")
            receipt = s.close(timeout_s=CLOSE_TIMEOUT_S)
        return ended_status(s, REASONS[receipt.ended.reason])

    def extend(self, sid: str, token: ModalToken, until: float) -> dict[str, Any]:
        rec = self._boot_of(sid, token)
        with self._accesses.use(token) as access:
            try:
                s = attach(access, sid)
            except LookupError:
                if rec is None or rec.ended_at is not None:
                    raise
                raise Conflict(f"{sid} is still booting: extend once it is running") from None
            match s.status():
                case Booting():
                    raise Conflict(f"{sid} is still booting: extend once it is running")
                case Running():
                    with contextlib.suppress(sdk.Gone):
                        s.extend(until)
            return machine_status(self.cfg, s, token, ready=False)

    def events(self, sid: str, token: ModalToken, last_id: str, start: Callable[[], Sse]) -> None:
        rec = self._boot_of(sid, token)
        with self._accesses.use(token) as access, self._stream_slot():
            session = attach(access, sid) if rec is None else None
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
            rec.cancel()
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
            rec.finish(wire("ended", rec.gpu, rec.created_at, rec.lease, reason="boot_failed"))

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
        with self._changed:
            rec = self._boots.get(sid)
        if rec is None or not hmac.compare_digest(rec.token_digest, digest(token)):
            return None
        return rec

    def _forget_old_boots(self) -> None:
        now = time.monotonic()
        for sid in [sid for sid, r in self._boots.items() if r.ended_at is not None and now - r.ended_at > BOOT_RECORD_S]:
            del self._boots[sid]
            self._threads.pop(sid).join()


def attach(access: Access, sid: str) -> sdk.Session:
    return sdk.attach(access.provider, session_id=sid, record=access.record)


@dataclass
class Sse:
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


def follow_machine(  # noqa: PLR0913
    cfg: Config, sse: Sse, s: sdk.Session, token: ModalToken, cursor: sdk.LogCursor, last: dict[str, Any] | None, closing: threading.Event,
) -> None:  # fmt: skip
    while last is None or last["state"] != "running":
        status = machine_status(cfg, s, token, ready=False)
        if status["state"] == "ended":
            break
        if status != last:
            sse.send(f"o{cursor[0]}.{cursor[1]}", {"t": time.time(), "kind": "status", "status": status})
            last = status
        if status["state"] != "running" and closing.wait(READY_POLL_S):
            return
        sse.ping()
    job = kernel_service(s)
    if job is not None and (cursor := forward_log(sse, job, cursor, closing)) is None:
        return
    with contextlib.suppress(TimeoutError):
        s.wait(END_WAIT_S)
    status = machine_status(cfg, s, token, ready=False)
    if status != last:
        sse.send(f"o{cursor[0]}.{cursor[1]}", {"t": time.time(), "kind": "status", "status": status})


def forward_log(sse: Sse, job: sdk.Job, cursor: sdk.LogCursor, closing: threading.Event) -> sdk.LogCursor | None:
    chunks: queue.Queue[sdk.LogChunk | BaseException | None] = queue.Queue(LOG_QUEUE)
    stop = threading.Event()

    def put(item: sdk.LogChunk | BaseException | None) -> None:
        while not stop.is_set():
            with contextlib.suppress(queue.Full):
                chunks.put(item, timeout=STREAM_TICK_S)
                return

    def follow() -> None:
        end: BaseException | None = None
        try:
            for chunk in job.logs(after=cursor, follow=True, stop=stop):
                put(chunk)
        except BaseException as e:
            end = e
        put(end)

    follower = threading.Thread(target=follow, name=f"follow-{job.session.id}", daemon=False)
    follower.start()
    try:
        while not closing.is_set():
            try:
                item = chunks.get(timeout=STREAM_TICK_S)
            except queue.Empty:
                sse.ping()
                continue
            if item is None:
                return cursor
            if isinstance(item, BaseException):
                raise item
            for stream, text, end in log_lines([item], cursor):
                sse.send(f"o{end[0]}.{end[1]}", {"t": time.time(), "kind": "log", "source": "machine", "stream": stream, "text": text})
                cursor = end
        return None
    finally:
        stop.set()
        follower.join(FOLLOWER_JOIN_S)
        if follower.is_alive():
            print(f"relay: {job.session.id}: log follower still running {FOLLOWER_JOIN_S:.0f} s after it was stopped", file=sys.stderr)


class Handler(BaseHTTPRequestHandler):
    server_version = "box-relay/0"
    protocol_version = "HTTP/1.1"
    timeout = IDLE_CONNECTION_S
    server: Server

    def log_message(self, fmt: str, *args: Any) -> None:
        pass

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
            if route == ("GET", 1, None) and parts == ["limits"]:
                code, body = 200, relay.cfg.limits.wire(relay.cfg.gpus)
            elif route == ("POST", 1, None) and parts == ["sessions"]:
                code, body = 202, relay.create(*self.create_request())
            elif sid is not None and route == ("GET", 2, None):
                code, body = 200, {"session_id": sid, "status": relay.get(sid, parse_token(self.headers.get("X-Box-Token", "")))}
            elif sid is not None and route == ("POST", 3, "end"):
                code, body = 200, {"session_id": sid, "status": relay.end(sid, parse_token(self.headers.get("X-Box-Token", "")))}
            elif sid is not None and route == ("POST", 3, "extend"):
                until = parse_extend(self.body())
                code, body = 200, {"session_id": sid, "status": relay.extend(sid, parse_token(self.headers.get("X-Box-Token", "")), until)}
            elif sid is not None and route == ("GET", 3, "events"):
                self.events(t0, sid, parse_token((parse_qs(url.query).get("token") or [""])[0]))
                return
            else:
                code, body = 404, {"error": f"no route {self.command} {url.path}"}
        except Exception as e:
            code = error_code(e)
            body = {"error": f"{type(e).__name__}: {e}" if code == 502 else str(e)}
        self.reply(code, body)
        self.wide(code, t0, session=sid or body.get("session_id"), **({"error": body["error"]} if "error" in body else {}))

    def body(self) -> bytes:
        raw = self.headers.get("Content-Length", "0")
        if not raw.isdigit():
            raise BadRequest(f"Content-Length {raw!r} is not a byte count")
        if int(raw) > MAX_BODY:
            raise BadRequest(f"body over {MAX_BODY} bytes")
        return self.rfile.read(int(raw))

    def create_request(self) -> tuple[CreateRequest, str]:
        req = parse_create(self.body(), self.server.relay.cfg.gpus, self.server.relay.cfg.limits)
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
            pass
        except Exception as e:
            if not started.is_set():
                self.reply(error_code(e), {"error": str(e)})
                self.wide(error_code(e), t0, session=sid, error=str(e))
                return
            print(f"relay: event stream {sid} broke: {e!r}", file=sys.stderr)
        self.wide(200, t0, session=sid, sent=sse.sent)


def error_code(e: Exception) -> int:
    match e:
        case BadRequest():
            return 400
        case LookupError():
            return 404
        case Conflict():
            return 409
        case Busy():
            return 429
        case _:
            return 502


def modal_access(token: ModalToken, region: str, volumes: dict[str, str]) -> Access:
    from box.providers.modal import Modal, ModalVolumeStore

    provider = Modal(token=token, region=region, volumes=volumes)
    return Access(provider, ModalVolumeStore(RECORD_VOLUME, provider=provider), close=provider.close,
                  check=lambda session_id: provider.list({sdk.LABEL_SESSION: session_id}))  # fmt: skip


def modal_config(a: argparse.Namespace, gpus: tuple[str | None, ...], limits: Limits) -> Config:
    return Config(
        access=lambda token: modal_access(token, a.region, dict(a.volume)), image=a.image, gpus=gpus, labels=dict(a.label),
        origins=re.compile(LOCAL_ORIGIN), idle_timeout_s=a.idle_timeout_s, limits=limits,
    )  # fmt: skip


def local_check(token: ModalToken) -> None:
    if not token.id.startswith("ak-"):
        raise PermissionError(f"local relay: a token id starts 'ak-', as Modal's do (got {token.id[:3]!r}...)")


def local_config(a: argparse.Namespace, gpus: tuple[str | None, ...], limits: Limits) -> Config:
    from box.providers.local import Local
    from box.store import DirStore

    machines = a.machines_dir.resolve()
    records = (a.records_dir or machines / "records").resolve()
    return Config(
        access=lambda token: Access(Local(machines), DirStore(records), check=lambda session_id: local_check(token)), image=None,
        gpus=gpus, labels=dict(a.label), origins=re.compile(LOCAL_ORIGIN), python=a.python, ip="127.0.0.1", port=free_port,
        idle_timeout_s=a.idle_timeout_s, limits=limits,
    )  # fmt: skip


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class Server(ThreadingHTTPServer):
    daemon_threads = False

    def __init__(self, relay: Relay, port: int) -> None:
        super().__init__(("127.0.0.1", port), Handler)
        self.relay = relay

    def server_close(self) -> None:
        self.relay.close()
        super().server_close()

    def handle_error(self, request: Any, client_address: Any) -> None:
        if isinstance(sys.exc_info()[1], ConnectionError):
            return
        super().handle_error(request, client_address)


def serve(cfg: Config, port: int) -> Server:
    return Server(Relay(cfg), port)


def label(raw: str) -> tuple[str, str]:
    key, sep, value = raw.partition("=")
    if not sep or not key:
        raise argparse.ArgumentTypeError(f"--label takes key=value, got {raw!r}")
    return key, value


def volume(raw: str) -> tuple[str, str]:
    path, sep, name = raw.partition("=")
    if not sep or not path.startswith("/") or not name:
        raise argparse.ArgumentTypeError(f"--volume takes /mount/path=volume-name, got {raw!r}")
    return path.rstrip("/") or "/", name


def main() -> None:
    from box.providers.local import BASE

    ap = argparse.ArgumentParser(description="The box relay: browser sessions on Modal or this machine (box/CONTRACT-gateway.md), over HTTP on localhost.", formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--provider", choices=("modal", "local"), default="modal")
    ap.add_argument("--port", type=int, default=8790)
    ap.add_argument("--gpus", help="comma-separated GPUs a reader may ask for (CPU, gpu null, always; default: T4 on modal, none on local)")
    defaults = Limits()
    ap.add_argument("--lease-min-s", type=int, default=defaults.min_s)
    ap.add_argument("--lease-max-s", type=int, default=defaults.max_s)
    ap.add_argument("--lease-default-s", type=int, default=defaults.default_s)
    ap.add_argument("--ceiling-s", type=int, default=defaults.ceiling_s, help="a session ends this long after it was created, however extended")
    ap.add_argument("--region", default="us", help="Modal region for every session")
    ap.add_argument("--idle-timeout-s", type=float, default=IDLE_TIMEOUT_S, help="no connection to Jupyter for this long ends a session")
    ap.add_argument("--label", type=label, action="append", default=[("box.purpose", "reader-path-dev")],
                    help="key=value stamped on every session (default box.purpose=reader-path-dev, for sweeps)")  # fmt: skip
    ap.add_argument("--image", default=KERNEL_IMAGE, help="kernel image: a path ending in Dockerfile, or a registry ref (default: kernel.Dockerfile next to relay.py)")
    ap.add_argument("--volume", type=volume, action="append", default=[],
                    help="/mount/path=volume-name, a Modal Volume in the reader's workspace (created if missing) on every session; repeatable")  # fmt: skip
    ap.add_argument("--machines-dir", type=Path, default=BASE, help="local: where sessions' machines live")
    ap.add_argument("--records-dir", type=Path, help="local: where ended sessions' records live (default: <machines-dir>/records)")
    ap.add_argument("--python", default=sys.executable, help="local: the interpreter that runs Jupyter and the kernel (default: this one)")
    a = ap.parse_args()
    if len({path for path, _ in a.volume}) != len(a.volume):
        ap.error("--volume: two volumes at one mount path")
    gpus = (None, *[g for g in (a.gpus if a.gpus is not None else "T4" if a.provider == "modal" else "").split(",") if g])
    try:
        limits = Limits(a.lease_min_s, a.lease_max_s, a.lease_default_s, a.ceiling_s)
    except ValueError as e:
        ap.error(str(e))
    cfg = (modal_config if a.provider == "modal" else local_config)(a, gpus, limits)
    server = serve(cfg, a.port)
    where = f"region {a.region}, image {a.image}, volumes {dict(a.volume)}" if a.provider == "modal" else f"machines {a.machines_dir}, python {a.python}"
    print(f"relay on http://localhost:{a.port} ({a.provider}, {where}, gpus {list(gpus)}, labels {dict(a.label)}, "
          f"leases {limits.min_s}-{limits.max_s} s (default {limits.default_s}), ceiling {limits.ceiling_s} s, idle {a.idle_timeout_s} s)", flush=True)  # fmt: skip
    with contextlib.suppress(KeyboardInterrupt):
        server.serve_forever()
    server.server_close()


if __name__ == "__main__":
    main()
