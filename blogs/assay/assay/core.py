from __future__ import annotations

import contextlib
import fcntl
import getpass
import hashlib
import importlib
import inspect
import json
import math
import os
import pwd
import select
import shutil
import signal
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import uuid
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from importlib import metadata
from pathlib import Path
from typing import Any


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def jsonable(obj: Any) -> Any:
    if isinstance(obj, float) and not math.isfinite(obj):
        return str(obj)
    if isinstance(obj, dict):
        return {k: jsonable(v) for k, v in obj.items()}
    if isinstance(obj, list | tuple):
        return [jsonable(v) for v in obj]
    return obj


def key_of(parts: Mapping[str, Any]) -> str:
    return sha256(canonical(parts))


def files_fp(paths: Iterable[Path], root: Path) -> str:
    listing = {p.relative_to(root).as_posix(): sha256(p.read_bytes()) for p in sorted(paths)}
    assert listing, f"no files to fingerprint under {root}"
    return key_of(listing)


@dataclass(frozen=True)
class Entry:
    kind: str
    key: str
    path: Path | None
    meta: dict[str, Any]

    def read(self, name: str) -> bytes:
        want = self.meta["files"][name]
        assert self.path is not None, f"{self.kind}/{self.key} is ephemeral: it has no files"
        data = (self.path / name).read_bytes()
        if sha256(data) != want:
            raise CorruptEntry(f"{self.kind}/{self.key}/{name}: content does not match its recorded sha256")
        return data


class CorruptEntry(Exception):
    pass


class Store:
    def __init__(self, root: Path) -> None:
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        if os.geteuid() == 0:
            root.chmod(0o700)

    @classmethod
    def from_env(cls) -> Store:
        if os.environ.get("ASSAY_STORE"):
            return cls(Path(os.environ["ASSAY_STORE"]))
        if os.environ.get("BLOGS_WS_PERSIST"):
            return cls(Path(os.environ["BLOGS_WS_PERSIST"]) / "cache" / "assay")
        return cls(Path.home() / ".cache" / "blogs-assay")

    def _dir(self, kind: str, key: str) -> Path:
        assert kind.isidentifier(), kind
        assert len(key) >= 8 and all(c in "0123456789abcdef-" for c in key), key
        return self.root / kind / key[:2] / key

    def get(self, kind: str, key: str) -> Entry | None:
        path = self._dir(kind, key)
        try:
            meta = json.loads((path / "meta.json").read_bytes())
        except FileNotFoundError:
            return None
        return Entry(kind, key, path, meta)

    def put(self, kind: str, key: str, meta: Mapping[str, Any], files: Mapping[str, bytes]) -> Entry:
        existing = self.get(kind, key)
        if existing is not None:
            return existing
        assert "meta.json" not in files
        tmp = self.root / "tmp" / uuid.uuid4().hex
        tmp.mkdir(parents=True)
        for name, data in files.items():
            assert "/" not in name and not name.startswith("."), name
            (tmp / name).write_bytes(data)
        full = {**meta, "kind": kind, "key": key, "created": time.time(),
                "files": {name: sha256(data) for name, data in files.items()}}
        (tmp / "meta.json").write_bytes(json.dumps(jsonable(full), indent=1, allow_nan=False).encode())
        final = self._dir(kind, key)
        final.parent.mkdir(parents=True, exist_ok=True)
        if final.exists():
            shutil.rmtree(final)
        try:
            tmp.rename(final)
        except OSError:
            shutil.rmtree(tmp, ignore_errors=True)
        entry = self.get(kind, key)
        assert entry is not None, f"{kind}/{key}: write did not land"
        with (self.root / "index.jsonl").open("a") as index:
            index.write(json.dumps({"kind": kind, "key": key, "created": full["created"],
                                    "summary": meta.get("summary", "")}) + "\n")
        return entry

    def derive(self, kind: str, parts: Mapping[str, Any], build: Any) -> Entry:
        key = key_of(parts)
        found = self.get(kind, key)
        if found is not None:
            return found
        meta, files = build()
        return self.put(kind, key, {**meta, "parts": dict(parts)}, files)


OUTCOMES = ("pass", "fail", "skip")
KNOWN = ("outcome", "score", "metrics", "tags", "notes", "details", "artifacts")


@dataclass(frozen=True)
class Result:
    outcome: str
    score: float | None = None
    metrics: dict[str, Any] = field(default_factory=dict)
    tags: tuple[str, ...] = ()
    notes: str = ""
    details: dict[str, Any] = field(default_factory=dict)
    artifacts: dict[str, bytes] = field(default_factory=dict)

    def __post_init__(self) -> None:
        assert self.outcome in OUTCOMES, self.outcome

    def to_json(self) -> dict[str, Any]:
        return {"outcome": self.outcome, "score": self.score, "metrics": jsonable(self.metrics),
                "tags": list(self.tags), "notes": self.notes, "details": jsonable(self.details),
                "artifacts": sorted(self.artifacts)}


def result(**fields: Any) -> Result:
    known = {k: v for k, v in fields.items() if k in KNOWN}
    extra = {k: v for k, v in fields.items() if k not in KNOWN}
    return Result(**{**known, "details": {**known.get("details", {}), **extra}})


def passed(**fields: Any) -> Result:
    return result(outcome="pass", score=1.0, **fields)


def failed(notes: str, **fields: Any) -> Result:
    return result(outcome="fail", score=0.0, notes=notes, **fields)


@dataclass(frozen=True)
class Check:
    name: str
    fn: Callable[[Entry, Mapping[str, Any]], Result]
    required: bool = True
    creates: tuple[str, ...] = ()


@dataclass(frozen=True)
class Grader:
    name: str
    checks: tuple[Check, ...]
    config: Mapping[str, Any] = field(default_factory=dict)

    def snapshot(self) -> dict[str, Any]:
        sources = sorted({inspect.getsourcefile(c.fn) or "?" for c in self.checks} | {__file__})
        return {"name": self.name, "config": dict(self.config),
                "checks": [{"name": c.name, "required": c.required, "creates": list(c.creates),
                            "fn": f"{c.fn.__module__}.{c.fn.__qualname__}"} for c in self.checks],
                "code": {Path(s).name: sha256(Path(s).read_bytes()) for s in sources}}

    def fingerprint(self) -> str:
        return key_of(self.snapshot())


def grade(store: Store, run: Entry, grader: Grader) -> Entry:
    assert run.kind == "run", run.kind
    snapshot = grader.snapshot()
    parts = {"run": run.key, "grader": key_of(snapshot)}

    def build() -> tuple[dict[str, Any], dict[str, bytes]]:
        rows, artifacts = apply(run, grader)
        outcome = "fail" if any(r["outcome"] == "fail" for r in rows) else "pass"
        return {"run": run.key, "grader": snapshot, "checks": rows, "outcome": outcome,
                "summary": f"{grader.name} {outcome}"}, artifacts

    if run.path is None:
        meta, _ = build()
        return Entry("grade", key_of(parts), None, {**meta, "parts": parts, "files": {}})
    return store.derive("grade", parts, build)


def apply(run: Entry, grader: Grader) -> tuple[list[dict[str, Any]], dict[str, bytes]]:
    rows: list[dict[str, Any]] = []
    artifacts: dict[str, bytes] = {}
    halted_by: str | None = None
    for check in grader.checks:
        if halted_by is not None:
            res = Result("skip", notes=f"skipped: required check {halted_by!r} failed")
        else:
            res = check.fn(run, grader.config)
            missing = [name for name in check.creates if name not in res.artifacts]
            if res.outcome != "skip" and missing:
                res = failed(f"promised {missing} but did not create them", details={"was": res.to_json()})
            if res.outcome == "fail" and check.required:
                halted_by = check.name
        artifacts.update({f"{check.name}.{name}": data for name, data in res.artifacts.items()})
        rows.append({"check": check.name, "required": check.required, **res.to_json()})
    return rows, artifacts


def first_failure(grade_entry: Entry) -> dict[str, Any] | None:
    return next((row for row in grade_entry.meta["checks"] if row["outcome"] == "fail"), None)


def verdict(grade_entry: Entry, *, blocking: bool, **fields: Any) -> dict[str, Any]:
    rows = grade_entry.meta["checks"]
    bad = first_failure(grade_entry)
    metrics: dict[str, Any] = {}
    for row in rows:
        metrics.update(row["metrics"])
    out = {"kind": "verdict", **{k: v for k, v in fields.items() if k != "where"},
           "outcome": grade_entry.meta["outcome"], "score": 0.0 if bad else 1.0, "metrics": metrics,
           "notes": f"{bad['check']}: {bad['notes']}" if bad else "", "blocking": blocking,
           "run": grade_entry.meta["run"], "grade": grade_entry.key}
    if bad and fields.get("where"):
        out["where"] = fields["where"]
    return out


MAX_HEADER_BYTES = 1 << 20
MAX_BLOB_BYTES = 1 << 30
PREFIX = struct.Struct(">4sIQ")
MAGIC = b"ASY1"
EXIT_GRACE_S = 5.0
PASS_ENV = ("PATH", "LANG", "LC_ALL", "HF_HOME", "HF_HUB_CACHE", "CUDA_VISIBLE_DEVICES", "OMP_NUM_THREADS",
            "MKL_NUM_THREADS", "CC", "CXX")


@dataclass(frozen=True)
class Isolation:
    mode: str
    user: str
    uid: int
    gid: int

    def popen_kwargs(self) -> dict[str, Any]:
        if self.mode == "same-uid":
            return {}
        return {"user": self.uid, "group": self.gid, "extra_groups": [], "umask": 0o077}

    def scratch(self, prefix: str) -> Path:
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
    env = {k: os.environ[k] for k in PASS_ENV if k in os.environ}
    env.setdefault("PATH", "/usr/local/bin:/usr/bin:/bin")
    return {**env, "HOME": str(scratch), "TMPDIR": str(scratch), "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONUNBUFFERED": "1", **(extra or {})}


@dataclass(frozen=True)
class CmdResult:
    argv: list[str]
    rc: int | None
    output: str
    seconds: float
    truncated: bool


def run_cmd(argv: list[str], *, cwd: Path, iso: Isolation, env: Mapping[str, str], timeout: float,
            on_line: Callable[[str], None], max_lines: int = 2000) -> CmdResult:
    started = time.perf_counter()
    proc = subprocess.Popen(argv, cwd=cwd, env=dict(env), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, errors="replace", bufsize=1,
                            start_new_session=True, **iso.popen_kwargs())
    LIVE.add(proc.pid)
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
    LIVE.discard(proc.pid)
    return CmdResult(argv, rc, "\n".join(lines), time.perf_counter() - started, truncated[0])


def _killpg(proc: subprocess.Popen[Any]) -> None:
    kill_group(proc.pid)


class ProtocolError(Exception):
    pass


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


BOOT = "import sys; from {module} import main; main(int(sys.argv[1]), int(sys.argv[2]))"
LIVE: set[int] = set()


class Child:
    def __init__(self, module: str, *, cwd: Path, iso: Isolation, pythonpath: Path,
                 extra_env: Mapping[str, str] | None = None, warm: Path | None = None) -> None:
        self.scratch = iso.scratch("assay-child-")
        self.log_path = self.scratch / "child.log"
        self.hung = False
        to_child_r, self.to_child = os.pipe()
        self.from_child, from_child_w = os.pipe()
        os.set_blocking(self.to_child, False)
        env = child_env(self.scratch, {"PYTHONPATH": str(pythonpath), **(extra_env or {})})
        log_fd = os.open(self.log_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            if warm is not None:
                drop = iso.mode == "unprivileged"
                self.proc = None
                self.pid = warm_request(warm, {
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
        if self.hung or self._wait(EXIT_GRACE_S) is None:
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


def child_send(fd: int, header: Mapping[str, Any], blobs: Mapping[str, bytes]) -> None:
    write_frame(fd, header, blobs, None)


def child_recv(fd: int) -> tuple[dict[str, Any], Blobs]:
    return read_frame(fd, None)


WARM_MODULES = ("torch", "transformers", "transformers.models.gpt2.modeling_gpt2", "jaxtyping", "coverage", "tokenizers",
        "safetensors.torch", "huggingface_hub")
IDLE_EXIT_S = 30 * 60
START_TIMEOUT_S = 120.0
MAX_REQUEST = 1 << 20


def runtime_dir() -> Path:
    path = Path("/tmp") / f"assay-{os.getuid()}"
    path.mkdir(mode=0o700, exist_ok=True)
    st = path.lstat()
    if st.st_uid != os.getuid() or st.st_mode & 0o077 or not path.is_dir() or path.is_symlink():
        raise RuntimeError(f"{path} is not a private dir owned by uid {os.getuid()}; refusing to use it")
    return path


def warm_fingerprint() -> str:
    versions = {}
    for dist in ("torch", "transformers", "coverage", "jaxtyping"):
        try:
            versions[dist] = metadata.version(dist)
        except metadata.PackageNotFoundError:
            versions[dist] = "absent"
    parts = {"code": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), "python": sys.executable, **versions}
    return hashlib.sha256(json.dumps(parts, sort_keys=True).encode()).hexdigest()[:16]


def warm_socket() -> Path:
    return runtime_dir() / f"warm-{warm_fingerprint()}.sock"


def warm_request(path: Path, header: dict[str, Any], fds: list[int]) -> dict[str, Any]:
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


def warm_alive(path: Path) -> bool:
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
            conn.connect(str(path))
            socket.send_fds(conn, [b'{"kind": "ping"}'], [])
            conn.shutdown(socket.SHUT_WR)
            return conn.recv(64) != b""
    except OSError:
        return False


def stop_warm() -> bool:
    path = warm_socket()
    if not warm_alive(path):
        return False
    warm_request(path, {"kind": "stop"}, [])
    return True


def ensure_warm(log: Any = None) -> Path:
    path = warm_socket()
    if warm_alive(path):
        return path
    with (path.parent / "start.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if warm_alive(path):
            return path
        for stale in path.parent.glob("warm-*.sock"):
            if stale != path:
                with contextlib.suppress(OSError, RuntimeError, ValueError):
                    warm_request(stale, {"kind": "stop"}, [])
                stale.unlink(missing_ok=True)
        if log is not None:
            log("starting the warm check process (imports torch + transformers once; later checks fork from it)")
        server_log = (path.parent / f"{path.stem}.log").open("ab")
        env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1])}
        if sys.platform == "darwin":
            env["OBJC_DISABLE_INITIALIZE_FORK_SAFETY"] = "YES"
        subprocess.Popen([sys.executable, "-c", f"from assay.core import serve_warm; serve_warm({str(path)!r})"],
                         stdin=subprocess.DEVNULL, stdout=server_log, stderr=server_log, start_new_session=True,
                         env=env, cwd="/")
        deadline = time.monotonic() + START_TIMEOUT_S
        while not warm_alive(path):
            if time.monotonic() > deadline:
                raise RuntimeError(f"the warm process did not come up in {START_TIMEOUT_S:g}s; see {server_log.name}")
            time.sleep(0.05)
    return path


def serve_warm(path_str: str) -> None:
    path = Path(path_str)
    for name in WARM_MODULES:
        importlib.import_module(name)
    signal.signal(signal.SIGCHLD, signal.SIG_IGN)
    with contextlib.suppress(FileNotFoundError):
        path.unlink()
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(str(path))
    path.chmod(0o600)
    listener.listen(64)
    listener.settimeout(IDLE_EXIT_S)
    print(f"[warm {os.getpid()}] warm ({', '.join(WARM_MODULES)}); serving {path}", flush=True)
    while True:
        try:
            conn, _ = listener.accept()
        except TimeoutError:
            print(f"[warm {os.getpid()}] idle {IDLE_EXIT_S}s: exiting", flush=True)
            path.unlink(missing_ok=True)
            return
        with conn:
            try:
                _handle(listener, conn)
            except SystemExit:
                path.unlink(missing_ok=True)
                return


def _handle(listener: socket.socket, conn: socket.socket) -> None:
    fds: list[int] = []
    try:
        conn.settimeout(10)
        if hasattr(socket, "SO_PEERCRED"):
            creds = conn.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
            peer_uid = int.from_bytes(creds[4:8], sys.byteorder)
            if peer_uid != os.getuid():
                raise PermissionError(f"peer uid {peer_uid}")
        msg, fds, _, _ = socket.recv_fds(conn, MAX_REQUEST, 8)
        while len(msg) < MAX_REQUEST and (more := conn.recv(65536)):
            msg += more
        header = json.loads(msg)
        if header["kind"] in ("ping", "stop"):
            conn.sendall(b'{"ok": true}')
            if header["kind"] == "stop":
                raise SystemExit(0)
            return
        assert header["kind"] in ("trusted", "untrusted"), header["kind"]
        pid = os.fork()
        if pid == 0:
            _in_fork(header, fds, keep=set(fds), close=(listener, conn))
        conn.sendall(json.dumps({"pid": pid}).encode())
    except Exception as exc:  # noqa: BLE001 -- a bad request never takes the server down (SystemExit = stop)
        with contextlib.suppress(OSError):
            conn.sendall(json.dumps({"error": f"{type(exc).__name__}: {exc}"}).encode())
    finally:
        for fd in fds:
            with contextlib.suppress(OSError):
                os.close(fd)


def _in_fork(header: dict[str, Any], fds: list[int], keep: set[int], close: tuple[socket.socket, ...]) -> None:
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
        if sys.platform == "darwin":
            os.environ.setdefault("no_proxy", "*")
        tempfile.tempdir = None
        sys.dont_write_bytecode = True
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
    if header.get("uid") is not None:
        os.setgroups([])
        os.setgid(header["gid"])
        os.setuid(header["uid"])
        assert os.getuid() != 0 and os.geteuid() != 0, "privilege drop failed"
    os.umask(0o077)
    hub = sys.modules.get("huggingface_hub.constants")
    if hub is not None and header["env"].get("HF_HUB_OFFLINE") == "1":
        hub.HF_HUB_OFFLINE = True
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
