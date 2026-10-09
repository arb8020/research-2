"""The Colab provider: a machine is a Colab runtime (a VM assigned to your Google account) whose
Jupyter kernels run the supervisor and box's commands. For your own account, with compute units.

How it talks to Colab: it imports the official CLI's Python modules (google-colab-cli 0.7.4,
`colab_cli`), not the `colab` command, because `colab exec` runs Python in the kernel and exits 0
whatever the code did (commands/execution.py:258-262), while box needs bash's exit code and
separate stdout/stderr. Those modules are the CLI's internals, not a published API: pinned (the
`colab` extra in pyproject.toml).

    account   colab_cli.client.Client: assign / list_assignments / unassign / ccu-info (client.py)
    runtime   one VM's Jupyter server behind Colab's proxy, reached with a short-lived proxy token:
              kernels over websocket (colab_cli.runtime.ColabRuntime), files over /api/contents

What a machine is here:
- exec(cmd): a cell in box's exec kernel runs `bash -c cmd` in a subprocess and prints rc, stdout and
  stderr (base64, after MARK); the same thing a notebook's `!cmd` does. No ssh, no terminal, no port.
- stream(cmd): a cell in a kernel of its own (a kernel runs one cell at a time, and exec must not wait
  behind a follow) runs bash with pipes and prints each chunk as it arrives, as a base64 frame; the
  kernel publishes each print on iopub, which the websocket pushes to us. Push, not a poll. close()
  interrupts the kernel (SIGINT -> KeyboardInterrupt in the cell, whose `finally` kills the
  command's process group), then the stream shuts its kernel down.
- the supervisor: a second kernel's cell starts BOOT (supervisor + backstop) and waits on it, so
  that kernel is busy for the whole session (Colab keeps a runtime by "kernel activity",
  colab_cli/README.md:22). When the supervisor exits, BOOT unassigns the VM from inside with the
  same call as google.colab.runtime.unassign(): POST http://$TBE_RUNTIME_ADDR/unassign
  (colabtools google/colab/runtime.py), so a session ends itself as on Modal and RunPod.
- gone(): the account no longer lists the runtime as assigned. Unassigned is what Colab bills by
  (compute units per assigned runtime-hour) and what it does when it takes the VM back.
- labels: Colab runtimes carry none; box writes ROOT/colab.json on the VM ({labels, exec_kernel})
  and list()/get() read it back. An assignment without it (your own notebooks) is not box's.
- the proxy token expires (~1 h, tokenExpiresInSeconds, client.py:121-130); list_assignments hands
  out a fresh one, as `colab` itself does (common.py:96-104); the kernel connection is reopened.

Refused (each before anything is rented, with an error that says why):
- image: Colab runs its own image.
- ports / expose: Colab's terms forbid web services and proxies; the only ways in are kernels and files.
- stream(pty=True) and shell_argv: a kernel cell cannot be a terminal. A running cell takes no input
  but an input_request it makes itself (input()), so there is no stdin to type Ctrl-C into, and a
  pty made inside the cell would have nothing on this side to drive it; Colab's own terminal is in
  its UI only, and reaching one from outside would be the remote control its terms restrict.
- mounts, so record=: Colab has no volumes. A Colab session has no durable record: once its runtime
  is gone, so is everything it wrote (status, logs, ended.json); get results out before it ends.
- more than one accelerator (`:N`); a GPU Colab does not rent (gpus.py `colab` ids). gpu=None is a CPU runtime.
- a ceiling whose backstop (ceiling + BACKSTOP_MARGIN_S) would come after Colab's max runtime (12 h;
  24 h on Pro+: BOX_COLAB_MAX_HOURS=24). Refused, never clamped: the lease is a guarantee.
- a zero compute-unit balance, unless allow_free (BOX_COLAB_ALLOW_FREE=1): Colab's free tier forbids
  remote control and bypassing the notebook UI, which is what box does; paid balances lift that.

Unknown until the live smoke (box/tests/smoke_colab.py) runs: does a busy kernel keep an unwatched
runtime alive? Does TBE_RUNTIME_ADDR exist on CLI-assigned runtimes? Is /api/contents rooted at `/`?
Does a kernel websocket outlive its proxy token? Is Colab's A100 40 GB, and is G4 an RTX PRO 6000?
"""

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
from box.sdk import BACKSTOP_MARGIN_S, LABEL_BY, LABEL_NAME, Endpoint, Gone, NameTaken
from box.store import Mount

T = TypeVar("T")
COLAB_CLI_VERSION = "0.7.4"  # the colab_cli internals below were read at this version
ROOT = "/content/box"  # /content: Colab's working dir, visible in its file browser
META = "colab.json"  # under the root: {labels, exec_kernel}
MAX_RUNTIME_S = 12 * 3600  # Colab ends a runtime after 12 h (24 h on Pro+); the FAQ, not an API
REFRESH_MARGIN_S = 300  # refresh the proxy token this long before it expires (colab: 5 min)
EXEC_TIMEOUT_S = 600  # one exec's bash; the kernel kills it past this
KERNEL_SLACK_S = 30  # the client waits this much longer than the bash it runs
SUBMIT_ACK_S = 60  # a submitted cell must be seen running within this
STOP_GRACE_S = 3.0  # a stream's cell, once interrupted, gets this long to kill its command and go idle (inside pump.JOIN_S)
CONTENTS_TIMEOUT_S = 300  # one /api/contents request
INLINE_MAX = 512 * 1024  # an exec result bigger than this comes back as a file, not on iopub
MARK = "\x1ebox-exec\x1e"  # precedes every result or frame a box cell prints on its stdout
STREAM_NAMES = {"o": "stdout", "e": "stderr"}  # a stream cell's frame kinds; also "r<rc>" (exited) and "t" (its own timeout)
GPU_ACCELERATORS = ("T4", "L4", "G4", "A100", "H100")  # colab_cli.client.Accelerator (client.py:62-70)
TPU_ACCELERATORS = ("V5E1", "V6E1")
CPU = "NONE"

# The exec kernel's cell. Prints MARK + {"rc", "out", "err"} (base64), or {"file"} when that is too
# big for iopub, or {"timeout"}; the client reads it back (parse_exec).
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

# A stream's cell, in a kernel of its own. One line per frame: MARK + kind + payload. The command's
# bytes are base64 (iopub carries text). Its own process group, so one killpg ends all of it; the
# `finally` does that on an interrupt (close) or past its own timeout (a client that vanished: the
# cell then ends by itself, and its kernel idles until the runtime ends).
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

# The supervisor kernel's cell: starts BOOT in its own session and waits, so the kernel stays busy.
BOOT_CELL = """
import base64 as _b, json as _j, os as _os, subprocess as _s
_spec = _j.loads(_b.b64decode({spec!r}))
_os.makedirs(_spec["root"], exist_ok=True)
with open(_spec["root"] + "/boot.log", "ab") as _log:
    _p = _s.Popen(["bash", "-c", _spec["boot"], "boot", *_spec["argv"]], env={{**_os.environ, **_spec["env"]}},
                  stdin=_s.DEVNULL, stdout=_log, stderr=_s.STDOUT, start_new_session=True)
_p.wait()
"""

# Runs as `bash -c BOOT boot <supervisor argv...>`. Whatever ends the supervisor (its own end, a
# crash), the VM is unassigned after it; the backstop does it at BOX_COLAB_BACKSTOP_AT (unix time,
# the launching computer's clock, as the supervisor's ceiling is) regardless.
BOOT = r"""
( sleep "$(( BOX_COLAB_BACKSTOP_AT - $(date +%s) ))"; echo "$(date) backstop" >> "$BOX_ROOT/shutdown.log"; bash -c "$BOX_COLAB_UNASSIGN" ) &
"$@"
echo "$(date) supervisor exited $?" >> "$BOX_ROOT/shutdown.log"
bash -c "$BOX_COLAB_UNASSIGN"
"""

# google.colab.runtime.unassign() without its frontend call: the runtime's own management service.
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
    """The kernel id no longer exists on the runtime (died, restarted, culled)."""


class Unreachable(Exception):
    """The runtime did not answer as a Jupyter server would (proxy error, VM going away)."""


@dataclass(frozen=True)
class Assignment:
    """One runtime assigned to the account, as the account API reports it."""

    endpoint: str  # Colab's id for it; box's machine id
    accelerator: str  # colab_cli Accelerator value: NONE, T4, ..., V6E1
    url: str  # its Jupyter server, behind Colab's proxy
    token: str  # the proxy token
    expires_at: float  # time.time() at which the token stops working


@dataclass(frozen=True)
class Balance:
    compute_units: float
    rate_per_hour: float
    runtimes: int


class Runtime(Protocol):
    """One assigned VM's Jupyter server, for one proxy token. Not shared between threads, except
    interrupt(), which a stream's close() calls while its reader is in run()."""

    def start_kernel(self) -> str: ...
    # The cell's nbformat outputs (stream, error) as the kernel publishes them; ends when it goes idle.
    # TimeoutError past timeout_s; KernelGone; Unreachable. stop set: the cell was interrupted, so it
    # gets STOP_GRACE_S more to go idle, and then the iteration just ends.
    def run(self, kernel_id: str, code: str, timeout_s: float, stop: threading.Event | None = None) -> Iterator[dict[str, Any]]: ...
    def submit(self, kernel_id: str, code: str) -> None: ...  # returns once the kernel runs it
    def interrupt(self, kernel_id: str) -> None: ...  # SIGINT to the kernel: KeyboardInterrupt in its cell
    def shutdown_kernel(self, kernel_id: str) -> None: ...
    def get_file(self, path: str) -> bytes: ...  # FileNotFoundError
    def put_file(self, path: str, data: bytes) -> None: ...  # the parent must exist
    def delete_file(self, path: str) -> None: ...
    def close(self) -> None: ...  # its connections and their threads; the kernels go on


class Backend(Protocol):
    """The Colab account: what `colab new/sessions/stop/usage` call."""

    def balance(self) -> Balance: ...
    def assign(self, accelerator: str) -> Assignment: ...
    def assignments(self) -> list[Assignment]: ...
    def unassign(self, endpoint: str) -> None: ...
    def runtime(self, assignment: Assignment) -> Runtime: ...
    def close(self) -> None: ...


class Colab:
    name = "colab"

    def __init__(
        self, backend: Backend, *, allow_free: bool = False, max_runtime_s: int = MAX_RUNTIME_S,
        root: str = ROOT, log: TextIO = sys.stderr,
    ) -> None:  # fmt: skip
        assert max_runtime_s > BACKSTOP_MARGIN_S, max_runtime_s
        self.backend = backend
        self.allow_free = allow_free
        self.max_runtime_s = max_runtime_s
        # The supervisor's directory on each VM. "{machine}" in it is the runtime's id: the fake account
        # (tests/fake_colab.py) runs every runtime on one computer, so each needs a directory of its own.
        self.root = root
        self.log = log
        self.closed = False
        # Every machine this Colab handed out, so close() reaches their connections: a kernel websocket
        # runs a non-daemon thread (jupyter_kernel_client wsclient.py:593), which would hold the
        # process open at exit. Keyed by object identity (machines compare by runtime id).
        self._machines: dict[int, ColabMachine] = {}

    @classmethod
    def from_env(cls) -> Colab:
        """Credentials from the `colab` CLI's login (BOX_COLAB_AUTH: oauth2, its default, or adc);
        BOX_COLAB_ALLOW_FREE=1 and BOX_COLAB_MAX_HOURS (12; 24 on Pro+) as described above."""
        hours = float(os.environ.get("BOX_COLAB_MAX_HOURS", MAX_RUNTIME_S / 3600))
        backend = CliBackend(login(os.environ.get("BOX_COLAB_AUTH", "oauth2")))
        return cls(backend, allow_free=os.environ.get("BOX_COLAB_ALLOW_FREE") == "1", max_runtime_s=int(hours * 3600))

    def close(self) -> None:
        """Close every machine's connections (its streams joined) and the account session. The
        runtimes go on: closing a provider ends no session. This Colab makes no calls after."""
        self.closed = True
        for machine in list(self._machines.values()):
            machine.close()
        self.backend.close()

    def launch(  # noqa: PLR0913 (keyword-only: what a machine is made with)
        self, *, gpu: str | None, image: str | None, entrypoint: list[str], env: dict[str, str],
        labels: dict[str, str], timeout_s: int, ports: list[int], mounts: list[Mount],
    ) -> ColabMachine:  # fmt: skip
        """Returns once the supervisor's kernel runs BOOT (the supervisor may still be starting).
        Everything it refuses, it refuses before renting anything."""
        backstop_at = int(time.time()) + timeout_s  # now, before the assign: timeout_s counts from create's clock reading
        if image is not None:
            raise ValueError(f"colab provider: Colab runs its own image; got image={image!r} (install what the job needs in the job)")
        if ports:
            raise ValueError(f"colab provider: no ports (got {ports}): Colab's terms forbid web services and proxies")
        if mounts:
            raise ValueError(
                f"colab provider: Colab has no volumes, so nothing can be mounted (got {[m.store.uri for m in mounts]}), "
                "and a Colab session has no durable record (record=): get results out before it ends"
            )  # fmt: skip
        if timeout_s > self.max_runtime_s:
            raise ValueError(self._past_max_runtime(timeout_s))
        accelerator = colab_accelerator(gpu)
        # Best-effort: Colab runtimes have no names (box's labels are a file on the VM), so two
        # launches racing can both pass this check; attach(name=) then sees two.
        if LABEL_NAME in labels and self.list({LABEL_NAME: labels[LABEL_NAME]}):
            raise NameTaken(f"colab provider: a live runtime is named {labels[LABEL_NAME]!r}")
        self._check_balance()
        machine = self._track(ColabMachine(self, self.backend.assign(accelerator), labels, exec_kernel=None))
        try:
            machine.boot(entrypoint, env, backstop_at)
        except BaseException:
            try:
                machine.terminate()  # no supervisor will ever end this runtime
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
            raise LookupError(f"colab provider: {machine_id} was not launched by box (no {self.root_of(machine_id)}/{META})")
        return machine

    def list(self, labels: dict[str, str] | None = None) -> list[ColabMachine]:
        """Runtimes with box's labels (and all of labels); another runtime that cannot be read is
        reported and skipped."""
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
            meta = parse_meta(runtime.get_file(f"{self.root_of(a.endpoint)}/{META}"))
        except FileNotFoundError:
            return None
        finally:
            runtime.close()
        if meta["labels"].get(LABEL_BY) != "box":
            return None
        return self._track(ColabMachine(self, a, meta["labels"], exec_kernel=meta["exec_kernel"]))

    def root_of(self, machine_id: str) -> str:
        return self.root.replace("{machine}", machine_id)

    def _track(self, machine: ColabMachine) -> ColabMachine:
        assert not self.closed, "colab provider: closed"
        self._machines[id(machine)] = machine
        return machine

    def _untrack(self, machine: ColabMachine) -> None:
        self._machines.pop(id(machine), None)

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
        self.root = colab.root_of(self.id)
        self.work = self.root.rsplit("/", 1)[0] + "/work"  # beside the root: /content/work by default (synced code)
        self._assignment = assignment
        self._exec_kernel = exec_kernel
        self._runtime: Runtime | None = None
        self._dirs: set[str] = set()  # parents known to exist, for write
        # One connection (the exec kernel's websocket) shared by the caller and Session.keep's renewal
        # thread; a stream has a connection of its own, owned by its reader.
        self._lock = threading.RLock()
        self._streams: weakref.WeakSet[Pumped] = weakref.WeakSet()  # open ones, for close()

    def boot(self, entrypoint: list[str], env: dict[str, str], backstop_at: int) -> None:
        """Start the exec kernel, check the runtime can unassign itself, record the labels, then
        start the supervisor in its own kernel."""
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
        """cmd in a kernel of its own (STREAM_CELL), its frames read off iopub as the kernel pushes
        them, by one reader thread that owns the stream's connection and kernel and ends both. The
        kernel is started here, before the stream's clock starts (a Colab kernel takes seconds).
        pty=True is refused: a cell is not a terminal (module docstring)."""
        if pty:
            raise ValueError("colab provider: no pty: a kernel cell takes no stdin, so nothing could type into it (Ctrl-C is close())")
        runtime = self._connection()
        try:
            kernel = runtime.start_kernel()
        except BaseException as e:
            runtime.close()
            raise self._gone_or(e) from e
        cell = STREAM_CELL.format(cmd=base64.b64encode(cmd.encode()).decode(), timeout=timeout_s + KERNEL_SLACK_S, read_bytes=READ_BYTES, mark=MARK)
        stop = threading.Event()  # set by kill: the cell was interrupted
        rc: list[int] = []

        def read(emit: Emit) -> None:
            discard = False  # the caller closed the stream: drain the interrupted cell, hand on nothing
            try:
                for kind, payload in stream_frames(runtime.run(kernel, cell, timeout_s + 2 * KERNEL_SLACK_S, stop), stop, cmd):
                    if kind in STREAM_NAMES and not discard:
                        try:
                            emit(STREAM_NAMES[kind], base64.b64decode(payload))
                        except Closed:
                            discard = True  # close() calls kill next, which interrupts the cell
                    elif kind == "r":
                        rc.append(int(payload))
                    elif kind == "t":
                        raise TimeoutError(f"colab: {self.id}: stream of `{cmd[:80]}` ran past its cell's own bound; killed")
            except (Unreachable, KernelGone) as e:
                raise self._gone_or(e) from e
            finally:
                with contextlib.suppress(Exception):  # a kernel on a runtime that is gone
                    runtime.shutdown_kernel(kernel)
                runtime.close()
            if discard or stop.is_set():
                raise Closed

        def kill() -> None:
            stop.set()
            runtime.interrupt(kernel)  # the cell's `finally` kills the command's process group

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
        return self._call(lambda rt: rt.get_file(path))  # FileNotFoundError passes through _call

    def expose(self, port: int) -> Endpoint:
        raise ValueError(f"colab provider: cannot expose port {port}: Colab's terms forbid web services and proxies")

    def shell_argv(self, cmd: str) -> list[str]:
        raise ValueError("colab provider: no shell: Colab's terminal is in its UI only, and a kernel cell is not one (stream runs commands)")

    def terminate(self) -> None:
        """Idempotent: an endpoint no longer assigned is already terminated. A stream still open
        ends with the runtime (its reader sees Gone)."""
        self._drop_connection()
        if self._lookup() is None:
            return
        try:
            self.colab.backend.unassign(self.id)
        except Exception:
            if self._lookup() is None:  # it ended itself meanwhile (BOOT's unassign)
                return
            raise

    def gone(self) -> bool:
        """The account no longer lists this runtime as assigned (no VM, no compute units). One
        account call, bounded by google-auth's default request timeout (120 s)."""
        return self._lookup() is None

    def close(self) -> None:
        """Close this object's connections and join its open streams; the runtime goes on."""
        for stream in list(self._streams):
            stream.close()
        self._drop_connection()
        self.colab._untrack(self)

    def _execute(self, rt: Runtime, cell: str) -> list[dict[str, Any]]:
        """cell in the exec kernel; a kernel that is gone (died, culled) is replaced once."""
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
        """op(runtime) under the lock; a failure on a runtime no longer assigned is Gone."""
        with self._lock:
            runtime = self._shared()
            try:
                return op(runtime)
            except (FileNotFoundError, KernelGone, Gone):
                raise
            except Exception as e:
                raise self._gone_or(e) from e

    def _gone_or(self, e: BaseException) -> BaseException:
        """Gone if the runtime is no longer assigned (the failure was the VM going away), else e."""
        if isinstance(e, Exception) and not isinstance(e, Gone) and self._lookup() is None:
            return Gone(f"{self.id}: runtime no longer assigned ({e!r})")
        return e

    def _shared(self) -> Runtime:
        """The connection exec, read and write share, with a proxy token good for REFRESH_MARGIN_S more."""
        with self._lock:
            if self._assignment.expires_at - time.time() < REFRESH_MARGIN_S:
                self._refresh()
                self._drop_connection()
            if self._runtime is None:
                self._runtime = self._connection()
            return self._runtime

    def _connection(self) -> Runtime:
        """A new connection to the runtime, with a proxy token good for REFRESH_MARGIN_S more."""
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
    """A stream cell's stdout, split into its frames (kind, payload). iopub may cut a line anywhere,
    so the tail of one message waits for the next. A line that is not a frame is the wrapper going
    wrong (the command's own output only ever arrives inside frames): raised, never passed on."""

    def __init__(self, cmd: str) -> None:
        self.cmd = cmd
        self._partial = ""

    def feed(self, text: str) -> list[tuple[str, str]]:
        lines = (self._partial + text).split("\n")  # not splitlines: it splits on MARK's \x1e
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
    """A stream cell's frames, from its outputs as they arrive. A Python error in the cell is the
    wrapper failing, raised; unless stop is set, when it is our own interrupt (KeyboardInterrupt)."""
    frames = Frames(cmd)
    for out in outputs:
        if out["output_type"] == "error":
            if stop.is_set():
                continue
            raise RuntimeError(f"colab: stream cell failed under `{cmd[:80]}`: {out.get('ename')}: {out.get('evalue')}")
        if out.get("name") == "stdout":  # not the cell's own stderr (a warning): the command's is inside frames
            yield from frames.feed(out["text"])
    if not stop.is_set():  # an interrupted cell may stop mid-line
        frames.end()


def colab_accelerator(gpu: str | None) -> str:
    """A canonical GPU name (box/gpus.py) as a colab_cli Accelerator value; None is a CPU runtime."""
    if gpu is None:
        return CPU
    name, _, count = gpu.partition(":")
    if count not in ("", "1"):
        raise ValueError(f"colab provider: one accelerator per runtime; got {gpu!r}")
    accelerator = gpus.provider_id(gpus.lookup(name), "colab")
    if accelerator is None:
        raise ValueError(f"colab provider: Colab does not rent {name!r}; it rents {', '.join(g.name for g in gpus.GPUS if g.colab)}")
    assert accelerator in GPU_ACCELERATORS + TPU_ACCELERATORS, accelerator
    return accelerator


def variant(accelerator: str) -> str:
    """colab_cli Variant for an accelerator (commands/session.py:66-91)."""
    if accelerator == CPU:
        return "DEFAULT"
    return "TPU" if accelerator in TPU_ACCELERATORS else "GPU"


def parse_meta(raw: bytes) -> dict[str, Any]:
    meta = json.loads(raw)
    if not isinstance(meta.get("labels"), dict) or not isinstance(meta.get("exec_kernel"), str):
        raise ValueError(f"colab provider: malformed {META}: {raw[:200]!r}")
    return meta


def parse_exec(outputs: list[dict[str, Any]], cmd: str) -> dict[str, Any]:
    """The exec cell's result from its outputs. A Python error in the cell is the wrapper failing
    (bash's own failures are its rc), so it is raised, not turned into an exit code."""
    errors = [o for o in outputs if o.get("output_type") == "error"]
    if errors:
        e = errors[0]
        raise RuntimeError(f"colab: exec cell failed under `{cmd[:80]}`: {e.get('ename')}: {e.get('evalue')}")
    stdout = "".join(o.get("text", "") for o in outputs if o.get("output_type") == "stream" and o.get("name") == "stdout")
    lines = [line for line in stdout.split("\n") if line.startswith(MARK)]  # not splitlines: it splits on \x1e
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
    """Seconds left to wait for a cell: timeout_s from now, cut to STOP_GRACE_S once stop is set.
    0 or less: give up."""
    give_up = time.monotonic() + timeout_s
    stopped_at: list[float] = []

    def left() -> float:
        now = time.monotonic()
        if stop is not None and stop.is_set() and not stopped_at:
            stopped_at.append(now)
        end = min(give_up, stopped_at[0] + STOP_GRACE_S) if stopped_at else give_up
        return end - now

    return left


# ---- the real Colab, through google-colab-cli's modules ----------------------------------------


def login(auth: str) -> Any:
    """An authorized requests session from the `colab` CLI's own login (colab_cli/auth.py:222-242).
    Refuses to start the browser flow itself: run `colab usage` once to log in."""
    from colab_cli import auth as colab_auth

    _check_version()
    provider = colab_auth.AuthProvider(auth)  # ValueError on anything but oauth2 / adc
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
        self.client = Client(Prod(), http)  # as the CLI builds it (common.py:70-77)

    def balance(self) -> Balance:
        info = self.client.get_consumption_user_info()  # GET /tun/m/ccu-info (client.py:246-250)
        return Balance(info.paid_compute_units_balance, info.consumption_rate_hourly, info.assignments_count)

    def assign(self, accelerator: str) -> Assignment:
        """A fresh runtime (a new notebook hash each time, as `colab new` does: session.py:140-143)."""
        from colab_cli.client import (
            Accelerator,
            ColabRequestError,
            TooManyAssignmentsError,
            Variant,
        )
        from colab_cli.utils import get_status_code

        try:
            res = self.client.assign(uuid.uuid4(), variant=Variant(variant(accelerator)), accelerator=Accelerator(accelerator))
        except TooManyAssignmentsError as e:  # 412 (client.py:282-285; wording from session.py:144-156)
            raise RuntimeError(f"colab: allocation refused: too many runtimes, or a usage/capacity limit for {accelerator}: {e}") from e
        except ColabRequestError as e:
            if get_status_code(e) == 400 and accelerator != CPU:  # session.py:157-172
                raise RuntimeError(f"colab: no quota or entitlement for {accelerator} on this account") from e
            raise
        return _assignment(res.endpoint, getattr(res, "accelerator", None) or Accelerator(accelerator), res.runtime_proxy_info)

    def assignments(self) -> list[Assignment]:
        return [_assignment(a.endpoint, a.accelerator, a.runtime_proxy_info) for a in self.client.list_assignments()]

    def unassign(self, endpoint: str) -> None:
        self.client.unassign(endpoint)  # GET then POST /tun/m/unassign/{endpoint} (client.py:257-263)

    def runtime(self, assignment: Assignment) -> CliRuntime:
        return CliRuntime(assignment.url, assignment.token)

    def close(self) -> None:
        self.http.close()  # google-auth's AuthorizedSession: a requests.Session (its pooled connections)


def _assignment(endpoint: str, accelerator: Any, proxy: Any) -> Assignment:
    return Assignment(endpoint, accelerator.value, proxy.url, proxy.token, proxy.expires_at().timestamp())


class CliRuntime:
    """Kernels through colab_cli.runtime.ColabRuntime (its websocket, headers and the proxy token:
    runtime.py:89-172); files through /api/contents with the params colab_cli sends (contents.py:29-51).
    Each connected kernel holds a websocket thread (not a daemon); close() joins them."""

    def __init__(self, url: str, token: str) -> None:
        self.url = url.rstrip("/")
        self.token = token
        self._kernels: dict[str, Any] = {}  # kernel id -> connected ColabRuntime

    def start_kernel(self) -> str:
        from colab_cli.runtime import ColabRuntime

        rt = ColabRuntime(self.url, self.token)
        kernel_id = rt.kernel_client.id  # no kernel id: POST /api/kernels, then connect
        self._kernels[kernel_id] = rt
        return kernel_id

    def run(self, kernel_id: str, code: str, timeout_s: float, stop: threading.Event | None = None) -> Iterator[dict[str, Any]]:
        """The cell's outputs as iopub delivers them. Not ColabRuntime.execute_code: jupyter_kernel_client's
        wait spins past its timeout without raising (wsclient.py execute_interactive), stores every
        cell in history, and hands outputs over only at the end."""
        ws = self._connect(kernel_id)
        ws.iopub_channel.get_msgs()  # drop what other clients' cells broadcast meanwhile
        msg_id = ws.execute(code, store_history=False, allow_stdin=False)
        for msg in self._replies(ws, msg_id, reply_window(timeout_s, stop), stop):
            kind, content = msg["header"]["msg_type"], msg["content"]
            if kind == "stream":
                yield {"output_type": "stream", "name": content["name"], "text": content["text"]}
            elif kind == "error":
                yield {"output_type": "error", "ename": content["ename"], "evalue": content["evalue"], "traceback": content["traceback"]}
            elif kind == "status" and content["execution_state"] == "idle":
                ws.shell_channel.get_msgs()  # our execute_reply; read so the queue does not grow
                return

    def submit(self, kernel_id: str, code: str) -> None:
        ws = self._connect(kernel_id)
        msg_id = ws.execute(code, store_history=False, allow_stdin=False)
        for msg in self._replies(ws, msg_id, reply_window(SUBMIT_ACK_S, None), None):
            if msg["header"]["msg_type"] == "status" and msg["content"]["execution_state"] == "busy":
                self._kernels.pop(kernel_id).stop()  # closes the websocket, leaves the kernel running (runtime.py:264-276)
                return
        raise AssertionError("unreachable: _replies raises when it runs out")

    def interrupt(self, kernel_id: str) -> None:
        rt = self._kernels.get(kernel_id)
        if rt is not None:  # else the reader already shut it down
            rt.kernel_client.interrupt()  # POST /api/kernels/<id>/interrupt (manager.py interrupt_kernel)

    def shutdown_kernel(self, kernel_id: str) -> None:
        rt = self._kernels.pop(kernel_id, None)
        if rt is not None:
            rt.stop(shutdown_kernel=True)  # closes its websocket, then DELETE /api/kernels/<id>

    def _replies(self, ws: Any, msg_id: str, left: Callable[[], float], stop: threading.Event | None) -> Iterator[dict[str, Any]]:
        """iopub messages answering msg_id, until left() runs out (TimeoutError, or after stop, just
        the end) or the socket closes (Unreachable)."""
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
            # jupyter_kernel_client starts a new kernel when the id is gone (manager.py refresh_model
            # -> None, client.py start); that is not the kernel asked for
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
        """A /api/contents request. Paths are absolute on the VM; Colab's server root is `/`. A 404
        from Jupyter (application/json) is FileNotFoundError; any other failure is not."""
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
            with contextlib.suppress(Exception):  # closing a socket to a VM that is gone
                rt.stop()  # joins its websocket thread (wsclient.py stop_channels)
        self._kernels.clear()


def _jupyter_error(r: Any) -> bool:
    """Jupyter's API handlers answer application/json (jupyter_server 2's 404 body is then plain text,
    "file or directory ... does not exist"; older servers send {"message": ...}). Assumed: a proxy's
    404 for a runtime that is gone is not application/json. Unverified on Colab (the smoke checks)."""
    return r.headers.get("content-type", "").startswith("application/json")
