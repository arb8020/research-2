"""box: rent a machine, run jobs on it, bring results back, and never leave it billing.

    with box.launch(provider, gpu="L4", image=IMAGE, deadline_s=3600) as s:   # a Session
        s.put("robots", "/work/robots")
        job = s.run("cd /work && python robots/train.py", on_exit="upload.sh")
        for chunk in job.logs(follow=True): ...   # LogChunk(stream, text, end)
        ending = job.wait()                  # Ending(reason="exited", exit_code=0, ...)
        s.get("/work/runs", "runs")
    # leaving the block ends the session: a running job is killed and its hook still runs
    s.status()                               # Ended(reason="stopped")

    s = box.attach(provider, session_id)     # from anywhere, by the session's own id
    match s.status():                        # Booting() | Running(started_at, deadline_at) | Ended(reason)
        case Running(): s.wait()             # -> Ended: the awaitable terminal state

    with box.launch(provider, deadline_s=3600, ports=[8888]) as s:   # ports: declared at launch
        s.serve("jupyter server --port 8888 ...")   # a service: beside the job queue, until the session ends
        s.expose(8888)                       # Endpoint(url="https://...", headers={})

    s = box.launch(provider, deadline_s=3600, record=store)   # the supervisor records into store (box/store.py)
    box.attach(provider, s.id, record=store).wait()           # works after the machine is gone too
    job.logs(after=chunk.end)                # resumes where a reader left off, live or from the record
    r = box.read_record(store, s.id)         # Record: no machine, no provider needed

A provider only rents raw machines (Machine: exec, write, read, terminate). Everything else is
here, built from those four calls and the supervisor (box/supervisor.py), which every machine
runs as its entrypoint and which talks to this file only through files under machine.root.
"""

from __future__ import annotations

import base64
import contextlib
import io
import json
import re
import secrets
import shlex
import sys
import tarfile
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from fnmatch import fnmatch
from pathlib import Path
from typing import Any, Literal, Protocol, TypeVar, get_args

from box.store import Mount, Store
from box.supervisor import HEARTBEAT_TTL_S, KINDS, MAX_SERVICES, utf8_cut

SUPERVISOR = Path(__file__).with_name("supervisor.py")
LABEL_BY = "box.by"
LABEL_SESSION = "box.session"  # the session's own id: a session is not its machine, even while 1:1
LABEL_DEADLINE = "box.deadline"  # unix time the session ends by
RESERVED = (LABEL_BY, LABEL_SESSION, LABEL_DEADLINE)  # launch stamps these; a caller's labels are the rest
POLL_S = 0.5
RECORD_PATH = "record"  # where a session's record is mounted on its machine, under the supervisor's root
SESSION_ID = re.compile(r"s-[0-9a-f]{12}")  # new_session_id()'s shape
T = TypeVar("T")
STREAMS = ("stdout", "stderr")
LogCursor = tuple[int, int]  # bytes of (stdout, stderr) a reader has had: where it resumes, live or from the record
MAX_LOG_READ = 4 * 1024 * 1024  # bytes of one stream one exec brings back; more is read by the next


class Gone(Exception):
    """The machine no longer exists (ended, terminated, or lost by the provider)."""


class Machine(Protocol):
    """What a provider rents: a machine running the supervisor, reachable by exec and files.
    Every method raises Gone once the machine no longer exists."""

    id: str
    labels: dict[str, str]
    root: str  # the supervisor's directory on the machine

    def exec(self, cmd: str) -> tuple[int, str, str]: ...  # bash on the machine: (rc, stdout, stderr)
    def write(self, path: str, data: bytes) -> None: ...
    def read(self, path: str) -> bytes: ...  # FileNotFoundError if absent
    def terminate(self) -> None: ...  # hard stop, idempotent; no hooks run
    def expose(self, port: int) -> Endpoint: ...  # ValueError unless port was declared at launch


class Provider(Protocol):
    name: str

    def launch(  # noqa: PLR0913 (keyword-only: what a machine is made with)
        self, *, gpu: str | None, image: str | None, entrypoint: list[str], env: dict[str, str],
        labels: dict[str, str], timeout_s: int, ports: list[int], mounts: list[Mount],
    ) -> Machine: ...  # fmt: skip  # mounts: ValueError for a store this provider cannot mount
    def get(self, machine_id: str) -> Machine: ...  # LookupError if box did not launch it
    def list(self, labels: dict[str, str] | None = None) -> list[Machine]: ...  # live machines labelled LABEL_BY and all of labels


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
class Running:
    """The supervisor is up and the session has not ended. Unix times, by the machine's clock."""

    started_at: float
    deadline_at: float


EndReason = Literal["stopped", "deadline", "idle", "lease_lost", "released", "machine_lost"]


@dataclass(frozen=True)
class Ended:
    """Why a session ended. All but machine_lost are the supervisor's word (ROOT/ended.json).
    machine_lost: the machine is gone and this Session never read ended.json, so either it died
    (supervisor crash, provider loss, backstop timeout) or it ended and was gone before anyone read
    why (Session.wait() and close() read it before letting go, so they never see this for an end)."""

    reason: EndReason


Status = Booting | Running | Ended


@dataclass(frozen=True)
class Ending:
    """How a job ended. reason: exited | killed | deadline | lease_lost | stopped; a service also
    idle | released (the session's end), or refused (past MAX_SERVICES, never started)."""

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
    """create(provider, **create_kw), wait until its supervisor is up, hold its lease: a Session
    ready for jobs, holding the lease (heartbeats) until release() or close(). A machine whose
    supervisor is not up in boot_timeout_s (image pull, a stuck host) is terminated here, since no
    supervisor exists yet to end it."""
    session = create(provider, **create_kw)
    try:
        session.wait_up(boot_timeout_s)
    except BaseException:
        session.machine.terminate()
        raise
    session.hold()
    return session


def create(  # noqa: PLR0913 (all keyword-only; each is one knob of the session)
    provider: Provider, *, deadline_s: int, gpu: str | None = None, image: str | None = None,
    env: dict[str, str] | None = None, labels: dict[str, str] | None = None,
    lease_ttl_s: float = 60.0, idle_timeout_s: float = 0.0,
    ports: tuple[int, ...] = (), record: Store | None = None, session_id: str | None = None,
) -> Session:  # fmt: skip
    """Rent a machine whose supervisor ends it by deadline_s (or sooner: lease lost, idle, stop).
    Returns once the provider has made it, before its supervisor is up (Session.wait_up), so a
    caller can say so while it boots; launch() is create + wait_up + hold. Until the supervisor is
    up nothing on the machine can end it: a caller that gives up terminates it (machine.terminate).
    Its id is new (LABEL_SESSION), not the machine's: attach() finds a session by it. labels are the caller's (who launched it,
    for what, e.g. box.user, box.cmd); box stamps only RESERVED. ports: what Session.expose may
    open later (Modal and RunPod route a port only if the machine was created with it). Idle: no
    job running and no connection to any of ports, for idle_timeout_s (0: never idle).
    record: the supervisor records status, jobs, and output into it, under record_prefix(id), so
    status() and wait() still answer after the machine is gone, and read_record() reads it.
    session_id: one from new_session_id(), for a caller that must name the session before launch
    returns (a relay answers the browser at once, while the machine boots); fresh by default."""
    session_id = new_session_id() if session_id is None else session_id
    if not SESSION_ID.fullmatch(session_id):
        raise ValueError(f"session_id {session_id!r} is not one new_session_id() makes")
    if clash := sorted(set(labels or {}) & set(RESERVED)):
        raise ValueError(f"labels {clash} are box's own (launch stamps them)")
    args = [
        "--deadline-s", str(deadline_s), "--lease-ttl-s", str(lease_ttl_s), "--idle-timeout-s", str(idle_timeout_s),
        "--ports", ",".join(map(str, ports)),
        *(["--record", RECORD_PATH, *(["--record-sync"] if record.sync_writes else [])] if record else []),
    ]  # fmt: skip
    boot = "import base64,os; exec(base64.b64decode(os.environ['BOX_SUPERVISOR']))"
    entrypoint = ["bash", "-c", f'exec python3 -c {shlex.quote(boot)} --root "$BOX_ROOT" {shlex.join(args)}']
    # TODO(handoff): LABEL_DEADLINE is stamped before the machine boots, but the supervisor's clock
    # starts at boot, so a slow boot (an unpinned Modal L4 took ~6 min) makes the label early by the
    # boot time. Only `box who`/`box gc` still read it (gc's 30 min margin covers the default 15 min
    # boot_timeout_s); the SDK reads the supervisor's own deadline (session.json). Same skew: the
    # provider backstop (timeout_s) also starts at create, so a boot over 600 s leaves it before
    # the supervisor's deadline. Fixing both means deadline_s counts from launch (pass the
    # supervisor an absolute deadline), which changes what deadline_s means: the author's call.
    machine = provider.launch(
        gpu=gpu, image=image, entrypoint=entrypoint,
        env={**(env or {}), "BOX_SUPERVISOR": base64.b64encode(SUPERVISOR.read_bytes()).decode()},
        labels={**(labels or {}), LABEL_BY: "box", LABEL_SESSION: session_id,
                LABEL_DEADLINE: str(int(time.time() + deadline_s))},
        timeout_s=deadline_s + 600,  # the provider's own backstop, past the supervisor's deadline
        ports=list(ports), mounts=[Mount(record, record_prefix(session_id), RECORD_PATH)] if record else [],
    )  # fmt: skip
    if record:
        try:  # nothing else ends a machine whose supervisor is not up
            launched = {"machine_id": machine.id, "provider": provider.name, "labels": machine.labels, "at": time.time()}
            record.put(f"{record_prefix(session_id)}/launch.json", json.dumps(launched).encode())
        except BaseException:
            machine.terminate()
            raise
    return Session(machine, record=record, lease_ttl_s=lease_ttl_s)


def new_session_id() -> str:
    return f"s-{secrets.token_hex(6)}"


def attach(provider: Provider, session_id: str, record: Store | None = None) -> Session:
    """A session launched elsewhere (another process, a detached run). Does not hold its lease.
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
    lease_ttl_s: float | None = None  # the lease's TTL, known to the process that created it (hold() needs it)
    _holding: threading.Event | None = field(default=None, repr=False)
    _running: Running | None = field(default=None, repr=False)  # session.json: fixed once written
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
        """Until the supervisor is up (its first act: ROOT/lease). TimeoutError past timeout_s."""
        give_up = time.monotonic() + timeout_s
        while not self._exists("lease"):
            if time.monotonic() > give_up:
                raise TimeoutError(f"{self.machine.id}: supervisor not up after {timeout_s:.0f} s")
            time.sleep(POLL_S)

    def hold(self) -> None:
        """Heartbeat the lease (4 beats a TTL) until release()/close(); the supervisor ends the
        session if heartbeats stop for its lease TTL (this process died, or lost the network)."""
        assert self.lease_ttl_s is not None, "hold(): a session from create() (attach does not know the lease TTL)"
        every_s = self.lease_ttl_s / 4
        stop = self._holding = threading.Event()

        def beat() -> None:
            while not stop.wait(every_s):
                try:
                    self.machine.exec(f"touch {self._path('lease')}")
                except Gone:
                    return  # nothing left to hold
                except Exception as exc:  # noqa: BLE001 (a missed beat is retried; the TTL allows several)
                    print(f"box: {self.id}: heartbeat failed, retrying: {exc!r}", file=sys.stderr)

        threading.Thread(target=beat, daemon=True, name=f"box-lease-{self.id}").start()

    def release(self) -> None:
        """Stop holding: the session now ends by itself once no job is left (or at its deadline)."""
        self._stop_holding()
        self._touch("released")

    def close(self, timeout_s: float = 900.0) -> None:
        """End the session: kill any running job, let its hook run, then terminate the machine.
        Waits up to timeout_s for the supervisor to say it ended (status() then has why)."""
        self._stop_holding()
        if not isinstance(self.status(), Ended):  # mkdir: a booting supervisor ends at once on stop
            with contextlib.suppress(Gone):  # it may end as soon as the supervisor exits
                self.machine.exec(f"mkdir -p {self.machine.root} && touch {self._path('watch')} {self._path('stop')}")
            with contextlib.suppress(TimeoutError):
                self.wait(timeout_s)
        self.machine.terminate()

    def expose(self, port: int) -> Endpoint:
        """Where to reach `port` on the machine (one of launch's ports) from anywhere. Something
        must listen there (e.g. a job); until it does, requests fail (Modal: 502). Asked of the
        provider once per Session: a port's endpoint is fixed for its machine's life."""
        if port not in self._endpoints:
            self._endpoints[port] = self.machine.expose(port)
        return self._endpoints[port]

    def status(self) -> Status:
        """Booting, Running, or Ended (and why), from the supervisor's files. Once the machine is
        gone, always Ended: machine_lost, or with a record, the record's word (Record.end), which
        may take up to HEARTBEAT_TTL_S to land. Ended is final: once this Session has seen it, it
        answers without asking the machine."""
        if self._ended is not None:
            return self._ended
        try:
            self._ended = self._read_ended()
            if self._ended is None and self._running is None:
                self._running = parse_running(self.machine.read(self._path("session.json")))
        except FileNotFoundError:
            return Booting()
        except Gone:
            return self._status_when_gone()
        return self._ended or self._running

    def wait(self, timeout_s: float | None = None) -> Ended:
        """Block until the session ends; returns why. While waiting it keeps the machine lingering
        (ROOT/watch), so the supervisor's reason is read before the machine goes. Bounded without
        timeout_s too: by the session's deadline (or its machine's loss). TimeoutError past timeout_s
        (checked between polls: a gone machine's status() can take up to HEARTBEAT_TTL_S)."""
        give_up = None if timeout_s is None else time.monotonic() + timeout_s
        while not (self._watch() or isinstance(status := self.status(), Ended)):  # watch first: no gap to end in
            if give_up is not None and time.monotonic() > give_up:
                raise TimeoutError(f"{self.id}: still {status} after {timeout_s:.0f} s")
            time.sleep(POLL_S)
        return status

    def run(self, cmd: str, *, on_exit: str | None = None, hook_budget_s: float = 300.0, env: dict[str, str] | None = None) -> Job:
        """Queue cmd (bash). Jobs run one at a time, in order. on_exit (bash) runs after it ends
        however it ended, with BOX_EXIT_CODE, BOX_REASON, BOX_JOB_DIR set, within hook_budget_s;
        the job is killed hook_budget_s before the session's deadline to leave the hook that time."""
        running = self._running_now()
        left = running.deadline_at - time.time()
        if on_exit and hook_budget_s >= left:
            raise ValueError(f"hook_budget_s={hook_budget_s} does not fit in the session's {left:.0f} s left")
        return self._start(Job(self, new_job_id(), "jobs"), {"cmd": cmd, "on_exit": on_exit, "hook_budget_s": hook_budget_s, "env": env or {}})

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

    def _read_ended(self) -> Ended | None:
        """ended.json's reason; None while the session lasts. Gone once the machine is."""
        try:
            return parse_ended(self.machine.read(self._path("ended.json")))
        except FileNotFoundError:
            return None

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

    def _stop_holding(self) -> None:
        if self._holding is not None:
            self._holding.set()

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

    def logs(self, *, after: LogCursor = (0, 0), follow: bool = False) -> Iterator[LogChunk]:
        """The job's output past `after` (the job's start by default); follow=True until it is done.
        A reader that resumes (a reconnecting browser) passes the last chunk's end, so it never
        re-reads a byte. Once the machine is gone, from the session's record (with follow, once the
        record has the session's end, so it is all of the output there will be). One exec per poll."""
        cursor = after
        while True:
            try:
                read = self._read_live(cursor, watch=follow)
            except Gone:
                if self.session.record is None:
                    raise
                if follow:
                    self.session.wait()
                yield from read_record(self.session.record, self.session.id).logs(self.id, after=cursor, kind=self.kind)
                return
            for chunk in read.chunks:
                cursor = chunk.end
                yield chunk
            if read.more:
                continue
            if read.done or not follow:
                return
            time.sleep(POLL_S)

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


def run_job(
    provider: Provider, cmd: str, *, deadline_s: int, put: list[tuple[str, str]] = (),
    get: list[tuple[str, str]] = (), on_exit: str | None = None, **launch_kw: object,
) -> Ending:  # fmt: skip
    """launch, put each (local, remote), run cmd with its output on this terminal, get each
    (remote, local), close. Exactly the Session calls; use them directly for anything else."""
    with launch(provider, deadline_s=deadline_s, **launch_kw) as s:
        for local, remote in put:
            s.put(local, remote)
        job = s.run(cmd, on_exit=on_exit)
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

    def write(self, path: str, data: bytes) -> None:
        raise Gone(f"{self.id}: gone (known from its record)")

    def read(self, path: str) -> bytes:
        raise Gone(f"{self.id}: gone (known from its record)")

    def expose(self, port: int) -> Endpoint:
        raise Gone(f"{self.id}: gone (known from its record)")

    def terminate(self) -> None:
        """Already gone: nothing to do."""


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
        running=_parse_if_present(store, f"{prefix}/session.json", parse_running),
        ended=_parse_if_present(store, f"{prefix}/ended.json", parse_ended),
        heartbeat=_parse_if_present(store, f"{prefix}/heartbeat.json", parse_heartbeat),
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


def parse_running(raw: bytes) -> Running:
    """session.json, as the supervisor wrote it."""
    d = json.loads(raw)
    return Running(started_at=float(d["started_at"]), deadline_at=float(d["deadline_at"]))


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


def parse_ended(raw: bytes) -> Ended:
    """ended.json, as the supervisor wrote it: its reason must be one box knows."""
    reason = json.loads(raw)["reason"]
    if reason not in get_args(EndReason) or reason == "machine_lost":
        raise ValueError(f"ended.json: unknown end reason {reason!r}")
    return Ended(reason)


def ignored(rel: str, ignore: tuple[str, ...]) -> bool:
    return any(fnmatch(rel, g) or (g.startswith("**/") and fnmatch(rel.rsplit("/", 1)[-1], g[3:])) for g in ignore)
