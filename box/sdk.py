"""box: rent a machine, run jobs on it, bring results back, and never leave it billing.

    with box.launch(provider, gpu="L4", image=IMAGE, lease_s=5400, ceiling_s=8 * 3600) as s:   # a Session
        s.put("robots", "/work/robots")
        job = s.run("cd /work && python robots/train.py", max_duration_s=3600, on_exit="upload.sh")
        for chunk in job.logs(follow=True): ...   # LogChunk(stream, text, end)
        ending = job.wait()                  # Ending(reason="exited", exit_code=0, ...)
        s.get("/work/runs", "runs")
    # leaving the block ends the session: a running job is killed and its hook still runs
    s.status()                               # Ended(reason="stopped")
    s.close()                                # -> Receipt(session_id, machine_id, ended, machine_gone_at): the
                                             #    supervisor's end, then the provider's word the machine is gone

    s = box.launch(provider, lease_s=600, ceiling_s=8 * 3600)   # detached: nothing ends it but its lease
    s.extend(time.time() + 3600)             # -> Lease(until, ceiling): clamped to the ceiling, never shorter
    with s.keep(every_s=60): ...             # interactive: renews to now + 120 s each minute, releases on exit
    s.release()                              # until = now: ends it (reason "released"), hooks still run

    s = box.attach(provider, session_id)     # from anywhere, by the session's own id
    match s.status():                        # Booting() | Running(started_at, lease) | Ended(reason)
        case Running(): s.wait()             # -> Ended: the awaitable terminal state

    with box.launch(provider, ceiling_s=3600, ports=[8888]) as s:   # ports: declared at launch
        s.serve("jupyter server --port 8888 ...")   # a service: beside the job queue, until the session ends
        s.expose(8888)                       # Endpoint(url="https://...", headers={})

    s = box.launch(provider, ceiling_s=3600, record=store)   # the supervisor records into store (box/store.py)
    box.attach(provider, s.id, record=store).wait()           # works after the machine is gone too
    job.logs(after=chunk.end)                # resumes where a reader left off, live or from the record
    r = box.read_record(store, s.id)         # Record: no machine, no provider needed

A provider only rents raw machines (Machine: exec, stream, write, read, terminate, gone). Everything else is
here, built from those calls and the supervisor (box/supervisor.py), which every machine
runs as its entrypoint and which talks to this file only through files under machine.root.

One lease ends a session: at min(lease.until, ceiling), both absolute unix times. Callers pass
durations to create() only; it parses them into those times once, and nothing after handles a
duration. The provider credential is the authority over a session (one person per credential):
anyone holding it can extend, release, or close; each lease change is audited (who, when) in
ROOT/lease-audit.json and the record, for debugging, enforcing nothing.
"""

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
from typing import Any, Literal, Protocol, TypeVar, get_args

from box.store import Mount, Store
from box.supervisor import HEARTBEAT_TTL_S, KINDS, MAX_CEILING_S, MAX_SERVICES, TAIL_FRAME_BYTES, TAIL_MAX_S, utf8_cut

SUPERVISOR = Path(__file__).with_name("supervisor.py")
LABEL_BY = "box.by"
LABEL_SESSION = "box.session"  # the session's own id: a session is not its machine, even while 1:1
LABEL_CEILING = "box.ceiling"  # unix time no lease of the session can pass (`box who`, `box gc`)
RESERVED = (LABEL_BY, LABEL_SESSION, LABEL_CEILING)  # launch stamps these; a caller's labels are the rest
CEILING_S = 3600  # create()'s default ceiling, from creation
BACKSTOP_MARGIN_S = 600  # the provider's own hard stop comes this long after the ceiling
MAX_ENV_VALUE = 32768  # bytes: Modal's limit on one environment value (Sandbox.create passes env as a secret)
MIN_KEEP_EVERY_S = 0.5  # keep(): each renewal is an exec (~0.1-0.5 s on a cloud); more often is a storm, not keep-alive
MAX_KEEP_EVERY_S = 3600  # keep(): renewing less often than hourly is a lease, not keep-alive
POLL_S = 0.5
RECORD_PATH = "record"  # where a session's record is mounted on its machine, under the supervisor's root
SESSION_ID = re.compile(r"s-[0-9a-f]{12}")  # new_session_id()'s shape
T = TypeVar("T")
STREAMS = ("stdout", "stderr")
LogCursor = tuple[int, int]  # bytes of (stdout, stderr) a reader has had: where it resumes, live or from the record
MAX_LOG_READ = 4 * 1024 * 1024  # bytes of one stream one exec brings back; more is read by the next
FOLLOW_QUIET_S = 10.0  # a follow stream with no frame this long (the tail beats every second) is dropped: reconnect
FOLLOW_TRIES = 5  # reconnects in a row with no frame in between; then the error is the caller's
FOLLOW_BACKOFF_S = 1.0  # before reconnect n: n times this
TAIL_ERR_BYTES = 4096  # the end of a tail's own stderr kept, to say why it failed


class Gone(Exception):
    """The machine no longer exists (ended, terminated, or lost by the provider)."""


class Stream(Protocol):
    """A command running on the machine (Machine.stream). Iterating yields (stream name, bytes) as the
    command writes them ("stdout" | "stderr"; chunked however the provider gets them) and ends when
    it exits; rc is then its exit code. close() (or leaving `with`), from any thread, kills it and
    ends an iteration in progress. Iterating raises Gone once the machine is gone, and TimeoutError
    past machine.stream's bounds; either way the command is killed."""

    rc: int | None

    def __iter__(self) -> Iterator[tuple[str, bytes]]: ...
    def close(self) -> None: ...
    def __enter__(self) -> Stream: ...
    def __exit__(self, *exc: object) -> None: ...


class Machine(Protocol):
    """What a provider rents: a machine running the supervisor, reachable by exec and files.
    Every method raises Gone once the machine no longer exists."""

    id: str
    labels: dict[str, str]
    root: str  # the supervisor's directory on the machine

    def exec(self, cmd: str) -> tuple[int, str, str]: ...  # bash on the machine: (rc, stdout, stderr)
    # bash on the machine, its output as it arrives. Bounded: killed (TimeoutError) past timeout_s, or
    # past quiet_s with no output. A provider that cannot stream may poll inside it; callers never know.
    def stream(self, cmd: str, *, timeout_s: float, quiet_s: float | None = None) -> Stream: ...
    def write(self, path: str, data: bytes) -> None: ...
    def read(self, path: str) -> bytes: ...  # FileNotFoundError if absent
    def terminate(self) -> None: ...  # hard stop, idempotent; no hooks run
    def expose(self, port: int) -> Endpoint: ...  # ValueError unless port was declared at launch
    # The provider's own word that this machine id runs nothing any more (no process, no bill): one
    # bounded check, never Gone (gone is the answer). Session.close polls it; a provider that cannot
    # say it honestly cannot be closed honestly, so it is required, as stream is.
    def gone(self) -> bool: ...


class Provider(Protocol):
    name: str

    def launch(  # noqa: PLR0913 (keyword-only: what a machine is made with)
        self, *, gpu: str | None, image: str | None, entrypoint: list[str], env: dict[str, str],
        labels: dict[str, str], timeout_s: int, ports: list[int], mounts: list[Mount],
    ) -> Machine: ...  # fmt: skip  # mounts: ValueError for a store this provider cannot mount
    def get(self, machine_id: str) -> Machine: ...  # LookupError if box did not launch it
    def list(self, labels: dict[str, str] | None = None) -> list[Machine]: ...  # live machines labelled LABEL_BY and all of labels
    # Releases what it holds open (Modal: its loop thread and client); idempotent. Its machines are
    # unreachable through it after (Modal raises). Whoever made a provider closes it, so every
    # provider has close, a no-op where nothing is held: `with contextlib.closing(provider):`.
    def close(self) -> None: ...


@dataclass(frozen=True)
class Endpoint:
    """A port on the machine, reachable from anywhere over HTTP(S), websockets included.
    headers: what every request must carry. Empty when the url alone reaches the port, as on every
    provider today: then whoever has the url does, and the service brings its own auth (Jupyter's
    token). A token-gated provider route (Modal's connect token) would fill it."""

    url: str  # no trailing slash; a request goes to url + path
    headers: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Booting:
    """The machine exists; its supervisor is not up yet (a session attached to mid-launch)."""


@dataclass(frozen=True)
class Lease:
    """When the session ends: until (unix time), which no extend can move past ceiling."""

    until: float
    ceiling: float


@dataclass(frozen=True)
class Running:
    """The supervisor is up and the session has not ended. Unix times, by the machine's clock."""

    started_at: float
    lease: Lease  # as of this status: an extend or a release changes it


EndReason = Literal["lease", "released", "stopped", "idle", "machine_lost"]


@dataclass(frozen=True)
class Ended:
    """Why a session ended. All but machine_lost are the supervisor's word (ROOT/ended.json).
    machine_lost: the machine is gone and this Session never read ended.json, so either it died
    (supervisor crash, provider loss, backstop timeout) or it ended and was gone before anyone read
    why (Session.wait() and close() read it before letting go, so they never see this for an end)."""

    reason: EndReason


Status = Booting | Running | Ended

GONE_TIMEOUT_S = 60.0  # close(): how long the provider gets to confirm the machine is gone (Modal: ~1-5 s after terminate)


class NotGone(TimeoutError):
    """close() terminated the machine, but the provider never said it was gone: it may still run
    (and bill). Never reported as a success: whoever sees this must look (box who, the console)."""


@dataclass(frozen=True)
class Receipt:
    """What Session.close() proves: the session ended (ended: the supervisor's word, or machine_lost
    if it never gave one) and then its provider said this exact machine is gone (machine_gone_at,
    unix time, this computer's clock). A receipt exists only once both are true: close() raises
    rather than make one without the second. The two facts are separate events, as seeker learned:
    a release is not a confirmed death."""

    session_id: str
    machine_id: str
    ended: Ended
    machine_gone_at: float

    # Derived, not a field: Ended's reasons other than machine_lost are by definition the supervisor's
    # own (ended.json), so a stored flag could only agree with ended or contradict it.
    @property
    def supervisor_confirmed(self) -> bool:
        """The supervisor said why it ended (False: it died, or close terminated it, before saying)."""
        return self.ended.reason != "machine_lost"


@dataclass(frozen=True)
class Ending:
    """How a job ended. reason: exited | killed | timeout (its max_duration_s) | lease | released |
    stopped (the session's end, or for lease, about to: killed hook_budget_s early, to leave its
    hook that time); a service also idle (the session's end), or refused (past MAX_SERVICES, never
    started)."""

    reason: str
    exit_code: int | None
    hook_exit_code: int | None = None


@dataclass(frozen=True)
class Queued:
    """The job waits its turn (a service: about to start). Also a job its record has no status for."""


@dataclass(frozen=True)
class JobRunning:
    started_at: float  # unix time, the machine's clock


@dataclass(frozen=True)
class Hooking:
    """The job ended (how: ending); its on_exit hook runs."""

    ending: Ending


@dataclass(frozen=True)
class Done:
    """Ended, hook included. started_at is None for a service refused before it started."""

    ending: Ending
    started_at: float | None
    ended_at: float


JobStatus = Queued | JobRunning | Hooking | Done


def launch(provider: Provider, *, boot_timeout_s: float = 900.0, **create_kw: Any) -> Session:
    """create(provider, **create_kw), then wait until its supervisor is up: a Session ready for
    jobs, which lives until its lease ends (or close, release, idle). A machine whose supervisor is
    not up in boot_timeout_s (image pull, a stuck host) is terminated here, since no supervisor
    exists yet to end it."""
    session = create(provider, **create_kw)
    try:
        session.wait_up(boot_timeout_s)
    except BaseException:
        session.machine.terminate()
        raise
    return session


def create(  # noqa: PLR0913 (all keyword-only; each is one knob of the session)
    provider: Provider, *, lease_s: float | None = None, ceiling_s: float = CEILING_S, gpu: str | None = None,
    image: str | None = None, env: dict[str, str] | None = None, labels: dict[str, str] | None = None,
    idle_timeout_s: float = 0.0, ports: tuple[int, ...] = (), record: Store | None = None, session_id: str | None = None,
) -> Session:  # fmt: skip
    """Rent a machine whose supervisor ends the session at min(lease, ceiling) (or sooner: idle,
    stop, release). lease_s (default: ceiling_s) and ceiling_s count from now, and are parsed here,
    once, into absolute times: the lease is the guarantee, so a session is detached from the start
    (nothing ends it because this process goes away). extend() moves the lease up to the ceiling;
    nothing moves the ceiling (at most MAX_CEILING_S). Returns once the provider has made the
    machine, before its supervisor is up (Session.wait_up), so a caller can say so while it boots;
    launch() is create + wait_up. Until the supervisor is up nothing on the machine can end it: a
    caller that gives up terminates it (machine.terminate). The provider's own backstop is the
    ceiling plus BACKSTOP_MARGIN_S, from the same clock reading, so a slow boot never cuts it short.
    Its id is new (LABEL_SESSION), not the machine's: attach() finds a session by it. labels are the caller's (who launched it,
    for what, e.g. box.user, box.cmd); box stamps only RESERVED. ports: what Session.expose may
    open later (Modal and RunPod route a port only if the machine was created with it). Idle: no
    job running and no connection to any of ports, for idle_timeout_s (0: never idle).
    record: the supervisor records status, jobs, the lease, and output into it, under
    record_prefix(id), so status() and wait() still answer after the machine is gone, and
    read_record() reads it. session_id: one from new_session_id(), for a caller that must name the
    session before launch returns (a relay answers the browser at once, while the machine boots)."""
    session_id = new_session_id() if session_id is None else session_id
    if not SESSION_ID.fullmatch(session_id):
        raise ValueError(f"session_id {session_id!r} is not one new_session_id() makes")
    if clash := sorted(set(labels or {}) & set(RESERVED)):
        raise ValueError(f"labels {clash} are box's own (launch stamps them)")
    lease_s = ceiling_s if lease_s is None else lease_s
    if not 0 < ceiling_s <= MAX_CEILING_S:
        raise ValueError(f"ceiling_s={ceiling_s}: a ceiling is more than 0 and at most {MAX_CEILING_S} s (48 h)")
    if not 0 < lease_s <= ceiling_s:
        raise ValueError(f"lease_s={lease_s}: a lease is more than 0 and at most the ceiling ({ceiling_s} s)")
    created_at = time.time()
    lease = Lease(until=created_at + lease_s, ceiling=created_at + ceiling_s)
    assert created_at < lease.until  # pair: the supervisor asserts these again at its start
    assert lease.until <= lease.ceiling
    assert lease.ceiling <= created_at + MAX_CEILING_S
    args = [
        "--created-at", repr(created_at), "--lease-until", repr(lease.until), "--ceiling", repr(lease.ceiling),
        "--host", socket.gethostname(), "--pid", str(os.getpid()),
        "--idle-timeout-s", str(idle_timeout_s), "--ports", ",".join(map(str, ports)),
        *(["--record", RECORD_PATH, *(["--record-sync"] if record.sync_writes else [])] if record else []),
    ]  # fmt: skip
    # the supervisor is installed as a file (ROOT/supervisor.py), so a later exec can run its `lease` command
    install = "import base64,os,zlib; open(os.environ['BOX_ROOT'] + '/supervisor.py', 'wb').write(zlib.decompress(base64.b64decode(os.environ['BOX_SUPERVISOR'])))"
    boot = f'mkdir -p "$BOX_ROOT" && python3 -c {shlex.quote(install)} && exec python3 "$BOX_ROOT/supervisor.py" --root "$BOX_ROOT" {shlex.join(args)}'
    backstop_s = int(lease.ceiling - time.time()) + BACKSTOP_MARGIN_S  # from the ceiling, not from boot
    assert backstop_s > BACKSTOP_MARGIN_S, backstop_s
    machine = provider.launch(
        gpu=gpu, image=image, entrypoint=["bash", "-c", boot],
        env={**(env or {}), "BOX_SUPERVISOR": supervisor_env()},
        labels={**(labels or {}), LABEL_BY: "box", LABEL_SESSION: session_id, LABEL_CEILING: str(int(lease.ceiling))},
        timeout_s=backstop_s, ports=list(ports), mounts=[Mount(record, record_prefix(session_id), RECORD_PATH)] if record else [],
    )  # fmt: skip
    if record:
        try:  # nothing else ends a machine whose supervisor is not up
            launched = {"machine_id": machine.id, "provider": provider.name, "labels": machine.labels, "at": time.time()}
            record.put(f"{record_prefix(session_id)}/launch.json", json.dumps(launched).encode())
        except BaseException:
            machine.terminate()
            raise
    return Session(machine, record=record)


def supervisor_env() -> str:
    """The supervisor's source as one environment value: compressed, since Modal refuses a value
    over MAX_ENV_VALUE (it passes env as a secret), and the plain base64 of it is past that."""
    value = base64.b64encode(zlib.compress(SUPERVISOR.read_bytes(), 9)).decode()
    assert len(value) <= MAX_ENV_VALUE, f"the supervisor is {len(value)} bytes as BOX_SUPERVISOR; Modal takes {MAX_ENV_VALUE}"
    return value


def new_session_id() -> str:
    return f"s-{secrets.token_hex(6)}"


def attach(provider: Provider, session_id: str, record: Store | None = None) -> Session:
    """A session launched elsewhere (another process, a detached run). It can extend, release, and
    close it as its creator can: the provider credential is the authority.
    Without record: while its machine lives; LookupError if no live machine carries that id. With
    the store it was launched with: also after its machine is gone (status() and wait() answer from
    the record, every machine call raises Gone; read the output with read_record)."""
    found = provider.list({LABEL_SESSION: session_id})
    if len(found) > 1:
        raise LookupError(f"{provider.name} provider: {len(found)} live machines for session {session_id}")
    if found:
        return Session(found[0], record=record)
    if record is None:
        raise LookupError(f"{provider.name} provider: no live machine for session {session_id}")
    recorded = read_record(record, session_id)  # LookupError if it was never recorded there
    return Session(Lost(recorded.machine_id, recorded.labels), record=record)


def record_prefix(session_id: str) -> str:
    """Where a session's record lives in its store."""
    if not SESSION_ID.fullmatch(session_id):
        raise ValueError(f"not a session id: {session_id!r}")
    return f"sessions/{session_id}"


@dataclass
class Session:
    machine: Machine
    record: Store | None = None  # where its supervisor records it (launch's record), if anywhere
    _ended: Ended | None = field(default=None, repr=False)  # terminal: once known, it stays
    _endpoints: dict[int, Endpoint] = field(default_factory=dict, repr=False)  # fixed for the machine's life

    @property
    def id(self) -> str:
        return self.machine.labels[LABEL_SESSION]

    def __enter__(self) -> Session:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def wait_up(self, timeout_s: float) -> None:
        """Until the supervisor is up (its last act at start: ROOT/up). TimeoutError past timeout_s."""
        give_up = time.monotonic() + timeout_s
        while not self._exists("up"):
            if time.monotonic() > give_up:
                raise TimeoutError(f"{self.machine.id}: supervisor not up after {timeout_s:.0f} s")
            time.sleep(POLL_S)

    def extend(self, until: float) -> Lease:
        """Move the lease's end to until (unix time), clamped to the ceiling. Never shorter: an
        earlier until is a no-op that returns the lease as it is (as SF Compute's "a shorter
        re-ask never cuts a hold"). A lease that ran out, or was released, stays over."""
        return self._change_lease("extend", until)

    def release(self) -> Lease:
        """End the lease now (until = now, by the machine's clock): the session ends with reason
        "released"; a running job is killed and its hook still runs."""
        return self._change_lease("release", 0.0)

    @contextlib.contextmanager
    def keep(self, every_s: float) -> Generator[Lease]:
        """Keep the session alive while the block runs (interactive use): extend to now + 2 *
        every_s at once and every every_s, then release on the way out, an exception or Ctrl-C
        included. If this process dies, the session ends at most 2 * every_s later (its lease).
        A renewer thread does the extending; this block owns it and joins it before leaving."""
        if not MIN_KEEP_EVERY_S <= every_s <= MAX_KEEP_EVERY_S:
            raise ValueError(f"every_s={every_s}: keep() renews every {MIN_KEEP_EVERY_S} to {MAX_KEEP_EVERY_S} s")
        lease = self.extend(time.time() + 2 * every_s)
        stop = threading.Event()
        # NOTE: stdlib threads, structured by hand (owned, joined, never a daemon). If box grows an
        # async version or mode, use anyio in trio style (nurseries and cancel scopes, no bare tasks)
        # on the asyncio backend, so Modal's .aio API works.
        renewer = threading.Thread(target=self._renew, args=(every_s, stop), daemon=False, name=f"box-keep-{self.id}")
        renewer.start()
        try:
            yield lease
        finally:
            stop.set()
            try:
                with contextlib.suppress(Gone):  # it already ended (its ceiling) and went
                    self.release()  # before the join: a Ctrl-C during a slow renew still ends the lease
            finally:
                renewer.join()  # bounded: one in-flight extend (an exec), then it sees stop
                assert not renewer.is_alive()

    def _renew(self, every_s: float, stop: threading.Event) -> None:
        """keep()'s renewer: extend every every_s until stopped, or the session is over."""
        while not stop.wait(every_s):
            try:
                lease = self.extend(time.time() + 2 * every_s)
            except Gone:
                return  # nothing left to keep
            except Exception as exc:  # noqa: BLE001 (a missed renewal is retried; the lease is 2 renewals long)
                print(f"box: {self.id}: renewing the lease failed, retrying: {exc!r}", file=sys.stderr)
                continue
            if lease.until <= time.time():
                return  # over (released, or past its ceiling): extending can't revive it

    def _change_lease(self, op: Literal["extend", "release"], until: float) -> Lease:
        """One exec: the supervisor's own `lease` command changes ROOT/lease.json under a lock,
        audits it as this host and process, and prints the lease after it."""
        root = self.machine.root
        argv = ["python3", f"{root}/supervisor.py", "lease", "--root", root, "--op", op, "--until", repr(until),
                "--host", socket.gethostname(), "--pid", str(os.getpid())]  # fmt: skip
        return parse_lease(self._check(shlex.join(argv)).encode())

    def close(self, timeout_s: float = 900.0, gone_timeout_s: float = GONE_TIMEOUT_S) -> Receipt:
        """End the session and prove it: ask the supervisor to stop (a running job is killed, its hook
        runs), wait up to timeout_s for it to say it ended, terminate the machine, then wait up to
        gone_timeout_s for the provider to say the machine is gone. A supervisor that never answers
        is terminated anyway: the receipt's end is then machine_lost (supervisor_confirmed False),
        unless its word reached the record first. NotGone if the provider never confirms: never a
        receipt without that. With a record, the receipt is written to it (receipt.json)."""
        assert timeout_s > 0, timeout_s
        assert gone_timeout_s > 0, gone_timeout_s
        ended = self._stop_and_wait(timeout_s)  # None: the supervisor did not answer in time
        # terminate even after the supervisor's word: it would linger for readers (LINGER_S), and on
        # RunPod its own delete is one more thing that could fail; ended.json is already written.
        self.machine.terminate()
        gone_at = self._confirm_gone(gone_timeout_s)
        if ended is None:  # read only now: the machine is gone, so this is the record's word or machine_lost
            ended = self.status()
            assert isinstance(ended, Ended), ended
        receipt = Receipt(session_id=self.id, machine_id=self.machine.id, ended=ended, machine_gone_at=gone_at)
        if self.record is not None:
            self.record.put(f"{record_prefix(self.id)}/receipt.json", receipt_json(receipt))
        return receipt

    def _stop_and_wait(self, timeout_s: float) -> Ended | None:
        """close()'s first half: stop, then the supervisor's end (or machine_lost if the machine went
        without one); None if it was still running at timeout_s."""
        if not isinstance(self.status(), Ended):  # mkdir: a booting supervisor ends at once on stop
            with contextlib.suppress(Gone):  # it may end as soon as the supervisor exits
                self.machine.exec(f"mkdir -p {self.machine.root} && touch {self._path('watch')} {self._path('stop')}")
        try:
            return self.wait(timeout_s)
        except TimeoutError:
            return None

    def _confirm_gone(self, timeout_s: float) -> float:
        """Poll the provider until it says the machine is gone; when it did (unix time). NotGone past
        timeout_s. A check that errors (the provider unreachable) is not a confirmation: it propagates."""
        give_up = time.monotonic() + timeout_s
        while not self.machine.gone():
            if time.monotonic() > give_up:
                raise NotGone(f"{self.id}: {self.machine.id} terminated, but its provider still has it after {timeout_s:.0f} s")
            time.sleep(POLL_S)
        return time.time()

    def expose(self, port: int) -> Endpoint:
        """Where to reach `port` on the machine (one of launch's ports) from anywhere. Something
        must listen there (e.g. a job); until it does, requests fail (Modal: 502). Asked of the
        provider once per Session: a port's endpoint is fixed for its machine's life."""
        if port not in self._endpoints:
            self._endpoints[port] = self.machine.expose(port)
        return self._endpoints[port]

    def status(self) -> Status:
        """Booting, Running (with the lease as it is now), or Ended (and why), from the
        supervisor's files, in one exec. Once the machine is gone, always Ended: machine_lost, or
        with a record, the record's word (Record.end), which may take up to HEARTBEAT_TTL_S to
        land. Ended is final: once this Session has seen it, it answers without asking the machine."""
        if self._ended is not None:
            return self._ended
        try:
            out = self._check(STATUS_SH.format(root=shlex.quote(self.machine.root)))
        except Gone:
            return self._status_when_gone()
        status = parse_status(out.encode())
        if isinstance(status, Ended):
            self._ended = status
        return status

    def wait(self, timeout_s: float | None = None) -> Ended:
        """Block until the session ends; returns why. While waiting it keeps the machine lingering
        (ROOT/watch), so the supervisor's reason is read before the machine goes. Bounded without
        timeout_s too: by the session's ceiling (or its machine's loss). TimeoutError past timeout_s
        (checked between polls: a gone machine's status() can take up to HEARTBEAT_TTL_S)."""
        give_up = None if timeout_s is None else time.monotonic() + timeout_s
        while not (self._watch() or isinstance(status := self.status(), Ended)):  # watch first: no gap to end in
            if give_up is not None and time.monotonic() > give_up:
                raise TimeoutError(f"{self.id}: still {status} after {timeout_s:.0f} s")
            time.sleep(POLL_S)
        return status

    def run(  # noqa: PLR0913 (keyword-only: each is one knob of the job)
        self, cmd: str, *, max_duration_s: float = 1800.0, on_exit: str | None = None, hook_budget_s: float = 300.0,
        env: dict[str, str] | None = None,
    ) -> Job:  # fmt: skip
        """Queue cmd (bash). Jobs run one at a time, in order. The job is killed (reason "timeout")
        max_duration_s after it starts; pass it explicitly: the default is a seatbelt, not a
        choice. on_exit (bash) runs after it ends however it ended, with BOX_EXIT_CODE, BOX_REASON,
        BOX_JOB_DIR set, within hook_budget_s; the job is killed hook_budget_s before the lease
        ends to leave the hook that time (so a hook needs a lease longer than its budget)."""
        if not 0 < max_duration_s <= MAX_CEILING_S:
            raise ValueError(f"max_duration_s={max_duration_s}: more than 0 and at most {MAX_CEILING_S} s")
        running = self._running_now()
        left = min(running.lease.until, running.lease.ceiling) - time.time()
        if on_exit and hook_budget_s >= left:
            raise ValueError(f"hook_budget_s={hook_budget_s} does not fit in the lease's {left:.0f} s left")
        spec = {"cmd": cmd, "on_exit": on_exit, "hook_budget_s": hook_budget_s, "max_duration_s": max_duration_s, "env": env or {}}
        return self._start(Job(self, new_job_id(), "jobs"), spec)

    def serve(self, cmd: str, *, env: dict[str, str] | None = None) -> Job:
        """Start cmd (bash) as a service: a long-lived server (e.g. behind an exposed port) that
        starts at once beside the job queue, is not work for idleness (connections to the ports
        are), keeps a released session alive, has no hook, and is killed when the session ends.
        At most MAX_SERVICES a session (ValueError past it). Its Job reads as a job's does."""
        self._running_now()
        if len([name for name in self._check(f"ls {self._path('services')}").split() if not name.endswith(".tmp")]) >= MAX_SERVICES:
            raise ValueError(f"{self.id}: a session runs at most {MAX_SERVICES} services")
        return self._start(Job(self, new_job_id(), "services"), {"cmd": cmd, "env": env or {}})

    def _running_now(self) -> Running:
        running = self.status()
        if not isinstance(running, Running):
            raise RuntimeError(f"{self.id}: cannot start anything on a session that is {running}")
        return running

    def _start(self, job: Job, spec: dict) -> Job:
        """Write job's spec where the supervisor picks it up: atomically, never half a spec."""
        tmp = self._path(f"{job.kind}/{job.id}.spec.tmp")
        self.machine.write(tmp, json.dumps(spec).encode())
        self._check(f"mkdir -p {job.dir} && mv {tmp} {job.dir}/spec.json")
        return job

    def put(self, local: str | Path, remote: str, ignore: tuple[str, ...] = ()) -> None:
        """Copy a local directory to remote (created), minus `ignore` globs (`**/x`: at any depth)."""
        root = Path(local)
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            for child in sorted(root.iterdir()):
                tar.add(child, arcname=child.name, filter=lambda i: None if ignored(i.name, ignore) else i)
        tmp = self._path(f"put-{secrets.token_hex(3)}.tgz")
        self.machine.write(tmp, buf.getvalue())
        self._check(f"mkdir -p {shlex.quote(remote)} && tar xzf {tmp} --no-same-owner -C {shlex.quote(remote)} && rm {tmp}")

    def get(self, remote: str, local: str | Path) -> None:
        """Copy the remote directory into local (created), overwriting files of the same name."""
        tmp = self._path(f"get-{secrets.token_hex(3)}.tgz")
        self._check(f"tar czf {tmp} -C {shlex.quote(remote)} .")
        data = self.machine.read(tmp)
        self.machine.exec(f"rm -f {tmp}")
        with tarfile.open(fileobj=io.BytesIO(data)) as tar:
            tar.extractall(local, filter="data")

    def jobs(self) -> list[Job]:
        """Every job this session was given (run), oldest first, from any process; once the
        machine is gone, every one its record has."""
        return self._listed("jobs")

    def services(self) -> list[Job]:
        """Every service this session was given (serve), oldest first; as jobs()."""
        return self._listed("services")

    def _listed(self, kind: str) -> list[Job]:
        try:
            out = self._check(f"ls {self._path(kind)}")
        except Gone:
            if self.record is None:
                raise
            return [Job(self, job_id, kind) for job_id in read_record(self.record, self.id).jobs(kind)]
        return [Job(self, name, kind) for name in sorted(out.split()) if not name.endswith(".tmp")]

    def _status_when_gone(self) -> Ended:
        """No record: machine_lost. Else the record's end, waiting out (at most HEARTBEAT_TTL_S) a
        heartbeat still fresh, while the record of the end may still be landing."""
        give_up = time.monotonic() + HEARTBEAT_TTL_S
        ended = Ended("machine_lost") if self.record is None else None
        while ended is None and time.monotonic() < give_up:
            ended = read_record(self.record, self.id).end(now=time.time())
            if ended is None:
                time.sleep(POLL_S)
        self._ended = ended or Ended("machine_lost")  # still fresh past the TTL: its clock is off; nothing more will land
        return self._ended

    def _watch(self) -> None:
        """Tell the supervisor someone is reading, so the machine lingers for us after it ends."""
        with contextlib.suppress(Gone):  # then the next status() says Ended
            self.machine.exec(f"touch {self._path('watch')}")

    def _path(self, rel: str) -> str:
        return f"{self.machine.root}/{rel}"

    def _touch(self, rel: str) -> None:
        self._check(f"touch {self._path(rel)}")

    def _exists(self, rel: str) -> bool:
        return self.machine.exec(f"test -e {self._path(rel)}")[0] == 0

    def _check(self, cmd: str) -> str:
        rc, out, err = self.machine.exec(cmd)
        if rc != 0:
            raise RuntimeError(f"{self.id}: `{cmd}` exited {rc}: {err.strip()}")
        return out


def new_job_id() -> str:
    return f"{int(time.time())}-{secrets.token_hex(3)}"  # sorts by when it was given


@dataclass(frozen=True)
class Job:
    """A job (Session.run) or a service (Session.serve): same files, same reading."""

    session: Session
    id: str
    kind: Literal["jobs", "services"] = "jobs"

    @property
    def dir(self) -> str:
        return self.session._path(f"{self.kind}/{self.id}")

    def status(self) -> JobStatus:
        """Queued, JobRunning, Hooking, or Done, from the supervisor's status.json."""
        try:
            return parse_job_status(self.session.machine.read(f"{self.dir}/status.json"))
        except FileNotFoundError:
            return Queued()

    def done(self) -> bool:
        return isinstance(self.status(), Done)

    def wait(self) -> Ending:
        """Block until the job is done (its hook too); how it ended. One exec per poll."""
        while not isinstance(status := self._read_live(None, watch=True).status, Done):
            time.sleep(POLL_S)
        return status.ending

    def kill(self) -> None:
        """Kill this job (its whole process group); its hook runs; the session goes on."""
        self.session._touch(f"{self.kind}/{self.id}/kill")

    def logs(self, *, after: LogCursor = (0, 0), follow: bool = False, stop: threading.Event | None = None) -> Iterator[LogChunk]:
        """The job's output past `after` (the job's start by default); follow=True until it is done
        (or the session ended without running it). A reader that resumes (a reconnecting browser)
        passes the last chunk's end, so it never re-reads a byte. Once the machine is gone, from the
        session's record (with follow, once the record has the session's end, so it is all of the
        output there will be). Without follow: one exec per MAX_LOG_READ. With follow: one stream
        (Machine.stream) as the output is written; stop, set from another thread, ends it within a
        second (the tail's beat)."""
        if follow:
            yield from self._follow(after, stop)
            return
        cursor = after
        while True:
            try:
                read = self._read_live(cursor, watch=False)
            except Gone:
                if self.session.record is None:
                    raise
                yield from read_record(self.session.record, self.session.id).logs(self.id, after=cursor, kind=self.kind)
                return
            for chunk in read.chunks:
                cursor = chunk.end
                yield chunk
            if not read.more:
                return

    def _follow(self, cursor: LogCursor, stop: threading.Event | None) -> Iterator[LogChunk]:
        """logs(follow=True): supervisor.py's tail mode on the machine sends both files from the cursor
        as they grow, in one streamed command, and exits once the job is done. A stream that drops
        (no frame for FOLLOW_QUIET_S, or an error) reconnects from the last chunk's end, at most
        FOLLOW_TRIES times in a row with no frame between; one that reached TAIL_MAX_S reconnects at once."""
        tries = 0
        while stop is None or not stop.is_set():
            tail = TailReader(cursor)
            try:
                for chunk in self._tail(tail, stop):
                    cursor = chunk.end
                    yield chunk
            except Gone:
                if self.session.record is None:
                    raise
                self.session.wait()  # the record's end landed: what it has is all there will be
                yield from read_record(self.session.record, self.session.id).logs(self.id, after=cursor, kind=self.kind)
                return
            except TailError:
                raise
            except Exception as e:  # a dropped stream: Modal's and ssh's errors differ, so any; bounded by FOLLOW_TRIES
                tries = 1 if tail.frames else tries + 1
                if tries > FOLLOW_TRIES:
                    raise
                print(f"box: {self.session.id}: following {self.id} dropped ({e!r}); reconnecting from {cursor}", file=sys.stderr)
                (stop or threading.Event()).wait(FOLLOW_BACKOFF_S * tries)
                continue
            if tail.end in ("done", "ended"):
                return
            if tail.end is None and not (stop and stop.is_set()):  # it exited without saying why: a failure, not a drop
                raise TailError(f"{self.id}: the log tail exited {tail.rc} without an end: {tail.errors.decode(errors='replace').strip()!r}")

    def _tail(self, tail: TailReader, stop: threading.Event | None) -> Iterator[LogChunk]:
        """One streamed tail (supervisor.py tail) from tail.cursor: its chunks as they come. After it,
        tail says how it ended (end, rc, errors). Stops at the first frame after stop is set."""
        cmd = f"exec python3 {shlex.quote(self.session._path('supervisor.py'))} tail {shlex.quote(self.dir)} {tail.cursor[0]} {tail.cursor[1]}"
        # timeout_s: the tail ends itself by TAIL_MAX_S; this bounds one that does not (a hung call)
        with self.session.machine.stream(cmd, timeout_s=TAIL_MAX_S + 60, quiet_s=FOLLOW_QUIET_S) as stream:
            for name, data in stream:
                if name == "stderr":
                    tail.errors = (tail.errors + data)[-TAIL_ERR_BYTES:]
                    continue
                yield from tail.feed(data)
                if stop is not None and stop.is_set():
                    return
        tail.rc = stream.rc

    def read(self, after: LogCursor, *, watch: bool = False) -> JobRead:
        """One look at the job in one exec: its status, then its output past after (so a "done"
        status comes with all of it, unless more). watch: also keep the machine lingering after
        the session ends, as a follower does (ROOT/watch). Once the machine is gone, from the
        session's record: as much as has landed (all of it once Session.status() says Ended)."""
        try:
            return self._read_live(after, watch=watch)
        except Gone:
            if self.session.record is None:
                raise
            record = read_record(self.session.record, self.session.id)
            return JobRead(record.job_status(self.id, kind=self.kind), list(record.logs(self.id, after=after, kind=self.kind)))

    def _read_live(self, after: LogCursor | None, *, watch: bool) -> JobRead:
        """status.json, then (after given) each stream past after, each file one base64 line, so
        the bytes and the cursor are exact. A UTF-8 character cut by the read waits for the next
        one, unless the job is done (then the output is whole: it is decoded as it is)."""
        files = [("status.json", 0), *([] if after is None else zip(STREAMS, after, strict=True))]
        reads = [f"{{ tail -c +{offset + 1} {name} 2>/dev/null | head -c {MAX_LOG_READ} | base64; }} | tr -d '\\n'; echo" for name, offset in files]
        out = self.session._check("; ".join([*([f"touch {self.session._path('watch')}"] if watch else []), f"cd {self.dir} || exit 1", *reads]))
        lines = out.split("\n")
        if len(lines) != len(files) + 1 or lines[-1]:
            raise RuntimeError(f"{self.id}: reading the job gave {len(lines) - 1} lines for {len(files)} files")
        raw = [base64.b64decode(line) for line in lines[:-1]]
        status = parse_job_status(raw[0]) if raw[0] else Queued()
        done = isinstance(status, Done)
        chunks, cursor, more = [], after, False
        for i, data in enumerate(raw[1:]):
            full = len(data) == MAX_LOG_READ
            more = more or full
            cut = len(data) if done and not full else utf8_cut(data)
            if cut:
                cursor = (cursor[0] + cut, cursor[1]) if i == 0 else (cursor[0], cursor[1] + cut)
                chunks.append(LogChunk(STREAMS[i], data[:cut].decode(errors="replace"), cursor))
        return JobRead(status, chunks, more)


@dataclass(frozen=True)
class JobRead:
    """One look at a job (Job.read): its status and its output past a cursor. more: some stream
    had over MAX_LOG_READ new bytes: read on from the last chunk."""

    status: JobStatus
    chunks: list[LogChunk]
    more: bool = False

    @property
    def done(self) -> bool:
        return isinstance(self.status, Done)


@dataclass(frozen=True)
class LogChunk:
    """Some of a job's output, and the cursor just past it (pass it as after= to read on)."""

    stream: Literal["stdout", "stderr"]
    text: str
    end: LogCursor


class TailError(RuntimeError):
    """The machine's log tail (supervisor.py tail) failed: not a dropped connection, so not retried.
    E.g. a machine booted by an older box, whose supervisor has no tail mode."""


class TailReader:
    """Job.logs(follow=True)'s side of one supervisor.tail: its frames in, LogChunks out, each with the
    cursor just past it. A UTF-8 character cut by a frame waits for the rest (the cursor stays before
    it), unless the job is done: then the output is whole and is decoded as it is."""

    def __init__(self, after: LogCursor) -> None:
        self.cursor = list(after)
        self.end: str | None = None  # done | ended | max, once the tail said it
        self.frames = 0  # frames read (beats too): any, and the connection worked
        self.rc: int | None = None  # the tail's exit code, once it exited
        self.errors = b""  # the end of its own stderr: why it failed, if it did
        self._held = dict.fromkeys(STREAMS, b"")  # the start of a character cut by the last frame
        self._buf = b""  # bytes of frames not parsed yet: at most a frame and a header

    def feed(self, data: bytes) -> list[LogChunk]:
        self._buf += data
        chunks: list[LogChunk] = []
        while self.end is None:
            header, sep, rest = self._buf.partition(b"\n")
            if not sep:
                if len(self._buf) > 64:  # no header is this long
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
        self.cursor[STREAMS.index(stream)] += cut
        return [LogChunk(stream, raw[:cut].decode(errors="replace"), (self.cursor[0], self.cursor[1]))]


def run_job(
    provider: Provider, cmd: str, *, max_duration_s: float, put: list[tuple[str, str]] = (),
    get: list[tuple[str, str]] = (), on_exit: str | None = None, **launch_kw: object,
) -> Ending:  # fmt: skip
    """launch (launch_kw: lease_s, ceiling_s, gpu, ...), put each (local, remote), run cmd with its
    output on this terminal, get each (remote, local), close. Exactly the Session calls; use them
    directly for anything else."""
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


@dataclass(frozen=True)
class Lost:
    """The machine of a session found only in its record (attach): gone, so every call is Gone."""

    id: str
    labels: dict[str, str]
    root: str = ""  # nothing is under it

    def exec(self, cmd: str) -> tuple[int, str, str]:
        raise Gone(f"{self.id}: gone (known from its record)")

    def stream(self, cmd: str, *, timeout_s: float, quiet_s: float | None = None) -> Stream:
        raise Gone(f"{self.id}: gone (known from its record)")

    def write(self, path: str, data: bytes) -> None:
        raise Gone(f"{self.id}: gone (known from its record)")

    def read(self, path: str) -> bytes:
        raise Gone(f"{self.id}: gone (known from its record)")

    def expose(self, port: int) -> Endpoint:
        raise Gone(f"{self.id}: gone (known from its record)")

    def terminate(self) -> None:
        """Already gone: nothing to do."""

    def gone(self) -> bool:
        """attach() found no live machine for the session (provider.list, the provider's word) before
        making this; a machine never comes back, so that answer stands."""
        return True


@dataclass(frozen=True)
class LeaseChange:
    """One entry of a session's lease audit: op (create | extend | release) made the lease end at
    until, at (unix time) from pid on host; n such in a row (keep()'s renewals) are one entry."""

    op: str
    until: float
    at: float
    host: str
    pid: int
    n: int


@dataclass(frozen=True)
class Heartbeat:
    """The recorder's last word: at (unix time, the machine's clock); stale past ttl_s."""

    at: float
    ttl_s: float


@dataclass(frozen=True)
class Record:
    """What a session's supervisor recorded into a store (launch's record), readable without its
    machine or its provider. The session-level files are read once, by read_record; jobs and logs
    are read when asked. Layout: box/supervisor.py's docstring, plus launch.json from launch."""

    store: Store
    machine_id: str
    labels: dict[str, str]  # the machine's, as launch gave them (LABEL_SESSION included)
    running: Running | None  # None: the supervisor never came up
    ended: Ended | None  # None: no end recorded (yet)
    heartbeat: Heartbeat | None
    receipt: Receipt | None  # None: nobody closed it (yet), or it ended on its own (lease, idle)

    @property
    def session_id(self) -> str:
        return self.labels[LABEL_SESSION]

    def end(self, now: float) -> Ended | None:
        """Why the session ended, for one whose machine is gone: the recorded end; else, while the
        heartbeat is fresh, None (a store can land the record's last writes after the machine
        ends, as a Modal Volume commits on its own); then machine_lost: it died without a word,
        or its word never reached the store."""
        if self.ended is not None:
            return self.ended
        if self.heartbeat is not None and now - self.heartbeat.at < self.heartbeat.ttl_s:
            return None
        return Ended("machine_lost")

    def lease_audit(self) -> list[LeaseChange]:
        """Every change of the session's lease, as last recorded (debugging: who extended or
        released it, from where, when). Empty if none was recorded."""
        raw = _parse_if_present(self.store, f"{record_prefix(self.session_id)}/lease-audit.json", json.loads)
        return [LeaseChange(e["op"], float(e["until"]), float(e["at"]), str(e["host"]), int(e["pid"]), int(e["n"])) for e in raw or []]

    def jobs(self, kind: str = "jobs") -> list[str]:
        """Every job id recorded (kind="services": every service's), oldest first."""
        assert kind in KINDS, kind
        prefix = f"{record_prefix(self.session_id)}/{kind}/"
        return sorted({key[len(prefix) :].split("/", 1)[0] for key in self.store.list(prefix)})

    def job_status(self, job_id: str, kind: str = "jobs") -> JobStatus:
        """The job's status as last recorded (Done comes with all its output); Queued if none was
        (it never started, or started after the last flush)."""
        try:
            return parse_job_status(self.store.get(f"{record_prefix(self.session_id)}/{kind}/{job_id}/status.json"))
        except FileNotFoundError:
            return Queued()

    def logs(self, job_id: str, after: LogCursor = (0, 0), kind: str = "jobs") -> Iterator[LogChunk]:
        """The job's recorded output past `after`, in the order it was recorded, as Job.logs gives
        it. Only chunks past the cursor are read. Output that is not UTF-8 is decoded with
        replacement characters."""
        prefix = f"{record_prefix(self.session_id)}/{kind}/{job_id}/"
        names = [key[len(prefix) :] for key in self.store.list(prefix)]
        chunks = sorted((*parse_chunk(name), name) for name in names if CHUNK.fullmatch(name))
        cursor = dict(zip(STREAMS, after, strict=True))
        begins = dict.fromkeys(STREAMS, 0)  # where the next chunk of each stream starts: the previous one's end
        for _n, stream, end, name in chunks:
            begin, begins[stream] = begins[stream], end
            if end <= cursor[stream]:
                continue  # the reader has all of it
            key = prefix + name
            data = self.store.get(key)
            if len(data) != end - begin:
                raise ValueError(f"{self.store.uri}: {key} holds {len(data)} bytes; its name says {end - begin}")
            text = data[max(0, cursor[stream] - begin) :].decode(errors="replace")
            cursor[stream] = end
            yield LogChunk(stream, text, (cursor["stdout"], cursor["stderr"]))


CHUNK = re.compile(r"(stdout|stderr)\.(\d+)\.(\d+)")  # a chunk's name in the record: <stream>.<n>.<end> (box/supervisor.py)


def parse_chunk(name: str) -> tuple[int, str, int]:
    """(n, stream, end): end is the stream's byte count just past the chunk."""
    stream, n, end = CHUNK.fullmatch(name).groups()
    return int(n), stream, int(end)


def read_record(store: Store, session_id: str) -> Record:
    """The session's record in store. LookupError if launch never recorded it there."""
    prefix = record_prefix(session_id)
    try:
        launched = json.loads(store.get(f"{prefix}/launch.json"))
    except FileNotFoundError as e:
        raise LookupError(f"{store.uri}: no record of session {session_id}") from e
    if launched["labels"].get(LABEL_SESSION) != session_id:
        raise ValueError(f"{store.uri}: {prefix}/launch.json is for session {launched['labels'].get(LABEL_SESSION)!r}")
    return Record(
        store=store, machine_id=str(launched["machine_id"]), labels=dict(launched["labels"]),
        running=_recorded_running(store, prefix),
        ended=_parse_if_present(store, f"{prefix}/ended.json", parse_ended),
        heartbeat=_parse_if_present(store, f"{prefix}/heartbeat.json", parse_heartbeat),
        receipt=_parse_if_present(store, f"{prefix}/receipt.json", parse_receipt),
    )  # fmt: skip


def _parse_if_present(store: Store, key: str, parse: Callable[[bytes], T]) -> T | None:  # noqa: UP047 (requires-python 3.11: no PEP 695)
    try:
        raw = store.get(key)
    except FileNotFoundError:
        return None
    return parse(raw)


def parse_heartbeat(raw: bytes) -> Heartbeat:
    d = json.loads(raw)
    return Heartbeat(at=float(d["at"]), ttl_s=float(d["ttl_s"]))


def _recorded_running(store: Store, prefix: str) -> Running | None:
    """session.json and lease.json as last recorded; None until both have landed."""
    session = _parse_if_present(store, f"{prefix}/session.json", json.loads)
    lease = _parse_if_present(store, f"{prefix}/lease.json", parse_lease)
    if session is None or lease is None:
        return None
    return Running(started_at=float(session["started_at"]), lease=lease)


def parse_lease(raw: bytes) -> Lease:
    """lease.json (or the supervisor's `lease` command's output): {until, ceiling, released}."""
    d = json.loads(raw)
    lease = Lease(until=float(d["until"]), ceiling=float(d["ceiling"]))
    if lease.until > lease.ceiling:
        raise ValueError(f"lease until {lease.until} is past its ceiling {lease.ceiling}")
    return lease


# One exec: ended.json if the session ended; else, once up, session.json and lease.json; else nothing (booting).
STATUS_SH = (
    "cd {root} 2>/dev/null || exit 0; "
    "if [ -e ended.json ]; then echo ended; cat ended.json; "
    "elif [ -e up ]; then echo running; cat session.json; echo; cat lease.json; fi"
)


def parse_status(raw: bytes) -> Status:
    """STATUS_SH's output."""
    kind, *docs = raw.decode().splitlines() or ["booting"]
    match kind, len(docs):
        case "booting", 0:
            return Booting()
        case "ended", 1:
            return parse_ended(docs[0].encode())
        case "running", 2:
            return Running(started_at=float(json.loads(docs[0])["started_at"]), lease=parse_lease(docs[1].encode()))
    raise ValueError(f"session status: unexpected {raw[:200]!r}")


def parse_job_status(raw: bytes) -> JobStatus:
    """A job's status.json, as the supervisor wrote it: {state: running | hook | done, ...}."""
    d = json.loads(raw)
    match d["state"]:
        case "running":
            return JobRunning(float(d["started"]))
        case "hook":
            return Hooking(Ending(d["reason"], d["exit_code"]))
        case "done":
            ending = Ending(d["reason"], d["exit_code"], d.get("hook_exit_code"))
            return Done(ending, float(d["started"]) if "started" in d else None, float(d["ended"]))
        case state:
            raise ValueError(f"status.json: unknown job state {state!r}")


def receipt_json(receipt: Receipt) -> bytes:
    """receipt.json: supervisor_confirmed spelled out for a reader of the JSON alone."""
    assert SESSION_ID.fullmatch(receipt.session_id), receipt  # pair: parse_receipt
    assert receipt.ended.reason in get_args(EndReason), receipt
    assert receipt.machine_gone_at > 0, receipt
    d = {"session_id": receipt.session_id, "machine_id": receipt.machine_id, "reason": receipt.ended.reason,
         "supervisor_confirmed": receipt.supervisor_confirmed, "machine_gone_at": receipt.machine_gone_at}  # fmt: skip
    return json.dumps(d).encode()


def parse_receipt(raw: bytes) -> Receipt:
    """receipt.json, as Session.close() wrote it."""
    d = json.loads(raw)
    reason = d["reason"]
    if reason not in get_args(EndReason):
        raise ValueError(f"receipt.json: unknown end reason {reason!r}")
    receipt = Receipt(str(d["session_id"]), str(d["machine_id"]), Ended(reason), float(d["machine_gone_at"]))
    if not SESSION_ID.fullmatch(receipt.session_id):
        raise ValueError(f"receipt.json: not a session id: {receipt.session_id!r}")
    if d["supervisor_confirmed"] is not receipt.supervisor_confirmed:
        raise ValueError(f"receipt.json: supervisor_confirmed {d['supervisor_confirmed']!r} contradicts reason {reason!r}")
    return receipt


def parse_ended(raw: bytes) -> Ended:
    """ended.json, as the supervisor wrote it: its reason must be one box knows."""
    reason = json.loads(raw)["reason"]
    if reason not in get_args(EndReason) or reason == "machine_lost":
        raise ValueError(f"ended.json: unknown end reason {reason!r}")
    return Ended(reason)


def ignored(rel: str, ignore: tuple[str, ...]) -> bool:
    return any(fnmatch(rel, g) or (g.startswith("**/") and fnmatch(rel.rsplit("/", 1)[-1], g[3:])) for g in ignore)
