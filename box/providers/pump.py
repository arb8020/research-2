"""Machine.stream underneath, for every provider: a running command's output, pumped by reader threads
this object owns into a bounded queue and read by the caller as it arrives (a box.sdk.Stream).

    Pumped([pipe_reader("stdout", p.stdout), pipe_reader("stderr", p.stderr)], kill=..., wait=p.wait, ...)

A provider says how to read its command (readers), how to kill it, and how to get its exit code
(wait, which raises Gone if the machine went with it); Pumped does the rest: the bounds (timeout_s
on the whole stream, quiet_s between chunks), cancelling (close(), from any thread), and joining.
"""

from __future__ import annotations

import contextlib
import queue
import shlex
import sys
import threading
import time
from collections.abc import Callable, Iterator
from typing import IO

QUEUE_CHUNKS = 64  # chunks held between the readers and the caller; when full, the readers wait (backpressure, never dropped)
PUT_TICK_S = 0.1  # a waiting reader looks this often whether the stream was closed under it
CHECK_S = 1.0  # a stream asks `check` this often whether the machine is still there
JOIN_S = 10.0  # close(): how long a reader gets to end once its command is killed
READ_BYTES = 64 * 1024  # one read from a pipe at most

Emit = Callable[[str, bytes], None]  # (stream name, bytes): a reader hands each chunk to it; raises Closed once closed
Reader = Callable[[Emit], None]  # pumps one source into emit until its end; each runs on its own thread


_WAKE = ("", b"")  # put by close(): wakes an iteration blocked on the queue


class Closed(Exception):
    """The stream was closed: a reader still pumping stops."""


class _Eof:
    """A reader reached the end of its source."""


class Pumped:
    """Iterate for (stream name, bytes) as they arrive; then rc is the command's exit code. Leaving
    `with` (or close(), safe from any thread, idempotent) kills the command and joins the readers.
    Raises (and kills the command): TimeoutError past timeout_s, or with no chunk for quiet_s; Gone
    (from wait or check) once the machine is gone; whatever a reader raised."""

    def __init__(  # noqa: PLR0913 (keyword-only: each is one part of the contract)
        self, readers: list[Reader], *, kill: Callable[[], None], wait: Callable[[], int | None],
        timeout_s: float, quiet_s: float | None, check: Callable[[], None] = lambda: None, label: str,
    ) -> None:  # fmt: skip
        assert readers and timeout_s > 0 and (quiet_s is None or quiet_s > 0), (readers, timeout_s, quiet_s)
        self.rc: int | None = None
        self.label = label
        self._kill, self._wait, self._check = kill, wait, check
        self._give_up = time.monotonic() + timeout_s
        self._timeout_s, self._quiet_s = timeout_s, quiet_s
        self._queue: queue.Queue[tuple[str, bytes] | _Eof | BaseException] = queue.Queue(QUEUE_CHUNKS)
        self._closed = threading.Event()
        self._close_lock = threading.Lock()
        self._finished = False  # the command exited and was waited for: nothing to kill
        # Not daemons: each ends when its source does, which close() forces by killing the command.
        self._threads = [threading.Thread(target=self._pump, args=(r,), name=f"box-stream-{label}-{i}") for i, r in enumerate(readers)]
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
            while open_readers and not self._closed.is_set():  # closed from another thread: iteration just ends
                now = time.monotonic()
                if now - checked >= CHECK_S:  # by the clock, not only when quiet: output can outlive its machine (local)
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
        finally:  # however iteration ends (a caller that stops early too): the command is killed, the readers joined
            self.close()

    def _on_quiet(self, last: float) -> None:
        """No chunk for a while: past a bound, end it (TimeoutError)."""
        now = time.monotonic()
        if now >= self._give_up:
            raise TimeoutError(f"{self.label}: stream ran past {self._timeout_s:.0f} s; killed")
        if self._quiet_s is not None and now - last >= self._quiet_s:
            raise TimeoutError(f"{self.label}: no output for {self._quiet_s:.0f} s; killed")

    def close(self) -> None:
        with self._close_lock:
            if self._closed.is_set():
                return
            self._closed.set()
        with contextlib.suppress(queue.Full):
            self._queue.put_nowait(_WAKE)  # an iteration waiting on another thread sees the close now
        if not self._finished:
            try:
                self._kill()
            except Exception as e:  # noqa: BLE001 (closing goes on: the readers are still joined)
                print(f"box: {self.label}: killing a stream's command failed: {e!r}", file=sys.stderr)
        give_up = time.monotonic() + JOIN_S
        for t in self._threads:
            if t is not threading.current_thread():
                t.join(max(0.0, give_up - time.monotonic()))
        if stuck := [t.name for t in self._threads if t.is_alive()]:
            # A reader blocked in a call that ignores both the kill and cancellation; it ends when that call returns.
            print(f"box: {self.label}: stream readers {stuck} still running {JOIN_S:.0f} s after close", file=sys.stderr)

    def _pump(self, reader: Reader) -> None:
        item: _Eof | BaseException
        try:
            reader(self._emit)
            item = _Eof()
        except Closed:
            return
        except BaseException as e:  # noqa: BLE001 (handed to the caller, raised from its iteration)
            item = e
        try:
            self._put(item)
        except Closed:
            pass

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


def pipe_reader(name: str, pipe: IO[bytes]) -> Reader:
    """A local pipe (a subprocess's stdout/stderr): each read returns what is there, up to READ_BYTES."""

    def read(emit: Emit) -> None:
        with pipe:
            while data := pipe.read1(READ_BYTES):  # type: ignore[attr-defined]
                emit(name, data)

    return read


def with_pid_file(cmd: str, pid_file: str) -> str:
    """cmd (bash) that first notes its pid in pid_file, so a stream whose provider cannot kill the
    command (Modal's exec has no kill; ssh's channel close reaches it only on its next write) kills it
    with kill_pid_file() in another call."""
    return f"echo $$ > {shlex.quote(pid_file)}; exec bash -c {shlex.quote(cmd)}"


def kill_pid_file(pid_file: str) -> str:
    """bash: SIGTERM the command noted in pid_file and its children, then forget it."""
    p = shlex.quote(pid_file)
    return f"if [ -e {p} ]; then pid=$(cat {p}); pkill -TERM -P \"$pid\"; kill -TERM \"$pid\"; rm -f {p}; fi 2>/dev/null; true"
