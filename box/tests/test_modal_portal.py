"""The Modal provider's loop (an anyio BlockingPortal it owns), without Modal: a fake sandbox whose
.aio calls are coroutines this file controls. What is proven: a call from inside a running event
loop works; a hung call is cancelled at its bound with nothing left on the loop; close() cancels an
open stream and joins the loop's thread; a closed provider (and a machine outliving it) raises;
no thread outlives the provider."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass

import anyio
import pytest

from box import sdk
from box.providers import modal as box_modal
from box.providers.modal import Modal, ModalMachine, ModalToken, ProviderClosed

TOKEN = ModalToken("ak-fake", "as-fake")  # never used: nothing here opens a Modal client


@dataclass(frozen=True)
class Aio:
    """A Modal method's async interface: .aio(*args) is the coroutine."""

    aio: Callable[..., Awaitable[object]]


class Out:
    """A process's stdout or stderr: read.aio() (exec) or `async for` (stream)."""

    def __init__(self, chunks: list[bytes], *, hang: bool) -> None:
        self.chunks, self.hang = chunks, hang
        self.read = Aio(self._read)

    async def _read(self) -> str:
        return b"".join(self.chunks).decode()

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for c in self.chunks:
            yield c
        if self.hang:
            await anyio.sleep_forever()


class Process:
    def __init__(self, out: list[bytes], *, hang: bool = False) -> None:
        self.stdout, self.stderr = Out(out, hang=hang), Out([], hang=hang)
        self.wait = Aio(self._wait)

    async def _wait(self) -> int:
        return 0


class FakeSandbox:
    """exec: `echo <word>` prints word; `hang` never answers (recording that it was cancelled);
    `own-timeout` raises a TimeoutError of its own; a stream (text=False) of `follow` prints one chunk
    and then waits for more forever. poll: still running."""

    object_id = "sb-fake"
    returncode = None

    def __init__(self) -> None:
        self.exec = Aio(self._exec)
        self.poll = Aio(self._poll)
        self.cancelled: list[str] = []

    async def _exec(self, *argv: str, text: bool = True, timeout: int | None = None) -> Process:
        cmd = argv[-1]
        if not text:
            return Process([b"first\n"], hang="follow" in cmd)
        if cmd == "hang":
            try:
                await anyio.sleep_forever()
            finally:
                self.cancelled.append(cmd)
        if cmd == "own-timeout":
            raise TimeoutError("the call's own")
        return Process([cmd.removeprefix("echo ").encode() + b"\n"])

    async def _poll(self) -> int | None:
        return None


def machine(provider: Modal) -> tuple[ModalMachine, FakeSandbox]:
    sandbox = FakeSandbox()
    return ModalMachine(provider, sandbox, {}), sandbox  # type: ignore[arg-type]


def loop_tasks(provider: Modal) -> int:
    """Tasks on the provider's loop right now (the portal's own included)."""
    assert provider._portal is not None
    return provider._portal.call(lambda: len(asyncio.all_tasks()))


def test_a_call_from_inside_a_running_event_loop() -> None:
    """A Jupyter cell is a coroutine on a running loop; it calls box synchronously. asyncio.run per
    call (before) raised RuntimeError here; the portal's loop is another thread's, so it does not."""
    with Modal(token=TOKEN, region=None) as provider:
        m, _ = machine(provider)

        async def cell() -> tuple[tuple[int, str, str], list[tuple[str, bytes]]]:
            with m.stream("cat log", timeout_s=30) as s:
                return m.exec("echo hi"), list(s)

        assert asyncio.run(cell()) == ((0, "hi\n", ""), [("stdout", b"first\n")])


def test_a_hung_call_is_cancelled_at_its_bound(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(box_modal, "CALL_TIMEOUT_S", 0.2)
    monkeypatch.setattr(box_modal, "ENDING_S", 0.2)  # the sandbox still polls running: not Gone
    with Modal(token=TOKEN, region=None) as provider:
        m, sandbox = machine(provider)
        assert m.exec("echo up") == (0, "up\n", "")
        idle = loop_tasks(provider)
        with pytest.raises(TimeoutError, match="hung for 0 s; sandbox still reports running"):
            m.exec("hang")
        assert sandbox.cancelled == ["hang"]  # the call itself was cancelled, not abandoned
        assert loop_tasks(provider) == idle  # nothing left running on the loop
        with pytest.raises(TimeoutError, match="the call's own"):  # not mistaken for the bound's
            m.exec("own-timeout")


def test_close_cancels_an_open_stream_and_joins_the_thread(capsys: pytest.CaptureFixture[str]) -> None:
    before = set(threading.enumerate())
    provider = Modal(token=TOKEN, region=None)
    m, _ = machine(provider)
    stream = m.stream("follow log", timeout_s=30)
    chunks = iter(stream)
    assert next(chunks) == ("stdout", b"first\n")
    assert set(threading.enumerate()) - before  # the loop's thread and the stream's reader
    provider.close()  # the pump is waiting on Modal for more: cancelled, not waited out
    with pytest.raises(ProviderClosed, match="closed under a stream"):
        next(chunks)
    assert set(threading.enumerate()) == before  # the loop's thread joined, the reader too
    assert "killing a stream's command failed" in capsys.readouterr().err  # said, never silent


def test_a_closed_provider_and_its_machines_raise() -> None:
    before = set(threading.enumerate())
    with Modal(token=TOKEN, region=None) as provider:
        m, _ = machine(provider)
        m.exec("echo up")
    provider.close()  # idempotent
    with pytest.raises(ProviderClosed):
        provider.list()
    with pytest.raises(ProviderClosed):  # a machine outliving its provider: never a silent reopen
        m.exec("echo up")
    with pytest.raises(ProviderClosed):
        m.stream("cat log", timeout_s=30)
    with pytest.raises(ProviderClosed):  # a Session holds a Machine, never the provider
        sdk.Session(m).status()
    assert set(threading.enumerate()) == before


def test_no_thread_outlives_the_provider() -> None:
    """Every thread a Modal starts (its loop's, its streams' readers) is joined by close(); a
    provider never used starts none."""
    before = set(threading.enumerate())
    Modal(token=TOKEN, region=None).close()
    with Modal(token=TOKEN, region=None) as provider:
        m, _ = machine(provider)
        for _ in range(3):
            assert m.exec("echo up") == (0, "up\n", "")
            with m.stream("cat log", timeout_s=30) as s:
                assert list(s) == [("stdout", b"first\n")]
        during = set(threading.enumerate()) - before
        assert [t.name for t in during] == [f"box-modal-{id(provider):x}"]  # one loop thread, however many calls
    after = set(threading.enumerate())
    assert after == before, [t.name for t in after - before]
    assert not [t for t in after - before if t.daemon]
