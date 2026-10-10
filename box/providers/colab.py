from __future__ import annotations

import base64
import contextlib
import json
import os
import queue
import shlex
import sys
import threading
import time
import uuid
import weakref
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, TextIO, TypeVar
from urllib.parse import quote

from box import gpus
from box.providers.pump import READ_BYTES, Closed, Emit, Pumped
from box.sdk import (
    BACKSTOP_MARGIN_S,
    LABEL_BY,
    LABEL_NAME,
    Dropped,
    Endpoint,
    Gone,
    NameTaken,
    Refused,
    Shell,
)
from box.store import Mount

T = TypeVar("T")
COLAB_CLI_VERSION = "0.7.4"
ROOT = "/content/box"
META = "colab.json"
MAX_RUNTIME_S = 12 * 3600  # Colab ends a runtime after 12 h (24 h on Pro+), per its FAQ
REFRESH_MARGIN_S = 300
EXEC_TIMEOUT_S = 600
KERNEL_SLACK_S = 30
SUBMIT_ACK_S = 60
STOP_GRACE_S = 3.0
CONTENTS_TIMEOUT_S = 300
INLINE_MAX = 512 * 1024
MARK = "\x1ebox-exec\x1e"
STREAM_NAMES = {"o": "stdout", "e": "stderr"}
GPU_ACCELERATORS = ("T4", "L4", "G4", "A100", "H100")
TPU_ACCELERATORS = ("V5E1", "V6E1")
CPU = "NONE"

EXEC_CELL = """
import base64 as _b, json as _j, subprocess as _s, tempfile as _t
try:
    _r = _s.run(["bash", "-c", _b.b64decode({cmd!r}).decode()], capture_output=True, stdin=_s.DEVNULL, timeout={timeout})
    _o = _j.dumps({{"rc": _r.returncode, "out": _b.b64encode(_r.stdout).decode(), "err": _b.b64encode(_r.stderr).decode()}})
except _s.TimeoutExpired:
    _o = _j.dumps({{"timeout": True}})
if len(_o) > {inline_max}:
    with _t.NamedTemporaryFile("w", prefix="box-exec-", suffix=".json", dir="/tmp", delete=False) as _f:
        _f.write(_o)
    _o = _j.dumps({{"file": _f.name}})
print({mark!r} + _o, flush=True)
"""

STREAM_CELL = """
import base64 as _b, os as _os, select as _sel, signal as _sig, subprocess as _s, sys as _sys, time as _t
_p = _s.Popen(["bash", "-c", _b.b64decode({cmd!r}).decode()], stdin=_s.DEVNULL, stdout=_s.PIPE, stderr=_s.PIPE, start_new_session=True)
_open, _give_up, _end = {{_p.stdout.fileno(): "o", _p.stderr.fileno(): "e"}}, _t.monotonic() + {timeout}, "t"
try:
    while _open and _t.monotonic() < _give_up:
        for _fd in _sel.select(list(_open), [], [], 1.0)[0]:
            _d = _os.read(_fd, {read_bytes})
            if _d:
                _sys.stdout.write({mark!r} + _open[_fd] + _b.b64encode(_d).decode() + "\\n")
                _sys.stdout.flush()
            else:
                del _open[_fd]
    if not _open:
        _end = "r" + str(_p.wait())
finally:
    _old = _sig.signal(_sig.SIGINT, _sig.SIG_IGN)  # a second interrupt must not cut the kill short
    if _p.returncode is None:
        try:
            _os.killpg(_p.pid, _sig.SIGKILL)
        except ProcessLookupError:
            pass
        _p.wait()
    _sig.signal(_sig.SIGINT, _old)
print({mark!r} + _end, flush=True)
"""

BOOT_CELL = """
import base64 as _b, json as _j, os as _os, subprocess as _s
_spec = _j.loads(_b.b64decode({spec!r}))
_os.makedirs(_spec["root"], exist_ok=True)
with open(_spec["root"] + "/boot.log", "ab") as _log:
    _p = _s.Popen(["bash", "-c", _spec["boot"], "boot", *_spec["argv"]], env={{**_os.environ, **_spec["env"]}},
                  stdin=_s.DEVNULL, stdout=_log, stderr=_s.STDOUT, start_new_session=True)
_p.wait()
"""

BOOT = r"""
( sleep "$(( BOX_COLAB_BACKSTOP_AT - $(date +%s) ))"; echo "$(date) backstop" >> "$BOX_ROOT/shutdown.log"; bash -c "$BOX_COLAB_UNASSIGN" ) &
"$@"
echo "$(date) supervisor exited $?" >> "$BOX_ROOT/shutdown.log"
bash -c "$BOX_COLAB_UNASSIGN"
"""

# what google.colab.runtime.unassign() does, minus its frontend call
UNASSIGN = r"""python3 - <<'PY' >> "$BOX_ROOT/shutdown.log" 2>&1
import os, time, urllib.request as u
req = u.Request("http://" + os.environ["TBE_RUNTIME_ADDR"] + "/unassign", data=b"", method="POST")
for _ in range(30):
    try:
        print(time.ctime(), "unassign", u.urlopen(req, timeout=30).status, flush=True); break
    except Exception as e:
        print(time.ctime(), "unassign", e, flush=True)
    time.sleep(10)
PY"""


class KernelGone(Exception):
    pass


class Unreachable(Exception):
    pass


@dataclass(frozen=True)
class Assignment:
    endpoint: str
    accelerator: str
    url: str
    token: str
    expires_at: float


@dataclass(frozen=True)
class Balance:
    compute_units: float
    rate_per_hour: float
    runtimes: int


class Runtime(Protocol):
    def start_kernel(self) -> str: ...
    def run(self, kernel_id: str, code: str, timeout_s: float, stop: threading.Event | None = None) -> Iterator[dict[str, Any]]: ...
    def submit(self, kernel_id: str, code: str) -> None: ...
    def interrupt(self, kernel_id: str) -> None: ...
    def shutdown_kernel(self, kernel_id: str) -> None: ...
    def get_file(self, path: str) -> bytes: ...
    def put_file(self, path: str, data: bytes) -> None: ...
    def delete_file(self, path: str) -> None: ...
    def close(self) -> None: ...


class Backend(Protocol):
    def balance(self) -> Balance: ...
    def assign(self, accelerator: str) -> Assignment: ...
    def assignments(self) -> list[Assignment]: ...
    def unassign(self, endpoint: str) -> None: ...
    def runtime(self, assignment: Assignment) -> Runtime: ...
    def root(self, endpoint: str) -> str: ...
    def close(self) -> None: ...


class Colab:
    name = "colab"

    def __init__(
        self, backend: Backend, *, allow_free: bool = False, max_runtime_s: int = MAX_RUNTIME_S, log: TextIO = sys.stderr,
    ) -> None:  # fmt: skip
        assert max_runtime_s > BACKSTOP_MARGIN_S, max_runtime_s
        self.backend = backend
        self.allow_free = allow_free
        self.max_runtime_s = max_runtime_s
        self.log = log
        self.closed = False
        # a kernel websocket runs a non-daemon thread (jupyter_kernel_client) that holds the process open at exit
        self._machines: dict[str, ColabMachine] = {}

    @classmethod
    def from_env(cls) -> Colab:
        hours = float(os.environ.get("BOX_COLAB_MAX_HOURS", MAX_RUNTIME_S / 3600))
        backend = CliBackend(login(os.environ.get("BOX_COLAB_AUTH", "oauth2")))
        return cls(backend, allow_free=os.environ.get("BOX_COLAB_ALLOW_FREE") == "1", max_runtime_s=int(hours * 3600))

    def record_store(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True
        for machine in list(self._machines.values()):
            machine.close()
        self.backend.close()

    def launch(  # noqa: PLR0913
        self, *, gpu: str | None, image: str | None, entrypoint: list[str], env: dict[str, str],
        labels: dict[str, str], timeout_s: int, ports: list[int], mounts: list[Mount],
    ) -> ColabMachine:  # fmt: skip
        backstop_at = int(time.time()) + timeout_s
        if image is not None:
            raise Refused(f"colab provider: Colab runs its own image; got image={image!r} (install what the job needs in the job)")
        if ports:
            raise Refused(f"colab provider: no ports (got {ports}): Colab's terms forbid web services and proxies")
        if mounts:
            raise Refused(
                f"colab provider: Colab has no volumes, so nothing can be mounted (got {[m.store.uri for m in mounts]}), "
                "and a Colab session has no durable record (record=): get results out before it ends"
            )  # fmt: skip
        if timeout_s > self.max_runtime_s:
            raise Refused(self._past_max_runtime(timeout_s))
        accelerator = colab_accelerator(gpu)
        # Colab runtimes have no names: this check races
        if LABEL_NAME in labels and self.list({LABEL_NAME: labels[LABEL_NAME]}):
            raise NameTaken(f"colab provider: a live runtime is named {labels[LABEL_NAME]!r}")
        self._check_balance()
        machine = self._track(ColabMachine(self, self.backend.assign(accelerator), labels, exec_kernel=None))
        try:
            machine.boot(entrypoint, env, backstop_at)
        except BaseException:
            try:
                machine.terminate()
            finally:
                machine.close()
            raise
        return machine

    def get(self, machine_id: str) -> ColabMachine:
        found = [a for a in self.backend.assignments() if a.endpoint == machine_id]
        if not found:
            raise LookupError(f"colab provider: no runtime {machine_id} on this account")
        machine = self._ours(found[0])
        if machine is None:
            raise LookupError(f"colab provider: {machine_id} was not launched by box (no {self.backend.root(machine_id)}/{META})")
        return machine

    def list(self, labels: dict[str, str] | None = None) -> list[ColabMachine]:
        want = {**(labels or {}), LABEL_BY: "box"}
        found = []
        for a in self.backend.assignments():
            try:
                machine = self._ours(a)
            except (Unreachable, OSError) as e:
                print(f"box: colab: runtime {a.endpoint}: cannot read {META}, skipped: {e}", file=self.log)
                continue
            if machine is not None and want.items() <= machine.labels.items():
                found.append(machine)
        return found

    def _ours(self, a: Assignment) -> ColabMachine | None:
        runtime = self.backend.runtime(a)
        try:
            meta = parse_meta(runtime.get_file(f"{self.backend.root(a.endpoint)}/{META}"))
        except FileNotFoundError:
            return None
        finally:
            runtime.close()
        if meta["labels"].get(LABEL_BY) != "box":
            return None
        return self._track(ColabMachine(self, a, meta["labels"], exec_kernel=meta["exec_kernel"]))

    def _track(self, machine: ColabMachine) -> ColabMachine:
        assert not self.closed, "colab provider: closed"
        return self._machines.setdefault(machine.id, machine)

    def _untrack(self, machine: ColabMachine) -> None:
        if self._machines.get(machine.id) is machine:
            del self._machines[machine.id]

    def _past_max_runtime(self, timeout_s: int) -> str:
        ceiling_h = (timeout_s - BACKSTOP_MARGIN_S) / 3600
        most_h = (self.max_runtime_s - BACKSTOP_MARGIN_S) / 3600
        return (
            f"colab provider: a ceiling of {ceiling_h:.2f} h is refused: Colab ends a runtime after "
            f"{self.max_runtime_s / 3600:g} h, and box's backstop comes {BACKSTOP_MARGIN_S // 60} min after the ceiling, "
            f"so a Colab ceiling is at most {most_h:.2f} h (BOX_COLAB_MAX_HOURS=24 if you have Pro+). "
            "Not clamped: a lease is a guarantee, and Colab would end the session before it."
        )  # fmt: skip

    def _check_balance(self) -> None:
        b = self.backend.balance()
        print(f"box: colab: {b.compute_units:.2f} compute units, using {b.rate_per_hour:.2f}/h on {b.runtimes} runtime(s)", file=self.log)
        if b.compute_units > 0:
            return
        if not self.allow_free:
            raise RuntimeError(
                "colab provider: no compute units on this account. Colab's free tier forbids remote control "
                "and bypassing the notebook UI, which is what box does; buy units (`colab pay`), or set "
                "BOX_COLAB_ALLOW_FREE=1 if you have checked that your use is allowed."
            )  # fmt: skip
        print("box: colab: no compute units; going ahead because allow_free is set", file=self.log)


class ColabMachine:
    def __init__(self, colab: Colab, assignment: Assignment, labels: dict[str, str], *, exec_kernel: str | None) -> None:
        self.colab = colab
        self.id = assignment.endpoint
        self.labels = labels
        self.root = colab.backend.root(self.id)
        self.work = self.root.rsplit("/", 1)[0] + "/work"
        self._assignment = assignment
        self._exec_kernel = exec_kernel
        self._runtime: Runtime | None = None
        self._dirs: set[str] = set()
        self._lock = threading.RLock()
        self._streams: weakref.WeakSet[Pumped] = weakref.WeakSet()

    def boot(self, entrypoint: list[str], env: dict[str, str], backstop_at: int) -> None:
        self._exec_kernel = self._call(lambda rt: rt.start_kernel())
        rc, _, err = self.exec(f'test -n "$TBE_RUNTIME_ADDR" && mkdir -p {shlex.quote(self.root)}')
        if rc != 0:
            raise RuntimeError(f"colab provider: {self.id} has no TBE_RUNTIME_ADDR, so it could not end itself; refused ({err.strip()})")
        self._write_meta()
        spec = {
            "root": self.root, "boot": BOOT, "argv": entrypoint,
            "env": {**env, "BOX_ROOT": self.root, "BOX_COLAB_UNASSIGN": UNASSIGN, "BOX_COLAB_BACKSTOP_AT": str(backstop_at)},
        }  # fmt: skip
        assert "BOX_ON_SHUTDOWN" not in spec["env"], "BOOT unassigns; the supervisor must not run a shutdown of its own"
        cell = BOOT_CELL.format(spec=base64.b64encode(json.dumps(spec).encode()).decode())
        self._call(lambda rt: rt.submit(rt.start_kernel(), cell))

    def exec(self, cmd: str) -> tuple[int, str, str]:
        cell = EXEC_CELL.format(cmd=base64.b64encode(cmd.encode()).decode(), timeout=EXEC_TIMEOUT_S, inline_max=INLINE_MAX, mark=MARK)
        result = parse_exec(self._call(lambda rt: self._execute(rt, cell)), cmd)
        if "file" in result:
            path = result["file"]
            result = parse_exec_result(self._call(lambda rt: rt.get_file(path)), cmd)
            self._call(lambda rt: rt.delete_file(path))
        if result.get("timeout"):
            raise TimeoutError(f"colab: {self.id}: `{cmd[:80]}` ran past {EXEC_TIMEOUT_S} s (killed)")
        return result["rc"], b64text(result["out"]), b64text(result["err"])

    def stream(self, cmd: str, *, timeout_s: float, quiet_s: float | None = None, pty: bool = False) -> Pumped:
        if pty:
            raise Refused("colab provider: no pty: a kernel cell takes no stdin, so nothing could type into it (Ctrl-C is close())")
        runtime = self._connection()
        try:
            kernel = runtime.start_kernel()
        except BaseException as e:
            runtime.close()
            raise self._gone_or(e) from e
        cell = STREAM_CELL.format(cmd=base64.b64encode(cmd.encode()).decode(), timeout=timeout_s + KERNEL_SLACK_S, read_bytes=READ_BYTES, mark=MARK)
        stop = threading.Event()
        rc: list[int] = []

        def read(emit: Emit) -> None:
            discard = False
            try:
                for kind, payload in stream_frames(runtime.run(kernel, cell, timeout_s + 2 * KERNEL_SLACK_S, stop), stop, cmd):
                    if kind in STREAM_NAMES and not discard:
                        try:
                            emit(STREAM_NAMES[kind], base64.b64decode(payload))
                        except Closed:
                            discard = True
                    elif kind == "r":
                        rc.append(int(payload))
                    elif kind == "t":
                        raise TimeoutError(f"colab: {self.id}: stream of `{cmd[:80]}` ran past its cell's own bound; killed")
            except (Unreachable, KernelGone) as e:
                gone = self._gone_or(e)
                if isinstance(gone, Gone):
                    raise gone from e
                raise Dropped(f"colab: {self.id}: the stream of `{cmd[:80]}` dropped: {e!r}") from e
            finally:
                with contextlib.suppress(Exception):
                    runtime.shutdown_kernel(kernel)
                runtime.close()
            if discard or stop.is_set():
                raise Closed

        def kill() -> None:
            stop.set()
            runtime.interrupt(kernel)

        def wait() -> int:
            if not rc:
                raise RuntimeError(f"colab: {self.id}: stream cell of `{cmd[:80]}` ended without an exit code")
            return rc[0]

        stream = Pumped([read], kill=kill, wait=wait, timeout_s=timeout_s, quiet_s=quiet_s, label=self.id)
        self._streams.add(stream)
        return stream

    def write(self, path: str, data: bytes) -> None:
        parent = path.rsplit("/", 1)[0] or "/"
        if parent not in self._dirs:
            rc, _, err = self.exec(f"mkdir -p {shlex.quote(parent)}")
            if rc != 0:
                raise RuntimeError(f"colab: {self.id}: mkdir -p {parent} exited {rc}: {err.strip()}")
            self._dirs.add(parent)
        self._call(lambda rt: rt.put_file(path, data))

    def read(self, path: str) -> bytes:
        return self._call(lambda rt: rt.get_file(path))

    def expose(self, port: int) -> Endpoint:
        raise Refused(f"colab provider: cannot expose port {port}: Colab's terms forbid web services and proxies")

    def shell(self, cmd: str) -> Shell:
        raise Refused("colab provider: no shell: Colab's terminal is in its UI only, and a kernel cell is not one (stream runs commands)")

    def terminate(self) -> None:
        self._drop_connection()
        if self._lookup() is None:
            return
        try:
            self.colab.backend.unassign(self.id)
        except Exception:
            if self._lookup() is None:
                return
            raise

    def gone(self) -> bool:
        return self._lookup() is None

    def close(self) -> None:
        for stream in list(self._streams):
            stream.close()
        self._drop_connection()
        self.colab._untrack(self)

    def _execute(self, rt: Runtime, cell: str) -> list[dict[str, Any]]:
        assert self._exec_kernel is not None, "exec before boot"
        try:
            return list(rt.run(self._exec_kernel, cell, EXEC_TIMEOUT_S + KERNEL_SLACK_S))
        except KernelGone:
            old, self._exec_kernel = self._exec_kernel, rt.start_kernel()
            print(f"box: colab: {self.id}: exec kernel {old} is gone; started {self._exec_kernel}", file=self.colab.log)
            self._write_meta()
            return list(rt.run(self._exec_kernel, cell, EXEC_TIMEOUT_S + KERNEL_SLACK_S))

    def _write_meta(self) -> None:
        meta = json.dumps({"labels": self.labels, "exec_kernel": self._exec_kernel}).encode()
        self._call(lambda rt: rt.put_file(f"{self.root}/{META}", meta))

    def _call(self, op: Callable[[Runtime], T]) -> T:
        with self._lock:
            runtime = self._shared()
            try:
                return op(runtime)
            except (FileNotFoundError, KernelGone, Gone):
                raise
            except Exception as e:
                raise self._gone_or(e) from e

    def _gone_or(self, e: BaseException) -> BaseException:
        if isinstance(e, Exception) and not isinstance(e, Gone) and self._lookup() is None:
            return Gone(f"{self.id}: runtime no longer assigned ({e!r})")
        return e

    def _shared(self) -> Runtime:
        with self._lock:
            if self._assignment.expires_at - time.time() < REFRESH_MARGIN_S:
                self._refresh()
                self._drop_connection()
            if self._runtime is None:
                self._runtime = self._connection()
            return self._runtime

    def _connection(self) -> Runtime:
        assert not self.colab.closed, "colab provider: closed"
        with self._lock:
            if self._assignment.expires_at - time.time() < REFRESH_MARGIN_S:
                self._refresh()
            return self.colab.backend.runtime(self._assignment)

    def _refresh(self) -> None:
        current = self._lookup()
        if current is None:
            raise Gone(f"{self.id}: runtime no longer assigned")
        self._assignment = current

    def _drop_connection(self) -> None:
        with self._lock:
            if self._runtime is not None:
                self._runtime.close()
                self._runtime = None

    def _lookup(self) -> Assignment | None:
        return next((a for a in self.colab.backend.assignments() if a.endpoint == self.id), None)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, ColabMachine) and other.id == self.id

    def __hash__(self) -> int:
        return hash(self.id)


class Frames:
    def __init__(self, cmd: str) -> None:
        self.cmd = cmd
        # iopub may split a line across stream messages
        self._partial = ""

    def feed(self, text: str) -> list[tuple[str, str]]:
        lines = (self._partial + text).split("\n")  # not splitlines: it also splits on \x1e, which MARK holds
        self._partial = lines.pop()
        frames = []
        for line in lines:
            if not line.startswith(MARK) or len(line) == len(MARK):
                raise RuntimeError(f"colab: stream cell printed a non-frame under `{self.cmd[:80]}`: {line[:200]!r}")
            body = line[len(MARK) :]
            frames.append((body[0], body[1:]))
        return frames

    def end(self) -> None:
        if self._partial:
            raise RuntimeError(f"colab: stream cell ended mid-frame under `{self.cmd[:80]}`: {self._partial[:200]!r}")


def stream_frames(outputs: Iterator[dict[str, Any]], stop: threading.Event, cmd: str) -> Iterator[tuple[str, str]]:
    frames = Frames(cmd)
    for out in outputs:
        if out["output_type"] == "error":
            if stop.is_set():
                continue
            raise RuntimeError(f"colab: stream cell failed under `{cmd[:80]}`: {out.get('ename')}: {out.get('evalue')}")
        if out.get("name") == "stdout":
            yield from frames.feed(out["text"])
    if not stop.is_set():
        frames.end()


def colab_accelerator(gpu: str | None) -> str:
    if gpu is None:
        return CPU
    name, _, count = gpu.partition(":")
    if count not in ("", "1"):
        raise Refused(f"colab provider: one accelerator per runtime; got {gpu!r}")
    accelerator = gpus.provider_id(gpus.lookup(name), "colab")
    if accelerator is None:
        raise Refused(f"colab provider: Colab does not rent {name!r}; it rents {', '.join(g.name for g in gpus.GPUS if g.colab)}")
    assert accelerator in GPU_ACCELERATORS + TPU_ACCELERATORS, accelerator
    return accelerator


def variant(accelerator: str) -> str:
    if accelerator == CPU:
        return "DEFAULT"
    return "TPU" if accelerator in TPU_ACCELERATORS else "GPU"


def parse_meta(raw: bytes) -> dict[str, Any]:
    meta = json.loads(raw)
    if not isinstance(meta.get("labels"), dict) or not isinstance(meta.get("exec_kernel"), str):
        raise ValueError(f"colab provider: malformed {META}: {raw[:200]!r}")
    return meta


def parse_exec(outputs: list[dict[str, Any]], cmd: str) -> dict[str, Any]:
    errors = [o for o in outputs if o.get("output_type") == "error"]
    if errors:
        e = errors[0]
        raise RuntimeError(f"colab: exec cell failed under `{cmd[:80]}`: {e.get('ename')}: {e.get('evalue')}")
    stdout = "".join(o.get("text", "") for o in outputs if o.get("output_type") == "stream" and o.get("name") == "stdout")
    lines = [line for line in stdout.split("\n") if line.startswith(MARK)]  # not splitlines: it also splits on \x1e, which MARK holds
    if len(lines) != 1:
        raise RuntimeError(f"colab: exec cell printed {len(lines)} results under `{cmd[:80]}`: {stdout[-300:]!r}")
    return parse_exec_result(lines[0][len(MARK) :].encode(), cmd)


def parse_exec_result(raw: bytes, cmd: str) -> dict[str, Any]:
    result = json.loads(raw)
    shapes = ({"rc", "out", "err"}, {"timeout"}, {"file"})
    if set(result) not in shapes:
        raise RuntimeError(f"colab: unexpected exec result under `{cmd[:80]}`: {sorted(result)}")
    return result


def b64text(data: str) -> str:
    return base64.b64decode(data).decode(errors="replace")


def reply_window(timeout_s: float, stop: threading.Event | None) -> Callable[[], float]:
    give_up = time.monotonic() + timeout_s
    stopped_at: list[float] = []

    def left() -> float:
        now = time.monotonic()
        if stop is not None and stop.is_set() and not stopped_at:
            stopped_at.append(now)
        end = min(give_up, stopped_at[0] + STOP_GRACE_S) if stopped_at else give_up
        return end - now

    return left


def login(auth: str) -> Any:
    from colab_cli import auth as colab_auth

    _check_version()
    provider = colab_auth.AuthProvider(auth)
    if provider == colab_auth.AuthProvider.OAUTH2 and not Path(colab_auth.TOKEN_CONFIG_PATH).exists():
        raise SystemExit(f"box: colab: not logged in ({colab_auth.TOKEN_CONFIG_PATH} missing); run `colab usage` once")
    return colab_auth.get_credentials(provider=provider)


def _check_version() -> None:
    from importlib.metadata import version

    found = version("google-colab-cli")
    if found != COLAB_CLI_VERSION:
        print(f"box: colab: google-colab-cli {found}; this provider was written against {COLAB_CLI_VERSION}", file=sys.stderr)


class CliBackend:
    def __init__(self, http: Any) -> None:
        from colab_cli.client import Client, Prod

        self.http = http
        self.client = Client(Prod(), http)

    def balance(self) -> Balance:
        info = self.client.get_consumption_user_info()
        return Balance(info.paid_compute_units_balance, info.consumption_rate_hourly, info.assignments_count)

    def assign(self, accelerator: str) -> Assignment:
        from colab_cli.client import (
            Accelerator,
            ColabRequestError,
            TooManyAssignmentsError,
            Variant,
        )
        from colab_cli.utils import get_status_code

        try:
            res = self.client.assign(uuid.uuid4(), variant=Variant(variant(accelerator)), accelerator=Accelerator(accelerator))
        except TooManyAssignmentsError as e:
            raise RuntimeError(f"colab: allocation refused: too many runtimes, or a usage/capacity limit for {accelerator}: {e}") from e
        except ColabRequestError as e:
            if get_status_code(e) == 400 and accelerator != CPU:
                raise RuntimeError(f"colab: no quota or entitlement for {accelerator} on this account") from e
            raise
        return _assignment(res.endpoint, getattr(res, "accelerator", None) or Accelerator(accelerator), res.runtime_proxy_info)

    def assignments(self) -> list[Assignment]:
        return [_assignment(a.endpoint, a.accelerator, a.runtime_proxy_info) for a in self.client.list_assignments()]

    def unassign(self, endpoint: str) -> None:
        self.client.unassign(endpoint)

    def runtime(self, assignment: Assignment) -> CliRuntime:
        return CliRuntime(assignment.url, assignment.token)

    def root(self, endpoint: str) -> str:
        return ROOT

    def close(self) -> None:
        self.http.close()


def _assignment(endpoint: str, accelerator: Any, proxy: Any) -> Assignment:
    return Assignment(endpoint, accelerator.value, proxy.url, proxy.token, proxy.expires_at().timestamp())


class CliRuntime:
    def __init__(self, url: str, token: str) -> None:
        self.url = url.rstrip("/")
        self.token = token
        self._kernels: dict[str, Any] = {}

    def start_kernel(self) -> str:
        from colab_cli.runtime import ColabRuntime

        rt = ColabRuntime(self.url, self.token)
        kernel_id = rt.kernel_client.id
        self._kernels[kernel_id] = rt
        return kernel_id

    def run(self, kernel_id: str, code: str, timeout_s: float, stop: threading.Event | None = None) -> Iterator[dict[str, Any]]:
        # not ColabRuntime.execute_code: jupyter_kernel_client's wait ignores its timeout and returns outputs only at the end
        ws = self._connect(kernel_id)
        ws.iopub_channel.get_msgs()
        msg_id = ws.execute(code, store_history=False, allow_stdin=False)
        for msg in self._replies(ws, msg_id, reply_window(timeout_s, stop), stop):
            kind, content = msg["header"]["msg_type"], msg["content"]
            if kind == "stream":
                yield {"output_type": "stream", "name": content["name"], "text": content["text"]}
            elif kind == "error":
                yield {"output_type": "error", "ename": content["ename"], "evalue": content["evalue"], "traceback": content["traceback"]}
            elif kind == "status" and content["execution_state"] == "idle":
                ws.shell_channel.get_msgs()
                return

    def submit(self, kernel_id: str, code: str) -> None:
        ws = self._connect(kernel_id)
        msg_id = ws.execute(code, store_history=False, allow_stdin=False)
        for msg in self._replies(ws, msg_id, reply_window(SUBMIT_ACK_S, None), None):
            if msg["header"]["msg_type"] == "status" and msg["content"]["execution_state"] == "busy":
                self._kernels.pop(kernel_id).stop()  # ColabRuntime.stop() closes the websocket and leaves the kernel running
                return
        raise AssertionError("unreachable: _replies raises when it runs out")

    def interrupt(self, kernel_id: str) -> None:
        rt = self._kernels.get(kernel_id)
        if rt is not None:
            rt.kernel_client.interrupt()

    def shutdown_kernel(self, kernel_id: str) -> None:
        rt = self._kernels.pop(kernel_id, None)
        if rt is not None:
            rt.stop(shutdown_kernel=True)

    def _replies(self, ws: Any, msg_id: str, left: Callable[[], float], stop: threading.Event | None) -> Iterator[dict[str, Any]]:
        while (remaining := left()) > 0:
            if not ws.connection_ready.is_set():
                raise Unreachable(f"colab: kernel websocket closed ({self.url})")
            try:
                msg = ws.iopub_channel.get_msg(timeout=min(remaining, 1.0))
            except queue.Empty:
                continue
            if msg["parent_header"].get("msg_id") == msg_id:
                yield msg
        if stop is None or not stop.is_set():
            raise TimeoutError(f"colab: no answer from the kernel in time ({self.url})")

    def _connect(self, kernel_id: str) -> Any:
        from colab_cli.runtime import ColabRuntime

        if kernel_id not in self._kernels:
            rt = ColabRuntime(self.url, self.token, kernel_id=kernel_id)
            # jupyter_kernel_client starts a new kernel when the id is gone
            if rt.kernel_client.id != kernel_id:
                rt.stop(shutdown_kernel=True)
                raise KernelGone(kernel_id)
            self._kernels[kernel_id] = rt
        return self._kernels[kernel_id].kernel_client._manager.client

    def get_file(self, path: str) -> bytes:
        model = self._contents("GET", path, params={"content": "1", "format": "base64", "type": "file"}).json()
        if model.get("type") != "file" or model.get("format") != "base64":
            raise IsADirectoryError(path) if model.get("type") == "directory" else ValueError(f"colab: {path}: {model.get('type')}/{model.get('format')}")
        return base64.b64decode(model["content"])

    def put_file(self, path: str, data: bytes) -> None:
        body = {"type": "file", "format": "base64", "content": base64.b64encode(data).decode()}
        self._contents("PUT", path, json=body)

    def delete_file(self, path: str) -> None:
        self._contents("DELETE", path)

    def _contents(self, method: str, path: str, **kw: Any) -> Any:
        import requests

        assert path.startswith("/"), path
        url = f"{self.url}/api/contents/{quote(path.strip('/'), safe='/')}"
        params = {"authuser": "0", "colab-runtime-proxy-token": self.token, **kw.pop("params", {})}
        headers = {"X-Colab-Runtime-Proxy-Token": self.token, "X-Colab-Client-Agent": "colab-cli"}
        r = requests.request(method, url, params=params, headers=headers, timeout=CONTENTS_TIMEOUT_S, **kw)
        if r.status_code == 404 and _jupyter_error(r):
            raise FileNotFoundError(path)
        if not r.ok:
            raise Unreachable(f"colab: {method} {path} -> {r.status_code}: {r.text[:300]}")
        return r

    def close(self) -> None:
        for rt in list(self._kernels.values()):
            with contextlib.suppress(Exception):
                rt.stop()
        self._kernels.clear()


def _jupyter_error(r: Any) -> bool:  # MUST KILL: tells a Jupyter 404 from a proxy 404 by content-type, unverified on Colab; check the body shape, or settle it with the smoke
    return r.headers.get("content-type", "").startswith("application/json")
