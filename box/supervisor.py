from __future__ import annotations

import argparse
import contextlib
import ctypes
import dataclasses
import fcntl
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Literal, TypeVar, get_args

TICK_S = 0.2
KILL_GRACE_S = 10.0
LINGER_S = 30.0
WATCH_TTL_S = 5.0
PROC_TCP = ("/proc/net/tcp", "/proc/net/tcp6")
TCP_ESTABLISHED = "01"
STREAMS = ("stdout", "stderr")
FLUSH_S = 2.0
FLUSH_BYTES = 256 * 1024
CHUNK_BYTES = 4 * 1024 * 1024
HEARTBEAT_TTL_S = 5 * FLUSH_S
MAX_CEILING_S = 48 * 3600
CHUNK_DIGITS = 7
MAX_CHUNKS = 10**CHUNK_DIGITS - 1
assert 2 * MAX_CEILING_S / TICK_S < MAX_CHUNKS, "a chunk number that fits CHUNK_DIGITS for a whole session"
MAX_SERVICES = 8
KINDS = ("jobs", "services")
LEASE_OPS = ("create", "extend", "release")
MAX_LEASE_AUDIT = 1024
PR_SET_PDEATHSIG = 1
SESSION, LEASE, AUDIT, ENDED, HEARTBEAT, UP = "session.json", "lease.json", "lease-audit.json", "ended.json", "heartbeat.json", "up"
ACTIVITY, WATCH, STOP = "activity", "watch", "stop"
SPEC, STATUS, KILL = "spec.json", "status.json", "kill"
CHUNK = re.compile(r"(stdout|stderr)\.(\d+)\.(\d+)")
EndReason = Literal["lease", "released", "stopped", "idle", "machine_lost"]
JobEndReason = Literal["exited", "killed", "timeout", "lease", "released", "stopped", "idle", "refused"]
T = TypeVar("T")


@dataclass(frozen=True)
class Started:
    started_at: float
    created_at: float
    ceiling: float


@dataclass(frozen=True)
class Lease:
    until: float
    ceiling: float
    released: bool = False

    def __post_init__(self) -> None:
        if self.until > self.ceiling:
            raise ValueError(f"lease until {self.until} is past its ceiling {self.ceiling}")


@dataclass(frozen=True)
class LeaseChange:
    op: str
    until: float
    at: float
    host: str
    pid: int
    n: int = 1

    def __post_init__(self) -> None:
        if self.op not in LEASE_OPS:
            raise ValueError(f"lease audit: unknown op {self.op!r}")


@dataclass(frozen=True)
class Heartbeat:
    at: float
    ttl_s: float

    def fresh(self, now: float) -> bool:
        return now - self.at < self.ttl_s


@dataclass(frozen=True)
class Ended:
    reason: EndReason

    def __post_init__(self) -> None:
        if self.reason not in get_args(EndReason):
            raise ValueError(f"unknown end reason {self.reason!r}")


@dataclass(frozen=True)
class Ending:
    reason: JobEndReason
    exit_code: int | None
    hook_exit_code: int | None = None

    def __post_init__(self) -> None:
        if self.reason not in get_args(JobEndReason):
            raise ValueError(f"unknown job end reason {self.reason!r}")


@dataclass(frozen=True)
class Queued:
    pass


@dataclass(frozen=True)
class JobRunning:
    started_at: float


@dataclass(frozen=True)
class Hooking:
    ending: Ending


@dataclass(frozen=True)
class Done:
    ending: Ending
    started_at: float | None
    ended_at: float


JobStatus = Queued | JobRunning | Hooking | Done


def dump(x: object, **extra: object) -> bytes:
    return json.dumps({**dataclasses.asdict(x), **extra}).encode()


def load(cls: type[T], raw: bytes) -> T:  # noqa: UP047
    return fields_of(cls, json.loads(raw))


def fields_of(cls: type[T], d: dict) -> T:  # noqa: UP047
    return cls(**{f.name: d[f.name] for f in dataclasses.fields(cls)})


def load_ended(raw: bytes) -> Ended:
    ended = load(Ended, raw)
    if ended.reason == "machine_lost":
        raise ValueError("ended.json: machine_lost is never a supervisor's word")
    return ended


def dump_audit(audit: list[LeaseChange]) -> bytes:
    return json.dumps([dataclasses.asdict(c) for c in audit]).encode()


def load_audit(raw: bytes) -> list[LeaseChange]:
    return [fields_of(LeaseChange, d) for d in json.loads(raw)]


def dump_job(status: JobRunning | Hooking | Done, pgids: list[int]) -> bytes:
    match status:
        case JobRunning(started_at=started):
            d = {"state": "running", "started": started}
        case Hooking(ending=ending):
            d = {"state": "hook", **dataclasses.asdict(ending)}
        case Done(ending=ending, started_at=started, ended_at=ended):
            d = {"state": "done", **dataclasses.asdict(ending), "started": started, "ended": ended}
    return json.dumps({**d, "pgids": pgids}).encode()


def load_job(raw: bytes) -> JobRunning | Hooking | Done:
    d = json.loads(raw)
    match d["state"]:
        case "running":
            return JobRunning(float(d["started"]))
        case "hook":
            return Hooking(fields_of(Ending, d))
        case "done":
            return Done(fields_of(Ending, d), None if d["started"] is None else float(d["started"]), float(d["ended"]))
    raise ValueError(f"status.json: unknown job state {d['state']!r}")


def job_pgids(raw: bytes) -> list[int]:
    return [int(pgid) for pgid in json.loads(raw)["pgids"]]


def chunk_name(stream: str, n: int, end: int) -> str:
    assert stream in STREAMS, stream
    assert 0 < n <= MAX_CHUNKS, n
    return f"{stream}.{n:0{CHUNK_DIGITS}d}.{end}"


def parse_chunk(name: str) -> tuple[int, str, int] | None:
    m = CHUNK.fullmatch(name)
    return None if m is None else (int(m[2]), m[1], int(m[3]))


def main(argv: list[str]) -> None:
    match argv[:1]:
        case ["lease"]:
            lease_main(argv[1:])
        case ["tail"]:
            tail_main(argv[1:])
        case _:
            supervise_main(argv)


def supervise_main(argv: list[str]) -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--root", required=True)
    p.add_argument("--created-at", type=float, required=True, help="unix time the client created the session")
    p.add_argument("--lease-until", type=float, required=True, help="unix time the session's first lease ends")
    p.add_argument("--ceiling", type=float, required=True, help="unix time no lease can pass")
    p.add_argument("--host", required=True, help="the creating client's host, for the lease audit")
    p.add_argument("--pid", type=int, required=True, help="the creating client's pid, for the lease audit")
    p.add_argument("--session-id", required=True, help="written into ROOT/up: whose supervisor is up (a snapshot can hold another's)")
    p.add_argument("--idle-timeout-s", type=float, default=0.0, help="end after this long with no job and no connection; 0 = never")
    p.add_argument("--ports", type=lambda s: [int(p) for p in s.split(",") if p], default=[], help="exposed ports, comma-separated")
    p.add_argument("--record", default="", help="record the session into this directory (a mounted store), relative to --root")
    p.add_argument(
        "--on-shutdown", default=os.environ.get("BOX_ON_SHUTDOWN", ""),
        help="bash run last, to end the machine itself (a provider sets BOX_ON_SHUTDOWN, e.g. its API's delete)",
    )  # fmt: skip
    a = p.parse_args(argv)
    assert a.created_at < a.lease_until, (a.created_at, a.lease_until)
    assert a.lease_until <= a.ceiling, (a.lease_until, a.ceiling)
    assert a.ceiling <= a.created_at + MAX_CEILING_S, (a.created_at, a.ceiling)
    root = Path(a.root)
    for kind in KINDS:
        (root / kind).mkdir(parents=True, exist_ok=True)
    put(root / SESSION, dump(Started(time.time(), a.created_at, a.ceiling)))
    put(root / LEASE, dump(Lease(a.lease_until, a.ceiling)))
    put(root / AUDIT, dump_audit([LeaseChange("create", a.lease_until, a.created_at, a.host, a.pid)]))
    recorder = Recorder(root, root / a.record, sync=os.environ.get("BOX_RECORD_SYNC") == "1") if a.record else None
    try:
        if recorder:
            recorder.start()
        (root / ACTIVITY).touch()
        (root / UP).write_text(a.session_id)
        reason = supervise(root, a.idle_timeout_s, a.ports)
    finally:
        if recorder:
            recorder.close()
    ended = dump(Ended(reason), at=time.time())
    try:
        if recorder:
            recorder.finish(ended)
    finally:
        put(root / ENDED, ended)
        linger(root)
        if a.on_shutdown:
            subprocess.run(["bash", "-c", a.on_shutdown], check=False)


def lease_main(argv: list[str]) -> None:
    p = argparse.ArgumentParser(prog="supervisor.py lease")
    p.add_argument("--root", required=True)
    p.add_argument("--op", choices=("extend", "release"), required=True)
    p.add_argument("--until", type=float, required=True, help="extend: unix time asked for; release: ignored")
    p.add_argument("--host", required=True)
    p.add_argument("--pid", type=int, required=True)
    a = p.parse_args(argv)
    sys.stdout.buffer.write(dump(change_lease(Path(a.root), a.op, a.until, a.host, a.pid)))


def change_lease(root: Path, op: str, until: float, host: str, pid: int) -> Lease:
    with (root / "lease.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        lease = read_lease(root)
        now = time.time()
        changed = next_lease(lease, op, until, now)
        if changed != lease:
            put(root / LEASE, dump(changed))
            audit = load_audit((root / AUDIT).read_bytes())
            put(root / AUDIT, dump_audit(next_audit(audit, LeaseChange(op, changed.until, now, host, pid))))
    return changed


def next_lease(lease: Lease, op: str, until: float, now: float) -> Lease:
    assert op in ("extend", "release"), op
    if lease.released or lease.until <= now:
        return lease
    if op == "release":
        return dataclasses.replace(lease, until=now, released=True)
    extended = dataclasses.replace(lease, until=max(lease.until, min(until, lease.ceiling)))
    assert extended.until >= lease.until, (lease, extended)
    return extended


def next_audit(audit: list[LeaseChange], entry: LeaseChange) -> list[LeaseChange]:
    last = audit[-1] if audit else None
    if last is not None and (last.op, last.host, last.pid) == (entry.op, entry.host, entry.pid):
        return [*audit[:-1], dataclasses.replace(entry, n=last.n + 1)]
    if len(audit) >= MAX_LEASE_AUDIT:
        raise RuntimeError(f"lease audit full ({MAX_LEASE_AUDIT} entries): refusing {entry.op}")
    return [*audit, entry]


def read_lease(root: Path) -> Lease:
    return load(Lease, (root / LEASE).read_bytes())


def lease_end(lease: Lease) -> tuple[float, str]:
    return lease.until, "released" if lease.released else "lease"


def linger(root: Path) -> None:
    def reading() -> bool:
        watch = root / WATCH
        return watch.exists() and time.time() - watch.stat().st_mtime < WATCH_TTL_S

    until = time.monotonic() + LINGER_S
    while time.monotonic() < until and reading():
        time.sleep(TICK_S)


def supervise(root: Path, idle_timeout_s: float, ports: list[int]) -> str:
    done: set[str] = set()
    services: dict[Path, tuple[subprocess.Popen, float]] = {}
    while (end := session_end(root, idle_timeout_s)) is None:
        tend_services(root, services)
        if idle_timeout_s and connected(ports):
            (root / ACTIVITY).touch()
        job_dir = next_job(root, done)
        if job_dir is None:
            time.sleep(TICK_S)
            continue
        done.add(job_dir.name)
        run_job(root, job_dir, lambda: tend_services(root, services))
        (root / ACTIVITY).touch()
    stop_services(services, end)
    return end


def tend_services(root: Path, services: dict[Path, tuple[subprocess.Popen, float]]) -> None:
    for job_dir in sorted((root / "services").iterdir()):
        if job_dir in services or (job_dir / STATUS).exists() or not (job_dir / SPEC).exists():
            continue
        if len(services) >= MAX_SERVICES:
            put(job_dir / STATUS, dump_job(Done(Ending("refused", None), None, time.time()), []))
            continue
        services[job_dir] = start(job_dir, read_spec(job_dir))
    for job_dir, (child, _) in services.items():
        if child.poll() is None and (job_dir / KILL).exists():
            kill_group(child)
            end_service(job_dir, services[job_dir], "killed")
        elif child.poll() is not None and running(job_dir):
            end_service(job_dir, services[job_dir], "exited")


def stop_services(services: dict[Path, tuple[subprocess.Popen, float]], reason: str) -> None:
    for job_dir, (child, started) in services.items():
        if child.poll() is None:
            kill_group(child)
            end_service(job_dir, (child, started), reason)
        elif running(job_dir):
            end_service(job_dir, (child, started), "exited")


def end_service(job_dir: Path, service: tuple[subprocess.Popen, float], reason: str) -> None:
    child, started = service
    put(job_dir / STATUS, dump_job(Done(Ending(reason, child.returncode), started, time.time()), [child.pid]))


def running(job_dir: Path) -> bool:
    return isinstance(load_job((job_dir / STATUS).read_bytes()), JobRunning)


def lease_over(root: Path, budget: float = 0.0) -> str | None:
    if (root / STOP).exists():
        return "stopped"
    end_at, reason = lease_end(read_lease(root))
    return reason if time.time() >= end_at - budget else None


def session_end(root: Path, idle_timeout_s: float) -> str | None:
    idle = idle_timeout_s and time.time() - (root / ACTIVITY).stat().st_mtime >= idle_timeout_s
    return lease_over(root) or ("idle" if idle else None)


def job_end(root: Path, job_dir: Path, killed_at: float, budget: float) -> str | None:
    return lease_over(root, budget) or ("timeout" if time.monotonic() >= killed_at else "killed" if (job_dir / KILL).exists() else None)


def connected(ports: list[int]) -> bool:
    return bool(ports) and any(port in ports for port in established_local_ports())


def established_local_ports() -> list[int]:
    # /proc/net/tcp's local address is HEXIP:HEXPORT; macOS netstat prints IP.PORT
    if sys.platform == "linux":
        tables = [Path(f).read_text().splitlines()[1:] for f in PROC_TCP if Path(f).exists()]
        rows = [line.split() for table in tables for line in table]
        return [int(r[1].rsplit(":", 1)[1], 16) for r in rows if r[3] == TCP_ESTABLISHED]
    out = subprocess.run(["netstat", "-an", "-p", "tcp"], capture_output=True, text=True, check=True).stdout
    local = [line.split()[3] for line in out.splitlines() if line.endswith("ESTABLISHED")]
    return [int(address.rsplit(".", 1)[1]) for address in local]


def next_job(root: Path, done: set[str]) -> Path | None:
    pending = [d for d in (root / "jobs").iterdir() if d.name not in done and (d / SPEC).exists()]
    return min(pending, key=lambda d: (d / SPEC).stat().st_mtime, default=None)


def read_spec(job_dir: Path) -> dict:
    spec = json.loads((job_dir / SPEC).read_text())
    return {**spec, "env": {**spec.get("env", {}), "BOX_JOB_ID": job_dir.name, "BOX_JOB_DIR": str(job_dir)}}


def start(job_dir: Path, spec: dict) -> tuple[subprocess.Popen, float]:
    child = spawn(spec["cmd"], spec["env"], job_dir, stdout=job_dir / "stdout", stderr=job_dir / "stderr")
    started = time.time()
    put(job_dir / STATUS, dump_job(JobRunning(started), [child.pid]))
    return child, started


def run_job(root: Path, job_dir: Path, tick: Callable[[], None]) -> None:
    spec = read_spec(job_dir)
    budget = float(spec.get("hook_budget_s", 300)) if spec.get("on_exit") else 0.0
    max_duration_s = float(spec["max_duration_s"])
    assert 0 < max_duration_s <= MAX_CEILING_S, max_duration_s
    child, started = start(job_dir, spec)
    killed_at = time.monotonic() + max_duration_s
    reason = None
    while (code := child.poll()) is None:
        if (reason := job_end(root, job_dir, killed_at, budget)) is not None:
            kill_group(child)
            code = child.returncode
            break
        tick()
        time.sleep(TICK_S)
    ending, ended = Ending(reason or "exited", code), time.time()
    if not spec.get("on_exit"):
        put(job_dir / STATUS, dump_job(Done(ending, started, ended), [child.pid]))
        return
    env = {**spec["env"], "BOX_EXIT_CODE": str(code), "BOX_REASON": ending.reason}
    timeout = max(0.0, min(budget, read_lease(root).ceiling - time.time()))
    hook = spawn(spec["on_exit"], env, job_dir, stdout=job_dir / "hook.stdout", stderr=job_dir / "hook.stderr")
    put(job_dir / STATUS, dump_job(Hooking(ending), [child.pid, hook.pid]))
    hooked = dataclasses.replace(ending, hook_exit_code=wait_hook(hook, timeout))
    put(job_dir / STATUS, dump_job(Done(hooked, started, ended), [child.pid, hook.pid]))


def spawn(cmd: str, env: dict[str, str], job_dir: Path, *, stdout: Path, stderr: Path) -> subprocess.Popen:
    with stdout.open("ab") as out, stderr.open("ab") as err:
        return subprocess.Popen(
            ["bash", "-c", cmd], env={**os.environ, **env}, cwd=os.environ.get("BOX_WORKDIR", str(job_dir)),
            stdin=subprocess.DEVNULL, stdout=out, stderr=err, start_new_session=True, preexec_fn=die_with_parent,
        )  # fmt: skip


def die_with_parent() -> None:
    if sys.platform == "linux":
        ctypes.CDLL("libc.so.6", use_errno=True).prctl(PR_SET_PDEATHSIG, signal.SIGKILL)


def kill_group(child: subprocess.Popen) -> None:
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


def wait_hook(hook: subprocess.Popen, timeout: float) -> int | None:
    try:
        return hook.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(hook.pid, signal.SIGKILL)
        hook.wait()
        return None


def recorded_spec(raw: bytes) -> bytes:
    spec = json.loads(raw)
    return json.dumps({**spec, "env": sorted(spec.get("env", {}))}).encode()


STORE_FAILURES = (OSError, subprocess.CalledProcessError)


class Recorder:
    def __init__(self, root: Path, dest: Path, *, sync: bool) -> None:
        self.root = root
        self.dest = dest
        self.sync = sync
        self.offsets: dict[tuple[str, str], int] = {}
        self.chunks: dict[str, int] = {}
        self.copied: dict[str, bytes] = {}
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.run, daemon=False, name="box-recorder")

    def start(self) -> None:
        self.dest.mkdir(parents=True, exist_ok=True)
        self.flush(final=False)
        self.thread.start()

    def close(self) -> None:
        self.stop.set()
        if self.thread.is_alive():
            self.thread.join()
        assert not self.thread.is_alive()

    def finish(self, ended: bytes) -> None:
        self.close()
        try:
            self.flush(final=True)
            put(self.dest / ENDED, ended)
            self.commit()
        except STORE_FAILURES as e:
            print(f"box supervisor: recording into {self.dest} failed at the end: {e!r}", file=sys.stderr, flush=True)

    def run(self) -> None:
        last = time.monotonic()
        while not self.stop.wait(TICK_S):
            if time.monotonic() - last < FLUSH_S and self.pending() < FLUSH_BYTES:
                continue
            try:
                self.flush(final=False)
            except STORE_FAILURES as e:
                print(f"box supervisor: recording into {self.dest} stopped: {e!r}", file=sys.stderr, flush=True)
                return
            last = time.monotonic()

    def flush(self, *, final: bool) -> None:
        for name in (SESSION, LEASE, AUDIT):
            self.copy(name, (self.root / name).read_bytes())
        for job_dir in self.job_dirs():
            self.flush_job(job_dir, final=final)
        put(self.dest / HEARTBEAT, dump(Heartbeat(time.time(), HEARTBEAT_TTL_S)))
        self.commit()

    def job_dirs(self) -> list[Path]:
        return [d for kind in KINDS for d in sorted((self.root / kind).iterdir()) if d.is_dir()]

    def flush_job(self, job_dir: Path, *, final: bool) -> None:
        job = f"{job_dir.parent.name}/{job_dir.name}"
        for code in sorted((job_dir / "code").glob("*")):
            self.copy(f"{job}/code/{code.name}", code.read_bytes())
        if (job_dir / SPEC).exists():
            self.copy(f"{job}/{SPEC}", recorded_spec((job_dir / SPEC).read_bytes()))
        status = (job_dir / STATUS).read_bytes() if (job_dir / STATUS).exists() else None
        caught_up = all([self.record_output(job_dir, stream, final=final) for stream in STREAMS])
        if status is not None and caught_up:
            self.copy(f"{job}/{STATUS}", status)

    def record_output(self, job_dir: Path, stream: str, *, final: bool) -> bool:
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
            put(self.dest / job / chunk_name(stream, n, offset + cut), data[:cut])
            self.chunks[job] = n
            self.offsets[(job, stream)] = offset + cut
            if not final:
                return src.stat().st_size == offset + cut

    def pending(self) -> int:
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
    for back in range(1, min(4, len(data)) + 1):
        byte = data[-back]
        if byte & 0xC0 != 0x80:
            need = 1 if byte < 0x80 else 2 if byte >> 5 == 0b110 else 3 if byte >> 4 == 0b1110 else 4 if byte >> 3 == 0b11110 else 1
            return len(data) if back >= need else len(data) - back
    return len(data)


def put(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


TAIL_TICK_S = 0.05
TAIL_BEAT_S = 1.0
TAIL_FRAME_BYTES = 256 * 1024
TAIL_MAX_S = 3600.0


def tail(job_dir: Path, offsets: list[int], max_s: float, out: BinaryIO) -> str:
    root = job_dir.parent.parent
    give_up = time.monotonic() + max_s
    last_beat = 0.0
    while True:
        status = job_dir / STATUS
        done = status.exists() and isinstance(load_job(status.read_bytes()), Done)
        ended = (root / ENDED).exists()
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
                (root / WATCH).touch()
            last_beat = time.monotonic()
        out.flush()
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
    main(sys.argv[1:])
