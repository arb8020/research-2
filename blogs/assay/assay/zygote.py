"""The warm process (a fork server): torch + transformers imported once; every check forks from it.

    run_checks ch01 ...  (stdlib-only client)
      ensure()         connect to /tmp/assay-<uid>/zygote-<fp>.sock, or start the server (detached) and wait for it
      request(trusted) pass a pipe's write end (SCM_RIGHTS); the server forks a TRUSTED worker (stays root) that runs
                       the check and writes JSON lines to the pipe; the client copies them to stdout until EOF
    trusted worker (fork, root)
      sandbox.Child -> request(untrusted): the server forks again, from its pristine state; the fork drops to the
                       child user (setgroups/setgid/setuid) BEFORE importing the candidate, then serves the frame
                       protocol on the passed pipes

Rules: the server never imports candidate code, never initialises CUDA (it does not survive fork; children init it
lazily), never runs a torch op (an OpenMP pool created before fork deadlocks the children), never starts threads.
A fresh fork per request: no state leaks between candidates. The socket lives in a dir only our uid can open (0700,
checked), so an unprivileged child can never ask for a root fork. The socket name carries a fingerprint of this file,
the interpreter and the warmed packages' versions (this module imports nothing else of assay, so every other assay
module is imported fresh in each fork): changed code or an upgraded torch starts a new server; an idle
server exits after IDLE_EXIT_S.
"""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import importlib
import json
import os
import signal
import socket
import subprocess
import sys
import time
import traceback
from importlib import metadata
from pathlib import Path
from typing import Any

WARM = ("torch", "transformers", "transformers.models.gpt2.modeling_gpt2", "jaxtyping", "coverage", "tokenizers",
        "safetensors.torch", "huggingface_hub")
IDLE_EXIT_S = 30 * 60
START_TIMEOUT_S = 120.0
MAX_REQUEST = 1 << 20


def runtime_dir() -> Path:
    """/tmp/assay-<uid>, 0700 and ours, or refuse (someone else made it: a socket there is not trustworthy)."""
    path = Path("/tmp") / f"assay-{os.getuid()}"
    path.mkdir(mode=0o700, exist_ok=True)
    st = path.lstat()
    if st.st_uid != os.getuid() or st.st_mode & 0o077 or not path.is_dir() or path.is_symlink():
        raise RuntimeError(f"{path} is not a private dir owned by uid {os.getuid()}; refusing to use it")
    return path


def fingerprint() -> str:
    versions = {}
    for dist in ("torch", "transformers", "coverage", "jaxtyping"):
        try:
            versions[dist] = metadata.version(dist)
        except metadata.PackageNotFoundError:
            versions[dist] = "absent"
    parts = {"code": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), "python": sys.executable, **versions}
    return hashlib.sha256(json.dumps(parts, sort_keys=True).encode()).hexdigest()[:16]


def socket_path() -> Path:
    return runtime_dir() / f"zygote-{fingerprint()}.sock"


# ---- client ----------------------------------------------------------------------------------------------------


def request(path: Path, header: dict[str, Any], fds: list[int]) -> dict[str, Any]:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
        conn.connect(str(path))
        socket.send_fds(conn, [json.dumps(header).encode()], fds)
        conn.shutdown(socket.SHUT_WR)
        reply = b""
        while chunk := conn.recv(65536):
            reply += chunk
    if not reply:
        raise RuntimeError("the warm process closed the connection without a reply")
    out = json.loads(reply)
    if "error" in out:
        raise RuntimeError(f"the warm process refused: {out['error']}")
    return out


def alive(path: Path) -> bool:
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
            conn.connect(str(path))
            socket.send_fds(conn, [b'{"kind": "ping"}'], [])
            conn.shutdown(socket.SHUT_WR)
            return conn.recv(64) != b""
    except OSError:
        return False


def ensure(log: Any = None) -> Path:
    """The warm process's socket, starting the server if nothing answers there (one starter at a time)."""
    path = socket_path()
    if alive(path):
        return path
    with (path.parent / "start.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if alive(path):
            return path
        if log is not None:
            log("starting the warm check process (imports torch + transformers once; later checks fork from it)")
        server_log = (path.parent / f"{path.stem}.log").open("ab")
        env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1])}
        if sys.platform == "darwin":  # macOS: fork after the ObjC runtime loaded aborts without this
            env["OBJC_DISABLE_INITIALIZE_FORK_SAFETY"] = "YES"
        subprocess.Popen([sys.executable, "-c", f"from assay.zygote import serve; serve({str(path)!r})"],
                         stdin=subprocess.DEVNULL, stdout=server_log, stderr=server_log, start_new_session=True,
                         env=env, cwd="/")
        deadline = time.monotonic() + START_TIMEOUT_S
        while not alive(path):
            if time.monotonic() > deadline:
                raise RuntimeError(f"the warm process did not come up in {START_TIMEOUT_S:g}s; see {server_log.name}")
            time.sleep(0.05)
    return path


# ---- server ----------------------------------------------------------------------------------------------------


def serve(path_str: str) -> None:
    path = Path(path_str)
    for name in WARM:
        importlib.import_module(name)
    signal.signal(signal.SIGCHLD, signal.SIG_IGN)  # forks are reaped by the kernel; clients watch their pipes
    with contextlib.suppress(FileNotFoundError):
        path.unlink()
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(str(path))
    path.chmod(0o600)
    listener.listen(64)
    listener.settimeout(IDLE_EXIT_S)
    print(f"[zygote {os.getpid()}] warm ({', '.join(WARM)}); serving {path}", flush=True)
    while True:
        try:
            conn, _ = listener.accept()
        except TimeoutError:
            print(f"[zygote {os.getpid()}] idle {IDLE_EXIT_S}s: exiting", flush=True)
            path.unlink(missing_ok=True)
            return
        with conn:
            _handle(listener, conn)


def _handle(listener: socket.socket, conn: socket.socket) -> None:
    fds: list[int] = []
    try:
        conn.settimeout(10)
        if hasattr(socket, "SO_PEERCRED"):  # Linux: only our own uid may ask (the dir is 0700 too)
            creds = conn.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
            peer_uid = int.from_bytes(creds[4:8], sys.byteorder)
            if peer_uid != os.getuid():
                raise PermissionError(f"peer uid {peer_uid}")
        msg, fds, _, _ = socket.recv_fds(conn, MAX_REQUEST, 8)
        while len(msg) < MAX_REQUEST and (more := conn.recv(65536)):  # the rest of the request, up to EOF
            msg += more
        header = json.loads(msg)
        if header["kind"] == "ping":
            conn.sendall(b'{"ok": true}')
            return
        assert header["kind"] in ("trusted", "untrusted"), header["kind"]
        pid = os.fork()
        if pid == 0:
            _in_fork(header, fds, keep=set(fds), close=(listener, conn))
        conn.sendall(json.dumps({"pid": pid}).encode())
    except Exception as exc:  # noqa: BLE001 -- a bad request never takes the server down
        with contextlib.suppress(OSError):
            conn.sendall(json.dumps({"error": f"{type(exc).__name__}: {exc}"}).encode())
    finally:
        for fd in fds:
            with contextlib.suppress(OSError):
                os.close(fd)


def _in_fork(header: dict[str, Any], fds: list[int], keep: set[int], close: tuple[socket.socket, ...]) -> None:
    """Never returns: the fork runs its target and _exits. fds: untrusted [to_child_r, from_child_w, log];
    trusted [out_w, err]."""
    code = 1
    try:
        for sock in close:
            sock.close()
        os.setsid()
        signal.signal(signal.SIGCHLD, signal.SIG_DFL)
        devnull = os.open(os.devnull, os.O_RDONLY)
        os.dup2(devnull, 0)
        if header["kind"] == "untrusted":
            os.dup2(fds[2], 1)
            os.dup2(fds[2], 2)
        else:
            os.dup2(fds[1], 2)
        _close_all_but(keep | {0, 1, 2})
        os.chdir(header["cwd"])
        os.environ.clear()
        os.environ.update(header["env"])
        if sys.platform == "darwin":  # macOS: the system proxy lookup (urllib -> _scproxy) segfaults after fork
            os.environ.setdefault("no_proxy", "*")
        import tempfile

        tempfile.tempdir = None  # recomputed from the new TMPDIR
        sys.path.insert(0, header["pythonpath"])
        if header["kind"] == "untrusted":
            code = _untrusted(header, fds)
        else:
            from assay.cli import worker

            code = worker(header["argv"], out_fd=fds[0], client_pid=header["client_pid"])
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else 1
    except BaseException:  # noqa: BLE001
        traceback.print_exc()
    finally:
        with contextlib.suppress(Exception):
            sys.stdout.flush()
            sys.stderr.flush()
        os._exit(code)


def _untrusted(header: dict[str, Any], fds: list[int]) -> int:
    """Drop privileges first; only then import anything the candidate can influence."""
    if header.get("uid") is not None:
        os.setgroups([])
        os.setgid(header["gid"])
        os.setuid(header["uid"])
        assert os.getuid() != 0 and os.geteuid() != 0, "privilege drop failed"
    os.umask(0o077)
    hub = sys.modules.get("huggingface_hub.constants")
    if hub is not None and header["env"].get("HF_HUB_OFFLINE") == "1":
        hub.HF_HUB_OFFLINE = True  # constants were read when the server imported the hub
    module = importlib.import_module(header["module"])
    module.main(fds[0], fds[1])
    return 0


def _close_all_but(keep: set[int]) -> None:
    top = min(os.sysconf("SC_OPEN_MAX"), 65536)
    start = 0
    for fd in sorted(keep | {top}):
        if fd > start:
            os.closerange(start, fd)
        start = fd + 1
