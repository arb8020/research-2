"""The supervisor: the first process on every box. Stdlib only; providers copy this file onto the
box (ROOT/supervisor.py) and run it as the entrypoint. It holds the session, runs jobs one at a
time, and ends the box.

Everything goes through files under ROOT (no sockets), so a client only needs the provider's exec:

    ROOT/supervisor.py          this file; a client changes the lease with `python3 ROOT/supervisor.py lease ...`
    ROOT/session.json           supervisor writes it first: {started_at, created_at, ceiling} (unix times)
    ROOT/lease.json             {until, ceiling, released}: the session ends at until (<= ceiling). The
                                supervisor writes the first one; after that only `lease` changes it
    ROOT/lease-audit.json       every change of the lease: [{op, until, at, host, pid, n}] (debugging only)
    ROOT/up                     supervisor writes it last at start: a client takes it as "the supervisor is up"
    ROOT/stop                   client wrote it: kill any job, run its hook, end
    ROOT/jobs/<id>/spec.json    client writes it (atomically) to queue a job: {cmd, on_exit, hook_budget_s, max_duration_s, env}
    ROOT/jobs/<id>/stdout       \\ the job's output
    ROOT/jobs/<id>/stderr       /
    ROOT/jobs/<id>/status.json  supervisor writes it: {state, reason, exit_code, hook_exit_code, started, ended}
    ROOT/jobs/<id>/kill         client wrote it: kill the job (its hook runs), the session goes on
    ROOT/services/<id>/...      a service: spec.json {cmd, env}, then as a job (no hook, no max duration)
    ROOT/watch                  a log follower (its tail, each beat) or job waiter (each poll) touches it (the machine lingers for it)
    ROOT/supervisor.py          this file, installed by the boot: `supervisor.py lease` changes the lease, `supervisor.py tail` feeds a log follower
    ROOT/ended.json             supervisor writes it last: {reason, at}; then it lingers up to LINGER_S
                                while someone is still reading (see linger)

A session ends at min(lease.until, ceiling) (reason "lease", or "released" if a client released
it), on stop ("stopped"), or idle timeout ("idle"). Nothing ends it because a client went away:
the lease is the guarantee. Idle means no job running and no established TCP connection to an
exposed port (--ports): the supervisor owns idleness, since a provider's own idle timer (Modal's)
sees only connections, never work in the box. Whatever ends it, a running job is killed (whole
process group) and its on_exit hook still runs, for up to its hook_budget_s but never past the
ceiling. A job is killed at min(its start + max_duration_s ("timeout"), the lease's end minus its
hook_budget_s ("lease")), so its hook fits inside the lease.

A service (ROOT/services/<id>) is a long-lived server, e.g. a Jupyter Server behind an exposed
port. It starts at once, beside the job queue (never waits for a job, never holds one up), and it
is not work for idleness: its connections are what count. It has no hook and no max duration,
and is killed (whole group) when the session ends; its status.json says why, as a job's does. A
session runs at most MAX_SERVICES: past that a service spec ends at once with reason "refused"
(the client refuses first; this covers two racing clients).

With --record DIR (a store mounted on the machine, box/store.py), a Recorder copies the session
there every FLUSH_S (sooner past FLUSH_BYTES of new output), so it outlives the machine:

    DIR/session.json            \\ as under ROOT, at start and whenever they change
    DIR/lease.json              |
    DIR/lease-audit.json        /
    DIR/heartbeat.json          every flush: {at, ttl_s}; older than ttl_s, the recorder has stopped
    DIR/jobs/<id>/spec.json     \\ as under ROOT (env: names only), copied when they change;
    DIR/jobs/<id>/status.json   /  services the same, under DIR/services/<id>
    DIR/jobs/<id>/<stream>.<n>.<end>  closed chunks of new output, n = 1, 2, ... per job across both
                                streams; end = the stream's bytes up to the chunk's last (a reader
                                resuming at a byte offset skips chunks without reading them)
    DIR/ended.json              as ROOT/ended.json, written (and synced) before ROOT/ended.json

Every file is whole (tmp + rename) and never changes once a reader could have seen it, except the
JSON ones, which are replaced whole. --record-sync runs `sync DIR` after each flush (a Modal
Volume commits on it). A chunk never splits a UTF-8 character unless the output is not UTF-8.
"""

from __future__ import annotations

import argparse
import contextlib
import ctypes
import fcntl
import json
import os
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import BinaryIO

TICK_S = 0.2
KILL_GRACE_S = 10.0  # SIGTERM -> SIGKILL
LINGER_S = 30.0  # after the session ends, the most a reader still there gets to finish reading
WATCH_TTL_S = 5.0  # a log follower touches ROOT/watch each beat; older than this, nobody is following
PROC_TCP = ("/proc/net/tcp", "/proc/net/tcp6")
TCP_ESTABLISHED = "01"  # /proc/net/tcp's st column (include/net/tcp_states.h)
STREAMS = ("stdout", "stderr")
FLUSH_S = 2.0  # the record lags the machine by at most this (plus a sync)
FLUSH_BYTES = 256 * 1024  # new output past this flushes sooner
CHUNK_BYTES = 4 * 1024 * 1024  # one chunk per stream per flush, at most this: more waits (backpressure, never dropped)
HEARTBEAT_TTL_S = 5 * FLUSH_S  # a reader takes a heartbeat older than this as "the recorder stopped"
MAX_CEILING_S = 48 * 3600  # the longest a session may be asked to live, from its creation
CHUNK_DIGITS = 7  # flushes come at most every TICK_S: a job over a whole MAX_CEILING_S session has < 2 * 864000 chunks
MAX_CHUNKS = 10**CHUNK_DIGITS - 1
assert 2 * MAX_CEILING_S / TICK_S < MAX_CHUNKS, "a chunk number that fits CHUNK_DIGITS for a whole session"
MAX_SERVICES = 8  # a session's long-lived servers; more is a client bug, not a workload
KINDS = ("jobs", "services")  # ROOT/<kind>/<id>: what a client queues and what it serves
LEASE_OPS = ("create", "extend", "release")  # what lease-audit.json records; create is the supervisor's own
MAX_LEASE_AUDIT = 1024  # entries; a run of one op from one process is one entry (n counts it), so this is runs, not calls


# TODO(handoff): if the supervisor itself dies, nothing writes ended.json or runs BOX_ON_SHUTDOWN;
# the job dies with it on Linux (PDEATHSIG), and only the provider's backstop ends the machine
# (Modal: sandbox timeout; RunPod: BOOT's backstop timer, and a container restart deletes the pod).
# With --record, the record still has everything up to the last flush, and its stale heartbeat plus
# the machine's absence read as machine_lost (sdk.Record.status).
def main() -> None:
    if sys.argv[1:2] == ["lease"]:
        lease_main(sys.argv[2:])
        return
    p = argparse.ArgumentParser()
    p.add_argument("--root", required=True)
    p.add_argument("--created-at", type=float, required=True, help="unix time the client created the session")
    p.add_argument("--lease-until", type=float, required=True, help="unix time the session's first lease ends")
    p.add_argument("--ceiling", type=float, required=True, help="unix time no lease can pass")
    p.add_argument("--host", required=True, help="the creating client's host, for the lease audit")
    p.add_argument("--pid", type=int, required=True, help="the creating client's pid, for the lease audit")
    p.add_argument("--idle-timeout-s", type=float, default=0.0, help="end after this long with no job and no connection; 0 = never")
    p.add_argument("--ports", type=lambda s: [int(p) for p in s.split(",") if p], default=[], help="exposed ports, comma-separated")
    p.add_argument("--record", default="", help="record the session into this directory (a mounted store), relative to --root")
    p.add_argument("--record-sync", action="store_true", help="run `sync <record dir>` after each flush (Modal Volumes)")
    p.add_argument(
        "--on-shutdown", default=os.environ.get("BOX_ON_SHUTDOWN", ""),
        help="bash run last, to end the machine itself (a provider sets BOX_ON_SHUTDOWN, e.g. its API's delete)",
    )  # fmt: skip
    a = p.parse_args()
    # pair of sdk.create's assertions: the times it parsed the caller's durations into
    assert a.created_at < a.lease_until, (a.created_at, a.lease_until)
    assert a.lease_until <= a.ceiling, (a.lease_until, a.ceiling)
    assert a.ceiling <= a.created_at + MAX_CEILING_S, (a.created_at, a.ceiling)
    root = Path(a.root)
    for kind in KINDS:
        (root / kind).mkdir(parents=True, exist_ok=True)
    write_json(root / "session.json", {"started_at": time.time(), "created_at": a.created_at, "ceiling": a.ceiling})
    write_json(root / "lease.json", {"until": a.lease_until, "ceiling": a.ceiling, "released": False})
    write_json(root / "lease-audit.json", [audit_entry("create", a.lease_until, a.created_at, a.host, a.pid)])
    recorder = Recorder(root, root / a.record, sync=a.record_sync) if a.record else None
    try:
        if recorder:
            recorder.start()  # the record has session.json and the lease before anyone is told the supervisor is up
        (root / "up").touch()  # last: a client takes it as "the supervisor is up"
        reason = supervise(root, a.idle_timeout_s, a.ports)
        ended = {"reason": reason, "at": time.time()}
        if recorder:
            recorder.finish(ended)  # first: a closer terminates the machine once it reads ROOT/ended.json
    finally:
        if recorder:
            recorder.close()  # its owner joins it, even if supervise() crashed (else this process never exits)
    write_json(root / "ended.json", ended)
    linger(root)
    if a.on_shutdown:
        subprocess.run(["bash", "-c", a.on_shutdown], check=False)


# ---- the lease ----


def lease_main(argv: list[str]) -> None:
    """`python3 ROOT/supervisor.py lease --root ROOT --op extend|release --until T --host H --pid P`:
    a client's change to the lease, in one exec. Prints the lease after it (lease.json's shape)."""
    p = argparse.ArgumentParser(prog="supervisor.py lease")
    p.add_argument("--root", required=True)
    p.add_argument("--op", choices=("extend", "release"), required=True)
    p.add_argument("--until", type=float, required=True, help="extend: unix time asked for; release: ignored")
    p.add_argument("--host", required=True)
    p.add_argument("--pid", type=int, required=True)
    a = p.parse_args(argv)
    print(json.dumps(change_lease(Path(a.root), a.op, a.until, a.host, a.pid)))


def change_lease(root: Path, op: str, until: float, host: str, pid: int) -> dict:
    """Apply op to ROOT/lease.json under a lock (two clients extending at once never lose one), and
    audit it if it changed anything. The clock is this machine's: the one the supervisor ends by."""
    with (root / "lease.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)  # released when the file closes
        lease = read_lease(root)
        now = time.time()
        changed = next_lease(lease, op, until, now)
        if changed != lease:
            write_json(root / "lease.json", changed)
            audit = json.loads((root / "lease-audit.json").read_text())
            write_json(root / "lease-audit.json", next_audit(audit, audit_entry(op, changed["until"], now, host, pid)))
    return changed


def next_lease(lease: dict, op: str, until: float, now: float) -> dict:
    """The lease after op, at now. extend clamps to the ceiling and never shortens: a shorter ask is
    a no-op, as SF Compute's "a shorter re-ask never cuts a hold". release ends it now. A lease that
    has run out (or was released) stays over: the session ends within a TICK_S, nothing revives it."""
    assert op in ("extend", "release"), op
    assert lease["until"] <= lease["ceiling"], lease
    if lease["released"] or lease["until"] <= now:
        return lease
    if op == "release":
        return {**lease, "until": now, "released": True}
    # the clamp is the contract (the caller reads what it got from the returned lease), not a fallback
    extended = {**lease, "until": max(lease["until"], min(until, lease["ceiling"]))}
    assert extended["until"] >= lease["until"], (lease, extended)
    assert extended["until"] <= lease["ceiling"], (lease, extended)
    return extended


def audit_entry(op: str, until: float, at: float, host: str, pid: int) -> dict:
    assert op in LEASE_OPS, op
    return {"op": op, "until": until, "at": at, "host": host, "pid": pid, "n": 1}


def next_audit(audit: list[dict], entry: dict) -> list[dict]:
    """audit plus entry. A run of the same op from the same process (keep()'s renewals) is one entry
    whose n counts it, so the audit stays small. Past MAX_LEASE_AUDIT entries the change is refused
    (a data limit: the lease still ends when it says, and the caller hears why)."""
    last = audit[-1] if audit else None
    if last is not None and (last["op"], last["host"], last["pid"]) == (entry["op"], entry["host"], entry["pid"]):
        return [*audit[:-1], {**entry, "n": last["n"] + 1}]
    if len(audit) >= MAX_LEASE_AUDIT:
        raise RuntimeError(f"lease audit full ({MAX_LEASE_AUDIT} entries): refusing {entry['op']}")
    return [*audit, entry]


def read_lease(root: Path) -> dict:
    """ROOT/lease.json, parsed: {until, ceiling, released}, until <= ceiling."""
    raw = json.loads((root / "lease.json").read_text())
    lease = {"until": float(raw["until"]), "ceiling": float(raw["ceiling"]), "released": bool(raw["released"])}
    if lease["until"] > lease["ceiling"]:
        raise ValueError(f"{root}/lease.json: until {lease['until']} past ceiling {lease['ceiling']}")
    return lease


def lease_end(lease: dict) -> tuple[float, str]:
    """When the lease ends the session, and the reason it will give."""
    return min(lease["until"], lease["ceiling"]), "released" if lease["released"] else "lease"


# ---- the session ----


def linger(root: Path) -> None:
    """Keep the machine up to LINGER_S after the session ended, while a follower of the logs or a
    waiter on a job is still reading (ROOT/watch touched within WATCH_TTL_S). A closer does not
    wait this out: it terminates the machine once ended.json exists."""

    def reading() -> bool:
        watch = root / "watch"
        return watch.exists() and time.time() - watch.stat().st_mtime < WATCH_TTL_S

    until = time.monotonic() + LINGER_S
    while time.monotonic() < until and reading():
        time.sleep(TICK_S)


def supervise(root: Path, idle_timeout_s: float, ports: list[int]) -> str:
    """Run jobs one at a time (services beside them) until the session ends; returns why it ended."""
    done: set[str] = set()
    services: dict[Path, subprocess.Popen] = {}  # every service started, running or not
    idle_since = time.monotonic()
    while (end := session_end(root, idle_timeout_s, idle_since)) is None:  # bounded: the lease ends by the ceiling
        tend_services(root, services)
        if idle_timeout_s and ports and connected(ports):
            idle_since = time.monotonic()  # someone is using an exposed port: not idle
        job_dir = next_job(root, done)
        if job_dir is None:
            time.sleep(TICK_S)
            continue
        done.add(job_dir.name)
        run_job(root, job_dir, lambda: tend_services(root, services))
        idle_since = time.monotonic()
    stop_services(services, end)
    return end


def tend_services(root: Path, services: dict[Path, subprocess.Popen]) -> None:
    """Start every service spec not started (or refused) yet; kill those asked to
    (ROOT/services/<id>/kill); record the end of each that exited by itself."""
    for job_dir in sorted((root / "services").iterdir()):
        if job_dir in services or (job_dir / "status.json").exists() or not (job_dir / "spec.json").exists():
            continue
        if len(services) >= MAX_SERVICES:  # the client checks too, but two clients can race past it
            write_json(job_dir / "status.json", {"state": "done", "reason": "refused", "exit_code": None, "ended": time.time()})
            continue
        spec = json.loads((job_dir / "spec.json").read_text())
        env = {**spec.get("env", {}), "BOX_JOB_ID": job_dir.name, "BOX_JOB_DIR": str(job_dir)}
        services[job_dir] = child = spawn(spec["cmd"], env, job_dir, stdout=job_dir / "stdout", stderr=job_dir / "stderr")
        write_json(job_dir / "status.json", {"state": "running", "started": time.time(), "pgid": child.pid})
    for job_dir, child in services.items():
        if child.poll() is None and (job_dir / "kill").exists():
            kill_group(child)
            end_service(job_dir, "killed", child.returncode)
        elif child.poll() is not None and service_state(job_dir) == "running":
            end_service(job_dir, "exited", child.returncode)


def stop_services(services: dict[Path, subprocess.Popen], reason: str) -> None:
    """The session ended: kill every running service's group; its status says the session's reason."""
    for job_dir, child in services.items():
        if child.poll() is None:
            kill_group(child)
            end_service(job_dir, reason, child.returncode)
        elif service_state(job_dir) == "running":
            end_service(job_dir, "exited", child.returncode)


def end_service(job_dir: Path, reason: str, code: int | None) -> None:
    status = json.loads((job_dir / "status.json").read_text())
    write_json(job_dir / "status.json", {**status, "state": "done", "reason": reason, "exit_code": code, "ended": time.time()})


def service_state(job_dir: Path) -> str:
    return json.loads((job_dir / "status.json").read_text())["state"]


def session_end(root: Path, idle_timeout_s: float, idle_since: float) -> str | None:
    if (root / "stop").exists():
        return "stopped"
    end_at, reason = lease_end(read_lease(root))
    if time.time() >= end_at:
        return reason
    if idle_timeout_s and time.monotonic() - idle_since >= idle_timeout_s:
        return "idle"
    return None


def connected(ports: list[int]) -> bool:
    """Does any established TCP connection end at one of ports on this machine?"""
    return any(port in ports for port in established_local_ports())


def established_local_ports() -> list[int]:
    """The local port of every established TCP connection. Linux: /proc/net/tcp{,6} (local address
    "HEXADDR:HEXPORT", state 01 = ESTABLISHED). Elsewhere (the local provider on macOS): netstat,
    whose local address ends ".PORT"."""
    if sys.platform == "linux":
        tables = [Path(f).read_text().splitlines()[1:] for f in PROC_TCP if Path(f).exists()]
        rows = [line.split() for table in tables for line in table]
        return [int(r[1].rsplit(":", 1)[1], 16) for r in rows if r[3] == TCP_ESTABLISHED]
    out = subprocess.run(["netstat", "-an", "-p", "tcp"], capture_output=True, text=True, check=True).stdout
    local = [line.split()[3] for line in out.splitlines() if line.endswith("ESTABLISHED")]
    return [int(address.rsplit(".", 1)[1]) for address in local]


def next_job(root: Path, done: set[str]) -> Path | None:
    """The oldest job with a spec that has not run yet."""
    pending = [d for d in (root / "jobs").iterdir() if d.name not in done and (d / "spec.json").exists()]
    return min(pending, key=lambda d: (d / "spec.json").stat().st_mtime, default=None)


def job_end(root: Path, job_dir: Path, killed_at: float, budget: float) -> str | None:
    """Why the running job must stop now, if it must. killed_at: its start + max_duration_s
    (monotonic). The lease's end is read each time: an extend moves it, a release brings it to now."""
    if (root / "stop").exists():
        return "stopped"
    end_at, reason = lease_end(read_lease(root))
    if time.time() >= end_at - budget:
        return reason  # in time for the hook to finish inside the lease
    if time.monotonic() >= killed_at:
        return "timeout"
    if (job_dir / "kill").exists():
        return "killed"
    return None


def run_job(root: Path, job_dir: Path, tick: Callable[[], None]) -> None:
    """Run one job and its hook, calling tick (services) while it runs. The session goes on after
    it: the main loop sees whatever ended the session (stop, the lease) on its next look."""
    spec = json.loads((job_dir / "spec.json").read_text())
    spec["env"] = {**spec.get("env", {}), "BOX_JOB_ID": job_dir.name, "BOX_JOB_DIR": str(job_dir)}
    budget = float(spec.get("hook_budget_s", 300)) if spec.get("on_exit") else 0.0  # time kept for the hook
    max_duration_s = float(spec["max_duration_s"])
    assert 0 < max_duration_s <= MAX_CEILING_S, max_duration_s  # pair of Session.run's check
    child = spawn(spec["cmd"], spec["env"], job_dir, stdout=job_dir / "stdout", stderr=job_dir / "stderr")
    killed_at = time.monotonic() + max_duration_s
    status = {"state": "running", "started": time.time(), "pgid": child.pid}
    write_json(job_dir / "status.json", status)

    reason = None
    while (code := child.poll()) is None:  # bounded: killed_at, and the lease ends by the ceiling
        if (reason := job_end(root, job_dir, killed_at, budget)) is not None:
            kill_group(child)
            code = child.returncode
            break
        tick()
        time.sleep(TICK_S)
    reason = reason or "exited"

    status.update(state="hook" if spec.get("on_exit") else "done", reason=reason, exit_code=code, ended=time.time())
    write_json(job_dir / "status.json", status)
    if spec.get("on_exit"):
        env = {**spec["env"], "BOX_EXIT_CODE": str(code), "BOX_REASON": reason}
        # the ceiling, not the lease: a release (until = now) still leaves a stopped job its hook
        timeout = max(0.0, min(budget, read_lease(root)["ceiling"] - time.time()))
        status["hook_exit_code"] = run_hook(spec["on_exit"], env, job_dir, timeout)
        status["state"] = "done"
        write_json(job_dir / "status.json", status)


def spawn(cmd: str, env: dict[str, str], job_dir: Path, *, stdout: Path, stderr: Path) -> subprocess.Popen:
    """cmd in its own process group (so a kill reaches every descendant) that dies with us on Linux."""
    with stdout.open("ab") as out, stderr.open("ab") as err:
        return subprocess.Popen(
            ["bash", "-c", cmd], env={**os.environ, **env}, cwd=os.environ.get("BOX_WORKDIR", str(job_dir)),
            stdin=subprocess.DEVNULL, stdout=out, stderr=err, start_new_session=True, preexec_fn=die_with_parent,
        )  # fmt: skip


def die_with_parent() -> None:
    """PR_SET_PDEATHSIG: the job gets SIGKILL if the supervisor dies. Linux only; macOS has no equivalent."""
    if sys.platform == "linux":
        ctypes.CDLL("libc.so.6", use_errno=True).prctl(1, signal.SIGKILL)


def kill_group(child: subprocess.Popen) -> None:
    """SIGTERM the job's whole process group, then SIGKILL it after KILL_GRACE_S."""
    for sig, wait_s in ((signal.SIGTERM, KILL_GRACE_S), (signal.SIGKILL, None)):
        try:
            os.killpg(child.pid, sig)
        except ProcessLookupError:
            break
        try:
            child.wait(timeout=wait_s)
            break
        except subprocess.TimeoutExpired:
            continue


def run_hook(cmd: str, env: dict[str, str], job_dir: Path, timeout: float) -> int | None:
    """The hook's exit code, or None if it ran past timeout (then its group is killed)."""
    hook = spawn(cmd, env, job_dir, stdout=job_dir / "hook.stdout", stderr=job_dir / "hook.stderr")
    try:
        return hook.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(hook.pid, signal.SIGKILL)
        hook.wait()
        return None


def recorded_spec(raw: bytes) -> bytes:
    """A job spec as the record keeps it: env values never leave the machine (they hold secrets,
    e.g. a service's JUPYTER_TOKEN, and the record outlives it), only their names."""
    spec = json.loads(raw)
    return json.dumps({**spec, "env": sorted(spec.get("env", {}))}).encode()


class Recorder:
    """Copies the session under root into dest (a store mounted on the machine) every FLUSH_S, on
    its own thread, so the session outlives the machine (layout: module docstring). main owns it:
    start() before ROOT/up, finish() before ROOT/ended.json, and close() (joins the thread) on any
    way out, a crash included: the thread is not a daemon, so an unjoined one would keep the
    supervisor from ever exiting. A recording that fails (the store
    unreachable, disk full) is reported on stderr and stops; the session goes on (fail-open: the
    job is the point), and readers see the heartbeat go stale."""

    def __init__(self, root: Path, dest: Path, *, sync: bool) -> None:
        self.root = root
        self.dest = dest
        self.sync = sync
        self.offsets: dict[tuple[str, str], int] = {}  # ("<kind>/<id>", stream) -> bytes of it recorded
        self.chunks: dict[str, int] = {}  # "<kind>/<id>" -> chunks written (numbered from 1)
        self.copied: dict[str, bytes] = {}  # rel path -> what was last copied there
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.run, daemon=False, name="box-recorder")  # owned: main joins it

    def start(self) -> None:
        self.dest.mkdir(parents=True, exist_ok=True)
        self.flush(final=False)  # session.json + a first heartbeat, synced
        self.thread.start()

    def close(self) -> None:
        """Stop the thread and join it (idempotent)."""
        self.stop.set()
        if self.thread.is_alive():
            self.thread.join()
        assert not self.thread.is_alive()

    def finish(self, ended: dict) -> None:
        self.close()
        try:
            self.flush(final=True)
            put(self.dest / "ended.json", json.dumps(ended).encode())
            self.commit()
        except Exception as e:  # noqa: BLE001 (fail-open, see class docstring)
            print(f"box supervisor: recording into {self.dest} failed at the end: {e!r}", file=sys.stderr, flush=True)

    def run(self) -> None:
        last = time.monotonic()
        while not self.stop.wait(TICK_S):
            if time.monotonic() - last < FLUSH_S and self.pending() < FLUSH_BYTES:
                continue
            try:
                self.flush(final=False)
            except Exception as e:  # noqa: BLE001 (fail-open, see class docstring)
                print(f"box supervisor: recording into {self.dest} stopped: {e!r}", file=sys.stderr, flush=True)
                return
            last = time.monotonic()

    def flush(self, *, final: bool) -> None:
        """Everything new since the last flush, then the heartbeat, then a sync. final: drain all
        output (the session has ended, nothing is written any more)."""
        for name in ("session.json", "lease.json", "lease-audit.json"):  # the lease: as often as it changes
            self.copy(name, (self.root / name).read_bytes())
        for job_dir in self.job_dirs():
            self.flush_job(job_dir, final=final)
        put(self.dest / "heartbeat.json", json.dumps({"at": time.time(), "ttl_s": HEARTBEAT_TTL_S}).encode())
        self.commit()

    def job_dirs(self) -> list[Path]:
        """Every job's and service's directory under root."""
        return [d for kind in KINDS for d in sorted((self.root / kind).iterdir()) if d.is_dir()]

    def flush_job(self, job_dir: Path, *, final: bool) -> None:
        job = f"{job_dir.parent.name}/{job_dir.name}"
        if (job_dir / "spec.json").exists():
            self.copy(f"{job}/spec.json", recorded_spec((job_dir / "spec.json").read_bytes()))
        status = (job_dir / "status.json").read_bytes() if (job_dir / "status.json").exists() else None  # before the output
        caught_up = all([self.record_output(job_dir, stream, final=final) for stream in STREAMS])
        if status is not None and caught_up:  # a recorded "done" comes with all of the job's output
            self.copy(f"{job}/status.json", status)

    def record_output(self, job_dir: Path, stream: str, *, final: bool) -> bool:
        """New bytes of job_dir/stream as closed chunks: one per flush (backpressure), all of them
        if final. Returns whether the record has all of it now."""
        job, src = f"{job_dir.parent.name}/{job_dir.name}", job_dir / stream
        if not src.exists():
            return True
        while True:
            offset = self.offsets.get((job, stream), 0)
            with src.open("rb") as f:
                f.seek(offset)
                data = f.read(CHUNK_BYTES)
            at_end = final and len(data) < CHUNK_BYTES
            cut = len(data) if at_end else utf8_cut(data)
            if cut == 0:
                return not data
            n = self.chunks.get(job, 0) + 1
            if n > MAX_CHUNKS:
                raise RuntimeError(f"{job}: more than {MAX_CHUNKS} chunks of output")
            put(self.dest / job / f"{stream}.{n:0{CHUNK_DIGITS}d}.{offset + cut}", data[:cut])
            self.chunks[job] = n
            self.offsets[(job, stream)] = offset + cut
            if not final:
                return src.stat().st_size == offset + cut

    def pending(self) -> int:
        """Bytes of output not recorded yet."""
        sizes = {(f"{d.parent.name}/{d.name}", s): (d / s).stat().st_size for d in self.job_dirs() for s in STREAMS if (d / s).exists()}
        return sum(size - self.offsets.get(key, 0) for key, size in sizes.items())

    def copy(self, rel: str, data: bytes) -> None:
        if self.copied.get(rel) != data:
            put(self.dest / rel, data)
            self.copied[rel] = data

    def commit(self) -> None:
        if self.sync:
            subprocess.run(["sync", str(self.dest)], check=True, capture_output=True)


def utf8_cut(data: bytes) -> int:
    """The longest prefix of data that does not end inside a UTF-8 character. Output that is not
    UTF-8 is cut anywhere (len(data)): holding back is only for a character split by a flush."""
    for back in range(1, min(4, len(data)) + 1):
        byte = data[-back]
        if byte & 0xC0 != 0x80:  # not a continuation byte: ASCII or the lead of a character
            need = 1 if byte < 0x80 else 2 if byte >> 5 == 0b110 else 3 if byte >> 4 == 0b1110 else 4 if byte >> 3 == 0b11110 else 1
            return len(data) if back >= need else len(data) - back
    return len(data)


def put(path: Path, data: bytes) -> None:
    """Whole: readers never see half a file (tmp + rename)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


def write_json(path: Path, data: dict | list) -> None:
    """Atomically: readers never see half a file."""
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data))
    tmp.replace(path)


# ---- tail: a log follower's reader, run on the machine by Job.logs(follow=True) as its own command ----
# Kept apart from the supervisor's loop (its only tie is the files under ROOT), and reached as a mode of
# this file, which the boot places at ROOT/supervisor.py: no second file to ship onto every machine.
TAIL_TICK_S = 0.05  # how often it looks for new output: the follower's latency floor (a local stat, no API call)
TAIL_BEAT_S = 1.0  # a frame at least this often: the follower tells a quiet job from a hung connection by it
TAIL_FRAME_BYTES = 256 * 1024  # one frame's payload at most; more goes in the next one
TAIL_MAX_S = 3600.0  # the longest one tail runs; the follower reconnects past it (so does one that vanished: this ends it)


def tail(job_dir: Path, offsets: list[int], max_s: float, out: BinaryIO) -> str:
    """Send job_dir's stdout and stderr past offsets as frames on out, as they are written, until the
    job is done or the session ended (or max_s, or out closes). Returns the end it sent. Frames:

        stdout <n>\\n<n bytes>   stderr <n>\\n<n bytes>   beat\\n   end done|ended|max\\n

    A "done" status is read before the output it ends with (as Job.read does), so end done comes
    after all of it. It touches ROOT/watch each beat, as a polling follower did, so the machine
    lingers for this reader after the session ends; it never counts as work or a connection, so it
    keeps no session from going idle, and it exits once the session ends."""
    root = job_dir.parent.parent
    give_up = time.monotonic() + max_s
    last_beat = 0.0
    while True:
        status = job_dir / "status.json"
        done = status.exists() and json.loads(status.read_bytes()).get("state") == "done"
        ended = (root / "ended.json").exists()
        sent = False
        for i, name in enumerate(STREAMS):
            with contextlib.suppress(FileNotFoundError), (job_dir / name).open("rb") as f:
                f.seek(offsets[i])
                data = f.read(TAIL_FRAME_BYTES)
                if data:
                    out.write(f"{name} {len(data)}\n".encode() + data)
                    offsets[i] += len(data)
                    sent = True
        end = None if sent else "done" if done else "ended" if ended else "max" if time.monotonic() > give_up else None
        if end is not None:
            out.write(f"end {end}\n".encode())
            out.flush()
            return end
        if time.monotonic() - last_beat >= TAIL_BEAT_S:
            out.write(b"beat\n")
            with contextlib.suppress(OSError):
                (root / "watch").touch()
            last_beat = time.monotonic()
        out.flush()  # a reader gone (BrokenPipeError) ends this
        if not sent:
            time.sleep(TAIL_TICK_S)


def tail_main(argv: list[str]) -> None:
    p = argparse.ArgumentParser(prog="supervisor.py tail")
    p.add_argument("job_dir", type=Path)
    p.add_argument("out_offset", type=int)
    p.add_argument("err_offset", type=int)
    p.add_argument("--max-s", type=float, default=TAIL_MAX_S)
    a = p.parse_args(argv)
    assert 0 < a.max_s <= TAIL_MAX_S, a.max_s
    tail(a.job_dir, [a.out_offset, a.err_offset], a.max_s, sys.stdout.buffer)


if __name__ == "__main__":
    if sys.argv[1:2] == ["tail"]:
        tail_main(sys.argv[2:])
    else:
        main()  # also `supervisor.py lease ...` (see lease_main)
