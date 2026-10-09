"""Isolation: the trusted parent runs untrusted code (the reader's file, a compiled check) in a child process.

    parent (trusted: holds expected answers, writes the store)       child (untrusted once the reader's code runs)
    Isolation: root -> the child runs as an unprivileged user        HOME/TMPDIR = a fresh private scratch dir
               (default `nobody`); else same uid, recorded            env: a short allowlist (no store location)
    run_cmd(argv): one command, output streamed, timeout, killpg      a build, a test binary, a script
    Child(...): a python child + a framed duplex channel              frames: JSON header + raw byte blobs
      send(header, blobs, timeout) / recv(timeout)                    NEVER pickle child -> parent: unpickling
                                                                      runs code; frames are parsed strictly

What the child reports about itself is only as honest as the child: the parent decides from bytes it parsed, and an
unprivileged child cannot reach the store (root-only) or the trusted code (root-owned, read-only). With same-uid
isolation (not root, e.g. a laptop) the child could read or write the store: runs say so (`isolation: same-uid`).
"""

from __future__ import annotations

import contextlib
import getpass
import json
import os
import pwd
import select
import shutil
import signal
import struct
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MAX_HEADER_BYTES = 1 << 20
MAX_BLOB_BYTES = 1 << 30  # gpt2 logits at 1024 tokens are ~206 MB fp32
PREFIX = struct.Struct(">4sIQ")  # magic, header bytes, blob bytes
MAGIC = b"ASY1"
EXIT_GRACE_S = 5.0
PASS_ENV = ("PATH", "LANG", "LC_ALL", "HF_HOME", "HF_HUB_CACHE", "CUDA_VISIBLE_DEVICES", "OMP_NUM_THREADS",
            "MKL_NUM_THREADS", "CC", "CXX")


@dataclass(frozen=True)
class Isolation:
    mode: str  # "unprivileged" | "same-uid"
    user: str
    uid: int
    gid: int

    def popen_kwargs(self) -> dict[str, Any]:
        if self.mode == "same-uid":
            return {}
        return {"user": self.uid, "group": self.gid, "extra_groups": [], "umask": 0o077}

    def scratch(self, prefix: str) -> Path:
        """A fresh dir only the child (and root) can use: its HOME, TMPDIR and output dir."""
        path = Path(tempfile.mkdtemp(prefix=prefix))
        if self.mode == "unprivileged":
            os.chown(path, self.uid, self.gid)
        return path

    def to_json(self) -> dict[str, Any]:
        return {"mode": self.mode, "user": self.user, "uid": self.uid}


def isolation() -> Isolation:
    if os.geteuid() == 0:
        name = os.environ.get("ASSAY_CHILD_USER", "nobody")
        entry = pwd.getpwnam(name)
        assert entry.pw_uid != 0, f"ASSAY_CHILD_USER={name} is root"
        return Isolation("unprivileged", name, entry.pw_uid, entry.pw_gid)
    return Isolation("same-uid", getpass.getuser(), os.getuid(), os.getgid())


def child_env(scratch: Path, extra: Mapping[str, str] | None = None) -> dict[str, str]:
    """The child's whole environment: an allowlist, never the parent's (which names the store, tokens, ...)."""
    env = {k: os.environ[k] for k in PASS_ENV if k in os.environ}
    env.setdefault("PATH", "/usr/local/bin:/usr/bin:/bin")
    return {**env, "HOME": str(scratch), "TMPDIR": str(scratch), "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONUNBUFFERED": "1", **(extra or {})}


# ---- one command (builds, compiled checks, scripts) -------------------------------------------------------------


@dataclass(frozen=True)
class CmdResult:
    argv: list[str]
    rc: int | None  # None: timed out (killed)
    output: str
    seconds: float
    truncated: bool


def run_cmd(argv: list[str], *, cwd: Path, iso: Isolation, env: Mapping[str, str], timeout: float,
            on_line: Callable[[str], None], max_lines: int = 2000) -> CmdResult:
    """Run one command in its own process group, stdout+stderr merged and streamed line by line to `on_line`.
    Past `timeout` or `max_lines` the whole group is killed."""
    started = time.perf_counter()
    proc = subprocess.Popen(argv, cwd=cwd, env=dict(env), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, errors="replace", bufsize=1,
                            start_new_session=True, **iso.popen_kwargs())
    lines: list[str] = []
    truncated = [False]

    def pump() -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            if len(lines) == max_lines:
                truncated[0] = True
                _killpg(proc)
                return
            lines.append(line.rstrip("\n"))
            on_line(lines[-1])

    reader = threading.Thread(target=pump, daemon=True)
    reader.start()
    try:
        rc: int | None = proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        _killpg(proc)
        proc.wait()
        rc = None
    reader.join(EXIT_GRACE_S)
    return CmdResult(argv, rc, "\n".join(lines), time.perf_counter() - started, truncated[0])


def _killpg(proc: subprocess.Popen[Any]) -> None:
    kill_group(proc.pid)


# ---- frames --------------------------------------------------------------------------------------------------


class ProtocolError(Exception):
    """Bytes from the child that do not parse as a frame: the child is broken or lying."""


class ChildTimeout(Exception):
    pass


class ChildDied(Exception):
    pass


Blobs = dict[str, bytes]


def encode(header: Mapping[str, Any], blobs: Mapping[str, bytes]) -> bytes:
    specs = [{"name": name, "nbytes": len(data)} for name, data in blobs.items()]
    head = json.dumps({**header, "blobs": specs}).encode()
    return PREFIX.pack(MAGIC, len(head), sum(len(d) for d in blobs.values())) + head + b"".join(blobs.values())


def parse(head: bytes, blob: bytes | bytearray) -> tuple[dict[str, Any], Blobs]:
    """The trust boundary: a header (JSON object with a string 'kind') and named blobs whose sizes add up exactly."""
    try:
        header = json.loads(head)
    except ValueError as exc:
        raise ProtocolError(f"header is not JSON: {exc}") from exc
    if not isinstance(header, dict) or not isinstance(header.get("kind"), str):
        raise ProtocolError("header is not an object with a string 'kind'")
    specs = header.pop("blobs", None)
    if not isinstance(specs, list):
        raise ProtocolError("'blobs' is not a list")
    blobs: Blobs = {}
    offset = 0
    view = memoryview(blob)
    for spec in specs:
        if not (isinstance(spec, dict) and isinstance(spec.get("name"), str)
                and isinstance(spec.get("nbytes"), int) and spec["nbytes"] >= 0):
            raise ProtocolError(f"bad blob spec {spec!r}")
        if spec["name"] in blobs:
            raise ProtocolError(f"blob {spec['name']!r} sent twice")
        if offset + spec["nbytes"] > len(blob):
            raise ProtocolError(f"blob {spec['name']!r} runs past the end ({len(blob)} bytes)")
        blobs[spec["name"]] = view[offset:offset + spec["nbytes"]].tobytes()
        offset += spec["nbytes"]
    if offset != len(blob):
        raise ProtocolError(f"{len(blob) - offset} trailing bytes after the last blob")
    return header, blobs


def _read_exact(fd: int, n: int, deadline: float | None) -> bytearray:
    buf = bytearray(n)
    view = memoryview(buf)
    got = 0
    while got < n:
        if deadline is not None:
            left = deadline - time.monotonic()
            if left <= 0 or not select.select([fd], [], [], left)[0]:
                raise ChildTimeout
        count = os.readv(fd, [view[got:]])
        if count == 0:
            raise ChildDied("the child closed its end (exited?)")
        got += count
    return buf


def read_frame(fd: int, deadline: float | None) -> tuple[dict[str, Any], Blobs]:
    magic, head_n, blob_n = PREFIX.unpack(bytes(_read_exact(fd, PREFIX.size, deadline)))
    if magic != MAGIC:
        raise ProtocolError(f"bad frame magic {magic!r}")
    if head_n > MAX_HEADER_BYTES or blob_n > MAX_BLOB_BYTES:
        raise ProtocolError(f"frame too large: header {head_n} B, blobs {blob_n} B")
    head = bytes(_read_exact(fd, head_n, deadline))
    return parse(head, _read_exact(fd, blob_n, deadline))


def write_frame(fd: int, header: Mapping[str, Any], blobs: Mapping[str, bytes], deadline: float | None) -> None:
    data = memoryview(encode(header, blobs))
    while data:
        if deadline is not None:
            left = deadline - time.monotonic()
            if left <= 0 or not select.select([], [fd], [], left)[1]:
                raise ChildTimeout
        try:
            sent = os.write(fd, data)
        except BlockingIOError:
            continue
        except (BrokenPipeError, ConnectionResetError) as exc:
            raise ChildDied(f"the child closed its end: {exc}") from exc
        data = data[sent:]


# ---- a python child with a frame channel ----------------------------------------------------------------------

BOOT = "import sys; from {module} import main; main(int(sys.argv[1]), int(sys.argv[2]))"
LIVE: set[int] = set()  # pids of children this process started: a watchdog kills them if our client goes away


class Child:
    """A python child running `<module>.main(in_fd, out_fd)` as the isolated user, cwd = the tree under check. Forked
    from the warm process when `zygote` names its socket (torch already imported), else spawned fresh. Either way
    it leads its own process group, which `close()` kills: a hung child never outlives the check."""

    def __init__(self, module: str, *, cwd: Path, iso: Isolation, pythonpath: Path,
                 extra_env: Mapping[str, str] | None = None, zygote: Path | None = None) -> None:
        self.scratch = iso.scratch("assay-child-")
        self.log_path = self.scratch / "child.log"
        self.hung = False
        to_child_r, self.to_child = os.pipe()
        self.from_child, from_child_w = os.pipe()
        os.set_blocking(self.to_child, False)
        env = child_env(self.scratch, {"PYTHONPATH": str(pythonpath), **(extra_env or {})})
        log_fd = os.open(self.log_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            if zygote is not None:
                from assay import zygote as server

                drop = iso.mode == "unprivileged"
                self.proc = None
                self.pid = server.request(zygote, {
                    "kind": "untrusted", "module": module, "cwd": str(cwd), "env": env,
                    "pythonpath": str(pythonpath), "uid": iso.uid if drop else None, "gid": iso.gid if drop else None,
                }, [to_child_r, from_child_w, log_fd])["pid"]
            else:
                self.proc = subprocess.Popen(
                    [sys.executable, "-c", BOOT.format(module=module), str(to_child_r), str(from_child_w)],
                    cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=log_fd, stderr=subprocess.STDOUT,
                    pass_fds=(to_child_r, from_child_w), start_new_session=True, **iso.popen_kwargs())
                self.pid = self.proc.pid
        finally:
            for fd in (to_child_r, from_child_w, log_fd):
                os.close(fd)
        LIVE.add(self.pid)

    def __enter__(self) -> Child:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def send(self, header: Mapping[str, Any], blobs: Mapping[str, bytes], timeout: float) -> None:
        try:
            write_frame(self.to_child, header, blobs, time.monotonic() + timeout)
        except ChildTimeout:
            self.hung = True
            raise

    def recv(self, timeout: float) -> tuple[dict[str, Any], Blobs]:
        try:
            return read_frame(self.from_child, time.monotonic() + timeout)
        except ChildTimeout:
            self.hung = True
            raise
        except ChildDied:
            code = self._wait(EXIT_GRACE_S)
            raise ChildDied(f"the child exited mid-call (exit code {code})") from None

    def _wait(self, timeout: float) -> int | str | None:
        """Wait for exit; its code when we are its parent, "?" for a fork of the warm process, None if still alive."""
        deadline = time.monotonic() + timeout
        while True:
            if self.proc is not None:
                if self.proc.poll() is not None:
                    return self.proc.returncode
            elif not pid_alive(self.pid):
                return "?"
            if time.monotonic() > deadline:
                return None
            time.sleep(0.01)

    def log_tail(self, limit: int = 4000) -> str:
        try:
            return self.log_path.read_bytes()[-limit:].decode(errors="replace")
        except OSError:
            return ""

    def close(self) -> None:
        for fd in (self.to_child, self.from_child):
            with contextlib.suppress(OSError):
                os.close(fd)
        if self.hung or self._wait(EXIT_GRACE_S) is None:  # closed pipes = EOF: a well-behaved child exits
            kill_group(self.pid)
            self._wait(EXIT_GRACE_S)
        LIVE.discard(self.pid)
        shutil.rmtree(self.scratch, ignore_errors=True)


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def kill_group(pid: int) -> None:
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(pid, signal.SIGKILL)


# ---- child side ------------------------------------------------------------------------------------------------


def child_send(fd: int, header: Mapping[str, Any], blobs: Mapping[str, bytes]) -> None:
    write_frame(fd, header, blobs, None)


def child_recv(fd: int) -> tuple[dict[str, Any], Blobs]:
    return read_frame(fd, None)
