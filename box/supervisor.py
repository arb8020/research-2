"""The supervisor: the first process on every box. Stdlib only; providers copy this file onto the
box and run it as the entrypoint. It holds the session, runs jobs one at a time, and ends the box.

Everything goes through files under ROOT (no sockets), so a client only needs the provider's exec:

    ROOT/lease                  client touches it to hold the session (mtime = last heartbeat)
    ROOT/released               client wrote it: stop checking the lease; end when no job is left
    ROOT/stop                   client wrote it: kill any job, run its hook, end
    ROOT/jobs/<id>/spec.json    client writes it (atomically) to start a job: {cmd, on_exit, hook_budget_s, env}
    ROOT/jobs/<id>/stdout       \\ the job's output
    ROOT/jobs/<id>/stderr       /
    ROOT/jobs/<id>/status.json  supervisor writes it: {state, reason, exit_code, hook_exit_code, started, ended}
    ROOT/watch                  a log follower or job waiter touches it each poll (the machine lingers for it)
    ROOT/ended.json             supervisor writes it last: {reason}; then it lingers up to LINGER_S
                                while someone is still reading (see linger)

A session ends on: stop, deadline, lease lost, idle timeout, or (released) no job left. Whatever
ends it, a running job is killed (whole process group) and its on_exit hook still runs, inside
the time left before the deadline. The job is killed hook_budget_s before the deadline for that.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

TICK_S = 0.2
KILL_GRACE_S = 10.0  # SIGTERM -> SIGKILL
LINGER_S = 30.0  # after the session ends, the most a reader still there gets to finish reading
WATCH_TTL_S = 5.0  # a log follower touches ROOT/watch each poll; older than this, nobody is following


# TODO(handoff): if the supervisor itself dies, nothing writes ended.json or runs BOX_ON_SHUTDOWN;
# the job dies with it on Linux (PDEATHSIG), and only the provider's backstop ends the machine
# (Modal: sandbox timeout; RunPod: BOOT's backstop timer, and a container restart deletes the pod).
def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--root", required=True)
    p.add_argument("--deadline-s", type=float, required=True, help="the session's lifetime, from now")
    p.add_argument("--lease-ttl-s", type=float, default=60.0, help="lost if not touched for this long")
    p.add_argument("--idle-timeout-s", type=float, default=0.0, help="end after this long with no job; 0 = never")
    p.add_argument(
        "--on-shutdown", default=os.environ.get("BOX_ON_SHUTDOWN", ""),
        help="bash run last, to end the machine itself (a provider sets BOX_ON_SHUTDOWN, e.g. its API's delete)",
    )  # fmt: skip
    a = p.parse_args()
    root = Path(a.root)
    (root / "jobs").mkdir(parents=True, exist_ok=True)
    (root / "lease").touch()
    reason = supervise(root, time.monotonic() + a.deadline_s, a.lease_ttl_s, a.idle_timeout_s)
    write_json(root / "ended.json", {"reason": reason, "at": time.time()})
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


def supervise(root: Path, deadline: float, lease_ttl_s: float, idle_timeout_s: float) -> str:
    """Run jobs one at a time until the session ends; returns why it ended."""
    done: set[str] = set()
    idle_since = time.monotonic()
    while True:
        now = time.monotonic()
        if (end := session_end(root, now, deadline, lease_ttl_s, idle_timeout_s, idle_since)) is not None:
            return end
        job_dir = next_job(root, done)
        if job_dir is None:
            if (root / "released").exists():
                return "released"
            time.sleep(TICK_S)
            continue
        done.add(job_dir.name)
        end = run_job(root, job_dir, deadline, lease_ttl_s)
        if end is not None:
            return end
        idle_since = time.monotonic()


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


def next_job(root: Path, done: set[str]) -> Path | None:
    """The oldest job with a spec that has not run yet."""
    pending = [d for d in (root / "jobs").iterdir() if d.name not in done and (d / "spec.json").exists()]
    return min(pending, key=lambda d: (d / "spec.json").stat().st_mtime, default=None)


def run_job(root: Path, job_dir: Path, deadline: float, lease_ttl_s: float) -> str | None:
    """Run one job and its hook. Returns the session's end reason if the session ended meanwhile,
    else None (the job finished on its own, and the session goes on)."""
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


def write_json(path: Path, data: dict) -> None:
    """Atomically: readers never see half a file."""
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data))
    tmp.replace(path)


if __name__ == "__main__":
    main()
