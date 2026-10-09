"""The relay (box/gateway/relay.py), end to end over HTTP, on the local provider: a real supervisor, a
real Jupyter Server as the session's service, a real kernel. What the page sees, in seconds, no cloud.
`box/gateway/prove_modal.py` is the same story on a Modal T4."""

from __future__ import annotations

import json
import re
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from box import sdk
from box.gateway import kernel_client, relay
from box.providers.local import Local
from box.store import DirStore

TOKEN = {"id": "ak-relay-test", "secret": "as-relay-test-secret"}
AUTH = f"{TOKEN['id']}:{TOKEN['secret']}"
ORIGIN = "http://localhost:8012"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def make_relay(tmp_path: Path) -> Iterator[Callable[..., str]]:
    servers = []

    def make(idle_timeout_s: float = 300) -> str:
        cfg = relay.Config(
            access=lambda token: relay.Access(Local(tmp_path / "machines"), DirStore(tmp_path / "records")), image=None, gpus=(None,), labels={"box.purpose": "relay-test"},
            origins=re.compile(relay.LOCAL_ORIGIN), python=sys.executable, ip="127.0.0.1", port=free_port,
            idle_timeout_s=idle_timeout_s,
        )  # fmt: skip
        server = relay.serve(cfg, free_port())
        threading.Thread(target=server.serve_forever, daemon=True).start()
        servers.append(server)
        return f"http://127.0.0.1:{server.server_address[1]}"

    yield make
    for server in servers:
        server.shutdown()
        server.server_close()
    for m in Local(tmp_path / "machines").list():
        m.terminate()


def call(url: str, method: str = "GET", body: dict | None = None, headers: dict | None = None) -> tuple[int, dict, dict]:
    req = urllib.request.Request(url, method=method, data=None if body is None else json.dumps(body).encode(), headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, json.loads(r.read()), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read()), dict(e.headers)


def create(gw: str) -> str:
    code, body, _ = call(f"{gw}/sessions", "POST", {"provider": "modal", "token": TOKEN, "gpu": None, "labels": {"box.caller": "blogs"}}, {"Origin": ORIGIN})
    assert code == 202, body
    assert body["status"]["state"] == "booting"
    return body["session_id"]


def events(gw: str, sid: str, until: str, last_id: str | None = None, timeout_s: float = 120) -> list[tuple[str, dict]]:
    """(id, event) from the SSE stream until a status event in state `until` (inclusive)."""
    headers = {"Last-Event-ID": last_id} if last_id else {}
    req = urllib.request.Request(f"{gw}/sessions/{sid}/events?token={AUTH}", headers=headers)
    got, event_id = [], None
    give_up = time.monotonic() + timeout_s
    with urllib.request.urlopen(req, timeout=timeout_s) as r:
        assert r.headers["Content-Type"] == "text/event-stream"
        for raw in r:
            assert time.monotonic() < give_up, f"no {until} status in {timeout_s} s: {got}"
            line = raw.decode().rstrip("\n")
            if line.startswith("id: "):
                event_id = line[4:]
            elif line.startswith("data: "):
                event = json.loads(line[6:])
                got.append((event_id, event))
                if event["kind"] == "status" and event["status"]["state"] == until:
                    return got
    raise AssertionError(f"stream closed before a {until} status: {got}")


def status(gw: str, sid: str) -> tuple[int, dict]:
    code, body, _ = call(f"{gw}/sessions/{sid}", headers={"X-Box-Token": AUTH})
    return code, body.get("status", body)


def test_connect_run_a_cell_end(make_relay: Callable[..., str]) -> None:
    gw = make_relay()
    sid = create(gw)
    boot = events(gw, sid, "running")
    steps = [e["text"] for _, e in boot if e["kind"] == "step"]
    assert steps[0] == "checking your Modal token" and any("Jupyter Server ready" in s for s in steps), steps
    assert all(isinstance(e["t"], float) and e["t"] > 1.7e9 for _, e in boot)  # unix seconds
    assert any(e["kind"] == "log" for _, e in boot), "Jupyter's startup log streams as machine log events"
    code, running = status(gw, sid)
    assert code == 200 and running["state"] == "running" and running["gpu"] is None
    assert not running["kernel"]["url"].endswith("/")
    out = kernel_client.run(running["kernel"], "print(6 * 7)")
    assert (out.status, out.stdout) == ("ok", "42\n")
    code, body, _ = call(f"{gw}/sessions/{sid}/end", "POST", headers={"X-Box-Token": AUTH})
    assert (code, body["status"]["state"], body["status"]["reason"]) == (200, "ended", "stopped")
    assert status(gw, sid) == (200, body["status"])  # the machine is gone: its record answers
    assert status(gw, "s-000000000000")[0] == 404  # a session nobody recorded is unknown


def test_the_relay_keeps_nothing_a_running_session_needs(make_relay: Callable[..., str]) -> None:
    gw = make_relay()
    sid = create(gw)
    events(gw, sid, "running")
    before = status(gw, sid)[1]
    other = make_relay()  # a second relay, or this one restarted: no memory of the boot
    for g in (gw, other):
        assert status(g, sid) == (200, before)
    replay = events(other, sid, "running")
    assert [e["status"]["state"] for _, e in replay if e["kind"] == "status"] == ["running"]
    assert all(i.startswith("o") for i, _ in replay)
    out = kernel_client.run(before["kernel"], "import os; print('pid', os.getpid())")
    assert out.status == "ok"


def test_reconnecting_with_last_event_id_resumes_without_repeats(make_relay: Callable[..., str]) -> None:
    gw = make_relay()
    sid = create(gw)
    first = events(gw, sid, "running")
    again = events(gw, sid, "running", last_id=first[2][0])
    assert [e for _, e in again] == [e for _, e in first[3:]]


def test_unknown_session_wrong_token_and_bad_requests(make_relay: Callable[..., str]) -> None:
    gw = make_relay()
    assert status(gw, "s-000000000000")[0] == 404
    code, body, _ = call(f"{gw}/sessions/s-000000000000", headers={"X-Box-Token": "no-colon"})
    assert code == 400 and "id:secret" in body["error"]
    for bad in ({"provider": "runpod", "token": TOKEN, "gpu": None}, {"provider": "modal", "token": TOKEN, "gpu": "H100"},
                {"provider": "modal", "token": TOKEN, "gpu": None, "labels": {"box.session": "s-x"}}):  # fmt: skip
        assert call(f"{gw}/sessions", "POST", bad)[0] == 400, bad


def test_cors_answers_the_page_origin_only(make_relay: Callable[..., str]) -> None:
    gw = make_relay()
    _, _, ok = call(f"{gw}/sessions/s-000000000000", headers={"X-Box-Token": AUTH, "Origin": ORIGIN})
    _, _, evil = call(f"{gw}/sessions/s-000000000000", headers={"X-Box-Token": AUTH, "Origin": "https://evil.example"})
    assert ok["Access-Control-Allow-Origin"] == ORIGIN
    assert "Access-Control-Allow-Origin" not in evil


def test_a_session_nobody_uses_ends_idle(make_relay: Callable[..., str]) -> None:
    gw = make_relay(idle_timeout_s=3)
    sid = create(gw)
    got = events(gw, sid, "ended", timeout_s=60)  # the stream follows the machine until it ends
    assert got[-1][1]["status"]["reason"] == "idle"
    assert status(gw, sid) == (200, got[-1][1]["status"])


def test_after_the_machine_is_gone_the_record_answers_with_why_and_the_log(make_relay: Callable[..., str]) -> None:
    gw = make_relay()
    sid = create(gw)
    boot = events(gw, sid, "running")
    call(f"{gw}/sessions/{sid}/end", "POST", headers={"X-Box-Token": AUTH})
    after = events(make_relay(), sid, "ended")  # a relay with no memory of it either
    assert after[-1][1]["status"]["reason"] == "stopped"
    logged = [e["text"] for _, e in after if e["kind"] == "log"]
    assert [e["text"] for _, e in boot if e["kind"] == "log"] == logged[: len([1 for _, e in boot if e["kind"] == "log"])]
    assert any("Jupyter Server" in line for line in logged), logged


def test_a_stream_that_saw_the_boot_does_not_repeat_its_log_from_the_record(make_relay: Callable[..., str]) -> None:
    gw = make_relay()
    sid = create(gw)
    events(gw, sid, "running")
    call(f"{gw}/sessions/{sid}/end", "POST", headers={"X-Box-Token": AUTH})
    again = events(gw, sid, "ended")  # the boot from memory, then the record
    lines = [e["text"] for _, e in again if e["kind"] == "log"]
    assert lines and len(lines) == len(set(lines)), lines


def test_resuming_a_replay_from_the_record_sends_only_what_came_after(make_relay: Callable[..., str]) -> None:
    gw = make_relay()
    sid = create(gw)
    events(gw, sid, "running")
    call(f"{gw}/sessions/{sid}/end", "POST", headers={"X-Box-Token": AUTH})
    replay = events(gw, sid, "ended")  # the boot from memory, then the machine's part: from the record
    machine = [i for i, (event_id, e) in enumerate(replay) if e["kind"] == "log" and not event_id.startswith("b")]
    assert len(machine) >= 2, replay  # Jupyter's shutdown lines
    again = events(gw, sid, "ended", last_id=replay[machine[0]][0])
    lines = lambda got: [(e["stream"], e["text"]) for _, e in got if e["kind"] == "log"]  # noqa: E731
    assert lines(again) == lines(replay[machine[0] + 1 :])


def relay_on(tmp_path: Path, access: Callable[[object], relay.Access]) -> relay.Server:
    cfg = relay.Config(
        access=access, image=None, gpus=(None,), labels={"box.purpose": "relay-test"}, origins=re.compile(relay.LOCAL_ORIGIN),
        python=sys.executable, ip="127.0.0.1", port=free_port,
    )  # fmt: skip
    server = relay.serve(cfg, free_port())
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def test_a_readers_client_is_reused_bounded_and_closed(tmp_path: Path) -> None:
    made, closed = [], []

    def access(token: object) -> relay.Access:
        made.append(token)
        return relay.Access(Local(tmp_path / "machines"), DirStore(tmp_path / "records"), close=lambda: closed.append(token))

    server = relay_on(tmp_path, access)
    gw = f"http://127.0.0.1:{server.server_address[1]}"
    for _ in range(3):
        assert status(gw, "s-000000000000")[0] == 404
    assert (len(made), closed) == (1, [])  # one client for one reader, across requests
    for i in range(relay.MAX_CLIENTS):
        call(f"{gw}/sessions/s-000000000000", headers={"X-Box-Token": f"ak-{i}:as-{i}"})
    assert len(made) == relay.MAX_CLIENTS + 1
    assert closed == made[:1]  # the least recently used, to make room
    server.shutdown()
    server.server_close()
    assert sorted(map(repr, closed)) == sorted(map(repr, made))  # every one closed with the relay


def test_closing_the_relay_ends_a_boot_in_flight_and_joins_it(tmp_path: Path) -> None:
    server = relay_on(tmp_path, lambda token: relay.Access(Local(tmp_path / "machines"), DirStore(tmp_path / "records")))
    sid = create(f"http://127.0.0.1:{server.server_address[1]}")
    server.shutdown()
    server.server_close()  # returns once the boot thread has ended the session it was making
    assert Local(tmp_path / "machines").list({"box.session": sid}) == []
    assert not [t for t in threading.enumerate() if t.name == f"boot-{sid}"]


def test_a_body_length_that_is_not_a_byte_count_is_refused(make_relay: Callable[..., str]) -> None:
    gw = make_relay()
    for bad in ("-1", "ten", "1e3"):
        req = urllib.request.Request(f"{gw}/sessions", method="POST", data=b"{}", headers={"Content-Length": bad})
        with pytest.raises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(req, timeout=30)
        assert e.value.code == 400, bad


class Counted:
    """A provider whose machines note the time of every call made on them."""

    def __init__(self, inner: Local, calls: list[float]) -> None:
        self.inner, self.calls, self.name = inner, calls, inner.name

    def list(self, labels: dict[str, str] | None = None) -> list:
        return [CountedMachine(m, self.calls) for m in self.inner.list(labels)]

    def __getattr__(self, attr: str) -> object:
        return getattr(self.inner, attr)


class CountedMachine:
    def __init__(self, inner: object, calls: list[float]) -> None:
        self.inner, self.calls = inner, calls

    def __getattr__(self, attr: str) -> object:
        value = getattr(self.inner, attr)
        if attr in ("exec", "read", "write", "expose"):
            self.calls.append(time.monotonic())
        return value


def wait_running(gw: str, sid: str) -> None:
    """By GET, not a stream: a stream would poll on after we hang up (until its next ping)."""
    give_up = time.monotonic() + 60
    while status(gw, sid)[1]["state"] != "running":
        assert time.monotonic() < give_up
        time.sleep(0.5)


def test_an_idle_event_stream_asks_the_machine_twice_a_poll(tmp_path: Path) -> None:
    calls: list[float] = []
    server = relay_on(tmp_path, lambda token: relay.Access(Counted(Local(tmp_path / "machines"), calls), DirStore(tmp_path / "records")))
    gw = f"http://127.0.0.1:{server.server_address[1]}"
    sid = create(gw)
    wait_running(gw, sid)
    stream = threading.Thread(target=events, args=(gw, sid, "ended"), daemon=True)
    stream.start()  # replays the boot from memory, then follows the machine
    time.sleep(2 * relay.STREAM_POLL_S)  # past its first poll (which also finds the job, the tunnel)
    window_from = time.monotonic()
    time.sleep(3 * relay.STREAM_POLL_S)
    in_window = [t for t in calls if t >= window_from]
    call(f"{gw}/sessions/{sid}/end", "POST", headers={"X-Box-Token": AUTH})
    stream.join(timeout=60)
    server.shutdown()
    server.server_close()
    assert len(in_window) <= 2 * 4, f"{len(in_window)} calls in 3 polls"  # the session's status + one read of the log, per poll (4 polls fit)


class Vanishing(Counted):
    """A provider whose machine dies just as the relay asks for its tunnel, once `armed`."""

    armed = False

    def list(self, labels: dict[str, str] | None = None) -> list:
        return [VanishingMachine(m, self) for m in self.inner.list(labels)]


class VanishingMachine:
    def __init__(self, inner: object, provider: Vanishing) -> None:
        self.inner, self.provider = inner, provider

    def expose(self, port: int) -> object:
        if self.provider.armed:
            self.inner.terminate()
            raise sdk.Gone(self.inner.id)
        return self.inner.expose(port)

    def __getattr__(self, attr: str) -> object:
        return getattr(self.inner, attr)


def test_a_machine_gone_between_two_asks_is_ended_not_an_error(tmp_path: Path) -> None:
    provider = Vanishing(Local(tmp_path / "machines"), [])
    server = relay_on(tmp_path, lambda token: relay.Access(provider, DirStore(tmp_path / "records")))
    gw = f"http://127.0.0.1:{server.server_address[1]}"
    sid = create(gw)
    wait_running(gw, sid)
    provider.armed = True  # status() says Running, then the tunnel's machine is gone
    code, after = status(gw, sid)
    server.shutdown()
    server.server_close()
    assert (code, after["state"], after["reason"]) == (200, "ended", "machine_lost"), after
