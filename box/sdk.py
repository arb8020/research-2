"""box: rent a machine, run jobs on it, bring results back, and never leave it billing.

    with box.launch(provider, gpu="L4", image=IMAGE, deadline_s=3600) as s:   # a Session
        s.put("robots", "/work/robots")
        job = s.run("cd /work && python robots/train.py", on_exit="upload.sh")
        for stream, text in job.logs(follow=True): ...
        ending = job.wait()                  # Ending(reason="exited", exit_code=0, ...)
        s.get("/work/runs", "runs")
    # leaving the block ends the session: a running job is killed and its hook still runs
    s.status()                               # Ended(reason="stopped")

    s = box.attach(provider, session_id)     # from anywhere, by the session's own id
    match s.status():                        # Booting() | Running(started_at, deadline_at) | Ended(reason)
        case Running(): s.wait()             # -> Ended: the awaitable terminal state

    with box.launch(provider, deadline_s=3600, ports=[8888]) as s:   # ports: declared at launch
        s.run("jupyter server --port 8888 ...")
        s.expose(8888)                       # Endpoint(url="https://...", headers={})

A provider only rents raw machines (Machine: exec, write, read, terminate). Everything else is
here, built from those four calls and the supervisor (box/supervisor.py), which every machine
runs as its entrypoint and which talks to this file only through files under machine.root.
"""

from __future__ import annotations

import base64
import contextlib
import io
import json
import secrets
import shlex
import sys
import tarfile
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from fnmatch import fnmatch
from pathlib import Path
from typing import Literal, Protocol, get_args

SUPERVISOR = Path(__file__).with_name("supervisor.py")
LABEL_BY = "box.by"
LABEL_SESSION = "box.session"  # the session's own id: a session is not its machine, even while 1:1
LABEL_DEADLINE = "box.deadline"  # unix time the session ends by
RESERVED = (LABEL_BY, LABEL_SESSION, LABEL_DEADLINE)  # launch stamps these; a caller's labels are the rest
POLL_S = 0.5


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

    def launch(
        self, *, gpu: str | None, image: str | None, entrypoint: list[str], env: dict[str, str],
        labels: dict[str, str], timeout_s: int, ports: list[int],
    ) -> Machine: ...  # fmt: skip
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
    """How a job ended. reason: exited | killed | deadline | lease_lost | stopped."""

    reason: str
    exit_code: int | None
    hook_exit_code: int | None = None


def launch(  # noqa: PLR0913 (all keyword-only; each is one knob of the session)
    provider: Provider, *, deadline_s: int, gpu: str | None = None, image: str | None = None,
    env: dict[str, str] | None = None, labels: dict[str, str] | None = None,
    lease_ttl_s: float = 60.0, idle_timeout_s: float = 0.0, boot_timeout_s: float = 900.0,
    ports: tuple[int, ...] = (),
) -> Session:  # fmt: skip
    """Rent a machine whose supervisor ends it by deadline_s (or sooner: lease lost, idle, stop).
    Returns once the supervisor is up; a machine that is not up in boot_timeout_s (image pull,
    a stuck host) is terminated here, since no supervisor exists yet to end it. The returned
    Session holds the lease (heartbeats) until release() or close(). Its id is new (LABEL_SESSION),
    not the machine's: attach() finds a session by it. labels are the caller's (who launched it,
    for what, e.g. box.user, box.cmd); box stamps only RESERVED. ports: what Session.expose may
    open later (Modal and RunPod route a port only if the machine was created with it). Idle: no
    job running and no connection to any of ports, for idle_timeout_s (0: never idle)."""
    if clash := sorted(set(labels or {}) & set(RESERVED)):
        raise ValueError(f"labels {clash} are box's own (launch stamps them)")
    args = [
        "--deadline-s", str(deadline_s), "--lease-ttl-s", str(lease_ttl_s), "--idle-timeout-s", str(idle_timeout_s),
        "--ports", ",".join(map(str, ports)),
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
        labels={**(labels or {}), LABEL_BY: "box", LABEL_SESSION: f"s-{secrets.token_hex(6)}",
                LABEL_DEADLINE: str(int(time.time() + deadline_s))},
        timeout_s=deadline_s + 600,  # the provider's own backstop, past the supervisor's deadline
        ports=list(ports),
    )  # fmt: skip
    session = Session(machine)
    give_up = time.monotonic() + boot_timeout_s
    while not session._exists("lease"):  # the supervisor's first act
        if time.monotonic() > give_up:
            machine.terminate()
            raise TimeoutError(f"{machine.id}: supervisor not up after {boot_timeout_s:.0f} s; terminated")
        time.sleep(POLL_S)
    session.hold(lease_ttl_s / 4)
    return session


def attach(provider: Provider, session_id: str) -> Session:
    """A session launched elsewhere (another process, a detached run), while its machine lives.
    Does not hold its lease. LookupError if no live machine carries that session id."""
    found = provider.list({LABEL_SESSION: session_id})
    if len(found) != 1:
        raise LookupError(f"{provider.name} provider: {len(found)} live machines for session {session_id}")
    return Session(found[0])


@dataclass
class Session:
    machine: Machine
    _holding: threading.Event | None = field(default=None, repr=False)
    _running: Running | None = field(default=None, repr=False)  # session.json: fixed once written
    _ended: Ended | None = field(default=None, repr=False)  # terminal: once known, it stays

    @property
    def id(self) -> str:
        return self.machine.labels[LABEL_SESSION]

    def __enter__(self) -> Session:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def hold(self, every_s: float) -> None:
        """Heartbeat the lease every every_s until release()/close(); the supervisor ends the
        session if heartbeats stop for its lease TTL (this process died, or lost the network)."""
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
        must listen there (e.g. a job); until it does, requests fail (Modal: 502)."""
        return self.machine.expose(port)

    def status(self) -> Status:
        """Booting, Running, or Ended (and why), from the supervisor's files. Ended is final: once
        this Session has seen it, it answers without asking the machine."""
        if self._ended is None:
            self._ended = self._read_ended()
        if self._ended is not None:
            return self._ended
        if self._running is None:
            try:
                self._running = parse_running(self.machine.read(self._path("session.json")))
            except FileNotFoundError:
                return Booting()
            except Gone:
                self._ended = Ended("machine_lost")
                return self._ended
        return self._running

    def wait(self, timeout_s: float | None = None) -> Ended:
        """Block until the session ends; returns why. While waiting it keeps the machine lingering
        (ROOT/watch), so the supervisor's reason is read before the machine goes. Bounded without
        timeout_s too: by the session's deadline (or its machine's loss). TimeoutError past timeout_s."""
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
        running = self.status()
        if not isinstance(running, Running):
            raise RuntimeError(f"{self.id}: cannot run a job on a session that is {running}")
        left = running.deadline_at - time.time()
        if on_exit and hook_budget_s >= left:
            raise ValueError(f"hook_budget_s={hook_budget_s} does not fit in the session's {left:.0f} s left")
        job = Job(self, f"{int(time.time())}-{secrets.token_hex(3)}")
        spec = {"cmd": cmd, "on_exit": on_exit, "hook_budget_s": hook_budget_s, "env": env or {}}
        tmp = self._path(f"jobs/{job.id}.spec.tmp")
        self.machine.write(tmp, json.dumps(spec).encode())
        self._check(f"mkdir -p {job.dir} && mv {tmp} {job.dir}/spec.json")  # atomic: never half a spec
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
        """Every job this session was given, oldest first (from any process)."""
        out = self._check(f"ls {self._path('jobs')}")
        return [Job(self, name) for name in sorted(out.split()) if not name.endswith(".tmp")]

    def _read_ended(self) -> Ended | None:
        """ended.json's reason; None while the session lasts; machine_lost if the machine is gone.
        Seam: once the supervisor also records status to durable storage, Gone reads that record."""
        try:
            return parse_ended(self.machine.read(self._path("ended.json")))
        except FileNotFoundError:
            return None
        except Gone:
            return Ended("machine_lost")

    def _watch(self) -> None:
        """Tell the supervisor someone is reading, so the machine lingers for us after it ends."""
        with contextlib.suppress(Gone):  # then the next status() says machine_lost
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


@dataclass(frozen=True)
class Job:
    session: Session
    id: str

    @property
    def dir(self) -> str:
        return self.session._path(f"jobs/{self.id}")

    def status(self) -> dict | None:
        """The supervisor's status.json, or None while the job waits its turn."""
        try:
            return json.loads(self.session.machine.read(f"{self.dir}/status.json"))
        except FileNotFoundError:
            return None

    def done(self) -> bool:
        return (self.status() or {}).get("state") == "done"

    # TODO(handoff): every poll here and in logs(follow) is 2-3 execs (~100 ms each on Modal, an ssh
    # round trip on RunPod). One exec returning status + both log tails would cut that to one.
    def wait(self) -> Ending:
        while not (self.session._watch() or self.done()):
            time.sleep(POLL_S)
        s = self.status() or {}
        return Ending(s["reason"], s["exit_code"], s.get("hook_exit_code"))

    def kill(self) -> None:
        """Kill this job (its whole process group); its hook runs; the session goes on."""
        self.session._touch(f"jobs/{self.id}/kill")

    def logs(self, *, follow: bool = False) -> Iterator[tuple[str, str]]:
        """(stream, text) chunks of the job's output from its start; follow=True until it is done."""
        offsets = {"stdout": 0, "stderr": 0}
        while True:
            if follow:
                self.session._watch()
            finished = self.done()  # read before the logs, so nothing written before "done" is missed
            for stream in offsets:
                rc, text, _ = self.session.machine.exec(f"tail -c +{offsets[stream] + 1} {self.dir}/{stream} 2>/dev/null")
                if rc == 0 and text:
                    offsets[stream] += len(text.encode())
                    yield stream, text
            if finished or not follow:
                return
            time.sleep(POLL_S)


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
        for stream, text in job.logs(follow=True):
            sinks[stream].write(text)
            sinks[stream].flush()
        ending = job.wait()
        for remote, local in get:
            s.get(remote, local)
    return ending


def parse_running(raw: bytes) -> Running:
    """session.json, as the supervisor wrote it."""
    d = json.loads(raw)
    return Running(started_at=float(d["started_at"]), deadline_at=float(d["deadline_at"]))


def parse_ended(raw: bytes) -> Ended:
    """ended.json, as the supervisor wrote it: its reason must be one box knows."""
    reason = json.loads(raw)["reason"]
    if reason not in get_args(EndReason) or reason == "machine_lost":
        raise ValueError(f"ended.json: unknown end reason {reason!r}")
    return Ended(reason)


def ignored(rel: str, ignore: tuple[str, ...]) -> bool:
    return any(fnmatch(rel, g) or (g.startswith("**/") and fnmatch(rel.rsplit("/", 1)[-1], g[3:])) for g in ignore)
