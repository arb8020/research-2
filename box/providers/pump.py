from __future__ import annotations

import contextlib
import errno
import os
import queue
import select
import shlex
import sys
import threading
import time
from collections.abc import Callable, Iterator
from typing import IO

QUEUE_CHUNKS = 64
PUT_TICK_S = 0.1
CHECK_S = 1.0
JOIN_S = 10.0
READ_BYTES = 64 * 1024
MAX_SEND_BYTES = 64 * 1024
SEND_TIMEOUT_S = 10.0

Emit = Callable[[str, bytes], None]
Reader = Callable[[Emit], None]


_WAKE = ("", b"")


class Closed(Exception):
    pass


class _Eof:
    pass


class Pumped:
    def __init__(  # noqa: PLR0913
        self, readers: list[Reader], *, kill: Callable[[], None], wait: Callable[[], int | None],
        timeout_s: float, quiet_s: float | None, check: Callable[[], None] = lambda: None, label: str,
        send: Callable[[bytes], None] | None = None,
    ) -> None:  # fmt: skip
        assert readers and timeout_s > 0 and (quiet_s is None or quiet_s > 0), (readers, timeout_s, quiet_s)
        self.rc: int | None = None
        self.label = label
        self._kill, self._wait, self._check, self._send = kill, wait, check, send
        self._give_up = time.monotonic() + timeout_s
        self._timeout_s, self._quiet_s = timeout_s, quiet_s
        self._queue: queue.Queue[tuple[str, bytes] | _Eof | BaseException] = queue.Queue(QUEUE_CHUNKS)
        self._closed = threading.Event()
        self._close_lock = threading.Lock()
        self._finished = False
        self._threads = [threading.Thread(target=self._pump, args=(r,), name=f"box-stream-{label}-{i}", daemon=False) for i, r in enumerate(readers)]
        for t in self._threads:
            t.start()

    def __enter__(self) -> Pumped:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def __iter__(self) -> Iterator[tuple[str, bytes]]:
        open_readers = len(self._threads)
        last = checked = time.monotonic()
        try:
            while open_readers and not self._closed.is_set():
                now = time.monotonic()
                if now - checked >= CHECK_S:
                    self._check()
                    checked = now
                quiet_left = float("inf") if self._quiet_s is None else last + self._quiet_s - now
                try:
                    item = self._queue.get(timeout=max(0.0, min(CHECK_S, self._give_up - now, quiet_left)))
                except queue.Empty:
                    self._on_quiet(last)
                    continue
                if isinstance(item, _Eof):
                    open_readers -= 1
                elif isinstance(item, BaseException):
                    raise item
                elif item is not _WAKE:
                    last = time.monotonic()
                    yield item
            if not open_readers:
                self.rc = self._wait()
                self._finished = True
        except GeneratorExit:
            raise
        except BaseException:
            self.close()
            raise
        self.close()

    def _on_quiet(self, last: float) -> None:
        now = time.monotonic()
        if now >= self._give_up:
            raise TimeoutError(f"{self.label}: stream ran past {self._timeout_s:.0f} s; killed")
        if self._quiet_s is not None and now - last >= self._quiet_s:
            raise TimeoutError(f"{self.label}: no output for {self._quiet_s:.0f} s; killed")

    def send(self, data: bytes) -> None:
        if self._send is None:
            raise ValueError(f"{self.label}: not a pty stream: its stdin is closed (stream(pty=True) to type into it)")
        if len(data) > MAX_SEND_BYTES:
            raise ValueError(f"{self.label}: send of {len(data)} bytes; at most {MAX_SEND_BYTES} a call")
        if self._closed.is_set() or self._finished:
            raise ValueError(f"{self.label}: the stream has ended")
        self._send(data)

    def close(self) -> None:
        with self._close_lock:
            if self._closed.is_set():
                return
            self._closed.set()
        with contextlib.suppress(queue.Full):
            self._queue.put_nowait(_WAKE)
        if not self._finished:
            try:
                self._kill()
            except Exception as e:  # MUST KILL: swallows any kill failure (was noqa BLE001); catch the providers' kill errors only
                print(f"box: {self.label}: killing a stream's command failed: {e!r}", file=sys.stderr)
        give_up = time.monotonic() + JOIN_S
        for t in self._threads:
            if t is not threading.current_thread():
                t.join(max(0.0, give_up - time.monotonic()))
        if stuck := [t.name for t in self._threads if t.is_alive()]:
            print(f"box: {self.label}: stream readers {stuck} still running {JOIN_S:.0f} s after close", file=sys.stderr)

    def _pump(self, reader: Reader) -> None:
        item: _Eof | BaseException
        try:
            reader(self._emit)
            item = _Eof()
        except Closed:
            return
        except BaseException as e:
            item = e
        with contextlib.suppress(Closed):
            self._put(item)

    def _emit(self, name: str, data: bytes) -> None:
        self._put((name, data))

    def _put(self, item: tuple[str, bytes] | _Eof | BaseException) -> None:
        while True:
            if self._closed.is_set():
                raise Closed
            try:
                self._queue.put(item, timeout=PUT_TICK_S)
                return
            except queue.Full:
                continue


def pipe_reader(name: str, pipe: IO[bytes]) -> Reader:  # MUST KILL: pipe typed IO[bytes] though read1 needs a buffered reader (was type: ignore[attr-defined]); type it io.BufferedReader
    def read(emit: Emit) -> None:
        with pipe:
            while data := pipe.read1(READ_BYTES):
                emit(name, data)

    return read


class Pty:
    def __init__(self, master: int) -> None:
        self.master = master
        self.stop = threading.Event()
        self._lock = threading.Lock()
        self._open = True
        os.set_blocking(master, False)

    def reader(self, name: str = "stdout") -> Reader:
        def read(emit: Emit) -> None:
            try:
                while not self.stop.is_set():
                    if not select.select([self.master], [], [], PUT_TICK_S)[0]:
                        continue
                    try:
                        data = os.read(self.master, READ_BYTES)
                    except BlockingIOError:
                        continue
                    except OSError as e:
                        if e.errno == errno.EIO:  # Linux: EIO once every slave fd is closed
                            return
                        raise
                    if not data:  # macOS: b"" at the end of a pty
                        return
                    emit(name, data)
            finally:
                with self._lock:
                    self._open = False
                    os.close(self.master)

        return read

    def send(self, data: bytes) -> None:
        give_up = time.monotonic() + SEND_TIMEOUT_S
        with self._lock:
            while data:
                if not self._open:
                    raise ValueError("the stream has ended: its terminal is closed")
                if not select.select([], [self.master], [], max(0.0, give_up - time.monotonic()))[1]:
                    raise TimeoutError(f"a terminal took no input for {SEND_TIMEOUT_S:.0f} s")
                data = data[os.write(self.master, data) :]


def with_pid_file(cmd: str, pid_file: str) -> str:
    # Modal's exec has no kill, and ssh's channel close reaches the command only at its next write
    return f"echo $$ > {shlex.quote(pid_file)}; exec bash -c {shlex.quote(cmd)}"


def kill_pid_file(pid_file: str) -> str:
    p = shlex.quote(pid_file)
    return f"if [ -e {p} ]; then pid=$(cat {p}); pkill -TERM -P \"$pid\"; kill -TERM \"$pid\"; rm -f {p}; fi 2>/dev/null; true"
