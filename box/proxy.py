"""http://127.0.0.1:<port> -> a port on the machine (sdk.Endpoint), adding the endpoint's headers, for a
client that cannot send them (a browser, a tool with no header option). Session.proxy makes one.

    with session.proxy(8000) as p:          # Proxy(endpoint, port=0, on_use=session.touch, every_s=...)
        urllib.request.urlopen(p.url + "/v1/models")

Each request is forwarded with the endpoint's headers (Modal: the connect token as a bearer) and the
response is copied back as it arrives, chunk by chunk, so server-sent events (an OpenAI-style
`stream: true`) reach the client live. HTTP/1.0 to the client: the body ends when the connection
closes, so no length is needed up front. Plain HTTP only: no websockets (an Upgrade is refused).
Listens on 127.0.0.1 only: anyone who can reach the listener rides on the token.

Every thread is owned and joined (never a daemon): the serving thread, one thread per request (at most
MAX_INFLIGHT; their sockets, both sides, are shut at close so none outlives it), and the keepalive,
which calls on_use (the session's touch of ROOT/activity) while the proxy is in use.
"""

from __future__ import annotations

import contextlib
import http.client
import socket
import sys
import threading
import time
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from box.sdk import Endpoint

CHUNK = 65536
UPSTREAM_TIMEOUT_S = 3600.0  # one read from the machine: a quiet stream (a long generation between events) is still alive
MAX_BODY_BYTES = 64 << 20  # a request body read before forwarding
MAX_INFLIGHT = 64  # requests at once; more get 503 (each is a thread)
JOIN_S = 10.0  # close(): how long the threads get once their sockets are shut
HOP_BY_HOP = {"connection", "keep-alive", "transfer-encoding", "te", "trailer", "upgrade", "proxy-authorization", "proxy-connection", "host"}


class _Server(ThreadingHTTPServer):
    daemon_threads = False  # http.server's default is True: here every request thread is joined (server_close)
    block_on_close = True


class Proxy:
    """Serving from construction until close() (or leaving `with`). url: where to send requests.
    on_use runs when a request starts and the last call was over every_s ago, and every every_s
    while one is in flight, so a long request keeps the session from going idle; its failure
    (the session ended) is reported, never raised into a request."""

    def __init__(self, endpoint: Endpoint, *, port: int = 0, on_use: Callable[[], None] | None = None, every_s: float = 60.0) -> None:
        upstream = urlsplit(endpoint.url)
        if upstream.scheme not in ("http", "https"):
            raise ValueError(f"proxy: {endpoint.url}: not http(s)")
        assert every_s > 0, every_s
        self.endpoint = endpoint
        self._on_use, self._every_s = on_use, every_s
        self._lock = threading.Lock()  # the fields below
        self._inflight = 0
        self._used_at = float("-inf")  # monotonic: on_use's last call
        self._sockets: set[socket.socket] = set()  # open client and upstream sockets: shut at close
        self._stop = threading.Event()
        self._server = _Server(("127.0.0.1", port), _handler(self, upstream))
        self.url = f"http://127.0.0.1:{self._server.server_address[1]}"
        self._threads = [
            threading.Thread(target=self._server.serve_forever, args=(0.1,), name=f"box-proxy-{self.url}", daemon=False),
            *([threading.Thread(target=self._keepalive, name=f"box-proxy-keepalive-{self.url}", daemon=False)] if on_use else []),
        ]
        for t in self._threads:
            t.start()

    def __enter__(self) -> Proxy:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        """Stop serving, end every request (its sockets shut), join every thread. Idempotent."""
        if self._stop.is_set():
            return
        self._stop.set()
        self._server.shutdown()  # serve_forever returns within its poll interval
        with self._lock:
            open_sockets = list(self._sockets)
        for sock in open_sockets:
            with contextlib.suppress(OSError):
                sock.shutdown(socket.SHUT_RDWR)  # a request thread blocked on either side wakes and ends
        self._server.server_close()  # joins the request threads (block_on_close)
        give_up = time.monotonic() + JOIN_S
        for t in self._threads:
            t.join(max(0.0, give_up - time.monotonic()))
        if stuck := [t.name for t in self._threads if t.is_alive()]:
            print(f"box proxy: threads {stuck} still running {JOIN_S:.0f} s after close", file=sys.stderr)

    def _begin(self) -> bool:
        """A request starts: False if MAX_INFLIGHT are already in flight. Calls on_use first if it
        is due, so a request after a quiet spell marks the session used before the machine sees it."""
        with self._lock:
            if self._inflight >= MAX_INFLIGHT:
                return False
            self._inflight += 1
            due = self._on_use is not None and time.monotonic() - self._used_at >= self._every_s
            if due:
                self._used_at = time.monotonic()
        if due:
            self._use()
        return True

    def _end(self) -> None:
        with self._lock:
            self._inflight -= 1
            assert self._inflight >= 0

    def _keepalive(self) -> None:
        while not self._stop.wait(self._every_s):
            with self._lock:
                due = self._inflight > 0
                if due:
                    self._used_at = time.monotonic()
            if due:
                self._use()

    def _use(self) -> None:
        assert self._on_use is not None
        try:
            self._on_use()
        except Exception as e:  # noqa: BLE001 (the session may have ended; the request still gets its answer or error)
            print(f"box proxy: marking the session used failed: {e!r}", file=sys.stderr)

    def _track(self, sock: socket.socket | None, *, add: bool) -> None:
        """Note an open socket for close() to shut. Adding after close() began raises: close sets
        _stop before it takes the sockets (under this lock), so no socket is ever missed."""
        if sock is None:
            return
        with self._lock:
            if add and self._stop.is_set():
                raise ConnectionAbortedError("box proxy: closing")
            (self._sockets.add if add else self._sockets.discard)(sock)


def _handler(proxy: Proxy, upstream: object) -> type[BaseHTTPRequestHandler]:
    connection = http.client.HTTPSConnection if upstream.scheme == "https" else http.client.HTTPConnection  # type: ignore[attr-defined]

    class Forward(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.0"

        def forward(self) -> None:
            if self.headers.get("Upgrade"):
                self.send_error(501, "box proxy forwards plain HTTP, not websockets")
                return
            length = int(self.headers.get("Content-Length") or 0)
            if not 0 <= length <= MAX_BODY_BYTES:
                self.send_error(413, f"box proxy: a body of {length} bytes (at most {MAX_BODY_BYTES})")
                return
            if not proxy._begin():
                self.send_error(503, f"box proxy: {MAX_INFLIGHT} requests already in flight")
                return
            conn = connection(upstream.hostname, upstream.port, timeout=UPSTREAM_TIMEOUT_S)  # type: ignore[attr-defined]
            answered = False
            try:
                proxy._track(self.connection, add=True)
                body = self.rfile.read(length)
                # Connection: close, so nothing upstream pools a connection to the machine's port after
                # this request (seen live: Modal's connect-token edge holds a keep-alive one 5+ min).
                headers = {k: v for k, v in self.headers.items() if k.lower() not in HOP_BY_HOP} | proxy.endpoint.headers | {"Connection": "close"}
                conn.connect()
                proxy._track(conn.sock, add=True)
                conn.request(self.command, upstream.path.rstrip("/") + self.path, body=body or None, headers=headers)  # type: ignore[attr-defined]
                resp = conn.getresponse()
                answered = True
                self.send_response(resp.status, resp.reason)
                for k, v in resp.getheaders():
                    if k.lower() not in HOP_BY_HOP and k.lower() != "content-length":
                        self.send_header(k, v)
                self.end_headers()
                while chunk := resp.read1(CHUNK):
                    self.wfile.write(chunk)
                    self.wfile.flush()
            except (OSError, http.client.HTTPException) as e:  # the upstream, the client hanging up, or close()
                print(f"box proxy: {self.command} {self.path}: {e!r}", file=sys.stderr)
                if not answered:
                    with contextlib.suppress(OSError):
                        self.send_error(502, f"box proxy: the machine's port did not answer: {e!r}")
            finally:
                proxy._track(conn.sock, add=False)
                proxy._track(self.connection, add=False)
                conn.close()
                proxy._end()

        do_GET = do_POST = do_PUT = do_DELETE = do_PATCH = do_HEAD = do_OPTIONS = forward

        def log_message(self, fmt: str, *args: object) -> None:
            print(f"box proxy: {fmt % args}", file=sys.stderr)

    return Forward
