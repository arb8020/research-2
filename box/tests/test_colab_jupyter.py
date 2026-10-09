"""The real Colab runtime client (providers/colab.py CliRuntime: colab_cli's kernel websocket, our
iopub loop, /api/contents) against a local Jupyter server rooted at `/`, as Colab's is. Everything
but Google's proxy and account. Needs the colab extra (the dev extra has jupyter_server):

    uv run --extra dev --extra colab pytest tests/test_colab_jupyter.py
"""

from __future__ import annotations

import base64
import os
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

pytest.importorskip("colab_cli")
pytest.importorskip("jupyter_server")

import requests  # noqa: E402

from box.providers import colab as colab_provider  # noqa: E402
from box.providers.colab import MARK, STREAM_CELL, CliRuntime, Frames, KernelGone  # noqa: E402


@pytest.fixture(scope="module")
def server() -> Iterator[str]:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    proc = subprocess.Popen(
        [sys.executable, "-m", "jupyter_server", "--no-browser", f"--port={port}", "--ServerApp.ip=127.0.0.1",
         "--ServerApp.root_dir=/", "--IdentityProvider.token=", "--ServerApp.disable_check_xsrf=True",
         "--ContentsManager.allow_hidden=True"],  # macOS flags /private (tmp_path) hidden
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )  # fmt: skip
    url = f"http://127.0.0.1:{port}"
    give_up = time.monotonic() + 60
    while True:
        try:
            requests.get(f"{url}/api/status", timeout=1).raise_for_status()
            break
        except requests.RequestException:
            assert time.monotonic() < give_up, "jupyter server did not start"
            time.sleep(0.3)
    yield url
    proc.terminate()
    proc.wait(timeout=30)


@pytest.fixture
def runtime(server: str) -> Iterator[CliRuntime]:
    rt = CliRuntime(server, token="local")
    yield rt
    rt.close()


def run(rt: CliRuntime, kernel: str, cmd: str) -> tuple[int, str, str]:
    cell = colab_provider.EXEC_CELL.format(cmd=base64.b64encode(cmd.encode()).decode(), timeout=60, inline_max=colab_provider.INLINE_MAX, mark=colab_provider.MARK)
    r = colab_provider.parse_exec(list(rt.run(kernel, cell, 90)), cmd)
    return r["rc"], colab_provider.b64text(r["out"]), colab_provider.b64text(r["err"])


def test_exec_cell_runs_bash_in_a_real_kernel(runtime: CliRuntime) -> None:
    kernel = runtime.start_kernel()
    assert run(runtime, kernel, "echo out; echo err >&2; exit 3") == (3, "out\n", "err\n")
    assert run(runtime, kernel, "seq 1 20000 | tail -1") == (0, "20000\n", "")  # many stream chunks


def test_a_second_connection_to_the_same_kernel_works(server: str, runtime: CliRuntime) -> None:
    kernel = runtime.start_kernel()
    other = CliRuntime(server, token="local")
    try:
        assert run(other, kernel, "echo shared")[1] == "shared\n"
        assert run(runtime, kernel, "echo mine")[1] == "mine\n"  # other's broadcasts did not confuse us
    finally:
        other.close()


def test_a_submitted_cell_keeps_running_after_we_disconnect(runtime: CliRuntime, tmp_path: Path) -> None:
    flag = tmp_path / "flag"
    runtime.submit(runtime.start_kernel(), f"import time, pathlib\ntime.sleep(1)\npathlib.Path({str(flag)!r}).write_text('ran')\ntime.sleep(30)")
    give_up = time.monotonic() + 30
    while not flag.exists():
        assert time.monotonic() < give_up
        time.sleep(0.2)


def test_an_unknown_kernel_is_kernel_gone(runtime: CliRuntime) -> None:
    with pytest.raises(KernelGone):
        list(runtime.run("00000000-0000-0000-0000-000000000000", "1", 30))


def test_files_round_trip_by_absolute_path(runtime: CliRuntime, tmp_path: Path) -> None:
    data = bytes(range(256)) * 4096  # 1 MiB, not utf-8
    path = str(tmp_path / "blob.bin")
    runtime.put_file(path, data)
    assert Path(path).read_bytes() == data
    assert runtime.get_file(path) == data
    runtime.delete_file(path)
    with pytest.raises(FileNotFoundError):
        runtime.get_file(path)


def stream_cell(cmd: str, timeout_s: float = 60) -> str:
    return STREAM_CELL.format(cmd=base64.b64encode(cmd.encode()).decode(), timeout=timeout_s, read_bytes=65536, mark=MARK)


def test_a_stream_cell_pushes_each_chunk_while_its_command_runs(runtime: CliRuntime, tmp_path: Path) -> None:
    """What stream() rests on: a real kernel publishes each frame on iopub as the cell prints it,
    not when the cell ends."""
    go = tmp_path / "go"
    kernel = runtime.start_kernel()
    outputs = runtime.run(kernel, stream_cell(f"echo first; while [ ! -e {go} ]; do sleep 0.05; done; echo second >&2; exit 4"), 90)
    frames = Frames("test")
    seen: list[tuple[str, str]] = []
    for out in outputs:
        seen += frames.feed(out["text"])
        if seen:
            break
    assert seen == [("o", base64.b64encode(b"first\n").decode())]  # while the command still waits on us
    go.touch()
    for out in outputs:
        seen += frames.feed(out["text"])
    frames.end()
    assert seen[1:] == [("e", base64.b64encode(b"second\n").decode()), ("r", "4")]


def test_interrupting_a_stream_cell_kills_its_command_group(runtime: CliRuntime, tmp_path: Path) -> None:
    pid_file = tmp_path / "pid"
    kernel = runtime.start_kernel()
    stop = threading.Event()
    outputs = runtime.run(kernel, stream_cell(f"sleep 999 & echo $! > {pid_file}; echo up; wait"), 90, stop)
    next(outputs)  # "up": running
    child = int(pid_file.read_text())
    stop.set()
    runtime.interrupt(kernel)
    rest = list(outputs)  # ends at the cell's idle, within STOP_GRACE_S
    assert [o["ename"] for o in rest if o["output_type"] == "error"] == ["KeyboardInterrupt"]
    give_up = time.monotonic() + 5
    while _alive(child):
        assert time.monotonic() < give_up, "the command's child outlived the interrupt"
        time.sleep(0.1)
    runtime.shutdown_kernel(kernel)


def test_close_joins_every_websocket_thread(server: str) -> None:
    before = {t.ident for t in threading.enumerate()}
    rt = CliRuntime(server, token="local")
    kernels = [rt.start_kernel() for _ in range(2)]
    assert len({t.ident for t in threading.enumerate()} - before) >= 2
    for k in kernels:
        rt.shutdown_kernel(k)
    rt.close()
    assert {t.ident for t in threading.enumerate() if t.is_alive()} - before == set()


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True
