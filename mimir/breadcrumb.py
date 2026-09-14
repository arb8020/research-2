"""breadcrumb — append-only event log to BREADCRUMBS.md."""

from __future__ import annotations

import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path


def _git(*args: str) -> str | None:
  try:
    return subprocess.check_output(
      ["git", *args], stderr=subprocess.DEVNULL, text=True
    ).strip()
  except (subprocess.CalledProcessError, FileNotFoundError):
    return None


def repo_root() -> Path | None:
  root = _git("rev-parse", "--show-toplevel")
  return Path(root) if root else None


def resolve_path(file_override: str | None = None) -> Path:
  if file_override:
    return Path(file_override)
  root = repo_root() or Path.cwd()
  return root / "BREADCRUMBS.md"


def append_entry(agent: str, message: str, path: Path) -> None:
  ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
  needs_header = not path.exists() or path.stat().st_size == 0
  with open(path, "a") as f:
    if needs_header:
      f.write("# Breadcrumbs\n\n")
    f.write(f"{ts} [{agent}] {message}\n")


def list_entries(path: Path) -> str:
  if path.exists():
    return path.read_text()
  return "(no breadcrumbs yet)"


def view(path: Path, port: int | None = None) -> None:
  """Serve BREADCRUMBS.md as live-updating HTML viewer. Blocks (ctrl-c to stop)."""
  import threading
  import webbrowser
  from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

  port = port or _free_port()

  class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
      if self.path == "/body":
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(_render_entries(path).encode())
      else:
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(_render_shell(path).encode())

    def log_message(self, *_args: object) -> None:
      pass

  server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
  server.daemon_threads = True
  thread = threading.Thread(target=server.serve_forever, daemon=True)
  thread.start()
  url = f"http://127.0.0.1:{port}"
  webbrowser.open(url)
  print(f"viewing {path} at {url} (live-updates, ctrl-c to stop)")
  try:
    thread.join()
  except KeyboardInterrupt:
    server.shutdown()


def _free_port() -> int:
  import socket
  with socket.socket() as s:
    s.bind(("127.0.0.1", 0))
    return s.getsockname()[1]


def _parse_line(line: str) -> str:
  import html as html_mod

  parts = line.split("] ", 1)
  if len(parts) == 2 and "[" in parts[0]:
    time_agent = parts[0]
    msg = html_mod.escape(parts[1])
    ts, agent = time_agent.split(" [", 1)
    return (
      f'<div class="entry">'
      f'<span class="ts">{html_mod.escape(ts)}</span>'
      f'<span class="agent">{html_mod.escape(agent)}</span>'
      f'<span class="msg">{msg}</span>'
      f'</div>'
    )
  return f'<div class="entry"><span class="msg">{__import__("html").escape(line)}</span></div>'


def _render_entries(path: Path) -> str:
  raw = list_entries(path)
  parts: list[str] = []
  for line in raw.splitlines():
    if line.startswith("# ") or not line.strip():
      continue
    parts.append(_parse_line(line))
  return "".join(parts)


def _render_shell(path: Path) -> str:
  import html as html_mod

  raw = list_entries(path)
  title = "Breadcrumbs"
  for line in raw.splitlines():
    if line.startswith("# "):
      title = line[2:].strip()
      break

  entries = _render_entries(path)

  return f"""\
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>{html_mod.escape(title)}</title>
<style>
  :root {{ --bg: #1a1a2e; --fg: #e0e0e0; --ts: #888; --agent: #7ec8e3; --border: #333; }}
  @media (prefers-color-scheme: light) {{
    :root {{ --bg: #fafafa; --fg: #222; --ts: #999; --agent: #2563eb; --border: #ddd; }}
  }}
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ background: var(--bg); color: var(--fg); font: 13px/1.6 'SF Mono', 'Cascadia Code', monospace; padding: 24px; }}
  h1 {{ font-size: 16px; margin-bottom: 16px; font-weight: 600; }}
  .entry {{ padding: 4px 0; border-bottom: 1px solid var(--border); display: flex; gap: 12px; align-items: baseline; }}
  .ts {{ color: var(--ts); flex-shrink: 0; }}
  .agent {{ color: var(--agent); font-weight: 600; flex-shrink: 0; }}
  .agent::before {{ content: "["; }} .agent::after {{ content: "]"; }}
  .msg {{ flex: 1; }}
</style>
</head>
<body>
<h1>{html_mod.escape(title)}</h1>
<div id="entries">{entries}</div>
<script>
  setInterval(async () => {{
    const r = await fetch('/body');
    const html = await r.text();
    const el = document.getElementById('entries');
    if (el.innerHTML !== html) {{
      el.innerHTML = html;
      window.scrollTo(0, document.body.scrollHeight);
    }}
  }}, 2000);
  window.scrollTo(0, document.body.scrollHeight);
</script>
</body>
</html>"""
