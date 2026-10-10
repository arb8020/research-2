from __future__ import annotations

import base64
import contextlib
import io
import json
import os
import re
import secrets
import shlex
import socket
import sys
import tarfile
import threading
import time
import zlib
from collections.abc import Callable, Generator, Iterator
from dataclasses import dataclass, field
from fnmatch import fnmatch
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Protocol, TypeVar, get_args

from box.gitsync import Synced
from box.setup_cache import SetupRecord, SetupSpec, parse_setup_record
from box.store import Mount, Store
from box.supervisor import (
    ACTIVITY,
    AUDIT,
    ENDED,
    HEARTBEAT,
    HEARTBEAT_TTL_S,
    KILL,
    LEASE,
    MAX_CEILING_S,
    MAX_SERVICES,
    SESSION,
    STATUS,
    STOP,
    TAIL_FRAME_BYTES,
    TAIL_MAX_S,
    UP,
    WATCH,
    Done,
    Ended,
    Ending,
    EndReason,
    Heartbeat,
    JobStatus,
    Lease,
    LeaseChange,
    Queued,
    Started,
    load,
    load_audit,
    load_ended,
    load_job,
    parse_chunk,
    utf8_cut,
)
from box.supervisor import Hooking as Hooking
from box.supervisor import JobEndReason as JobEndReason
from box.supervisor import JobRunning as JobRunning

if TYPE_CHECKING:
    from box.proxy import Proxy

SUPERVISOR = Path(__file__).with_name("supervisor.py")
LABEL_BY = "box.by"
LABEL_SESSION = "box.session"
LABEL_CEILING = "box.ceiling"
LABEL_NAME = "box.name"
LABEL_IDLE = "box.idle"
LABEL_PORTS = "box.ports"
RESERVED = (LABEL_BY, LABEL_SESSION, LABEL_CEILING, LABEL_NAME, LABEL_IDLE, LABEL_PORTS)
# fits Modal's sandbox-name rule, the strictest provider's
NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,62}")
NAME_TRIES = 3
KEEPALIVE_S = 60.0
MIN_KEEPALIVE_S = 1.0
CEILING_S = 3600
BACKSTOP_MARGIN_S = 600
MAX_ENV_VALUE = 32768  # Modal's limit on one secret value; Sandbox.create passes env as a secret
MIN_KEEP_EVERY_S = 0.5
MAX_KEEP_EVERY_S = 3600
POLL_S = 0.5
RECORD_PATH = "record"
SESSION_ID = re.compile(r"s-[0-9a-f]{12}")
SERVICE_NAME = re.compile(r"[a-z][a-z0-9-]{0,31}")
T = TypeVar("T")
STREAMS = ("stdout", "stderr")
LogCursor = tuple[int, int]
Kind = Literal["jobs", "services"]
MAX_LOG_READ = 4 * 1024 * 1024
FOLLOW_QUIET_S = 10.0
FOLLOW_TRIES = 5
FOLLOW_BACKOFF_S = 1.0
TAIL_ERR_BYTES = 4096
SETUP_BOOT_TIMEOUT_S = 900.0
SETUP_FAIL_TAIL = 4000


class Gone(Exception):
    pass


class Refused(ValueError):
    pass


class Dropped(ConnectionError):
    pass


class Stream(Protocol):
    rc: int | None

    def __iter__(self) -> Iterator[tuple[str, bytes]]: ...
    def send(self, data: bytes) -> None: ...
    def close(self) -> None: ...
    def __enter__(self) -> Stream: ...
    def __exit__(self, *exc: object) -> None: ...


class Machine(Protocol):
    id: str
    labels: dict[str, str]
    root: str
    work: str

    def exec(self, cmd: str) -> tuple[int, str, str]: ...
    def stream(self, cmd: str, *, timeout_s: float, quiet_s: float | None = None, pty: bool = False) -> Stream: ...
    def write(self, path: str, data: bytes) -> None: ...
    def read(self, path: str) -> bytes: ...
    def terminate(self) -> None: ...
    def expose(self, port: int) -> Endpoint: ...
    def shell(self, cmd: str) -> Shell: ...
    def gone(self) -> bool: ...


class Provider(Protocol):
    name: str

    def launch(  # noqa: PLR0913
        self, *, gpu: str | None, image: str | None, entrypoint: list[str], env: dict[str, str],
        labels: dict[str, str], timeout_s: int, ports: list[int], mounts: list[Mount],
    ) -> Machine: ...  # fmt: skip
    def get(self, machine_id: str) -> Machine: ...
    def list(self, labels: dict[str, str] | None = None) -> list[Machine]: ...
    def close(self) -> None: ...


@dataclass(frozen=True)
class Dockerfile:
    path: Path


@dataclass(frozen=True)
class RegistryImage:
    ref: str


@dataclass(frozen=True)
class SnapshotImage:
    provider: str
    id: str


Image = Dockerfile | RegistryImage | SnapshotImage
SNAPSHOT_REF = re.compile(r"(modal|local)-snapshot:(.+)")


def parse_image(image: str) -> Image:
    if snapshot := SNAPSHOT_REF.fullmatch(image):
        return SnapshotImage(provider=snapshot[1], id=snapshot[2])
    if image.lower().endswith("dockerfile"):
        return Dockerfile(Path(image))
    return RegistryImage(image)


def snapshot_ref(provider: str, snapshot_id: str) -> str:
    ref = f"{provider}-snapshot:{snapshot_id}"
    assert parse_image(ref) == SnapshotImage(provider, snapshot_id), ref
    return ref


@dataclass(frozen=True)
class Shell:
    argv: list[str]
    env: dict[str, str] = field(default_factory=dict, repr=False)


@dataclass(frozen=True)
class Endpoint:
    url: str
    headers: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Booting:
    pass


@dataclass(frozen=True)
class Running:
    started_at: float
    lease: Lease


Status = Booting | Running | Ended

GONE_TIMEOUT_S = 60.0


class NameTaken(Exception):
    pass


class SetupFailed(RuntimeError):
    pass


class NotGone(TimeoutError):
    pass


@dataclass(frozen=True)
class Receipt:
    session_id: str
    machine_id: str
    ended: Ended
    machine_gone_at: float

    @property
    def supervisor_confirmed(self) -> bool:
        return self.ended.reason != "machine_lost"


def launch(provider: Provider, *, boot_timeout_s: float = 900.0, **create_kw: Any) -> Session:
    session = create(provider, **create_kw)
    try:
        session.wait_up(boot_timeout_s)
    except BaseException:
        session.machine.terminate()
        raise
    return session


def create(  # noqa: PLR0913
    provider: Provider, *, lease_s: float | None = None, ceiling_s: float = CEILING_S, gpu: str | None = None,
    image: str | None = None, env: dict[str, str] | None = None, labels: dict[str, str] | None = None,
    idle_timeout_s: float = 0.0, ports: tuple[int, ...] = (), record: Store | None = None, session_id: str | None = None,
    name: str | None = None, setup: SetupSpec | None = None,
) -> Session:  # fmt: skip
    kw = {"lease_s": lease_s, "ceiling_s": ceiling_s, "gpu": gpu, "labels": labels, "idle_timeout_s": idle_timeout_s,
          "ports": ports, "record": record, "session_id": session_id, "name": name}  # fmt: skip
    if setup is not None:
        return _create_set_up(provider, setup, image=image, env=env or {}, **kw)
    return _create(provider, image=image, env=env, **kw)


def _create(  # noqa: PLR0913
    provider: Provider, *, lease_s: float | None, ceiling_s: float, gpu: str | None, image: str | None,
    env: dict[str, str] | None, labels: dict[str, str] | None, idle_timeout_s: float, ports: tuple[int, ...],
    record: Store | None, session_id: str | None, name: str | None, fresh_root: bool = False,
) -> Session:  # fmt: skip
    session_id = new_session_id() if session_id is None else session_id
    if not SESSION_ID.fullmatch(session_id):
        raise Refused(f"session_id {session_id!r} is not one new_session_id() makes")
    if clash := sorted(set(labels or {}) & set(RESERVED)):
        raise Refused(f"labels {clash} are box's own (launch stamps them)")
    if name is not None and not NAME.fullmatch(name):
        raise Refused(f"name {name!r}: letters, digits, '.', '_', '-', at most 63, starting with a letter or digit")
    if not 0 <= idle_timeout_s <= MAX_CEILING_S:
        raise Refused(f"idle_timeout_s={idle_timeout_s}: 0 (never idle) to {MAX_CEILING_S} s")
    lease_s = ceiling_s if lease_s is None else lease_s
    if not 0 < ceiling_s <= MAX_CEILING_S:
        raise Refused(f"ceiling_s={ceiling_s}: a ceiling is more than 0 and at most {MAX_CEILING_S} s (48 h)")
    if not 0 < lease_s <= ceiling_s:
        raise Refused(f"lease_s={lease_s}: a lease is more than 0 and at most the ceiling ({ceiling_s} s)")
    created_at = time.time()
    lease = Lease(until=created_at + lease_s, ceiling=created_at + ceiling_s)
    assert created_at < lease.until
    assert lease.until <= lease.ceiling
    assert lease.ceiling <= created_at + MAX_CEILING_S
    args = [
        "--created-at", repr(created_at), "--lease-until", repr(lease.until), "--ceiling", repr(lease.ceiling),
        "--host", socket.gethostname(), "--pid", str(os.getpid()), "--session-id", session_id,
        "--idle-timeout-s", str(idle_timeout_s), "--ports", ",".join(map(str, ports)),
        *(["--record", RECORD_PATH, *(["--record-sync"] if record.sync_writes else [])] if record else []),
    ]  # fmt: skip
    install = "import base64,os,zlib; open(os.environ['BOX_ROOT'] + '/supervisor.py', 'wb').write(zlib.decompress(base64.b64decode(os.environ['BOX_SUPERVISOR'])))"
    clear = f'find "$BOX_ROOT" -mindepth 1 -maxdepth 1 ! -name {RECORD_PATH} -exec rm -rf {{}} + && ' if fresh_root else ""
    boot = f'mkdir -p "$BOX_ROOT" && {clear}python3 -c {shlex.quote(install)} && exec python3 "$BOX_ROOT/supervisor.py" --root "$BOX_ROOT" {shlex.join(args)}'
    backstop_s = int(lease.ceiling - time.time()) + BACKSTOP_MARGIN_S
    assert backstop_s > BACKSTOP_MARGIN_S, backstop_s
    machine = provider.launch(
        gpu=gpu, image=image, entrypoint=["bash", "-c", boot],
        env={**(env or {}), "BOX_SUPERVISOR": supervisor_env()},
        labels={
            **(labels or {}), LABEL_BY: "box", LABEL_SESSION: session_id, LABEL_CEILING: str(int(lease.ceiling)),
            LABEL_IDLE: f"{idle_timeout_s:g}", LABEL_PORTS: ",".join(map(str, ports)), **({LABEL_NAME: name} if name else {}),
        },
        timeout_s=backstop_s, ports=list(ports), mounts=[Mount(record, record_prefix(session_id), RECORD_PATH)] if record else [],
    )  # fmt: skip
    if record:
        try:
            launched = {"machine_id": machine.id, "provider": provider.name, "labels": machine.labels, "at": time.time()}
            record.put(f"{record_prefix(session_id)}/launch.json", json.dumps(launched).encode())
        except BaseException:
            machine.terminate()
            raise
    return Session(machine, record=record)


def _create_set_up(provider: Provider, spec: SetupSpec, *, image: str | None, env: dict[str, str], **kw: Any) -> Session:  # MUST KILL: narrowing the checker can't follow (`snaps` holds an isinstance, record checked non-None earlier: three type: ignores); split the snapshot path into a function taking a Snapshotter and a Store
    from box import setup_cache as sc

    record: Store | None = kw["record"]
    snapping: tuple[sc.Snapshotter, Store] | None = None
    if isinstance(provider, sc.Snapshotter):
        if record is None:
            raise Refused(f"{provider.name} provider snapshots its setup: pass record= (the store that remembers which snapshot a key is)")
        snapping = (provider, record)
    key = sc.setup_key(spec, provider=provider.name, image=image)
    cached = None
    if snapping is not None and not spec.rebuild:
        cached = sc.lookup(snapping[1], key, now=time.time(), max_age_s=spec.max_age_s)
    session, began, timings = None, time.monotonic(), {}

    def lap(phase: str) -> None:
        timings[phase] = round(time.monotonic() - began - sum(timings.values()), 3)

    if cached is not None:
        try:
            session = _create(provider, image=cached.image, env=env, fresh_root=True, **kw)
        except LookupError as e:
            print(f"box: setup {key[:12]}: snapshot {cached.image} is gone ({e}); setting up again", file=sys.stderr)
            cached = None
    if session is None:
        session = _create(provider, image=image, env=env, **kw)
    try:
        session.wait_up(SETUP_BOOT_TIMEOUT_S)
        lap("boot")
        synced = session.sync(spec.repo, paths=spec.paths)
        lap("sync")
        setup_job, made, built_at = None, cached.image if cached else None, cached.built_at if cached else None
        if cached is None:
            setup_job = session._run_to_end(sc.script_cmd(synced.path, spec.script, unset=list(env)), spec.max_duration_s, "setup")
            lap("setup")
            if snapping is not None:
                snapshotter, cache = snapping
                made = snapshotter.snapshot(session.machine, ttl_s=int(spec.max_age_s + sc.SNAPSHOT_TTL_MARGIN_S))
                built_at = time.time()
                sc.remember(cache, sc.Cached(key, made, built_at, session.id, synced.commit))
                lap("snapshot")
        resume_job = None
        if spec.resume is not None:
            resume_job = session._run_to_end(sc.script_cmd(synced.path, spec.resume, unset=[]), spec.max_duration_s, "resume")
            lap("resume")
        if record is not None:
            prepared = SetupRecord(key=key, hit=cached is not None, image=made, base=image or "", built_at=built_at,
                                   setup_job=setup_job, resume_job=resume_job, timings=timings)  # fmt: skip
            record.put(f"{record_prefix(session.id)}/setup.json", sc.setup_record_json(prepared))
    except BaseException:
        try:
            session.close()
        except NotGone:
            raise
        except (Gone, OSError) as e:
            print(f"box: {session.id}: closing after a failed setup failed too ({e!r}); terminating", file=sys.stderr)
            session.machine.terminate()
        except BaseException:
            session.machine.terminate()
            raise
        raise
    return session


def supervisor_env() -> str:
    value = base64.b64encode(zlib.compress(SUPERVISOR.read_bytes(), 9)).decode()
    assert len(value) <= MAX_ENV_VALUE, f"the supervisor is {len(value)} bytes as BOX_SUPERVISOR; Modal takes {MAX_ENV_VALUE}"
    return value


def new_session_id() -> str:
    return f"s-{secrets.token_hex(6)}"


def attach(provider: Provider, *, session_id: str | None = None, name: str | None = None, record: Store | None = None) -> Session:
    if (session_id is None) == (name is None):
        raise Refused("attach: pass exactly one of session_id or name")
    found = _find(provider, {LABEL_SESSION: session_id} if name is None else {LABEL_NAME: name}, record)
    if found is not None:
        return found
    if record is None or session_id is None:
        raise LookupError(f"{provider.name} provider: no live machine for session {session_id or repr(name)}")
    return Session(None, record, read_record(record, session_id))


def _find(provider: Provider, labels: dict[str, str], record: Store | None = None) -> Session | None:
    found = provider.list(labels)
    if len(found) > 1:
        raise LookupError(f"{provider.name} provider: {len(found)} live machines for {labels}: {[m.id for m in found]}")
    return Session(found[0], record=record) if found else None


def find_or_create(provider: Provider, name: str, **create_kw: Any) -> tuple[Session, bool]:
    for _ in range(NAME_TRIES):
        found = _find(provider, {LABEL_NAME: name}, create_kw.get("record"))
        if found is not None and not isinstance(found.status(), Ended):
            return found, False
        if found is not None:
            found.close()
        try:
            return create(provider, name=name, **create_kw), True
        except NameTaken:
            continue
    raise NameTaken(f"{provider.name} provider: {name!r}: taken, then gone, {NAME_TRIES} times in a row")


def declared_ports(labels: dict[str, str]) -> tuple[int, ...]:
    return tuple(int(p) for p in labels.get(LABEL_PORTS, "").split(",") if p)


def record_prefix(session_id: str) -> str:
    if not SESSION_ID.fullmatch(session_id):
        raise Refused(f"not a session id: {session_id!r}")
    return f"sessions/{session_id}"


class Session:
    def __init__(self, machine: Machine | None, record: Store | None = None, place: Place | None = None) -> None:
        assert machine is not None or place is not None, "a Session needs a machine or its record"
        self.machine = machine
        self.record = record
        self.place: Place = place or Live(machine)
        self._ended: Ended | None = None
        self._endpoints: dict[int, Endpoint] = {}

    @property
    def labels(self) -> dict[str, str]:
        return self.place.labels

    @property
    def id(self) -> str:
        return self.labels[LABEL_SESSION]

    @property
    def name(self) -> str | None:
        return self.labels.get(LABEL_NAME)

    def _live(self) -> Machine:
        if self.machine is None:
            raise Gone(f"{self.id}: gone (known from its record)")
        return self.machine

    def __enter__(self) -> Session:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def wait_up(self, timeout_s: float) -> None:
        give_up = time.monotonic() + timeout_s
        while not self._up():
            if time.monotonic() > give_up:
                raise TimeoutError(f"{self._live().id}: supervisor not up after {timeout_s:.0f} s")
            time.sleep(POLL_S)

    def _up(self) -> bool:
        rc, out, _ = self._live().exec(f"cat {self._path(UP)}")
        return rc == 0 and out.strip() == self.id

    def extend(self, until: float) -> Lease:
        return self._change_lease("extend", until)

    def release(self) -> Lease:
        return self._change_lease("release", 0.0)

    @contextlib.contextmanager
    def keep(self, every_s: float) -> Generator[Lease]:
        if not MIN_KEEP_EVERY_S <= every_s <= MAX_KEEP_EVERY_S:
            raise Refused(f"every_s={every_s}: keep() renews every {MIN_KEEP_EVERY_S} to {MAX_KEEP_EVERY_S} s")
        lease = self.extend(time.time() + 2 * every_s)
        stop = threading.Event()
        failed: list[Exception] = []
        renewer = threading.Thread(target=self._renew, args=(every_s, stop, failed), daemon=False, name=f"box-keep-{self.id}")
        renewer.start()
        try:
            yield lease
        finally:
            stop.set()
            try:
                with contextlib.suppress(Gone):
                    self.release()
            finally:
                renewer.join()
                assert not renewer.is_alive()
        if failed:
            raise failed[0]

    def _renew(self, every_s: float, stop: threading.Event, failed: list[Exception]) -> None:
        while not stop.wait(every_s):
            try:
                lease = self.extend(time.time() + 2 * every_s)
            except Gone:
                return
            except (Dropped, TimeoutError) as exc:
                print(f"box: {self.id}: renewing the lease failed, retrying: {exc!r}", file=sys.stderr)
                continue
            except Exception as exc:
                failed.append(exc)
                raise
            if lease.until <= time.time():
                return

    def _change_lease(self, op: Literal["extend", "release"], until: float) -> Lease:
        root = self._live().root
        argv = ["python3", f"{root}/supervisor.py", "lease", "--root", root, "--op", op, "--until", repr(until),
                "--host", socket.gethostname(), "--pid", str(os.getpid())]  # fmt: skip
        return load(Lease, self._check(shlex.join(argv)).encode())

    def close(self, timeout_s: float = 900.0, gone_timeout_s: float = GONE_TIMEOUT_S) -> Receipt:
        assert timeout_s > 0, timeout_s
        assert gone_timeout_s > 0, gone_timeout_s
        ended = self._stop_and_wait(timeout_s)
        gone_at = self._terminate(gone_timeout_s)
        if ended is None:
            ended = self.status()
            assert isinstance(ended, Ended), ended
        receipt = Receipt(session_id=self.id, machine_id=self.place.machine_id, ended=ended, machine_gone_at=gone_at)
        if self.record is not None:
            self.record.put(f"{record_prefix(self.id)}/receipt.json", receipt_json(receipt))
        return receipt

    def _stop_and_wait(self, timeout_s: float) -> Ended | None:
        if not isinstance(self.status(), Ended):
            with contextlib.suppress(Gone):
                self._live().exec(f"mkdir -p {self._live().root} && touch {self._path(WATCH)} {self._path(STOP)}")
        try:
            return self.wait(timeout_s)
        except TimeoutError:
            return None

    def _terminate(self, timeout_s: float) -> float:
        if self.machine is None:
            return time.time()
        self.machine.terminate()
        give_up = time.monotonic() + timeout_s
        while not self.machine.gone():
            if time.monotonic() > give_up:
                raise NotGone(f"{self.id}: {self.machine.id} terminated, but its provider still has it after {timeout_s:.0f} s")
            time.sleep(POLL_S)
        return time.time()

    def expose(self, port: int) -> Endpoint:
        if not 0 < port < 65536:
            raise Refused(f"port {port}: not a TCP port")
        if port in self._endpoints:
            return self._endpoints[port]
        endpoint = self._live().expose(port)
        if not endpoint.headers:
            self._endpoints[port] = endpoint
        return endpoint

    def proxy(self, port: int, *, local_port: int = 0) -> Proxy:
        from box.proxy import Proxy

        return Proxy(self.expose(port), port=local_port, on_use=self.touch, every_s=self._keepalive_every_s())

    def stream(  # noqa: PLR0913
        self, cmd: str, *, cwd: str | None = None, pty: bool = False, timeout_s: float | None = None, quiet_s: float | None = None,
    ) -> Stream:  # fmt: skip
        running = self._running_now()
        left = running.lease.ceiling - time.time()
        timeout_s = left if timeout_s is None else timeout_s
        if not 0 < timeout_s <= left:
            raise Refused(f"timeout_s={timeout_s}: more than 0 and at most the {left:.0f} s to the session's ceiling")
        inner = f"cd {shlex.quote(cwd)} && {cmd}" if cwd else cmd
        then = f"exec bash -c {shlex.quote(inner)}"
        return self._live().stream(self._keepalive(then, until=time.time() + timeout_s), timeout_s=timeout_s, quiet_s=quiet_s, pty=pty)

    def shell(self, cwd: str | None = None) -> Shell:
        running = self._running_now()
        start = f"cd {shlex.quote(cwd)} && " if cwd else ""
        return self._live().shell(self._keepalive(f"{start}exec bash -l", until=running.lease.ceiling))

    def sync(self, repo: str | Path, *, paths: tuple[str, ...] = (), force: bool = False) -> Synced:
        from box import gitsync

        keep = f"refs/box/{self.name or self.id}"
        synced = gitsync.sync(self._live(), Path(repo), paths=paths, force=force, keep=keep, touch=self._path(ACTIVITY))
        if self.record is not None:
            entry = {"commit": synced.commit, "path": synced.path, "pack_bytes": synced.pack_bytes, "local": str(Path(repo).resolve()), "at": time.time()}
            self.record.put(f"{record_prefix(self.id)}/syncs/{time.time_ns()}.json", json.dumps(entry).encode())
        return synced

    def touch(self) -> None:
        self._touch(ACTIVITY)

    def _keepalive_every_s(self) -> float:
        idle_s = float(self.labels.get(LABEL_IDLE) or 0)
        return max(MIN_KEEPALIVE_S, min(KEEPALIVE_S, idle_s / 4)) if idle_s else KEEPALIVE_S

    def _keepalive(self, then: str, *, until: float) -> str:
        activity = shlex.quote(self._path(ACTIVITY))
        loop = (f"while kill -0 $$ 2>/dev/null; do touch {activity}; "
                f"if [ $(date +%s) -ge {int(until)} ]; then kill -HUP $$; exit; fi; sleep {self._keepalive_every_s():g}; done")  # fmt: skip
        # braced: `x && ( loop ) &` would background x too, in a shell that holds the caller's stdout open
        return f"{{ ( {loop} ) </dev/null >/dev/null 2>&1 & }} && {then}"

    def status(self) -> Status:
        return self._status(watch=False)

    def wait(self, timeout_s: float | None = None) -> Ended:
        give_up = None if timeout_s is None else time.monotonic() + timeout_s
        while not isinstance(status := self._status(watch=True), Ended):
            if give_up is not None and time.monotonic() > give_up:
                raise TimeoutError(f"{self.id}: still {status} after {timeout_s:.0f} s")
            time.sleep(POLL_S)
        return status

    def _status(self, *, watch: bool) -> Status:
        give_up = time.monotonic() + HEARTBEAT_TTL_S
        while (status := self._ended or self._status_now(watch=watch)) is None:
            if time.monotonic() > give_up:
                status = Ended("machine_lost")
                break
            time.sleep(POLL_S)
        if isinstance(status, Ended):
            self._ended = status
        return status

    def _status_now(self, *, watch: bool) -> Status | None:
        try:
            files = self._read(dict.fromkeys(STATUS_FILES, 0), watch=watch)
        except Gone:
            return Ended("machine_lost")
        return parse_status(files, gone=self.place.gone, now=time.time())

    def started_at(self) -> float | None:
        raw = self._read({SESSION: 0})[SESSION]
        return None if raw is None else load(Started, raw).started_at

    def _read(self, rels: dict[str, int], *, watch: bool = False) -> dict[str, bytes | None]:
        return self._ask(lambda place: place.read(rels, watch=watch))

    def _ask(self, ask: Callable[[Place], T]) -> T:
        try:
            return ask(self.place)
        except Gone:
            if self.record is None:
                raise
            self.place = Record(self.record, self.place.machine_id, self.place.labels)
            return ask(self.place)

    def run(  # noqa: PLR0913
        self, cmd: str, *, max_duration_s: float = 1800.0, on_exit: str | None = None, hook_budget_s: float = 300.0,
        env: dict[str, str] | None = None,
    ) -> Job:  # fmt: skip
        if not 0 < max_duration_s <= MAX_CEILING_S:
            raise Refused(f"max_duration_s={max_duration_s}: more than 0 and at most {MAX_CEILING_S} s")
        running = self._running_now()
        left = min(running.lease.until, running.lease.ceiling) - time.time()
        if on_exit and hook_budget_s >= left:
            raise Refused(f"hook_budget_s={hook_budget_s} does not fit in the lease's {left:.0f} s left")
        spec = {"cmd": cmd, "on_exit": on_exit, "hook_budget_s": hook_budget_s, "max_duration_s": max_duration_s, "env": env or {}}
        return self._start(Job(self, new_job_id(), "jobs"), spec)

    def _run_to_end(self, cmd: str, max_duration_s: float, what: str) -> str:
        job = self.run(cmd, max_duration_s=max_duration_s)
        ending = job.wait()
        if ending != Ending("exited", 0):
            out = "".join(chunk.text for chunk in job.logs())[-SETUP_FAIL_TAIL:]
            raise SetupFailed(f"{self.id}: {what} ({cmd}) ended {ending.reason}, exit {ending.exit_code}:\n{out}")
        return job.id

    def serve(self, cmd: str, *, env: dict[str, str] | None = None, name: str | None = None) -> Job:
        self._running_now()
        if name is not None and not SERVICE_NAME.fullmatch(name):
            raise Refused(f"service name {name!r}: a lowercase letter, then lowercase letters, digits or '-', at most 32")
        started = [job.id for job in self.jobs("services")]
        if len(started) >= MAX_SERVICES:
            raise Refused(f"{self.id}: a session runs at most {MAX_SERVICES} services")
        if name in started:
            raise Refused(f"{self.id}: a service is already named {name!r}")
        return self._start(Job(self, name or new_job_id(), "services"), {"cmd": cmd, "env": env or {}})

    def _running_now(self) -> Running:
        running = self.status()
        if not isinstance(running, Running):
            raise RuntimeError(f"{self.id}: cannot start anything on a session that is {running}")
        return running

    def _start(self, job: Job, spec: dict) -> Job:
        tmp = self._path(f"{job.kind}/{job.id}.spec.tmp")
        self._live().write(tmp, json.dumps(spec).encode())
        work, code = shlex.quote(self._live().work), shlex.quote(f"{job.dir}/code")
        heads = (f'for t in {work}/*/; do if [ -e "$t.git" ] && h=$(git -C "$t" rev-parse HEAD 2>/dev/null); '
                 f'then mkdir -p {code} && echo "$h" > {code}/"$(basename "$t")"; fi; done; ')  # fmt: skip
        self._check(f"{heads}mkdir -p {job.dir} && mv {tmp} {job.dir}/spec.json")
        return job

    def put(self, local: str | Path, remote: str, ignore: tuple[str, ...] = ()) -> None:
        root = Path(local)
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            for child in sorted(root.iterdir()):
                tar.add(child, arcname=child.name, filter=lambda i: None if ignored(i.name, ignore) else i)
        tmp = self._path(f"put-{secrets.token_hex(3)}.tgz")
        self._live().write(tmp, buf.getvalue())
        self._check(f"mkdir -p {shlex.quote(remote)} && tar xzf {tmp} --no-same-owner -C {shlex.quote(remote)} && rm {tmp}")

    def get(self, remote: str, local: str | Path) -> None:
        tmp = self._path(f"get-{secrets.token_hex(3)}.tgz")
        self._check(f"tar czf {tmp} -C {shlex.quote(remote)} .")
        data = self._live().read(tmp)
        self._live().exec(f"rm -f {tmp}")
        with tarfile.open(fileobj=io.BytesIO(data)) as tar:
            tar.extractall(local, filter="data")

    def jobs(self, kind: Kind = "jobs") -> list[Job]:
        return [Job(self, job_id, kind) for job_id in self._ask(lambda place: place.jobs(kind))]

    def _path(self, rel: str) -> str:
        return f"{self._live().root}/{rel}"

    def _touch(self, rel: str) -> None:
        self._check(f"touch {self._path(rel)}")

    def _check(self, cmd: str) -> str:
        rc, out, err = self._live().exec(cmd)
        if rc != 0:
            raise RuntimeError(f"{self.id}: `{cmd}` exited {rc}: {err.strip()}")
        return out


def new_job_id() -> str:
    return f"{int(time.time())}-{secrets.token_hex(3)}"


@dataclass(frozen=True)
class Job:
    session: Session
    id: str
    kind: Kind = "jobs"

    @property
    def dir(self) -> str:
        return self.session._path(self.rel)

    @property
    def rel(self) -> str:
        return f"{self.kind}/{self.id}"

    def status(self) -> JobStatus:
        return self.read(None).status

    def wait(self) -> Ending:
        while True:
            final = self.session.place.gone and isinstance(self.session.status(), Ended)
            status = self.read(None, watch=True).status
            if isinstance(status, Done):
                return status.ending
            if final:
                raise Gone(f"{self.session.id}: its machine went before {self.id} ended ({status})")
            time.sleep(POLL_S)

    def kill(self) -> None:
        self.session._touch(f"{self.rel}/{KILL}")

    def logs(self, *, after: LogCursor = (0, 0), follow: bool = False, stop: threading.Event | None = None) -> Iterator[LogChunk]:
        if follow:
            yield from self._follow(after, stop)
            return
        read = JobRead(Queued(), [], more=True)
        while read.more:
            read = self.read(read.chunks[-1].end if read.chunks else after)
            yield from read.chunks

    def _follow(self, cursor: LogCursor, stop: threading.Event | None) -> Iterator[LogChunk]:
        tries = 0
        while stop is None or not stop.is_set():
            tail = TailReader(cursor)
            try:
                for chunk in self._tail(tail, stop):
                    cursor = chunk.end
                    yield chunk
            except Gone:
                self.session.wait()
                yield from self.logs(after=cursor)
                return
            except Dropped as e:
                tries = 1 if tail.frames else tries + 1
                if tries > FOLLOW_TRIES:
                    raise
                print(f"box: {self.session.id}: following {self.id} dropped ({e!r}); reconnecting from {cursor}", file=sys.stderr)
                (stop or threading.Event()).wait(FOLLOW_BACKOFF_S * tries)
                continue
            if tail.end in ("done", "ended"):
                return
            if tail.end is None and not (stop and stop.is_set()):
                raise TailError(f"{self.id}: the log tail exited {tail.rc} without an end: {tail.errors.decode(errors='replace').strip()!r}")

    def _tail(self, tail: TailReader, stop: threading.Event | None) -> Iterator[LogChunk]:
        cmd = f"exec python3 {shlex.quote(self.session._path('supervisor.py'))} tail {shlex.quote(self.dir)} {tail.cursor[0]} {tail.cursor[1]}"
        with self.session._live().stream(cmd, timeout_s=TAIL_MAX_S + 60, quiet_s=FOLLOW_QUIET_S) as stream:
            for name, data in stream:
                if name == "stderr":
                    tail.errors = (tail.errors + data)[-TAIL_ERR_BYTES:]
                    continue
                yield from tail.feed(data)
                if stop is not None and stop.is_set():
                    return
        tail.rc = stream.rc

    def read(self, after: LogCursor | None, *, watch: bool = False) -> JobRead:
        streams = {} if after is None else {f"{self.rel}/{name}": offset for name, offset in zip(STREAMS, after, strict=True)}
        files = self.session._read({f"{self.rel}/{STATUS}": 0, **streams}, watch=watch)
        raw = files[f"{self.rel}/{STATUS}"]
        status = Queued() if raw is None else load_job(raw)
        chunks, cursor, more = [], after, False
        for name, rel in zip(STREAMS, streams, strict=False):
            data = files[rel] or b""
            full = len(data) == MAX_LOG_READ
            more = more or full
            cut = len(data) if isinstance(status, Done) and not full else utf8_cut(data)
            if cut:
                cursor = advance(cursor, name, cut)
                chunks.append(LogChunk(name, data[:cut].decode(errors="replace"), cursor))
        return JobRead(status, chunks, more)


def advance(cursor: LogCursor, stream: str, n: int) -> LogCursor:
    assert stream in STREAMS, stream
    return (cursor[0] + n, cursor[1]) if stream == "stdout" else (cursor[0], cursor[1] + n)


@dataclass(frozen=True)
class JobRead:
    status: JobStatus
    chunks: list[LogChunk]
    more: bool = False

    @property
    def done(self) -> bool:
        return isinstance(self.status, Done)


@dataclass(frozen=True)
class LogChunk:
    stream: Literal["stdout", "stderr"]
    text: str
    end: LogCursor


class TailError(RuntimeError):
    pass


class TailReader:
    def __init__(self, after: LogCursor) -> None:
        self.cursor = after
        self.end: str | None = None
        self.frames = 0
        self.rc: int | None = None
        self.errors = b""
        self._held = dict.fromkeys(STREAMS, b"")
        self._buf = b""

    def feed(self, data: bytes) -> list[LogChunk]:
        self._buf += data
        chunks: list[LogChunk] = []
        while self.end is None:
            header, sep, rest = self._buf.partition(b"\n")
            if not sep:
                if len(self._buf) > 64:
                    raise TailError(f"log tail sent no frame header: {self._buf[:64]!r}")
                break
            word, _, arg = header.decode(errors="replace").partition(" ")
            self.frames += 1
            if word in STREAMS:
                n = int(arg)
                if not 0 < n <= TAIL_FRAME_BYTES:
                    raise TailError(f"log tail frame of {n} bytes (at most {TAIL_FRAME_BYTES})")
                if len(rest) < n:
                    break
                chunks += self._text(word, rest[:n], whole=False)
                self._buf = rest[n:]
            elif word == "beat":
                self._buf = rest
            elif word == "end" and arg in ("done", "ended", "max"):
                self._buf, self.end = rest, arg
                if arg == "done":
                    chunks += [c for stream in STREAMS for c in self._text(stream, b"", whole=True)]
            else:
                raise TailError(f"log tail sent {header[:64]!r}")
        return chunks

    def _text(self, stream: str, data: bytes, *, whole: bool) -> list[LogChunk]:
        raw = self._held[stream] + data
        cut = len(raw) if whole else utf8_cut(raw)
        self._held[stream] = raw[cut:]
        if not cut:
            return []
        self.cursor = advance(self.cursor, stream, cut)
        return [LogChunk(stream, raw[:cut].decode(errors="replace"), self.cursor)]


def run_job(
    provider: Provider, cmd: str, *, max_duration_s: float, put: list[tuple[str, str]] = (),
    get: list[tuple[str, str]] = (), on_exit: str | None = None, **launch_kw: object,
) -> Ending:  # fmt: skip
    with launch(provider, **launch_kw) as s:
        for local, remote in put:
            s.put(local, remote)
        job = s.run(cmd, max_duration_s=max_duration_s, on_exit=on_exit)
        sinks = {"stdout": sys.stdout, "stderr": sys.stderr}
        for chunk in job.logs(follow=True):
            sinks[chunk.stream].write(chunk.text)
            sinks[chunk.stream].flush()
        ending = job.wait()
        for remote, local in get:
            s.get(remote, local)
    return ending


STATUS_FILES = (ENDED, UP, SESSION, LEASE, HEARTBEAT)


def parse_status(files: dict[str, bytes | None], *, gone: bool, now: float) -> Status | None:
    if (ended := files[ENDED]) is not None:
        return load_ended(ended)
    if files[UP] is not None:
        return Running(started_at=load(Started, files[SESSION]).started_at, lease=load(Lease, files[LEASE]))
    if not gone:
        return Booting()
    beat = files[HEARTBEAT]
    return None if beat is not None and load(Heartbeat, beat).fresh(now) else Ended("machine_lost")


class Place(Protocol):
    gone: bool
    machine_id: str
    labels: dict[str, str]

    def read(self, rels: dict[str, int], *, watch: bool = False) -> dict[str, bytes | None]: ...
    def jobs(self, kind: Kind) -> list[str]: ...


@dataclass(frozen=True)
class Live:
    machine: Machine
    gone = False

    @property
    def machine_id(self) -> str:
        return self.machine.id

    @property
    def labels(self) -> dict[str, str]:
        return self.machine.labels

    def read(self, rels: dict[str, int], *, watch: bool = False) -> dict[str, bytes | None]:
        each = [f"if [ -e {shlex.quote(rel)} ]; then tail -c +{offset + 1} {shlex.quote(rel)} | head -c {MAX_LOG_READ} | base64 | tr -d '\\n'; else printf -; fi; echo"
                for rel, offset in rels.items()]  # fmt: skip
        out = self._check("; ".join([f"cd {shlex.quote(self.machine.root)} 2>/dev/null || exit 0", *([f"touch {WATCH}"] if watch else []), *each]))
        if not out:
            return dict.fromkeys(rels)
        lines = out.split("\n")
        if len(lines) != len(rels) + 1 or lines[-1]:
            raise RuntimeError(f"{self.machine.id}: reading {len(rels)} files gave {len(lines) - 1} lines")
        return {rel: None if line == "-" else base64.b64decode(line) for rel, line in zip(rels, lines, strict=False)}

    def jobs(self, kind: Kind) -> list[str]:
        return sorted(name for name in self._check(f"ls {shlex.quote(f'{self.machine.root}/{kind}')}").split() if not name.endswith(".tmp"))

    def _check(self, cmd: str) -> str:
        rc, out, err = self.machine.exec(cmd)
        if rc != 0:
            raise RuntimeError(f"{self.machine.id}: `{cmd[:200]}` exited {rc}: {err.strip()}")
        return out


@dataclass(frozen=True)
class Record:
    store: Store
    machine_id: str
    labels: dict[str, str]
    gone = True

    @property
    def prefix(self) -> str:
        return record_prefix(self.labels[LABEL_SESSION])

    def read(self, rels: dict[str, int], *, watch: bool = False) -> dict[str, bytes | None]:
        return {rel: self._output(rel, offset) if rel.rsplit("/", 1)[-1] in STREAMS else self._file(rel) for rel, offset in rels.items()}

    def jobs(self, kind: Kind) -> list[str]:
        prefix = f"{self.prefix}/{kind}/"
        return sorted({key[len(prefix) :].split("/", 1)[0] for key in self.store.list(prefix)})

    def receipt(self) -> Receipt | None:
        return self._load("receipt.json", parse_receipt)

    def setup(self) -> SetupRecord | None:
        return self._load("setup.json", parse_setup_record)

    def lease_audit(self) -> list[LeaseChange]:
        return self._load(AUDIT, load_audit) or []

    def syncs(self) -> list[dict]:
        prefix = f"{self.prefix}/syncs/"
        return [json.loads(self.store.get(key)) for key in sorted(self.store.list(prefix), key=lambda k: int(k[len(prefix) :].split(".")[0]))]

    def job_code(self, job_id: str, kind: Kind = "jobs") -> dict[str, str]:
        prefix = f"{self.prefix}/{kind}/{job_id}/code/"
        return {key[len(prefix) :]: self.store.get(key).decode().strip() for key in self.store.list(prefix)}

    def _load(self, rel: str, parse: Callable[[bytes], T]) -> T | None:  # noqa: UP047
        raw = self._file(rel)
        return None if raw is None else parse(raw)

    def _file(self, rel: str) -> bytes | None:
        try:
            return self.store.get(f"{self.prefix}/{rel}")
        except FileNotFoundError:
            return None

    def _output(self, rel: str, offset: int) -> bytes:
        job, stream = rel.rsplit("/", 1)
        prefix = f"{self.prefix}/{job}/"
        chunks = sorted((*parsed, key) for key in self.store.list(prefix) if (parsed := parse_chunk(key[len(prefix) :])) is not None)
        data, begin = b"", 0
        for _n, name, end, key in chunks:
            if name != stream:
                continue
            if end > offset and len(data) < MAX_LOG_READ:
                got = self.store.get(key)
                if len(got) != end - begin:
                    raise ValueError(f"{self.store.uri}: {key} holds {len(got)} bytes; its name says {end - begin}")
                data += got[max(0, offset - begin) :]
            begin = end
        return data[:MAX_LOG_READ]


def read_record(store: Store, session_id: str) -> Record:
    prefix = record_prefix(session_id)
    try:
        launched = json.loads(store.get(f"{prefix}/launch.json"))
    except FileNotFoundError as e:
        raise LookupError(f"{store.uri}: no record of session {session_id}") from e
    if launched["labels"].get(LABEL_SESSION) != session_id:
        raise ValueError(f"{store.uri}: {prefix}/launch.json is for session {launched['labels'].get(LABEL_SESSION)!r}")
    return Record(store, str(launched["machine_id"]), dict(launched["labels"]))


def receipt_json(receipt: Receipt) -> bytes:
    assert SESSION_ID.fullmatch(receipt.session_id), receipt
    assert receipt.ended.reason in get_args(EndReason), receipt
    assert receipt.machine_gone_at > 0, receipt
    d = {"session_id": receipt.session_id, "machine_id": receipt.machine_id, "reason": receipt.ended.reason,
         "supervisor_confirmed": receipt.supervisor_confirmed, "machine_gone_at": receipt.machine_gone_at}  # fmt: skip
    return json.dumps(d).encode()


def parse_receipt(raw: bytes) -> Receipt:
    d = json.loads(raw)
    receipt = Receipt(str(d["session_id"]), str(d["machine_id"]), Ended(d["reason"]), float(d["machine_gone_at"]))
    if not SESSION_ID.fullmatch(receipt.session_id):
        raise ValueError(f"receipt.json: not a session id: {receipt.session_id!r}")
    if d["supervisor_confirmed"] is not receipt.supervisor_confirmed:
        raise ValueError(f"receipt.json: supervisor_confirmed {d['supervisor_confirmed']!r} contradicts reason {receipt.ended.reason!r}")
    return receipt


def ignored(rel: str, ignore: tuple[str, ...]) -> bool:
    return any(fnmatch(rel, g) or (g.startswith("**/") and fnmatch(rel.rsplit("/", 1)[-1], g[3:])) for g in ignore)
