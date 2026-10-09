"""The relay with --push (variants B and C): its boot events and the machine's forwarder reach a
fan-out. Here the fan-out is a stub HTTP server that records what each push carried; the real one
(box/gateway-do, a Worker + Durable Object) is tested against this same relay in scenarios.py."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import sys
import threading
import time
from collections.abc import Callable, Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from box import sdk
from box.gateway import kernel_client, relay
from box.gateway.push import Push
from box.local_provider import Local
from box.store import DirStore
from box.tests.test_relay import AUTH, call, create, free_port, status

SECRET = bytes(range(32))


class Fanout:
    """A stand-in fan-out: checks each push's key, keeps every event per session, in arrival order."""

    def __init__(self) -> None:
        self.events: dict[str, list[dict]] = {}
        self.pushes: dict[str, int] = {}
        self.changed = threading.Condition()
        fan = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_: object) -> None:
                pass

            def do_POST(self) -> None:
                m = re.fullmatch(r"/sessions/(s-[0-9a-f]{12})/push", self.path)
                body = self.rfile.read(int(self.headers["Content-Length"]))
                want = hmac.new(SECRET, f"push:{m and m[1]}".encode(), hashlib.sha256).hexdigest()
                ok = m is not None and hmac.compare_digest(self.headers.get("X-Push-Key", ""), want)
                if ok:
                    with fan.changed:
                        fan.events.setdefault(m[1], []).extend(json.loads(line) for line in body.decode().splitlines() if line)
                        fan.pushes[m[1]] = fan.pushes.get(m[1], 0) + 1
                        fan.changed.notify_all()
                self.send_response(200 if ok else 401)
                self.send_header("Content-Length", "0")
                self.end_headers()

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def wait_for(self, sid: str, pred: Callable[[list[dict]], bool], timeout_s: float = 60) -> list[dict]:
        give_up = time.monotonic() + timeout_s
        with self.changed:
            while not pred(got := list(self.events.get(sid, []))):
                assert time.monotonic() < give_up, f"{sid}: not seen in {timeout_s} s: {got[-5:]}"
                self.changed.wait(0.5)
        return got


def ended(events: list[dict]) -> bool:
    return any(e["kind"] == "status" and e["status"]["state"] == "ended" for e in events)


def running(events: list[dict]) -> bool:
    return any(e["kind"] == "status" and e["status"]["state"] == "running" for e in events)


@pytest.fixture
def pushing_relay(tmp_path: Path) -> Iterator[Callable[..., tuple[str, Fanout]]]:
    made = []

    def make(idle_timeout_s: float = 300) -> tuple[str, Fanout]:
        fan = Fanout()
        push = Push(fan.url, SECRET).start()
        cfg = relay.Config(
            access=lambda token: relay.Access(Local(tmp_path / "machines"), DirStore(tmp_path / "records")), image=None, gpus=(None,), labels={"box.purpose": "relay-test"},
            origins=re.compile(relay.LOCAL_ORIGIN), python=sys.executable, ip="127.0.0.1", port=free_port,
            idle_timeout_s=idle_timeout_s, push=push,
        )  # fmt: skip
        server = relay.serve(cfg, free_port())
        threading.Thread(target=server.serve_forever, daemon=True).start()
        made.append((server, push, fan))
        return f"http://127.0.0.1:{server.server_address[1]}", fan

    yield make
    for server, push, fan in made:
        server.shutdown()
        push.close()
        fan.server.shutdown()
    for m in Local(tmp_path / "machines").list():
        m.terminate()
    relay.BOOTS.clear()


def test_boot_then_machine_log_then_end_reach_the_fanout(pushing_relay: Callable[..., tuple[str, Fanout]]) -> None:
    gw, fan = pushing_relay()
    sid = create(gw)
    boot = fan.wait_for(sid, running)
    steps = [e["text"] for e in boot if e["kind"] == "step"]
    assert steps[0] == "checking your Modal token" and any("forwarder started" in s for s in steps), steps
    kernel = next(e["status"]["kernel"] for e in boot if e["kind"] == "status" and e["status"]["state"] == "running")
    # a line in Jupyter's own output (the kernel inherits BOX_JOB_DIR): the machine log, pushed by the forwarder
    out = kernel_client.run(kernel, "import os; open(os.environ['BOX_JOB_DIR'] + '/stdout', 'a').write('marker-17\\n')")
    assert out.status == "ok", out
    got = fan.wait_for(sid, lambda es: any(e.get("text") == "marker-17" for e in es), timeout_s=10)
    assert [e for e in got if e.get("text") == "marker-17"][0]["source"] == "machine"
    code, body, _ = call(f"{gw}/sessions/{sid}/end", "POST", headers={"X-Box-Token": AUTH})
    assert code == 200, body
    last = fan.wait_for(sid, ended, timeout_s=30)[-1]
    assert last["kind"] == "status" and last["status"]["reason"] == "stopped", last
    assert last["status"]["gpu"] is None and last["status"]["deadline"] > time.time()


def test_a_quiet_machine_heartbeats(pushing_relay: Callable[..., tuple[str, Fanout]]) -> None:
    gw, fan = pushing_relay()
    sid = create(gw)
    fan.wait_for(sid, running)
    before = fan.pushes[sid]
    time.sleep(11)  # two heartbeats (forwarder.HEARTBEAT_S = 5)
    assert fan.pushes[sid] - before >= 2, (before, fan.pushes[sid])


def test_idle_end_is_pushed_with_its_reason(pushing_relay: Callable[..., tuple[str, Fanout]]) -> None:
    gw, fan = pushing_relay(idle_timeout_s=3)
    sid = create(gw)
    last = fan.wait_for(sid, ended, timeout_s=60)[-1]
    assert last["status"]["reason"] == "idle", last
    # the relay agrees at once: its Jupyter is done (the supervisor wrote why before the forwarder's
    # final push), even while the supervisor has not written ended.json yet
    code, after = status(gw, sid)
    assert (code, after["state"], after["reason"]) == (200, "ended", "idle"), after


def test_a_session_whose_jupyter_died_says_ended_not_booting(pushing_relay: Callable[..., tuple[str, Fanout]], tmp_path: Path) -> None:
    gw, fan = pushing_relay()
    sid = create(gw)
    fan.wait_for(sid, running)
    jupyter = sdk.attach(Local(tmp_path / "machines"), sid).jobs()[0]
    jupyter.kill()  # the forwarder (a service too) keeps the released session alive: supervisor up, Jupyter gone
    jupyter.wait()
    code, after = status(gw, sid)
    assert (code, after["state"], after["reason"]) == (200, "ended", "machine_lost"), after


def test_a_terminated_machine_goes_silent(pushing_relay: Callable[..., tuple[str, Fanout]], tmp_path: Path) -> None:
    gw, fan = pushing_relay()
    sid = create(gw)
    fan.wait_for(sid, running)
    (machine,) = Local(tmp_path / "machines").list({"box.session": sid})
    machine.terminate()  # no hooks, no SIGTERM to the forwarder: nothing more is pushed
    time.sleep(1)
    count = fan.pushes[sid]
    time.sleep(6)
    assert fan.pushes[sid] == count
    assert not ended(fan.events[sid])
