"""The supervisor: the first process on every box. Stdlib only; providers copy this file onto the
box and run it as the entrypoint. It holds the session, runs jobs one at a time, and ends the box.

Everything goes through files under ROOT (no sockets), so a client only needs the provider's exec:

    ROOT/session.json           supervisor writes it first: {started_at, deadline_at} (unix times, this clock)
    ROOT/lease                  client touches it to hold the session (mtime = last heartbeat)
    ROOT/released               client wrote it: stop checking the lease; end when no job is left
    ROOT/stop                   client wrote it: kill any job, run its hook, end
    ROOT/jobs/<id>/spec.json    client writes it (atomically) to start a job: {cmd, on_exit, hook_budget_s, env, service}
    ROOT/jobs/<id>/stdout       \\ the job's output
    ROOT/jobs/<id>/stderr       /
    ROOT/jobs/<id>/status.json  supervisor writes it: {state, reason, exit_code, hook_exit_code, started, ended}
    ROOT/watch                  a log follower or job waiter touches it each poll (the machine lingers for it)
    ROOT/ended.json             supervisor writes it last: {reason}; then it lingers up to LINGER_S
                                while someone is still reading (see linger)

A session ends on: stop, deadline, lease lost, idle timeout, or (released) no job or service left.
Idle means no job running and no established TCP connection to an exposed port (--ports): the
supervisor owns idleness, since a provider's own idle timer (Modal's) sees only connections, never
work in the box. Whatever ends it, a running job is killed (whole process group) and its on_exit
hook still runs, inside the time left before the deadline. The job is killed hook_budget_s before
the deadline for that.

A service (spec "service": true) is a long-lived server, e.g. a Jupyter Server behind an exposed
port. It starts at once, beside the job queue (never waits for a job, never holds one up), and it
is not work for idleness: its connections are what count. It keeps a released session alive (it
is something left), has no hook, and is killed (whole group) when the session ends; its
status.json says why, as a job's does.

With --record DIR (a store mounted on the machine, box/store.py), a Recorder copies the session
there every FLUSH_S (sooner past FLUSH_BYTES of new output), so it outlives the machine:

    DIR/session.json            as ROOT/session.json, at start
    DIR/heartbeat.json          every flush: {at, ttl_s}; older than ttl_s, the recorder has stopped
    DIR/jobs/<id>/spec.json     \\ as under ROOT, copied when they change
    DIR/jobs/<id>/status.json   /
    DIR/jobs/<id>/<stream>.<n>  closed chunks of new output, n = 1, 2, ... per job across both streams
    DIR/ended.json              as ROOT/ended.json, written (and synced) before ROOT/ended.json

Every file is whole (tmp + rename) and never changes once a reader could have seen it, except the
JSON ones, which are replaced whole. --record-sync runs `sync DIR` after each flush (a Modal
Volume commits on it). A chunk never splits a UTF-8 character unless the output is not UTF-8.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path

TICK_S = 0.2
KILL_GRACE_S = 10.0  # SIGTERM -> SIGKILL
LINGER_S = 30.0  # after the session ends, the most a reader still there gets to finish reading
WATCH_TTL_S = 5.0  # a log follower touches ROOT/watch each poll; older than this, nobody is following
PROC_TCP = ("/proc/net/tcp", "/proc/net/tcp6")
TCP_ESTABLISHED = "01"  # /proc/net/tcp's st column (include/net/tcp_states.h)
STREAMS = ("stdout", "stderr")
FLUSH_S = 2.0  # the record lags the machine by at most this (plus a sync)
FLUSH_BYTES = 256 * 1024  # new output past this flushes sooner
CHUNK_BYTES = 4 * 1024 * 1024  # one chunk per stream per flush, at most this: more waits (backpressure, never dropped)
HEARTBEAT_TTL_S = 5 * FLUSH_S  # a reader takes a heartbeat older than this as "the recorder stopped"
CHUNK_DIGITS = 6  # flushes come at most every TICK_S, so a 24 h session (Modal's cap) has < 2 * 432000 chunks
MAX_CHUNKS = 10**CHUNK_DIGITS - 1
MAX_SERVICES = 8  # a session's long-lived servers; more is a client bug, not a workload


# TODO(handoff): if the supervisor itself dies, nothing writes ended.json or runs BOX_ON_SHUTDOWN;
# the job dies with it on Linux (PDEATHSIG), and only the provider's backstop ends the machine
# (Modal: sandbox timeout; RunPod: BOOT's backstop timer, and a container restart deletes the pod).
# With --record, the record still has everything up to the last flush, and its stale heartbeat plus
# the machine's absence read as machine_lost (sdk.Record.status).
def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--root", required=True)
    p.add_argument("--deadline-s", type=float, required=True, help="the session's lifetime, from now")
    p.add_argument("--lease-ttl-s", type=float, default=60.0, help="lost if not touched for this long")
    p.add_argument("--idle-timeout-s", type=float, default=0.0, help="end after this long with no job and no connection; 0 = never")
    p.add_argument("--ports", type=lambda s: [int(p) for p in s.split(",") if p], default=[], help="exposed ports, comma-separated")
    p.add_argument("--record", default="", help="record the session into this directory (a mounted store), relative to --root")
    p.add_argument("--record-sync", action="store_true", help="run `sync <record dir>` after each flush (Modal Volumes)")
    p.add_argument(
        "--on-shutdown", default=os.environ.get("BOX_ON_SHUTDOWN", ""),
        help="bash run last, to end the machine itself (a provider sets BOX_ON_SHUTDOWN, e.g. its API's delete)",
    )  # fmt: skip
    a = p.parse_args()
    root = Path(a.root)
    (root / "jobs").mkdir(parents=True, exist_ok=True)
    started_at = time.time()
    write_json(root / "session.json", {"started_at": started_at, "deadline_at": started_at + a.deadline_s})
    recorder = Recorder(root, root / a.record, sync=a.record_sync) if a.record else None
    if recorder:
        recorder.start()  # the record has session.json before anyone is told the supervisor is up
    (root / "lease").touch()  # last: a client takes the lease as "the supervisor is up"
    reason = supervise(root, time.monotonic() + a.deadline_s, a.lease_ttl_s, a.idle_timeout_s, a.ports)
    ended = {"reason": reason, "at": time.time()}
    if recorder:
        recorder.finish(ended)  # first: a closer terminates the machine once it reads ROOT/ended.json
    write_json(root / "ended.json", ended)
    linger(root, reason, a.lease_ttl_s)
    if a.on_shutdown:
        subprocess.run(["bash", "-c", a.on_shutdown], check=False)


def linger(root: Path, reason: str, lease_ttl_s: float) -> None:
    """Keep the machine up to LINGER_S after the session ended, while someone is still reading:
    the holder (lease fresh) after an end it did not ask for (deadline, idle), or a follower of the
    logs or a waiter on a job (ROOT/watch touched within WATCH_TTL_S) after any end. A closer
    does not wait this out: it terminates the machine once ended.json exists."""

    def reading() -> bool:
        holder = reason in ("deadline", "idle") and not lease_lost(root, lease_ttl_s)
        watch = root / "watch"
        return holder or (watch.exists() and time.time() - watch.stat().st_mtime < WATCH_TTL_S)

    until = time.monotonic() + LINGER_S
    while time.monotonic() < until and reading():
        time.sleep(TICK_S)


def supervise(root: Path, deadline: float, lease_ttl_s: float, idle_timeout_s: float, ports: list[int]) -> str:
    """Run jobs one at a time (services beside them) until the session ends; returns why it ended."""
    done: set[str] = set()
    services: dict[Path, subprocess.Popen] = {}  # every service started, running or not
    plain: set[Path] = set()  # job dirs known not to be services (a spec never changes once written)
    end = None
    idle_since = time.monotonic()
    while end is None:
        tend_services(root, services, plain)
        now = time.monotonic()
        if idle_timeout_s and ports and connected(ports):
            idle_since = now  # someone is using an exposed port: not idle
        if (end := session_end(root, now, deadline, lease_ttl_s, idle_timeout_s, idle_since)) is not None:
            break
        job_dir = next_job(root, done)
        if job_dir is None:
            if (root / "released").exists() and all(child.poll() is not None for child in services.values()):
                end = "released"
                break
            time.sleep(TICK_S)
            continue
        done.add(job_dir.name)
        end = run_job(root, job_dir, deadline, lease_ttl_s, lambda: tend_services(root, services, plain))
        idle_since = time.monotonic()
    stop_services(services, end)
    return end


def tend_services(root: Path, services: dict[Path, subprocess.Popen], plain: set[Path]) -> None:
    """Start every service spec not started yet; kill those asked to (ROOT/jobs/<id>/kill); record
    the end of each that exited by itself."""
    for job_dir in sorted((root / "jobs").iterdir()):
        if job_dir in services or job_dir in plain or not (job_dir / "spec.json").exists():
            continue
        if not is_service(job_dir):
            plain.add(job_dir)
            continue
        assert len(services) < MAX_SERVICES, f"more than {MAX_SERVICES} services in one session"
        spec = json.loads((job_dir / "spec.json").read_text())
        env = {**spec.get("env", {}), "BOX_JOB_ID": job_dir.name, "BOX_JOB_DIR": str(job_dir)}
        services[job_dir] = child = spawn(spec["cmd"], env, job_dir, stdout=job_dir / "stdout", stderr=job_dir / "stderr")
        write_json(job_dir / "status.json", {"state": "running", "service": True, "started": time.time(), "pgid": child.pid})
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


def is_service(job_dir: Path) -> bool:
    return json.loads((job_dir / "spec.json").read_text()).get("service") is True


def session_end(root: Path, now: float, deadline: float, lease_ttl_s: float, idle_timeout_s: float, idle_since: float) -> str | None:
    if (root / "stop").exists():
        return "stopped"
    if now >= deadline:
        return "deadline"
    if lease_lost(root, lease_ttl_s):
        return "lease_lost"
    if idle_timeout_s and now - idle_since >= idle_timeout_s:
        return "idle"
    return None


def lease_lost(root: Path, lease_ttl_s: float) -> bool:
    if (root / "released").exists():
        return False
    return time.time() - (root / "lease").stat().st_mtime > lease_ttl_s


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
    """The oldest job (not a service) with a spec that has not run yet."""
    pending = [d for d in (root / "jobs").iterdir() if d.name not in done and (d / "spec.json").exists() and not is_service(d)]
    return min(pending, key=lambda d: (d / "spec.json").stat().st_mtime, default=None)


def run_job(root: Path, job_dir: Path, deadline: float, lease_ttl_s: float, tick: Callable[[], None]) -> str | None:
    """Run one job and its hook, calling tick (services) while it runs. Returns the session's end
    reason if the session ended meanwhile, else None (the job finished on its own; the session goes on)."""
    spec = json.loads((job_dir / "spec.json").read_text())
    spec["env"] = {**spec.get("env", {}), "BOX_JOB_ID": job_dir.name, "BOX_JOB_DIR": str(job_dir)}
    budget = float(spec.get("hook_budget_s", 300)) if spec.get("on_exit") else 0.0  # time kept for the hook
    child = spawn(spec["cmd"], spec["env"], job_dir, stdout=job_dir / "stdout", stderr=job_dir / "stderr")
    status = {"state": "running", "started": time.time(), "pgid": child.pid}
    write_json(job_dir / "status.json", status)

    session_ended = None
    while (code := child.poll()) is None:
        now = time.monotonic()
        if (root / "stop").exists():
            session_ended = "stopped"
        elif now >= deadline - budget:
            session_ended = "deadline"
        elif lease_lost(root, lease_ttl_s):
            session_ended = "lease_lost"
        elif (job_dir / "kill").exists():
            kill_group(child)
            code, reason = child.returncode, "killed"
            break
        if session_ended:
            kill_group(child)
            code = child.returncode
            break
        tick()
        time.sleep(TICK_S)
    else:
        reason = "exited"
    if session_ended:
        reason = session_ended

    status.update(state="hook" if spec.get("on_exit") else "done", reason=reason, exit_code=code, ended=time.time())
    write_json(job_dir / "status.json", status)
    if spec.get("on_exit"):
        env = {**spec["env"], "BOX_EXIT_CODE": str(code), "BOX_REASON": reason}
        timeout = max(0.0, min(budget, deadline - time.monotonic()))
        status["hook_exit_code"] = run_hook(spec["on_exit"], env, job_dir, timeout)
        status["state"] = "done"
        write_json(job_dir / "status.json", status)
    return session_ended


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


class Recorder:
    """Copies the session under root into dest (a store mounted on the machine) every FLUSH_S, on
    its own thread, so the session outlives the machine (layout: module docstring). main owns it:
    start() before the lease, finish() before ROOT/ended.json. A recording that fails (the store
    unreachable, disk full) is reported on stderr and stops; the session goes on (fail-open: the
    job is the point), and readers see the heartbeat go stale."""

    def __init__(self, root: Path, dest: Path, *, sync: bool) -> None:
        self.root = root
        self.dest = dest
        self.sync = sync
        self.offsets: dict[tuple[str, str], int] = {}  # (job, stream) -> bytes of it recorded
        self.chunks: dict[str, int] = {}  # job -> chunks written (numbered from 1)
        self.copied: dict[str, bytes] = {}  # rel path -> what was last copied there
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.run, daemon=True, name="box-recorder")

    def start(self) -> None:
        self.dest.mkdir(parents=True, exist_ok=True)
        self.flush(final=False)  # session.json + a first heartbeat, synced
        self.thread.start()

    def finish(self, ended: dict) -> None:
        self.stop.set()
        self.thread.join()
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
        self.copy("session.json", (self.root / "session.json").read_bytes())
        for job_dir in sorted(d for d in (self.root / "jobs").iterdir() if d.is_dir()):
            self.flush_job(job_dir, final=final)
        put(self.dest / "heartbeat.json", json.dumps({"at": time.time(), "ttl_s": HEARTBEAT_TTL_S}).encode())
        self.commit()

    def flush_job(self, job_dir: Path, *, final: bool) -> None:
        job = job_dir.name
        if (job_dir / "spec.json").exists():
            self.copy(f"jobs/{job}/spec.json", (job_dir / "spec.json").read_bytes())
        status = (job_dir / "status.json").read_bytes() if (job_dir / "status.json").exists() else None  # before the output
        caught_up = all([self.record_output(job_dir, stream, final=final) for stream in STREAMS])
        if status is not None and caught_up:  # a recorded "done" comes with all of the job's output
            self.copy(f"jobs/{job}/status.json", status)

    def record_output(self, job_dir: Path, stream: str, *, final: bool) -> bool:
        """New bytes of job_dir/stream as closed chunks: one per flush (backpressure), all of them
        if final. Returns whether the record has all of it now."""
        job, src = job_dir.name, job_dir / stream
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
            put(self.dest / "jobs" / job / f"{stream}.{n:0{CHUNK_DIGITS}d}", data[:cut])
            self.chunks[job] = n
            self.offsets[(job, stream)] = offset + cut
            if not final:
                return src.stat().st_size == offset + cut

    def pending(self) -> int:
        """Bytes of output not recorded yet."""
        sizes = {(d.name, s): (d / s).stat().st_size for d in (self.root / "jobs").iterdir() for s in STREAMS if (d / s).exists()}
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


def write_json(path: Path, data: dict) -> None:
    """Atomically: readers never see half a file."""
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data))
    tmp.replace(path)


if __name__ == "__main__":
    main()
