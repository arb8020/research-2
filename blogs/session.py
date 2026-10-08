"""Local stand-in for a reader's session (later: a Modal sandbox behind a Cloudflare Durable Object).

    uv run session.py rl/01-flappy.md [--port 8787] [--timeout 30]

    POST /run {cell, source}   streams text/plain; the last line is PASS or FAIL
    GET  /state                {"passed": {cell: latest passing source}, "wasm": {cell: "/wasm/<hash>/<cell>.js"}}
    GET  /wasm/<hash>/<file>   play widget built from a reader's passing C cell

Running cell X: check.run_cell with the given blocks, the reader's latest passing source for every
cell before X, the posted source as X, then X's check (and budget). run_cell runs each in a fresh
subprocess, so a crash or a hang in reader code kills only that subprocess. Only a PASS updates
.session/<chapter>/state.json.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import build_web
from check import Block, cell_order, find, parse, run_cell

HERE = Path(__file__).parent
TYPES = {".js": "text/javascript", ".wasm": "application/wasm", ".html": "text/html"}
POOL = ThreadPoolExecutor(2)


def build_wasm(env: Block, store: Path) -> tuple[str, float]:
    start = time.perf_counter()
    digest = hashlib.sha256(env.source.encode()).hexdigest()[:16]
    out = store / "wasm" / digest
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        build_web.build_play(Block("c", "solution", env.name, env.source, env.line), out, Path(tmp))
    return f"/wasm/{digest}/{env.name}.js", time.perf_counter() - start


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("chapter", type=Path)
    ap.add_argument("--port", type=int, default=8787)
    ap.add_argument("--timeout", type=float, default=30)
    args = ap.parse_args()
    store = HERE / ".session" / args.chapter.with_suffix("").name
    state_path = store / "state.json"
    build_web.ensure_raylib()

    def load() -> dict:
        return json.loads(state_path.read_text()) if state_path.exists() else {"passed": {}, "wasm": {}}

    def run(cell: str, source: str, emit) -> bool:
        blocks = parse(args.chapter.read_text())
        order = cell_order(blocks)
        state = load()
        upstream = order[: order.index(cell)]
        if missing := [n for n in upstream if n not in state["passed"]]:
            emit(f"locked: {missing[0]} has not passed yet\n")
            return False
        stub = find(blocks, "cell", cell)
        target = Block(stub.lang, "cell", cell, source, stub.line)
        job = [b for b in blocks if b.role == "given" or (b.role in ("check", "budget") and b.name == cell)]
        job += [Block(find(blocks, "cell", n).lang, "solution", n, state["passed"][n], 0) for n in upstream]
        job.append(target)
        emit(f"checking {cell} with your latest passing {', '.join(upstream)}\n" if upstream else f"checking {cell}\n")

        wasm = POOL.submit(build_wasm, target, store) if target.lang == "c" else None
        store.mkdir(parents=True, exist_ok=True)
        start = time.perf_counter()
        with tempfile.TemporaryDirectory() as tmp:
            if not run_cell(job, order, Path(tmp), cell, stub=True, emit=emit, timeout=args.timeout):
                return False

        state = load()
        state["passed"][cell] = source
        if wasm:
            waited = time.perf_counter()
            try:
                state["wasm"][cell], took = wasm.result()
                emit(f"play widget rebuilt from your env: emcc {took:.1f}s, check {waited - start:.1f}s, "
                     f"extra wait {time.perf_counter() - waited:.1f}s\n")  # fmt: skip
            except SystemExit as e:
                emit(f"play widget could not be rebuilt (it keeps the previous env):\n{e}\n")
        state_path.write_text(json.dumps(state, indent=1))
        return True

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def head(self, code: int, ctype: str, length: int | None = None) -> None:
            self.send_response(code)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Type", ctype)
            if length is None:
                self.send_header("Transfer-Encoding", "chunked")
                self.send_header("X-Content-Type-Options", "nosniff")
            else:
                self.send_header("Content-Length", str(length))
            self.end_headers()

        def reply(self, code: int, body: bytes, ctype: str) -> None:
            self.head(code, ctype, len(body))
            self.wfile.write(body)

        def do_GET(self) -> None:
            parts = self.path.strip("/").split("/")
            if parts == ["state"]:
                return self.reply(200, json.dumps(load()).encode(), "application/json")
            if len(parts) == 3 and parts[0] == "wasm" and (file := store / "wasm" / parts[1] / parts[2]).is_file():
                return self.reply(200, file.read_bytes(), TYPES[file.suffix])
            self.reply(404, b"not found", "text/plain")

        def do_POST(self) -> None:
            req = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            self.head(200, "text/plain; charset=utf-8")

            def emit(text: str) -> None:
                data = text.encode()
                self.wfile.write(b"%x\r\n%s\r\n" % (len(data), data))
                self.wfile.flush()

            emit("PASS\n" if run(req["cell"], req["source"], emit) else "FAIL\n")
            self.wfile.write(b"0\r\n\r\n")

    print(f"session for {args.chapter} on http://localhost:{args.port}, state in {state_path}")
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
