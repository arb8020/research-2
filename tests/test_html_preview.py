"""HTTP tests for /preview/ — rendered-HTML annotate support."""

from __future__ import annotations

import socket
import threading
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path

from mimir.annotate import _AnnotateHandler, resolve_target


def _free_port() -> int:
  with socket.socket() as s:
    s.bind(("127.0.0.1", 0))
    return s.getsockname()[1]


def _start(root: Path, paths: list[str]) -> tuple[ThreadingHTTPServer, int]:
  port = _free_port()
  target = resolve_target(paths=paths, root=str(root))
  _AnnotateHandler.root = str(root)
  _AnnotateHandler.target = target
  _AnnotateHandler.result = None
  _AnnotateHandler.submitted = threading.Event()
  server = ThreadingHTTPServer(("127.0.0.1", port), _AnnotateHandler)
  thread = threading.Thread(target=server.serve_forever, daemon=True)
  thread.start()
  return server, port


def _get(port: int, path: str) -> tuple[int, str, bytes]:
  conn = HTTPConnection("127.0.0.1", port, timeout=5)
  try:
    conn.request("GET", path)
    resp = conn.getresponse()
    return resp.status, resp.getheader("Content-Type") or "", resp.read()
  finally:
    conn.close()


def test_preview_serves_html(tmp_path: Path) -> None:
  html = tmp_path / "doc.html"
  html.write_text("<!doctype html><h1>hello-preview</h1>", encoding="utf-8")
  server, port = _start(tmp_path, ["doc.html"])
  try:
    status, ctype, body = _get(port, "/preview/doc.html")
    assert status == 200
    assert ctype.startswith("text/html")
    assert b"hello-preview" in body
  finally:
    server.shutdown()


def test_preview_serves_relative_asset(tmp_path: Path) -> None:
  (tmp_path / "docs").mkdir()
  (tmp_path / "docs" / "page.html").write_text(
    '<link rel="stylesheet" href="page.css"><h1>x</h1>', encoding="utf-8",
  )
  (tmp_path / "docs" / "page.css").write_text("h1{color:red}", encoding="utf-8")
  server, port = _start(tmp_path, ["docs/page.html"])
  try:
    status, ctype, body = _get(port, "/preview/docs/page.css")
    assert status == 200
    assert ctype.startswith("text/css")
    assert b"color:red" in body
  finally:
    server.shutdown()


def test_preview_rejects_missing_and_escape(tmp_path: Path) -> None:
  (tmp_path / "doc.html").write_text("<h1>ok</h1>", encoding="utf-8")
  outside = tmp_path.parent / "secret.txt"
  outside.write_text("nope", encoding="utf-8")
  server, port = _start(tmp_path, ["doc.html"])
  try:
    status, _, _ = _get(port, "/preview/missing.html")
    assert status == 404
    status, _, _ = _get(port, "/preview/../" + outside.name)
    assert status == 404
  finally:
    server.shutdown()
