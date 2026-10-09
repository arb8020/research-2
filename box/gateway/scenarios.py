"""Scenario harness: the same reader-path scenarios against any gateway variant, by base URL
(box/CONTRACT-gateway.md is all it speaks, plus a provider handle to kill a machine). Variants:

    A relay    (box/gateway/relay.py)           e.g. http://localhost:8790
    B do-owns  (box/gateway-do, OwnerDO)        e.g. https://box-gateway-do.<sub>.workers.dev/b
    C fanout   (box/gateway-do, FanoutDO)       e.g. https://box-gateway-do.<sub>.workers.dev/c

    cd box && uv run --extra dev python -m box.gateway.scenarios --provider modal \\
        --gw A=http://localhost:8790 --gw B=https://.../b --gw C=https://.../c --run live --out gateway-do/results/live.json
    ... --run deadline   # against stacks started with a short deadline + idle (scripts/up.sh DEADLINE_S=... IDLE_S=...)
    ... --run latency    # a T4 per variant: connect, nvidia-smi, per-cell RTT

Runs (variants in parallel, one thread each):
  live:     one CPU session per variant, reused: (3) two tabs, (2) reload + reattach, then (1) kill the
            machine mid-run (what the reader sees, do logs survive, recovery = a new session).
  deadline: (4) two CPU sessions per variant: one left alone (idle), one holding a kernel websocket
            (deadline): who ends each, why, and how late.
  latency:  (7) a T4 session per variant: connect time, first nvidia-smi, trivial-cell RTT, cost.
(5) token location and (6) code weight are static: box/gateway/static_facts.py.

Modal token: [arb8020] in ~/.modal.toml (never herdora; read here, never printed).
"""

from __future__ import annotations

import argparse
import contextlib
import http.client
import json
import socket
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlsplit

from websockets.sync.client import connect

from box import sdk
from box.gateway import kernel_client

T4_PER_S = 0.000164  # Modal list price, $/s (0.59 $/h)
CPU_PER_S = 0.0000131 * 1 + 0.00000222 * 1  # 1 physical core + ~1 GiB, $/s (Modal sandbox list prices; upper bound)
CONNECT_S = 15 * 60
MARKERS = 20
SILENT_WAIT_S = 75  # after a kill: B/C notice silence after SILENT_S (20 s) + one alarm; A after its next poll
LOCAL_TOKEN = {"id": "ak-local", "secret": "as-local"}


# ---- the contract, from Python ----


@dataclass(frozen=True)
class Gateway:
    name: str  # A | B | C
    url: str
    token: dict[str, str] = field(repr=False)

    @property
    def auth(self) -> str:
        return f"{self.token['id']}:{self.token['secret']}"

    def call(self, path: str, method: str = "GET", body: dict | None = None) -> tuple[int, dict]:
        req = urllib.request.Request(f"{self.url}{path}", method=method, data=None if body is None else json.dumps(body).encode(),
                                     headers={"X-Box-Token": self.auth, "Content-Type": "application/json"})  # fmt: skip
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")

    def create(self, gpu: str | None) -> str:
        code, body = self.call("/sessions", "POST", {"provider": "modal", "token": self.token, "gpu": gpu, "labels": {"box.caller": "scenarios"}})
        assert code == 202, (self.name, code, body)
        return body["session_id"]

    def status(self, sid: str) -> tuple[int, dict]:
        code, body = self.call(f"/sessions/{sid}")
        return code, body.get("status", body)

    def end(self, sid: str) -> tuple[int, dict]:
        return self.call(f"/sessions/{sid}/end", "POST")


class Tab:
    """One reader's event stream (an EventSource): every event with its id and local arrival time."""

    def __init__(self, gw: Gateway, sid: str, last_id: str | None = None) -> None:
        url = urlsplit(f"{gw.url}/sessions/{sid}/events?{urlencode({'token': gw.auth})}")
        conn_class = http.client.HTTPSConnection if url.scheme == "https" else http.client.HTTPConnection
        self.conn = conn_class(url.netloc, timeout=30)
        self.opened = time.monotonic()
        self.conn.request("GET", f"{url.path}?{url.query}", headers={"Last-Event-ID": last_id} if last_id else {})
        self.sock = self.conn.sock  # before getresponse: a response read to close detaches it from conn
        self.resp = self.conn.getresponse()
        self.code = self.resp.status
        self.sock.settimeout(None)  # a stream: quiet for as long as the session is
        self.events: list[tuple[str | None, dict, float]] = []  # (id, event, time.time() at arrival)
        self.first_at: float | None = None  # monotonic, the first event
        self.changed = threading.Condition()
        self.closed = False
        self.thread = threading.Thread(target=self._read, daemon=True)
        if self.code == 200:
            self.thread.start()

    def _read(self) -> None:
        """read1: whatever bytes have arrived (a fixed-size read would hold a lone event back)."""
        event_id, buf = None, b""
        try:
            while chunk := self.resp.read1(65536):
                *lines, buf = (buf + chunk).split(b"\n")
                for raw in (line.decode() for line in lines):
                    if raw.startswith("id: "):
                        event_id = raw[4:]
                    elif raw.startswith("data: "):
                        self._got(event_id, json.loads(raw[6:]))
        except (http.client.HTTPException, OSError, ValueError):
            pass  # closed under us (close()) or the stream broke
        with self.changed:
            self.closed = True
            self.changed.notify_all()

    def _got(self, event_id: str | None, event: dict) -> None:
        with self.changed:
            self.first_at = self.first_at or time.monotonic()
            self.events.append((event_id, event, time.time()))
            self.changed.notify_all()

    def wait(self, pred: Callable[[list[dict]], bool], timeout_s: float) -> bool:
        give_up = time.monotonic() + timeout_s
        with self.changed:
            while not pred([e for _, e, _ in self.events]):
                if time.monotonic() > give_up or self.closed:
                    return pred([e for _, e, _ in self.events])
                self.changed.wait(0.5)
        return True

    def last_id(self) -> str | None:
        return next((i for i, _, _ in reversed(self.events) if i is not None), None)

    def markers(self, tag: str) -> list[tuple[int, float, float]]:
        """(n, machine time, arrival time) of each 'tag-<n>-<machine unix time>' log line."""
        out = []
        for _, e, at in self.events:
            text = e.get("text", "")
            if e["kind"] == "log" and text.startswith(f"{tag}-"):
                _, n, ts = text.rsplit("-", 2)
                out.append((int(n), float(ts), at))
        return out

    def close(self) -> None:
        """Hang up, as a closed tab does. shutdown, not close: it wakes the reader blocked in read1
        (a stream whose server ended it without closing the connection never sends EOF)."""
        with contextlib.suppress(OSError):
            self.sock.shutdown(socket.SHUT_RDWR)
        if self.code == 200:
            self.thread.join(timeout=10)
        self.conn.close()


def state_is(state: str) -> Callable[[list[dict]], bool]:
    return lambda es: any(e["kind"] == "status" and e["status"]["state"] == state for e in es)


def last_status(events: list[dict]) -> dict | None:
    return next((e["status"] for e in reversed(events) if e["kind"] == "status"), None)


def boot(gw: Gateway, gpu: str | None) -> tuple[str, dict, float]:
    """Create and follow until running: (sid, running status, seconds from POST)."""
    t0 = time.monotonic()
    sid = gw.create(gpu)
    tab = Tab(gw, sid)
    ok = tab.wait(lambda es: state_is("running")(es) or state_is("ended")(es), CONNECT_S)
    tab.close()
    status = last_status([e for _, e, _ in tab.events])
    assert ok and status is not None and status["state"] == "running", (gw.name, sid, status, [e for _, e, _ in tab.events][-5:])
    return sid, status, time.monotonic() - t0


# ---- machine-side actions, through the kernel ----

MARK_CODE = """
import os, time
with open(os.environ['BOX_JOB_DIR'] + '/stdout', 'a', buffering=1) as f:
    for i in range({n}):
        f.write(f'{tag}-{{i}}-{{time.time():.3f}}\\n'); time.sleep({gap})
"""


def write_markers(kernel: dict, tag: str, n: int, gap: float = 0.1) -> None:
    """n lines in the machine's log (Jupyter's own stdout, which the kernel inherits as BOX_JOB_DIR)."""
    out = kernel_client.run(kernel, MARK_CODE.format(n=n, tag=tag, gap=gap))
    assert out.status == "ok", out


def clock_offset(kernel: dict) -> float:
    """machine clock - this clock (s), NTP-style off one cell: the print is taken at the RTT's middle."""
    out = kernel_client.run(kernel, "import time; print(time.time())")
    t_end = time.time()
    return float(out.stdout) - (t_end - out.seconds / 2)


def pct(xs: list[float], p: float) -> float | None:
    s = sorted(xs)
    return round(s[min(len(s) - 1, int(p / 100 * len(s)))], 3) if s else None


# ---- killing a machine (scenario 1): the provider, not the gateway ----


def killer(provider: str, token: dict[str, str]) -> Callable[[str], None]:
    if provider == "local":
        from box.gateway.local_stack import MACHINES
        from box.local_provider import Local

        return lambda sid: [m.terminate() for m in Local(MACHINES).list({sdk.LABEL_SESSION: sid})]  # type: ignore[func-returns-value]
    from box.modal_provider import Modal, ModalToken

    modal = Modal(token=ModalToken(token["id"], token["secret"]), region="us")
    return lambda sid: sdk.attach(modal, sid).machine.terminate()


# ---- runs ----


@dataclass
class Ledger:
    """Every session a run made: (variant, gpu, seconds alive), for the cost line."""

    rows: list[tuple[str, str | None, float]] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def add(self, variant: str, gpu: str | None, seconds: float) -> None:
        with self.lock:
            self.rows.append((variant, gpu, round(seconds, 1)))

    def dollars(self, variant: str) -> float:
        return round(sum(s * (T4_PER_S if gpu else CPU_PER_S) for v, gpu, s in self.rows if v == variant), 4)


def two_tabs(gw: Gateway, sid: str, kernel: dict, offset: float) -> tuple[dict, Tab, Tab]:
    """(3): two readers, one stream of machine log lines. Latency: machine write -> arrival here."""
    tabs = Tab(gw, sid), Tab(gw, sid)
    for t in tabs:
        assert t.wait(state_is("running"), 60), (gw.name, "tab never saw running")
    write_markers(kernel, "two", MARKERS)
    for t in tabs:
        t.wait(lambda _es, t=t: len(t.markers("two")) >= MARKERS, 30)
    seen = [t.markers("two") for t in tabs]
    lat = [[(at - (ts - offset)) * 1000 for _, ts, at in m] for m in seen]
    return {
        "both_saw_all": all([n for n, _, _ in m] == list(range(MARKERS)) for m in seen),
        "same_order": [n for n, _, _ in seen[0]] == [n for n, _, _ in seen[1]],
        "lat_ms_p50": [pct(x, 50) for x in lat], "lat_ms_max": [pct(x, 100) for x in lat],
    }, *tabs  # fmt: skip


def reattach(gw: Gateway, sid: str, kernel: dict, tab: Tab) -> dict:
    """(2): a tab drops, 5 lines are written, it comes back with Last-Event-ID; then a reload (no id)."""
    last = tab.last_id()
    tab.close()
    write_markers(kernel, "gap", 5)
    time.sleep(3)  # the lines are on the machine (and, for B/C, pushed) before the tab returns
    back = Tab(gw, sid, last_id=last)
    back.wait(lambda _es: len(back.markers("gap")) >= 5, 30)
    gap_done = time.monotonic()
    reload = Tab(gw, sid)
    reload.wait(lambda _es: len(reload.markers("two")) >= MARKERS and len(reload.markers("gap")) >= 5, 30)
    reload_done = time.monotonic()
    get_ms = []
    for _ in range(5):
        t0 = time.monotonic()
        assert gw.status(sid)[0] == 200
        get_ms.append((time.monotonic() - t0) * 1000)
    out = {
        "resume_code": back.code, "resume_first_event_ms": None if back.first_at is None else round((back.first_at - back.opened) * 1000),
        "resume_gap_lines": [n for n, _, _ in back.markers("gap")], "resume_repeats": len(back.markers("two")),
        "resume_all_gap_ms": round((gap_done - back.opened) * 1000),
        "reload_replayed": {"two": len(reload.markers("two")), "gap": len(reload.markers("gap"))},
        "reload_full_replay_ms": round((reload_done - reload.opened) * 1000), "get_ms_p50": pct(get_ms, 50),
    }  # fmt: skip
    back.close()
    reload.close()
    return out


def machine_dies(gw: Gateway, sid: str, kernel: dict, tab: Tab, kill: Callable[[str], None]) -> dict:
    """(1): a cell is writing log lines; the machine is terminated (no hooks, no goodbye)."""
    threading.Thread(target=lambda: _quietly(lambda: write_markers(kernel, "run", 600, gap=0.5)), daemon=True).start()
    tab.wait(lambda _es: len(tab.markers("run")) >= 4, 60)
    killed_at = time.time()
    kill(sid)
    tab.wait(state_is("ended"), SILENT_WAIT_S)
    seen = [(round(at - killed_at, 1), e) for _, e, at in tab.events if at > killed_at and e["kind"] != "log"]
    code, after = gw.status(sid)
    fresh = Tab(gw, sid)
    time.sleep(5)
    fresh.close()
    tab.close()
    return {
        "reader_saw": [{"after_s": s, "kind": e["kind"], "what": e.get("text") or e.get("status")} for s, e in seen],
        "run_lines_before_kill": len([m for m in tab.markers("run") if m[2] < killed_at]),
        "get_after": {"code": code, "status": after},
        "fresh_tab": {"code": fresh.code, "run_lines_replayed": len(fresh.markers("run")), "events": len(fresh.events)},
    }


def say(gw: Gateway, text: str) -> None:
    print(f"[{gw.name} {time.strftime('%H:%M:%S')}] {text}", flush=True)


def _quietly(fn: Callable[[], None]) -> None:
    try:
        fn()
    except Exception as e:  # noqa: BLE001 (the machine was killed under this cell: expected)
        print(f"  (mid-run cell ended: {type(e).__name__})", flush=True)


def run_live(gw: Gateway, kill: Callable[[str], None], ledger: Ledger) -> dict:
    created = time.monotonic()
    sid, running, connect_s = boot(gw, None)
    kernel = running["kernel"]
    offset = clock_offset(kernel)
    out: dict[str, Any] = {"session": sid, "connect_cpu_s": round(connect_s, 1), "clock_offset_s": round(offset, 3)}
    say(gw, f"running {sid} in {connect_s:.1f} s")
    out["two_tabs"], tab1, tab2 = two_tabs(gw, sid, kernel, offset)
    say(gw, f"two tabs: {out['two_tabs']}")
    out["reattach"] = reattach(gw, sid, kernel, tab1)
    say(gw, f"reattach: {out['reattach']}")
    out["machine_dies"] = machine_dies(gw, sid, kernel, tab2, kill)
    say(gw, "machine killed; recovering")
    ledger.add(gw.name, None, time.monotonic() - created)
    t0 = time.monotonic()
    sid2, _, connect2 = boot(gw, None)
    out["recovery"] = {"new_session": sid2, "connect_s": round(connect2, 1), "end": gw.end(sid2)[1].get("status", {}).get("reason")}
    ledger.add(gw.name, None, time.monotonic() - t0)
    return out


def hold_kernel(kernel: dict, stop: threading.Event) -> None:
    """An open kernel websocket, as the page keeps: connections to Jupyter are not idle."""
    url = kernel_client.api(kernel, f"/api/kernels/{kernel_client.kernel_id(kernel)}/channels").replace("http", "ws", 1)
    with connect(url, open_timeout=60, ping_interval=20):
        stop.wait()


def run_deadline(gw: Gateway, ledger: Ledger) -> dict:
    """(4): one session left alone, one held by a kernel websocket. Who ends each, why, how late."""

    def one(hold: bool) -> dict:
        created = time.monotonic()
        sid, running, _ = boot(gw, None)
        running_at = time.time()
        stop = threading.Event()
        if hold:
            threading.Thread(target=lambda: _quietly(lambda: hold_kernel(running["kernel"], stop)), daemon=True).start()
        tab = Tab(gw, sid)
        tab.wait(state_is("ended"), running["deadline"] - time.time() + 300)
        stop.set()
        tab.close()
        ended = [(e, at) for _, e, at in tab.events if e["kind"] == "status" and e["status"]["state"] == "ended"]
        ledger.add(gw.name, None, time.monotonic() - created)
        if not ended:
            return {"session": sid, "held": hold, "ended": False}
        e, at = ended[0]
        steps = [e["text"] for _, e, a in tab.events if e["kind"] == "step" and a >= at - 60]
        return {"session": sid, "held": hold, "reason": e["status"]["reason"], "ended_after_running_s": round(at - running_at, 1),
                "late_vs_deadline_s": round(at - running["deadline"], 1), "steps_near_end": steps[-4:]}  # fmt: skip

    with ThreadPoolExecutor(2) as pool:
        idle, held = pool.map(one, (False, True))
    return {"idle": idle, "deadline": held}


def run_latency(gw: Gateway, ledger: Ledger, gpu: str) -> dict:
    """(7): connect to running (POST -> running status), first cell (kernel start + nvidia-smi), RTTs."""
    created = time.monotonic()
    sid, running, connect_s = boot(gw, gpu)
    kernel = running["kernel"]
    t0 = time.monotonic()
    smi = kernel_client.run(kernel, "!nvidia-smi --query-gpu=name --format=csv,noheader")
    first_cell_s = time.monotonic() - t0
    assert smi.status == "ok" and gpu in smi.stdout, smi
    rtt = [kernel_client.run(kernel, "1").seconds * 1000 for _ in range(20)]
    t0 = time.monotonic()
    code, ended = gw.end(sid)
    end_s = time.monotonic() - t0
    ledger.add(gw.name, gpu, time.monotonic() - created)
    return {
        "session": sid, "gpu_seen": smi.stdout.strip(), "connect_s": round(connect_s, 1), "first_cell_s": round(first_cell_s, 2),
        "cell_rtt_ms_p50": pct(rtt, 50), "cell_rtt_ms_p90": pct(rtt, 90), "end_s": round(end_s, 1),
        "end": {"code": code, "reason": ended.get("status", {}).get("reason")},
    }  # fmt: skip


def modal_token() -> dict[str, str]:
    from box.gateway.prove_modal import token

    return token()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--gw", action="append", required=True, type=lambda s: tuple(s.split("=", 1)), help="NAME=URL (repeat)")
    ap.add_argument("--provider", choices=("modal", "local"), default="modal")
    ap.add_argument("--run", choices=("live", "deadline", "latency"), required=True)
    ap.add_argument("--gpu", default="T4", help="latency run's GPU")
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    token = modal_token() if a.provider == "modal" else LOCAL_TOKEN
    gws = [Gateway(name, url.rstrip("/"), token) for name, url in a.gw]
    kill = killer(a.provider, token)
    ledger = Ledger()
    runs: dict[str, Callable[[Gateway], dict]] = {
        "live": lambda gw: run_live(gw, kill, ledger), "deadline": lambda gw: run_deadline(gw, ledger),
        "latency": lambda gw: run_latency(gw, ledger, a.gpu),
    }  # fmt: skip

    def one(gw: Gateway) -> dict:
        try:
            return {"url": gw.url, **runs[a.run](gw)}
        except Exception as e:  # noqa: BLE001 (one variant failing must not hide the others' results)
            return {"url": gw.url, "error": f"{type(e).__name__}: {e}"}

    started = time.time()
    with ThreadPoolExecutor(len(gws)) as pool:
        results = dict(zip([g.name for g in gws], pool.map(one, gws), strict=True))
    for gw in gws:
        results[gw.name]["modal_usd"] = ledger.dollars(gw.name)
    report = {"run": a.run, "provider": a.provider, "started": started, "seconds": round(time.time() - started), "variants": results, "sessions": ledger.rows}
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
