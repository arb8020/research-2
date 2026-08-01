"""mimir ui — minimal local web surface over the quests/at engine.

Plannotator recipe: stdlib HTTP server on a random port, one hand-written HTML
file (no build step), open the browser. The server is a thin JSON adapter over
the same engine functions the CLI prints; the UI never gets data the CLI
doesn't have (granularity rule).
"""

from __future__ import annotations

import json
import os
import socket
import time
import webbrowser
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .at import query_at
from .quests import _git, collect_turn_in

_UI_DIR = os.path.join(os.path.dirname(__file__), "ui")
_DIST_DIR = os.path.join(_UI_DIR, "dist")
_LEGACY_PATH = os.path.join(_UI_DIR, "index.html")

def _use_dist() -> bool:
  return os.path.isdir(_DIST_DIR) and os.path.isfile(os.path.join(_DIST_DIR, "index.html"))

_MIME_TYPES: dict[str, str] = {
  ".html": "text/html",
  ".js": "application/javascript",
  ".css": "text/css",
  ".json": "application/json",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".ico": "image/x-icon",
  ".woff2": "font/woff2",
}


def _tree(root: str) -> dict:
  """File list (git-tracked) + quest badges: which files live branches touch."""
  files = (_git(root, "ls-files") or "").splitlines()
  touched: dict[str, list[str]] = {}
  base = (_git(root, "rev-parse", "--abbrev-ref", "HEAD") or "main").strip()
  now = time.time()
  merged = set((_git(root, "branch", "--format=%(refname:short)", "--merged", "main") or "").split())
  branches = []
  for line in (_git(root, "for-each-ref", "refs/heads",
                    "--format=%(refname:short)|%(committerdate:unix)") or "").splitlines():
    name, ts = line.split("|")
    if name != "main" and name not in merged and (now - int(ts)) < 14 * 86400:
      branches.append(name)
  for b in branches:
    out = _git(root, "diff", "--name-only", f"main...{b}") or ""
    for f in out.splitlines():
      touched.setdefault(f, []).append(b)
  return {"files": files, "touched": touched, "branch": base}


class _Handler(BaseHTTPRequestHandler):
  root: str = "."

  def log_message(self, *a: object) -> None:  # quiet
    pass

  def _json(self, obj: object, code: int = 200) -> None:
    body = json.dumps(obj).encode()
    self.send_response(code)
    self.send_header("Content-Type", "application/json")
    self.send_header("Content-Length", str(len(body)))
    self.end_headers()
    self.wfile.write(body)

  def do_GET(self) -> None:  # noqa: N802 (http.server API)
    url = urlparse(self.path)
    q = parse_qs(url.query)
    if url.path == "/api/tree":
      self._json(_tree(self.root))
    elif url.path == "/api/file":
      rel = q.get("path", [""])[0]
      full = os.path.realpath(os.path.join(self.root, rel))
      if not full.startswith(os.path.realpath(self.root)) or not os.path.isfile(full):
        self._json({"error": "not found"}, 404)
        return
      try:
        with open(full, encoding="utf-8", errors="replace") as f:
          self._json({"path": rel, "content": f.read()})
      except OSError:
        self._json({"error": "unreadable"}, 500)
    elif url.path == "/api/at":
      rel = q.get("path", [""])[0]
      start = q.get("start", [None])[0]
      end = q.get("end", [start])[0]
      rep = query_at(self.root, rel,
                     int(start) if start else None,
                     int(end) if end else None)
      self._json({"at": asdict(rep) if rep else None})
    elif url.path == "/api/quests":
      t = collect_turn_in(self.root)
      self._json({"turn_in": asdict(t) if t else None})
    elif _use_dist():
      # Serve from Vite build
      path = url.path.lstrip("/") or "index.html"
      full = os.path.realpath(os.path.join(_DIST_DIR, path))
      if not full.startswith(os.path.realpath(_DIST_DIR)) or not os.path.isfile(full):
        # SPA fallback: serve index.html for non-file routes
        full = os.path.join(_DIST_DIR, "index.html")
      try:
        with open(full, "rb") as f:
          body = f.read()
      except OSError:
        self._json({"error": "not found"}, 404)
        return
      ext = os.path.splitext(full)[1]
      mime = _MIME_TYPES.get(ext, "application/octet-stream")
      self.send_response(200)
      self.send_header("Content-Type", mime)
      self.send_header("Content-Length", str(len(body)))
      if ext in (".js", ".css") and "/assets/" in full:
        self.send_header("Cache-Control", "public, max-age=31536000, immutable")
      self.end_headers()
      self.wfile.write(body)
    elif url.path == "/":
      # Legacy single-file UI
      try:
        with open(_LEGACY_PATH, encoding="utf-8") as f:
          body = f.read().encode()
      except OSError:
        self._json({"error": "ui missing"}, 500)
        return
      self.send_response(200)
      self.send_header("Content-Type", "text/html")
      self.send_header("Content-Length", str(len(body)))
      self.end_headers()
      self.wfile.write(body)
    else:
      self._json({"error": "no such route"}, 404)


def serve_ui(root: str, port: int | None = None, open_browser: bool = True) -> None:
  if port is None:
    with socket.socket() as s:
      s.bind(("127.0.0.1", 0))
      port = s.getsockname()[1]
  _Handler.root = root
  server = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
  url = f"http://127.0.0.1:{port}"
  print(f"mimir ui · {url} · ctrl-c to stop")
  if open_browser and os.environ.get("BROWSER") not in ("true", "false", ":"):
    webbrowser.open(url)
  try:
    server.serve_forever()
  except KeyboardInterrupt:
    print("\nbye")
