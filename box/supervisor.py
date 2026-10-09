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
    p.add_argument("--session-id", default="", help="written into ROOT/up: whose supervisor is up (a snapshot can hold another's)")
    p.add_argument("--idle-timeout-s", type=float, default=0.0, help="end after this long with no job and no connection; 0 = never")
    p.add_argument("--ports", type=lambda s: [int(p) for p in s.split(",") if p], default=[], help="exposed ports, comma-separated")
    p.add_argument("--record", default="", help="record the session into this directory (a mounted store), relative to --root")
    p.add_argument("--record-sync", action="store_true", help="run `sync <record dir>` after each flush (Modal Volumes)")
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
    put(root / "session.json", json.dumps({"started_at": time.time(), "created_at": a.created_at, "ceiling": a.ceiling}).encode())
    put(root / "lease.json", json.dumps({"until": a.lease_until, "ceiling": a.ceiling, "released": False}).encode())
    put(root / "lease-audit.json", json.dumps([audit_entry("create", a.lease_until, a.created_at, a.host, a.pid)]).encode())
    recorder = Recorder(root, root / a.record, sync=a.record_sync) if a.record else None
    try:
        if recorder:
            recorder.start()
        (root / "activity").touch()
        (root / "up").write_text(a.session_id)
        reason = supervise(root, a.idle_timeout_s, a.ports)
    finally:
        if recorder:
            recorder.close()
    ended = {"reason": reason, "at": time.time()}
    try:
        if recorder:
            recorder.finish(ended)
    finally:
        put(root / "ended.json", json.dumps(ended).encode())
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
    print(json.dumps(change_lease(Path(a.root), a.op, a.until, a.host, a.pid)))


def change_lease(root: Path, op: str, until: float, host: str, pid: int) -> dict:
    with (root / "lease.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        lease = read_lease(root)
        now = time.time()
        changed = next_lease(lease, op, until, now)
        if changed != lease:
            put(root / "lease.json", json.dumps(changed).encode())
            audit = json.loads((root / "lease-audit.json").read_text())
            put(root / "lease-audit.json", json.dumps(next_audit(audit, audit_entry(op, changed["until"], now, host, pid))).encode())
    return changed


def next_lease(lease: dict, op: str, until: float, now: float) -> dict:
    assert op in ("extend", "release"), op
    assert lease["until"] <= lease["ceiling"], lease
    if lease["released"] or lease["until"] <= now:
        return lease
    if op == "release":
        return {**lease, "until": now, "released": True}
    extended = {**lease, "until": max(lease["until"], min(until, lease["ceiling"]))}
    assert extended["until"] >= lease["until"], (lease, extended)
    assert extended["until"] <= lease["ceiling"], (lease, extended)
    return extended


def audit_entry(op: str, until: float, at: float, host: str, pid: int) -> dict:
    assert op in LEASE_OPS, op
    return {"op": op, "until": until, "at": at, "host": host, "pid": pid, "n": 1}


def next_audit(audit: list[dict], entry: dict) -> list[dict]:
    last = audit[-1] if audit else None
    if last is not None and (last["op"], last["host"], last["pid"]) == (entry["op"], entry["host"], entry["pid"]):
        return [*audit[:-1], {**entry, "n": last["n"] + 1}]
    if len(audit) >= MAX_LEASE_AUDIT:
        raise RuntimeError(f"lease audit full ({MAX_LEASE_AUDIT} entries): refusing {entry['op']}")
    return [*audit, entry]


def read_lease(root: Path) -> dict:
    raw = json.loads((root / "lease.json").read_text())
    lease = {"until": float(raw["until"]), "ceiling": float(raw["ceiling"]), "released": bool(raw["released"])}
    if lease["until"] > lease["ceiling"]:
        raise ValueError(f"{root}/lease.json: until {lease['until']} past ceiling {lease['ceiling']}")
    return lease


def lease_end(lease: dict) -> tuple[float, str]:
    return min(lease["until"], lease["ceiling"]), "released" if lease["released"] else "lease"


def linger(root: Path) -> None:
    def reading() -> bool:
        watch = root / "watch"
        return watch.exists() and time.time() - watch.stat().st_mtime < WATCH_TTL_S

    until = time.monotonic() + LINGER_S
    while time.monotonic() < until and reading():
        time.sleep(TICK_S)


def supervise(root: Path, idle_timeout_s: float, ports: list[int]) -> str:
    done: set[str] = set()
    services: dict[Path, subprocess.Popen] = {}
    while (end := session_end(root, idle_timeout_s)) is None:
        tend_services(root, services)
        if idle_timeout_s and connected(ports):
            (root / "activity").touch()
        job_dir = next_job(root, done)
        if job_dir is None:
            time.sleep(TICK_S)
            continue
        done.add(job_dir.name)
        run_job(root, job_dir, lambda: tend_services(root, services))
        (root / "activity").touch()
    stop_services(services, end)
    return end


def tend_services(root: Path, services: dict[Path, subprocess.Popen]) -> None:
    for job_dir in sorted((root / "services").iterdir()):
        if job_dir in services or (job_dir / "status.json").exists() or not (job_dir / "spec.json").exists():
            continue
        if len(services) >= MAX_SERVICES:
            put(job_dir / "status.json", json.dumps({"state": "done", "reason": "refused", "exit_code": None, "ended": time.time()}).encode())
            continue
        spec = json.loads((job_dir / "spec.json").read_text())
        env = {**spec.get("env", {}), "BOX_JOB_ID": job_dir.name, "BOX_JOB_DIR": str(job_dir)}
        services[job_dir] = child = spawn(spec["cmd"], env, job_dir, stdout=job_dir / "stdout", stderr=job_dir / "stderr")
        put(job_dir / "status.json", json.dumps({"state": "running", "started": time.time(), "pgid": child.pid}).encode())
    for job_dir, child in services.items():
        if child.poll() is None and (job_dir / "kill").exists():
            kill_group(child)
            end_service(job_dir, "killed", child.returncode)
        elif child.poll() is not None and service_state(job_dir) == "running":
            end_service(job_dir, "exited", child.returncode)


def stop_services(services: dict[Path, subprocess.Popen], reason: str) -> None:
    for job_dir, child in services.items():
        if child.poll() is None:
            kill_group(child)
            end_service(job_dir, reason, child.returncode)
        elif service_state(job_dir) == "running":
            end_service(job_dir, "exited", child.returncode)


def end_service(job_dir: Path, reason: str, code: int | None) -> None:
    status = json.loads((job_dir / "status.json").read_text())
    put(job_dir / "status.json", json.dumps({**status, "state": "done", "reason": reason, "exit_code": code, "ended": time.time()}).encode())


def service_state(job_dir: Path) -> str:
    return json.loads((job_dir / "status.json").read_text())["state"]


def session_end(root: Path, idle_timeout_s: float) -> str | None:
    if (root / "stop").exists():
        return "stopped"
    end_at, reason = lease_end(read_lease(root))
    if time.time() >= end_at:
        return reason
    if idle_timeout_s and time.time() - (root / "activity").stat().st_mtime >= idle_timeout_s:
        return "idle"
    return None


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
    pending = [d for d in (root / "jobs").iterdir() if d.name not in done and (d / "spec.json").exists()]
    return min(pending, key=lambda d: (d / "spec.json").stat().st_mtime, default=None)


def job_end(root: Path, job_dir: Path, killed_at: float, budget: float) -> str | None:
    if (root / "stop").exists():
        return "stopped"
    end_at, reason = lease_end(read_lease(root))
    if time.time() >= end_at - budget:
        return reason
    if time.monotonic() >= killed_at:
        return "timeout"
    if (job_dir / "kill").exists():
        return "killed"
    return None


def run_job(root: Path, job_dir: Path, tick: Callable[[], None]) -> None:
    spec = json.loads((job_dir / "spec.json").read_text())
    spec["env"] = {**spec.get("env", {}), "BOX_JOB_ID": job_dir.name, "BOX_JOB_DIR": str(job_dir)}
    budget = float(spec.get("hook_budget_s", 300)) if spec.get("on_exit") else 0.0
    max_duration_s = float(spec["max_duration_s"])
    assert 0 < max_duration_s <= MAX_CEILING_S, max_duration_s
    child = spawn(spec["cmd"], spec["env"], job_dir, stdout=job_dir / "stdout", stderr=job_dir / "stderr")
    killed_at = time.monotonic() + max_duration_s
    status = {"state": "running", "started": time.time(), "pgid": child.pid}
    put(job_dir / "status.json", json.dumps(status).encode())

    reason = None
    while (code := child.poll()) is None:
        if (reason := job_end(root, job_dir, killed_at, budget)) is not None:
            kill_group(child)
            code = child.returncode
            break
        tick()
        time.sleep(TICK_S)
    reason = reason or "exited"

    status.update(state="hook" if spec.get("on_exit") else "done", reason=reason, exit_code=code, ended=time.time())
    if not spec.get("on_exit"):
        put(job_dir / "status.json", json.dumps(status).encode())
        return
    env = {**spec["env"], "BOX_EXIT_CODE": str(code), "BOX_REASON": reason}
    timeout = max(0.0, min(budget, read_lease(root)["ceiling"] - time.time()))
    hook = spawn(spec["on_exit"], env, job_dir, stdout=job_dir / "hook.stdout", stderr=job_dir / "hook.stderr")
    status["hook_pgid"] = hook.pid
    put(job_dir / "status.json", json.dumps(status).encode())
    status["hook_exit_code"] = wait_hook(hook, timeout)
    status["state"] = "done"
    put(job_dir / "status.json", json.dumps(status).encode())


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

    def finish(self, ended: dict) -> None:
        self.close()
        try:
            self.flush(final=True)
            put(self.dest / "ended.json", json.dumps(ended).encode())
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
        for name in ("session.json", "lease.json", "lease-audit.json"):
            self.copy(name, (self.root / name).read_bytes())
        for job_dir in self.job_dirs():
            self.flush_job(job_dir, final=final)
        put(self.dest / "heartbeat.json", json.dumps({"at": time.time(), "ttl_s": HEARTBEAT_TTL_S}).encode())
        self.commit()

    def job_dirs(self) -> list[Path]:
        return [d for kind in KINDS for d in sorted((self.root / kind).iterdir()) if d.is_dir()]

    def flush_job(self, job_dir: Path, *, final: bool) -> None:
        job = f"{job_dir.parent.name}/{job_dir.name}"
        for code in sorted((job_dir / "code").glob("*")):
            self.copy(f"{job}/code/{code.name}", code.read_bytes())
        if (job_dir / "spec.json").exists():
            self.copy(f"{job}/spec.json", recorded_spec((job_dir / "spec.json").read_bytes()))
        status = (job_dir / "status.json").read_bytes() if (job_dir / "status.json").exists() else None
        caught_up = all([self.record_output(job_dir, stream, final=final) for stream in STREAMS])
        if status is not None and caught_up:
            self.copy(f"{job}/status.json", status)

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
            put(self.dest / job / f"{stream}.{n:0{CHUNK_DIGITS}d}.{offset + cut}", data[:cut])
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
