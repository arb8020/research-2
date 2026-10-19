from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
import time
import traceback
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import build_web
from check import PASSED, Block, Result, cell_order, find, one_line, parse, run_cell

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
    ap = argparse.ArgumentParser(
        description="Local stand-in for a reader's session: runs a chapter's cells for its page (check.run_cell).",
        epilog="POST /run {cell, source}  NDJSON: {\"out\"} lines as output arrives, then exactly one {\"result\": {passed, message}}\n"
               "GET  /state                {\"passed\": {cell: source}, \"wasm\": {cell: url}}\n"
               "GET  /wasm/<hash>/<file>   the play widget built from a reader's passing C cell",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("chapter", type=Path)
    ap.add_argument("--port", type=int, default=8787)
    ap.add_argument("--timeout", type=float, default=30, help="seconds a cell may run before it is killed")
    args = ap.parse_args()
    store = HERE / ".session" / args.chapter.with_suffix("").name
    state_path = store / "state.json"
    build_web.ensure_raylib()

    def load() -> dict:
        return json.loads(state_path.read_text()) if state_path.exists() else {"passed": {}, "wasm": {}}

    def run(cell: str, source: str, emit: Callable[[str], None]) -> Result:
        blocks = parse(args.chapter.read_text())
        order = cell_order(blocks)
        state = load()
        upstream = order[: order.index(cell)]
        if missing := [n for n in upstream if n not in state["passed"]]:
            why = f"locked: {missing[0]} has not passed yet"
            emit(why + "\n")
            return Result(False, why)
        stub = find(blocks, "cell", cell)
        target = Block(stub.lang, "cell", cell, source, stub.line)
        job = [b for b in blocks if b.role == "given" or (b.role in ("check", "budget") and b.name == cell)]
        job += [Block(find(blocks, "cell", n).lang, "solution", n, state["passed"][n], 0) for n in upstream]
        job.append(target)
        emit(f"checking {cell} with your latest passing {', '.join(upstream)}\n" if upstream else f"checking {cell}\n")

        wasm = POOL.submit(build_wasm, target, store) if target.lang == "c" else None
        store.mkdir(parents=True, exist_ok=True)
        start = time.perf_counter()
        if not (result := run_cell(job, order, cell, stub=True, emit=emit, timeout=args.timeout)).passed:
            return result

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
        return PASSED

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
            self.head(200, "application/x-ndjson")

            def line(obj: dict) -> None:
                data = json.dumps(obj).encode() + b"\n"
                self.wfile.write(b"%x\r\n%s\r\n" % (len(data), data))
                self.wfile.flush()

            def emit(text: str) -> None:
                line({"out": text})

            try:
                result = run(req["cell"], req["source"], emit)
            except Exception as e:  # noqa: BLE001 - a session bug still ends the stream with a result
                emit(traceback.format_exc())
                result = Result(False, one_line(f"session error: {type(e).__name__}: {e}"))
            line({"result": {"passed": result.passed, "message": result.message}})
            self.wfile.write(b"0\r\n\r\n")

    print(f"session for {args.chapter} on http://localhost:{args.port}, state in {state_path}")
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
