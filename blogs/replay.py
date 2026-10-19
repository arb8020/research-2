"""Connect, workspace cells and nn-fit's remote runs, in two tiers.

    uv run --with playwright replay.py fast                   recorded streams replayed into the built pages (seconds)
    uv run --with playwright replay.py slow [--record]        one local relay, one CPU session, the real path in order;
                                                              re-records the streams and fails on drift from fixtures/replay/
    uv run --with playwright replay.py slow --gateway URL     the same real path on a running relay (Modal: a T4,
                                                              nvidia-smi; start it with short leases: --lease-min-s 2
                                                              --lease-default-s 20 --lease-max-s 60 --ceiling-s 60)
"""

from __future__ import annotations

import argparse
import contextlib
import difflib
import functools
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit
from urllib.request import Request, urlopen

from playwright.sync_api import Browser, Page, Route, WebSocketRoute, sync_playwright

from local_relay import api, relay, wait_limits

HERE = Path(__file__).resolve().parent
FIXTURES = HERE / "fixtures" / "replay"
OUT = HERE / ".evidence" / "replay"
CHROME = sorted(glob.glob(os.path.expanduser(
    "~/Library/Caches/ms-playwright/chromium-*/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing")))[-1]  # fmt: skip
GATEWAY = "http://127.0.0.1:9"
KERNEL = f"{GATEWAY}/kernel"
TOKEN = ("ak-replay", "as-replay-secret")
CORS = {"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Headers": "Content-Type, X-Box-Token, Last-Event-ID",
        "Access-Control-Allow-Methods": "GET, POST, PUT, OPTIONS"}  # fmt: skip
TIMES = ("t", "started_at", "lease_until", "ceiling")
SLOW_LIMITS = ("--lease-min-s", "2", "--lease-default-s", "20", "--lease-max-s", "35", "--ceiling-s", "35", "--idle-timeout-s", "35")
DEFAULT_LIMITS = {"lease": {"min_s": 60, "max_s": 43200, "default_s": 5400}, "ceiling_s": 43200, "gpus": [None, "T4", "L4", "A10G"]}
PAGES = {"connect": "dl/neural-nets.md", "workspace": "engine/ch00-toy.md", "ch01": "engine/ch01-forward.md"}
VOLATILE = {"msg_id", "date", "session", "username", "token", "t", "id", "session_id", "url", "banner", "execution_state", "connections", "last_activity"}
ID = re.compile(r"[0-9a-f]{8}-[0-9a-f-]{27}|\b(?=[0-9a-f]*\d)[0-9a-f]{7,}\b|local-\w+|s-\w{12}|(?:/[\w.@+-]+){2,}|-?\d+(?:\.\d+)?(?:e[-+]?\d+)?")


def check(ok: bool, what: str) -> None:
    if not ok:
        raise AssertionError(f"FAIL {what}")
    print(f"ok   {what}", flush=True)


class Quiet(SimpleHTTPRequestHandler):
    def log_message(self, fmt: str, *args: object) -> None:
        pass


@contextlib.contextmanager
def serve_dist() -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=str(HERE / "dist")))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://localhost:{server.server_address[1]}"
    finally:
        server.shutdown()


def build(*names: str) -> None:
    subprocess.run(["uv", "run", "build_page.py", *(PAGES[n] for n in names)], cwd=HERE, check=True, stdout=subprocess.DEVNULL)


def page_url(base: str, name: str, gateway: str = GATEWAY) -> str:
    return f"{base}/{Path(PAGES[name]).stem}/?gateway={gateway}"


def load(name: str) -> list[dict[str, Any]]:
    return [json.loads(line) for line in (FIXTURES / f"{name}.jsonl").read_text().splitlines()]


def rows_of(rows: list[dict[str, Any]], key: str) -> list[Any]:
    return [r[key] for r in rows if key in r]


def code_key(code: str) -> str:
    return "\n".join(ID.sub("#", line)[:100] for line in code.splitlines()[:3])


def shifted(obj: Any, by: float) -> Any:
    if isinstance(obj, dict):
        out = {k: (v + by if k in TIMES and isinstance(v, int | float) else shifted(v, by)) for k, v in obj.items()}
        if isinstance(out.get("kernel"), dict):
            out["kernel"] = {**out["kernel"], "url": KERNEL}
        return out
    return [shifted(v, by) for v in obj] if isinstance(obj, list) else obj


class Session:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        create = rows_of(rows, "create")[0]["response"]
        self.id: str = create["session_id"]
        self.by = time.time() - create["status"]["started_at"]
        self.create = shifted(create, self.by)
        self.events = shifted(rows_of(rows, "event"), self.by)
        self.extends = iter(shifted(rows_of(rows, "extend"), self.by))
        self.ends = shifted(rows_of(rows, "end"), self.by)
        running = next((i for i, e in enumerate(self.events) if e["kind"] == "status" and e["status"]["state"] == "running"), len(self.events))
        self.hold = next((i for i in range(running + 1, len(self.events)) if self.events[i]["kind"] == "status"), len(self.events))
        self.latest = self.create["status"]

    def sse(self, last: str | None) -> str:
        start = int(last[1:]) + 1 if last else 0
        for e in self.events[start : self.hold]:
            if e["kind"] == "status":
                self.latest = e["status"]
        return "retry: 200\n\n" + "".join(f"id: r{i}\ndata: {json.dumps(e)}\n\n" for i, e in enumerate(self.events[start : self.hold], start))

    def extend(self) -> dict[str, Any]:
        got: dict[str, Any] = next(self.extends)["response"]
        self.latest = got["status"]
        return got

    def push(self, status: dict[str, Any]) -> None:
        self.events.insert(self.hold, {"t": time.time(), "kind": "status", "status": status})
        self.hold += 1


class Replay:
    def __init__(self, page: Page, kernel: tuple[str, ...] = ("scratch",), sessions: tuple[str, ...] = (), limits: dict | None = None) -> None:
        self.queue = list(sessions)
        self.limits = limits or rows_of(load("session"), "limits")[0]
        self.sessions: dict[str, Session] = {}
        self.posts: list[dict[str, Any]] = []
        self.extends: list[dict[str, Any]] = []
        self.on_get: Callable[[dict], dict] = lambda body: body
        rows = [r for name in kernel for r in load(name)]
        self.info = rows_of(rows, "info")[0] if rows else []
        self.listed = (rows_of(rows, "kernels") or [[]])[0]
        self.made = (rows_of(rows, "kernel") or [{"id": "k"}])[0]
        self.contents = {c["path"]: (c["status"], c["body"]) for c in rows_of(rows, "contents")}
        self.exchanges = rows_of(rows, "exchange")
        self.used: set[int] = set()
        self.held: list[tuple[WebSocketRoute, dict, list[dict], str]] = []
        self.errors: list[str] = []
        page.route(f"{GATEWAY}/**", self.http)
        page.route_web_socket(re.compile(r"^ws://127\.0\.0\.1:9/"), self.socket)

    @property
    def session(self) -> Session:
        return next(reversed(self.sessions.values()))

    def release(self) -> None:
        self.session.hold = len(self.session.events)

    def http(self, route: Route) -> None:
        req = route.request
        url = urlsplit(req.url)
        if req.method == "OPTIONS":
            route.fulfill(status=204, headers=CORS)
            return
        if url.path.startswith("/kernel/"):
            self.kernel_http(route, url.path.removeprefix("/kernel"))
            return
        parts = url.path.strip("/").split("/")
        sid = parts[1] if len(parts) > 1 else ""
        if parts == ["sessions", sid, "events"]:
            route.fulfill(status=200, headers={**CORS, "Content-Type": "text/event-stream"}, body=self.sessions[sid].sse(req.headers.get("last-event-id")))
            return
        body: Any
        if parts == ["limits"]:
            body = self.limits
        elif parts == ["sessions"]:
            self.posts.append(req.post_data_json)
            s = Session(load(self.queue.pop(0) if self.queue else "session"))
            self.sessions[s.id] = s
            body = s.create
        elif sid not in self.sessions:
            route.fulfill(status=404, headers=CORS, json={"error": f"no session {sid}"})
            return
        elif parts == ["sessions", sid]:
            body = self.on_get({"session_id": sid, "status": self.sessions[sid].latest})
        elif parts[2:] == ["extend"]:
            self.extends.append(req.post_data_json)
            body = self.sessions[sid].extend()
        else:
            body = self.sessions[sid].ends[0]
        route.fulfill(status=200, headers=CORS, json=body)

    def kernel_http(self, route: Route, path: str) -> None:
        req = route.request
        if path == "/api/kernels":
            if req.method == "POST":
                self.listed = [self.made]
            route.fulfill(status=200, headers=CORS, json=self.made if req.method == "POST" else self.listed)
        elif path.endswith("/interrupt"):
            self.wake("interrupt")
            route.fulfill(status=204, headers=CORS)
        elif path.startswith("/api/contents/"):
            name = unquote(path.removeprefix("/api/contents/"))
            if req.method == "PUT":
                model = req.post_data_json
                if model["type"] == "file" and model["format"] == "text":
                    self.contents[name] = (200, {"type": "file", "format": "text", "content": model["content"]})
                route.fulfill(status=201, headers=CORS, json={})
            else:
                status, body = self.contents.get(name, (404, {"message": f"No such file: {name}"}))
                route.fulfill(status=status, headers=CORS, json=body)
        else:
            route.fulfill(status=200, headers=CORS, json={})

    def socket(self, ws: WebSocketRoute) -> None:
        ws.on_message(lambda raw: self.message(ws, json.loads(raw)))

    def message(self, ws: WebSocketRoute, msg: dict[str, Any]) -> None:
        head = msg["header"]
        if head["msg_type"] == "kernel_info_request":
            self.play(ws, head, [{**r, "channel": msg["channel"]} if r["header"]["msg_type"] == "kernel_info_reply" else r for r in self.info])
            return
        key = code_key(msg["content"].get("code", ""))
        found = [i for i, x in enumerate(self.exchanges) if x["key"] == key]
        if not found:
            self.errors.append(f"no recorded exchange for {key!r}")
            self.play(ws, head, [{"header": {"msg_type": "execute_reply"}, "channel": "shell", "content": {"status": "error", "ename": "Replay", "evalue": f"not recorded: {key!r}", "traceback": []}},
                                 {"header": {"msg_type": "status"}, "channel": "iopub", "content": {"execution_state": "idle"}}])  # fmt: skip
            return
        i = next((i for i in found if i not in self.used), found[0])
        self.used.add(i)
        self.play(ws, head, self.exchanges[i]["replies"])
        self.wake(key)

    def play(self, ws: WebSocketRoute, head: dict[str, Any], replies: list[dict[str, Any]]) -> None:
        for n, r in enumerate(replies):
            if "await" in r:
                self.held.append((ws, head, replies[n + 1 :], r["await"]))
                return
            ws.send(json.dumps({**r, "header": {**r["header"], "msg_id": uuid.uuid4().hex}, "parent_header": head, "metadata": {}, "buffers": []}))

    def wake(self, key: str) -> None:
        for held in [h for h in self.held if h[3] == key]:
            self.held.remove(held)
            self.play(*held[:3])


class Recorder:
    def __init__(self, page: Page, gateway: str) -> None:
        self.gateway = gateway
        self.frames: list[tuple[str, str, Any]] = []
        self.rows: dict[str, list[dict[str, Any]]] = {}
        self.name = "session"
        page.on("websocket", lambda ws: (ws.on("framesent", lambda p: self.frames.append((self.name, "sent", json.loads(p)))),
                                         ws.on("framereceived", lambda p: self.frames.append((self.name, "recv", json.loads(p))))))  # fmt: skip
        page.on("request", lambda r: self.frames.append((self.name, "interrupt", None)) if r.url.split("?")[0].endswith("/interrupt") else None)
        page.on("response", self.response)

    def add(self, name: str, row: dict[str, Any]) -> None:
        self.rows.setdefault(name, []).append(row)

    @contextlib.contextmanager
    def scenario(self, name: str, page: Page) -> Iterator[None]:
        self.name = name
        try:
            yield
        finally:
            sent = {m["header"]["msg_id"] for _, kind, m in self.frames if kind == "sent" and m["header"]["msg_type"] == "execute_request"}
            for _ in range(100):
                if not sent - {m["parent_header"].get("msg_id") for _, kind, m in self.frames if kind == "recv" and m["header"]["msg_type"] == "execute_reply"}:
                    break
                page.wait_for_timeout(100)
            self.name = "session"

    def response(self, r: Any) -> None:
        url, method = urlsplit(r.url), r.request.method
        if r.url.startswith(self.gateway) and method == "POST":
            row = {"request": r.request.post_data_json, "response": r.json()}
            self.add("session", {url.path.rsplit("/", 1)[-1] if url.path != "/sessions" else "create": row})
        elif url.path == "/api/kernels":
            self.add(self.name, {"kernel" if method == "POST" else "kernels": r.json()})
        elif url.path.startswith("/api/contents/") and method == "GET" and "content" in parse_qs(url.query):
            self.add(self.name, {"contents": {"path": unquote(url.path.removeprefix("/api/contents/")), "status": r.status, "body": r.json()}})

    def exchanges(self) -> None:
        open_: dict[str, dict[str, Any]] = {}
        info: list[dict[str, Any]] = []
        info_id = None
        for name, kind, msg in self.frames:
            if kind == "recv":
                parent = msg.get("parent_header", {}).get("msg_id")
                if parent in open_ or parent == info_id:
                    (open_[parent]["replies"] if parent in open_ else info).append({k: msg[k] for k in ("header", "channel", "content")})
            elif kind == "sent" and msg["header"]["msg_type"] == "kernel_info_request":
                info_id = info_id or msg["header"]["msg_id"]
            elif kind == "interrupt" or msg["header"]["msg_type"] == "execute_request":
                key = "interrupt" if kind == "interrupt" else code_key(msg["content"]["code"])
                for ex in open_.values():
                    ex["replies"].append({"await": key})
                if kind == "sent":
                    open_[msg["header"]["msg_id"]] = {"key": key, "replies": []}
                    self.add(name, {"exchange": open_[msg["header"]["msg_id"]]})
        for ex in open_.values():
            while ex["replies"] and "await" in ex["replies"][-1]:
                ex["replies"].pop()
        for name in {n for n, *_ in self.frames} - {"session"}:
            self.rows[name].insert(0, {"info": info})


def replies(rs: list[dict[str, Any]]) -> list[Any]:
    out: list[Any] = []
    for r in rs:
        kind = "await" if "await" in r else r["header"]["msg_type"]
        if kind == "stream" and out and out[-1].get("stream") == r["content"]["name"]:
            out[-1]["lines"] = shape(out[-1]["lines"] + r["content"]["text"].splitlines())
        elif kind == "stream":
            out.append({"stream": r["content"]["name"], "lines": shape(r["content"]["text"].splitlines())})
        elif kind not in ("status", "execute_input"):
            out.append(shape(r) if kind == "await" else {kind: shape(r["content"])})
    return out


def shape(obj: Any) -> Any:
    if isinstance(obj, dict):
        if obj.get("kind") == "log":
            return {"kind": "log"}
        if "replies" in obj or "info" in obj:
            return {k: replies(v) if k in ("replies", "info") else shape(v) for k, v in obj.items()}
        return {k: shape(v) for k, v in sorted(obj.items()) if k not in VOLATILE}
    if isinstance(obj, list):
        out: list[Any] = []
        for v in map(shape, obj):
            if v != "" and (not out or out[-1] != v):
                out.append(v)
        return out
    return ID.sub("#", obj) if isinstance(obj, str) else "#" if isinstance(obj, int | float) and not isinstance(obj, bool) else obj


def drift(name: str, rows: list[dict[str, Any]], fixtures: Path = FIXTURES) -> list[str]:
    def lines(rs: list[dict[str, Any]]) -> list[str]:
        out: list[str] = []
        rs = [r for r in rs if "contents" not in r] + sorted((r for r in rs if "contents" in r), key=lambda r: r["contents"]["path"])
        for line in (json.dumps(shape(r), sort_keys=True) for r in rs):
            if not out or out[-1] != line:
                out.append(line)
        return out

    old = lines([json.loads(line) for line in (fixtures / f"{name}.jsonl").read_text().splitlines()]) if (fixtures / f"{name}.jsonl").exists() else []
    return list(difflib.unified_diff(old, lines(rows), f"fixtures/replay/{name}.jsonl", "this run", lineterm="", n=1))


def follow(gateway: str, sid: str, token: tuple[str, str], into: list[dict[str, Any]]) -> threading.Thread:
    def run() -> None:
        with urlopen(Request(f"{gateway}/sessions/{sid}/events?token={token[0]}:{token[1]}"), timeout=300) as r:
            for raw in r:
                line = raw.decode().rstrip("\n")
                if line.startswith("data: "):
                    event = json.loads(line[6:])
                    into.append({"event": event})
                    if event["kind"] == "status" and event["status"]["state"] == "ended":
                        return

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread


def descendants(pid: int) -> set[int]:
    rows = [row.split() for row in subprocess.run(["ps", "-A", "-o", "pid=,ppid="], capture_output=True, text=True, check=True).stdout.splitlines()]
    found, todo = set(), [pid]
    while todo:
        parent = todo.pop()
        for child in (int(p) for p, pp in rows if int(pp) == parent):
            found.add(child)
            todo.append(child)
    return found


def slow(browser: Browser, args: argparse.Namespace) -> None:
    import remote_e2e

    import verify_connect
    import verify_workspace

    machines = Path(tempfile.mkdtemp(prefix="replay-slow-"))
    persist = machines / "persist"
    port = int(subprocess.run([sys.executable, "-c", "import socket; s = socket.socket(); s.bind(('127.0.0.1', 0)); print(s.getsockname()[1])"],
                              capture_output=True, text=True, check=True).stdout)  # fmt: skip
    gateway = args.gateway or f"http://127.0.0.1:{port}"
    token = (os.environ["MODAL_TOKEN_ID"], os.environ["MODAL_TOKEN_SECRET"]) if args.gateway else TOKEN
    proc = None
    if not args.gateway:
        python = subprocess.run(["uv", "run", "--project", str(HERE / "assay"), "--frozen", "python", "-c", "import sys; print(sys.executable)"],
                                capture_output=True, text=True, check=True).stdout.split()[-1]  # fmt: skip
        log = (OUT / "relay.log").open("wb")
        proc = subprocess.Popen(relay(port, "--provider", "local", "--machines-dir", str(machines), "--python", python, *SLOW_LIMITS),
                                stdout=log, stderr=log, env={**os.environ, "BLOGS_WS_PERSIST": str(persist)})  # fmt: skip
    t0 = time.monotonic()
    limits = wait_limits(gateway, proc)
    gpu = "T4" if "T4" in limits["gpus"] else None
    context = browser.new_context(viewport={"width": 1100, "height": 900})
    page = context.new_page()
    rec = Recorder(page, gateway)
    seen: set[int] = set()
    try:
        with serve_dist() as base:
            rec.add("session", {"limits": limits})
            with rec.scenario("workspace", page):
                page.goto(page_url(base, "workspace", gateway))
                verify_workspace.queued_run(page, token)
                sid = page.evaluate("JSON.parse(localStorage.getItem('connect.session')).session_id")
                events = rec.rows["session"]
                thread = follow(gateway, sid, token, events)
                lease = api(gateway, f"/sessions/{sid}", token)["status"]["lease_until"]
                rec.add("session", {"extend": {"request": {"until": lease + 5}, "response": api(gateway, f"/sessions/{sid}/extend", token, {"until": lease + 5})}})
                verify_connect.extend(page, 0)
                verify_workspace.cells(page)
                if proc is not None:
                    seen |= descendants(proc.pid)
                    check((persist / "workspace.bundle").stat().st_size > 0, f"the workspace persisted ({persist / 'workspace.bundle'})")
            with rec.scenario("scratch", page):
                page.goto(page_url(base, "connect", gateway))
                page.wait_for_selector("connect-pill[data-phase=connected]", timeout=60_000)
                if gpu is not None:
                    verify_connect.nvidia_smi(page, gpu)
                verify_connect.scratch(page)
            with rec.scenario("nn-fit", page):
                remote_e2e.runs(page, gpu)
            if proc is not None:
                seen |= descendants(proc.pid)
            print(f"  real path done {time.monotonic() - t0:.0f} s after the relay started; waiting for the lease to run out", flush=True)
            verify_connect.runout(page)
            thread.join(30)
            rec.add("session", {"end": api(gateway, f"/sessions/{sid}/end", token, {})})
            bad = api(gateway, "/sessions", body={"provider": "modal", "token": {"id": "not-a-modal-token", "secret": "x"}, "gpu": None})
            rec.add("bad-token", {"create": {"request": {}, "response": bad}})
            follow(gateway, bad["session_id"], ("not-a-modal-token", "x"), rec.rows["bad-token"]).join(30)
    finally:
        context.close()
        if proc is not None:
            proc.terminate()
            proc.wait(30)
    if proc is not None:
        deadline = time.monotonic() + 15
        while (alive := {p for p in seen if subprocess.run(["kill", "-0", str(p)], capture_output=True).returncode == 0}) and time.monotonic() < deadline:
            time.sleep(0.2)
        check(not alive, f"cleanup: all {len(seen)} processes the relay started are gone")
        check(not [m for m in machines.glob("local-*") if (m / "pid").exists() and subprocess.run(["kill", "-0", (m / "pid").read_text()], capture_output=True).returncode == 0],
              "cleanup: no machine's supervisor runs")  # fmt: skip
        shutil.rmtree(machines)
        check(not machines.exists(), f"cleanup: {machines} removed")
        recorded(rec, args.record)


def recorded(rec: Recorder, record: bool) -> None:
    rec.exchanges()
    for where in (FIXTURES, OUT) if record else (OUT,):
        where.mkdir(parents=True, exist_ok=True)
        for name, rows in rec.rows.items():
            (where / f"{name}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    if record:
        print(f"ok   recorded {sorted(rec.rows)} into {FIXTURES}")
        return
    drifted = {name: diff for name, rows in rec.rows.items() if (diff := drift(name, rows))}
    for diff in drifted.values():
        print("\n".join(line[:240] for line in diff[:40]))
    check(not drifted, f"the recorded streams match fixtures/replay/ ({'drift in ' + ', '.join(drifted) + ': re-record with --record' if drifted else 'no drift'})")


def fast(browser: Browser) -> None:
    import remote_e2e

    import verify_connect
    import verify_workspace

    with serve_dist() as base:
        verify_connect.fast(browser, base)
        verify_workspace.fast(browser, base)
        remote_e2e.fast(browser, base)


def alone(fast: Callable[[Browser, str], None], *pages: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    t0 = time.monotonic()
    build(*pages)
    with sync_playwright() as p, serve_dist() as base:
        browser = p.chromium.launch(executable_path=CHROME)
        fast(browser, base)
        browser.close()
    print(f"ok: fast {', '.join(pages)} in {time.monotonic() - t0:.0f} s")


def main() -> None:
    sys.path.insert(0, str(HERE / "web" / "embeds" / "nn-fit"))
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("tier", choices=("fast", "slow"))
    ap.add_argument("--record", action="store_true", help="slow: write the streams to fixtures/replay/ instead of diffing")
    ap.add_argument("--gateway", help="slow: a running relay instead of a local one (no recording)")
    args = ap.parse_args()
    shutil.rmtree(OUT, ignore_errors=True)
    OUT.mkdir(parents=True)
    t0 = time.monotonic()
    build(*PAGES)
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=CHROME)
        (fast(browser) if args.tier == "fast" else slow(browser, args))
        browser.close()
    print(f"ok: {args.tier} tier in {time.monotonic() - t0:.0f} s")


if __name__ == "__main__":
    main()
