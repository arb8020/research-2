"""A fake Colab account for tests: box/providers/colab.py's Backend and Runtime, on this computer.

A "runtime" is a directory under BASE/vms with its state in state.json, so another process (a test's
vanished client) sees the same account. Its kernels run each cell as `python -c cell` here (its stdout read as it comes, as iopub
pushes it; an interrupt is SIGINT to that process, as Jupyter's is to the kernel), with
TBE_RUNTIME_ADDR pointing at a small HTTP server (one per runtime, like Colab's management service)
whose POST /unassign ends the runtime: every process the runtime started is killed, as when Colab
takes the VM back. Each assignments() mints a fresh proxy token (as `colab` relies on its
list_assignments doing); every token works until token_ttl_s after it was minted. Files are this
computer's, so each runtime's root (Backend.root) is a directory of its own under its vm, and every
runtime sees the same files except a foreign one (assign_foreign: a notebook of yours), which has none of box's.

    config.json  {"compute_units": float, "token_ttl_s": float, "tbe": bool}   (FakeBackend.configure)
"""

from __future__ import annotations

import contextlib
import fcntl
import http.server
import json
import os
import secrets
import select
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Generator, Iterator
from pathlib import Path
from typing import Any

from box.providers.colab import Assignment, Balance, KernelGone, Unreachable, reply_window

DEFAULTS = {"compute_units": 100.0, "token_ttl_s": 3600.0, "tbe": True}


class FakeBackend:
    def __init__(self, base: Path) -> None:
        self.base = base
        (base / "vms").mkdir(parents=True, exist_ok=True)

    def configure(self, **kw: Any) -> None:
        unknown = set(kw) - set(DEFAULTS)
        assert not unknown, unknown
        _write(self.base / "config.json", {**self.config(), **kw})

    def config(self) -> dict[str, Any]:
        path = self.base / "config.json"
        return {**DEFAULTS, **(json.loads(path.read_text()) if path.exists() else {})}

    def balance(self) -> Balance:
        return Balance(self.config()["compute_units"], 1.5 * len(self.assignments()), len(self.assignments()))

    def assign_foreign(self, accelerator: str) -> Assignment:
        a = self.assign(accelerator)
        _update(self.vm(a.endpoint), foreign=True)
        return a

    def assign(self, accelerator: str) -> Assignment:
        vm = self.base / "vms" / f"fake-{accelerator.lower()}-{secrets.token_hex(3)}"
        vm.mkdir()
        state = {"accelerator": accelerator, "alive": True, "kernels": [], "pids": [], "server": None, "addr": None, "tokens": {}, "foreign": False}
        _write(vm / "state.json", _mint(state, self.config()["token_ttl_s"]))
        if self.config()["tbe"]:
            server = subprocess.Popen([sys.executable, "-m", "box.tests.fake_colab", str(vm)], start_new_session=True)
            while not (vm / "addr").exists():
                assert server.poll() is None, "fake TBE server died"
                time.sleep(0.02)
            _update(vm, server=server.pid, addr=(vm / "addr").read_text())
        return _assignment(vm)

    def assignments(self) -> list[Assignment]:
        found = []
        for vm in sorted((self.base / "vms").iterdir()):
            with _locked(vm):
                state = _state(vm)
                if not state["alive"]:
                    continue
                _write(vm / "state.json", _mint(state, self.config()["token_ttl_s"]))
            found.append(_assignment(vm))
        return found

    def unassign(self, endpoint: str) -> None:
        vm = self.base / "vms" / endpoint
        if not vm.exists() or not _state(vm)["alive"]:
            raise RuntimeError(f"fake colab: 404 no assignment {endpoint}")
        end(vm)

    def runtime(self, assignment: Assignment) -> FakeRuntime:
        return FakeRuntime(self.base / "vms" / assignment.endpoint, assignment.token)

    def root(self, endpoint: str) -> str:
        return str(self.vm(endpoint) / "content" / "box")

    def close(self) -> None:
        pass  # no connections: the account is files

    def vm(self, endpoint: str) -> Path:
        return self.base / "vms" / endpoint


class FakeRuntime:
    def __init__(self, vm: Path, token: str) -> None:
        self.vm = vm
        self.token = token
        self.executes = 0
        self._cells: dict[str, subprocess.Popen] = {}  # kernel id -> the cell it runs

    def start_kernel(self) -> str:
        self._check()
        kernel_id = secrets.token_hex(4)
        _change(self.vm, "kernels", lambda kernels: [*kernels, kernel_id])
        return kernel_id

    def run(self, kernel_id: str, code: str, timeout_s: float, stop: threading.Event | None = None) -> Iterator[dict[str, Any]]:
        self._check_kernel(kernel_id)
        self.executes += 1
        cell = subprocess.Popen(
            [sys.executable, "-c", code], env=self._env(), cwd=self.vm, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True,
        )  # fmt: skip
        _change(self.vm, "pids", lambda pids: [*pids, cell.pid])  # the runtime's end kills it
        self._cells[kernel_id] = cell
        left = reply_window(timeout_s, stop)
        try:
            while (remaining := left()) > 0:
                if not select.select([cell.stdout], [], [], min(remaining, 0.1))[0]:
                    continue
                data = os.read(cell.stdout.fileno(), 65536)
                if not data:
                    break
                yield {"output_type": "stream", "name": "stdout", "text": data.decode()}  # cells print ascii frames
            else:
                if stop is None or not stop.is_set():
                    raise TimeoutError(f"fake colab: cell ran past {timeout_s} s")
                return
            rc = cell.wait()
            if rc != 0:
                if not _state(self.vm)["alive"]:
                    raise Unreachable(f"fake colab: runtime {self.vm.name} is gone (cell killed)")
                yield {"output_type": "error", "ename": "FakeCellError", "evalue": cell.stderr.read().decode()[-500:], "traceback": []}
        finally:
            self._cells.pop(kernel_id, None)
            if cell.poll() is None:
                cell.kill()
                cell.wait()
            cell.stdout.close()
            cell.stderr.close()
            _change(self.vm, "pids", lambda pids: [p for p in pids if p != cell.pid])

    def interrupt(self, kernel_id: str) -> None:
        cell = self._cells.get(kernel_id)
        if cell is not None:
            with contextlib.suppress(ProcessLookupError):
                os.kill(cell.pid, signal.SIGINT)

    def shutdown_kernel(self, kernel_id: str) -> None:
        self.kill_kernel(kernel_id)

    def submit(self, kernel_id: str, code: str) -> None:
        self._check_kernel(kernel_id)
        cell = subprocess.Popen([sys.executable, "-c", code], env=self._env(), cwd=self.vm, start_new_session=True)
        _change(self.vm, "pids", lambda pids: [*pids, cell.pid])

    def get_file(self, path: str) -> bytes:
        self._check()
        if _state(self.vm)["foreign"]:
            raise FileNotFoundError(path)
        return Path(path).read_bytes()

    def put_file(self, path: str, data: bytes) -> None:
        self._check()
        if not Path(path).parent.is_dir():
            raise Unreachable(f"fake colab: 500 no directory for {path}")  # Jupyter's save does not mkdir
        Path(path).write_bytes(data)

    def delete_file(self, path: str) -> None:
        self._check()
        Path(path).unlink()

    def close(self) -> None:
        pass

    def kill_kernel(self, kernel_id: str) -> None:
        _change(self.vm, "kernels", lambda kernels: [k for k in kernels if k != kernel_id])

    def _check(self) -> None:
        state = _state(self.vm)
        if not state["alive"]:
            raise Unreachable(f"fake colab: 404 runtime {self.vm.name} is gone")
        if time.time() > state["tokens"].get(self.token, 0):
            raise Unreachable("fake colab: 401 proxy token expired")

    def _check_kernel(self, kernel_id: str) -> None:
        self._check()
        if kernel_id not in _state(self.vm)["kernels"]:
            raise KernelGone(kernel_id)

    def _env(self) -> dict[str, str]:
        addr = _state(self.vm)["addr"]
        env = {k: v for k, v in os.environ.items() if k != "TBE_RUNTIME_ADDR"}
        return {**env, "TBE_RUNTIME_ADDR": addr} if addr else env


def end(vm: Path) -> None:
    """Colab takes the VM back: it is no longer assigned and every process on it dies."""
    state = _state(vm)
    _update(vm, alive=False)
    roots = [p for p in (*state["pids"], state["server"]) if p and p != os.getpid()]
    for pid in roots + [d for p in roots for d in _descendants(p)]:
        with contextlib.suppress(ProcessLookupError):
            os.kill(pid, signal.SIGKILL)


def _descendants(pid: int) -> list[int]:
    table = subprocess.run(["ps", "-A", "-o", "pid=,ppid="], capture_output=True, text=True, check=True).stdout
    children: dict[int, list[int]] = {}
    for line in table.splitlines():
        child, parent = map(int, line.split())
        children.setdefault(parent, []).append(child)
    found, todo = [], [pid]
    while todo:
        for child in children.get(todo.pop(), []):
            found.append(child)
            todo.append(child)
    return found


def _mint(state: dict[str, Any], ttl_s: float) -> dict[str, Any]:
    token, now = secrets.token_hex(8), time.time()
    live = {t: at for t, at in state["tokens"].items() if at > now}
    return {**state, "token": token, "expires_at": now + ttl_s, "tokens": {**live, token: now + ttl_s}}


def _assignment(vm: Path) -> Assignment:
    s = _state(vm)
    return Assignment(vm.name, s["accelerator"], f"fake://{vm.name}", s["token"], s["expires_at"])


def _state(vm: Path) -> dict[str, Any]:
    return json.loads((vm / "state.json").read_text())


def _update(vm: Path, **kw: Any) -> None:
    with _locked(vm):
        _write(vm / "state.json", {**_state(vm), **kw})


def _change(vm: Path, key: str, change: Callable[[Any], Any]) -> None:
    """state[key] = change(state[key]), in one locked read-modify-write: a stream's reader and the
    caller start and end cells and kernels at once."""
    with _locked(vm):
        state = _state(vm)
        _write(vm / "state.json", {**state, key: change(state[key])})


@contextlib.contextmanager
def _locked(vm: Path) -> Generator[None, None, None]:
    """One read-modify-write of state.json at a time, across processes."""
    with (vm / ".lock").open("a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        yield


def _write(path: Path, data: dict[str, Any]) -> None:
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{secrets.token_hex(2)}")
    tmp.write_text(json.dumps(data))
    tmp.replace(path)


def serve(vm: Path) -> None:
    """The runtime's management service: POST /unassign ends the runtime (and this server)."""

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802 (http.server's name)
            if self.path != "/unassign":
                self.send_error(404)
                return
            self.send_response(200)
            self.end_headers()
            self.wfile.flush()
            end(vm)
            os._exit(0)

        def log_message(self, *args: object) -> None:
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    tmp = vm / ".addr"
    tmp.write_text(f"127.0.0.1:{server.server_port}")
    tmp.replace(vm / "addr")
    server.serve_forever()


if __name__ == "__main__":
    serve(Path(sys.argv[1]))
