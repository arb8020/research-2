"""mimir annotate — annotation gate for agent harnesses.

Start a local web server showing files or diffs, block until the user
submits annotations, print structured JSON to stdout, exit.

Protocol:
  mimir annotate [target...]         → browse mode (files)
  mimir annotate --diff <branch>     → diff mode
  mimir annotate --last              → last agent message

Output (one JSON line on stdout):
  {"annotations": [...], "mode": "browse|diff|message", "target": "..."}

Exit 0 = annotations submitted. Exit 1 = closed without submitting.
"""

from __future__ import annotations

import json
import os
import re
import socket
import sys
import threading
import time
import webbrowser
from dataclasses import asdict, dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

import subprocess

from .at import query_at
from .quests import _git


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Annotation:
  file: str
  start_line: int
  end_line: int
  side: str | None = None       # "old" | "new" (diff mode only)
  text: str = ""
  original_text: str | None = None  # selected text (message mode)


@dataclass
class AnnotateResult:
  annotations: list[Annotation] = field(default_factory=list)
  mode: str = "browse"       # "browse" | "diff" | "message"
  target: str = ""


# ---------------------------------------------------------------------------
# Annotate target resolution
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AnnotateTarget:
  mode: str                  # "browse" | "diff" | "message"
  label: str                 # human-readable description
  paths: list[str]           # files to show (browse/message mode)
  diff_ref: str | None       # branch/range (diff mode)
  message_text: str | None   # raw text (message mode) — the selected message
  messages: list | None = None  # all recent messages (message mode)
  stdin_diff: str | None = None  # raw diff from stdin (diff mode)


def resolve_target(
  *,
  paths: list[str] | None = None,
  diff: str | None = None,
  last: bool = False,
  root: str = ".",
) -> AnnotateTarget:
  """Normalize CLI args into an AnnotateTarget."""
  if last:
    messages = _load_session_messages()
    return AnnotateTarget(
      mode="message",
      label="last",
      paths=[],
      diff_ref=None,
      message_text=messages[0].text,
      messages=messages,
    )
  if diff is not None:
    if diff == "-":
      # Read diff from stdin
      raw = sys.stdin.read()
      if not raw.strip():
        raise SystemExit("no diff on stdin")
      # Extract summary line if meat-style (first line starting with #)
      lines = raw.split("\n")
      label = "stdin"
      if lines and lines[0].startswith("# "):
        label = lines[0][2:].strip()
      return AnnotateTarget(
        mode="diff",
        label=label,
        paths=[],
        diff_ref=None,
        message_text=None,
        stdin_diff=raw,
      )
    return AnnotateTarget(
      mode="diff",
      label=diff,
      paths=[],
      diff_ref=diff,
      message_text=None,
    )
  if paths:
    expanded: list[str] = []
    for p in paths:
      full = os.path.join(root, p)
      if os.path.isdir(full):
        # Expand directory to sorted list of files within it
        for entry in sorted(os.listdir(full)):
          entry_path = os.path.join(full, entry)
          if os.path.isfile(entry_path):
            expanded.append(os.path.join(p, entry))
      else:
        expanded.append(p)
    return AnnotateTarget(
      mode="browse",
      label=" ".join(paths),
      paths=expanded if expanded else paths,
      diff_ref=None,
      message_text=None,
    )
  # Default: browse cwd
  return AnnotateTarget(
    mode="browse",
    label=".",
    paths=["."],
    diff_ref=None,
    message_text=None,
  )


@dataclass(frozen=True)
class SessionMessage:
  index: int        # 0 = most recent
  text: str
  preview: str      # first ~60 chars for sidebar display


def _preview(text: str) -> str:
  preview = text[:60].replace("\n", " ").strip()
  return preview + "..." if len(text) > 60 else preview


def _collect_before_last_user(
  texts: list[tuple[bool, str]], *, max_messages: int,
) -> list[SessionMessage]:
  """`texts` is (is_user, text) in session order. Skip the current turn."""
  last_user_idx = next((i for i in range(len(texts) - 1, -1, -1) if texts[i][0]), None)
  search_end = last_user_idx if last_user_idx is not None else len(texts)
  messages: list[SessionMessage] = []
  for is_user, text in reversed(texts[:search_end]):
    if is_user or not text.strip():
      continue
    messages.append(SessionMessage(index=len(messages), text=text, preview=_preview(text)))
    if len(messages) >= max_messages:
      break
  return messages


def _jsonl_by_mtime(directory: Path) -> list[Path]:
  if not directory.is_dir():
    return []
  files = [p for p in directory.iterdir() if p.is_file() and p.suffix == ".jsonl"]
  files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
  return files


def _claude_project_slug(cwd: str) -> str:
  """Claude Code slug: every character outside [a-zA-Z0-9-] becomes '-'."""
  return re.sub(r"[^a-zA-Z0-9-]", "-", cwd)


def _claude_projects_dir() -> Path:
  root = Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude"))
  return root / "projects"


def _claude_logs_for_cwd(projects_dir: Path, cwd: str) -> list[Path]:
  slug = _claude_project_slug(cwd)
  logs = _jsonl_by_mtime(projects_dir / slug)
  if logs:
    return logs
  if not projects_dir.is_dir():
    return []
  slug_l = slug.lower()
  for child in projects_dir.iterdir():
    if child.is_dir() and child.name.lower() == slug_l:
      logs = _jsonl_by_mtime(child)
      if logs:
        return logs
  return []


def _claude_logs_ancestor(projects_dir: Path, cwd: str) -> list[Path]:
  parent = str(Path(cwd).parent)
  seen: set[str] = set()
  while parent and parent not in seen:
    seen.add(parent)
    logs = _claude_logs_for_cwd(projects_dir, parent)
    if logs:
      return logs
    nxt = str(Path(parent).parent)
    if nxt == parent:
      break
    parent = nxt
  return []


def _find_claude_session_file(projects_dir: Path, session_id: str) -> Path | None:
  if not projects_dir.is_dir():
    return None
  matches = list(projects_dir.glob(f"*/{session_id}.jsonl"))
  return matches[0] if len(matches) == 1 else (max(matches, key=lambda p: p.stat().st_mtime) if matches else None)


def resolve_claude_log(
  *,
  cwd: str,
  session_id: str | None,
  projects_dir: Path,
) -> Path | None:
  """Pick a Claude transcript. Never a session from an unrelated project.

  Explicit session id wins. Otherwise newest jsonl for this cwd slug,
  then the first ancestor cwd that has any logs. Missing id does not
  fall back to a global newest-across-all-projects.
  """
  if session_id:
    return _find_claude_session_file(projects_dir, session_id)
  logs = _claude_logs_for_cwd(projects_dir, cwd)
  if logs:
    return logs[0]
  logs = _claude_logs_ancestor(projects_dir, cwd)
  return logs[0] if logs else None


def _assistant_text(content: object) -> str:
  if isinstance(content, str):
    return content
  if not isinstance(content, list):
    return ""
  parts: list[str] = []
  for block in content:
    if isinstance(block, dict) and block.get("type") == "text":
      text = block.get("text")
      if isinstance(text, str) and text.strip():
        parts.append(text)
  return "\n".join(parts)


def _parse_session_jsonl(path: Path, *, assistant_from_message: bool) -> list[tuple[bool, str]]:
  rows: list[tuple[bool, str]] = []
  for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
    if not line.strip():
      continue
    try:
      row = json.loads(line)
    except json.JSONDecodeError:
      continue
    kind = row.get("type")
    if kind == "user":
      rows.append((True, ""))
    elif kind == "assistant":
      if assistant_from_message:
        message = row.get("message") if isinstance(row.get("message"), dict) else {}
        text = _assistant_text(message.get("content") if message else None)
      else:
        content = row.get("content") or ""
        text = content if isinstance(content, str) else ""
      rows.append((False, text))
  return rows


def _grok_history_path() -> Path | None:
  grok_home = Path(os.environ.get("GROK_HOME", Path.home() / ".grok"))
  root = grok_home / "sessions"
  if not root.is_dir():
    return None
  session_id = os.environ.get("GROK_SESSION_ID")
  if session_id:
    matches = list(root.glob(f"*/{session_id}/chat_history.jsonl"))
    return matches[0] if matches else None
  group = root / quote(str(Path.cwd()), safe="")
  if group.is_dir():
    newest = max(group.glob("*/chat_history.jsonl"), key=lambda p: p.stat().st_mtime, default=None)
    if newest is not None:
      return newest
  return None


def _load_grok_session_messages(*, max_messages: int) -> list[SessionMessage] | None:
  history = _grok_history_path()
  if history is None:
    return None
  messages = _collect_before_last_user(
    _parse_session_jsonl(history, assistant_from_message=False),
    max_messages=max_messages,
  )
  if messages:
    print(f"mimir annotate --last · grok {history}", file=sys.stderr)
  return messages or None


def _load_claude_session_messages(*, max_messages: int) -> list[SessionMessage] | None:
  cwd = os.environ.get("PLANNOTATOR_CWD") or os.getcwd()
  session_id = os.environ.get("CLAUDE_CODE_SESSION_ID")
  path = resolve_claude_log(
    cwd=cwd,
    session_id=session_id,
    projects_dir=_claude_projects_dir(),
  )
  if path is None:
    return None
  messages = _collect_before_last_user(
    _parse_session_jsonl(path, assistant_from_message=True),
    max_messages=max_messages,
  )
  if messages:
    print(f"mimir annotate --last · claude {path}", file=sys.stderr)
  return messages or None


def _load_session_messages(*, max_messages: int = 20) -> list[SessionMessage]:
  """Load recent completed-turn assistant messages from this cwd / this agent.

  Never pick a Claude transcript from another project, and never fall
  through from a Grok fingerprint to a random Claude session.
  """
  prefer_grok = bool(os.environ.get("GROK_SESSION_ID") or os.environ.get("GROK_AGENT"))
  prefer_claude = bool(os.environ.get("CLAUDE_CODE_SESSION_ID")) and not prefer_grok

  if prefer_grok:
    grok = _load_grok_session_messages(max_messages=max_messages)
    if grok is not None:
      return grok
    if os.environ.get("GROK_SESSION_ID"):
      raise SystemExit(f"no Grok session found for {os.environ['GROK_SESSION_ID']}")
    raise SystemExit("no Grok session found")

  if prefer_claude:
    claude = _load_claude_session_messages(max_messages=max_messages)
    if claude is not None:
      return claude
    raise SystemExit(
      f"no Claude session found for {os.environ['CLAUDE_CODE_SESSION_ID']}"
    )

  grok = _load_grok_session_messages(max_messages=max_messages)
  if grok is not None:
    return grok
  claude = _load_claude_session_messages(max_messages=max_messages)
  if claude is not None:
    return claude
  raise SystemExit("no session found for this directory")


def _read_last_message() -> str:
  """Read last assistant message from the current Claude Code session."""
  messages = _load_session_messages(max_messages=1)
  return messages[0].text


# ---------------------------------------------------------------------------
# Gate server — blocks until user submits or closes
# ---------------------------------------------------------------------------


class _AnnotateHandler(BaseHTTPRequestHandler):
  root: str = "."
  target: AnnotateTarget = AnnotateTarget(mode="browse", label=".", paths=["."], diff_ref=None, message_text=None)
  result: AnnotateResult | None = None
  submitted: threading.Event = threading.Event()

  def log_message(self, *a: object) -> None:
    pass

  def _json(self, obj: object, code: int = 200) -> None:
    body = json.dumps(obj).encode()
    self.send_response(code)
    self.send_header("Content-Type", "application/json")
    self.send_header("Content-Length", str(len(body)))
    self.end_headers()
    self.wfile.write(body)

  def _read_body(self) -> bytes:
    length = int(self.headers.get("Content-Length", 0))
    return self.rfile.read(length)

  def do_GET(self) -> None:  # noqa: N802
    url = urlparse(self.path)
    q = parse_qs(url.query)

    if url.path == "/api/annotate/target":
      resp: dict = {
        "mode": self.target.mode,
        "label": self.target.label,
        "paths": self.target.paths,
        "diff_ref": self.target.diff_ref,
        "message_text": self.target.message_text,
      }
      if self.target.messages:
        resp["messages"] = [
          {"index": m.index, "preview": m.preview}
          for m in self.target.messages
        ]
      self._json(resp)
    elif url.path == "/api/message":
      self._serve_message(q)
    elif url.path == "/api/tree":
      self._json(_tree(self.root))
    elif url.path == "/api/file":
      self._serve_file(q)
    elif url.path == "/api/diff":
      self._serve_diff(q)
    elif url.path == "/api/browse/children":
      self._serve_browse_children(q)
    elif url.path == "/api/at":
      self._serve_at(q)
    elif _use_dist():
      self._serve_static(url.path)
    else:
      self._json({"error": "not found"}, 404)

  def do_POST(self) -> None:  # noqa: N802
    url = urlparse(self.path)
    if url.path == "/api/annotate/submit":
      body = json.loads(self._read_body())
      annotations = [
        Annotation(
          file=a["file"],
          start_line=a["start_line"],
          end_line=a["end_line"],
          side=a.get("side"),
          text=a.get("text", ""),
          original_text=a.get("original_text"),
        )
        for a in body.get("annotations", [])
      ]
      _AnnotateHandler.result = AnnotateResult(
        annotations=annotations,
        mode=self.target.mode,
        target=self.target.label,
      )
      self._json({"status": "ok"})
      _AnnotateHandler.submitted.set()
    else:
      self._json({"error": "not found"}, 404)

  # --- file serving (shared with webui.py) ---

  def _serve_file(self, q: dict[str, list[str]]) -> None:
    rel = q.get("path", [""])[0]
    ref = q.get("ref", [None])[0]
    if ref:
      content = _git(self.root, "show", f"{ref}:{rel}")
      if content is None:
        self._json({"error": "not found"}, 404)
      else:
        self._json({"path": rel, "ref": ref, "content": content})
    else:
      full = os.path.realpath(os.path.join(self.root, rel))
      if not full.startswith(os.path.realpath(self.root)) or not os.path.isfile(full):
        self._json({"error": "not found"}, 404)
        return
      try:
        with open(full, encoding="utf-8", errors="replace") as f:
          self._json({"path": rel, "content": f.read()})
      except OSError:
        self._json({"error": "unreadable"}, 500)

  def _serve_diff(self, q: dict[str, list[str]]) -> None:
    # Serve stdin diff if available
    if self.target.stdin_diff:
      self._json({"diff": self.target.stdin_diff, "ref": None, "range": None})
      return
    ref = q.get("ref", [None])[0]
    range_spec = q.get("range", [None])[0]
    if range_spec:
      diff = _git(self.root, "diff", range_spec)
    elif ref and ".." in ref:
      diff = _git(self.root, "diff", ref)
    elif ref:
      # Try merge-base for branch names; fall back to direct diff for commits
      base = _git(self.root, "merge-base", "main", ref)
      if base:
        diff = _git(self.root, "diff", f"{base.strip()}...{ref}")
      else:
        diff = _git(self.root, "diff", f"{ref}~..{ref}")
    else:
      diff = _git(self.root, "diff", "HEAD")
    self._json({"diff": diff or "", "ref": ref, "range": range_spec})

  def _serve_at(self, q: dict[str, list[str]]) -> None:
    from .at import query_at
    from dataclasses import asdict
    rel = q.get("path", [""])[0]
    start = q.get("start", [None])[0]
    end = q.get("end", [start])[0]
    rep = query_at(
      self.root, rel,
      int(start) if start else None,
      int(end) if end else None,
    )
    self._json({"at": asdict(rep) if rep else None})

  def _serve_browse_children(self, q: dict[str, list[str]]) -> None:
    """List directory children for the codebase tree, respecting .gitignore."""
    rel = q.get("path", [""])[0]
    full = os.path.realpath(os.path.join(self.root, rel))
    root_real = os.path.realpath(self.root)
    if not full.startswith(root_real) or not os.path.isdir(full):
      self._json({"error": "not found"}, 404)
      return
    # Use git ls-files + ls-tree to respect .gitignore
    # First, get git-tracked files in this directory (non-recursive, one level)
    entries: list[dict] = []
    try:
      # git ls-tree lists the immediate children of a tree path
      tree_path = rel if rel else "."
      # Use git ls-tree HEAD to get tracked entries at this level
      result = subprocess.run(
        ["git", "ls-tree", "--name-only", "HEAD", tree_path + "/" if rel else ""],
        cwd=self.root, capture_output=True, text=True, timeout=5,
      )
      if result.returncode == 0 and result.stdout.strip():
        git_entries = set(result.stdout.strip().splitlines())
      else:
        git_entries = set()

      # Also check for untracked-but-not-ignored files via git status
      # Fall back to just listing the directory, filtering with git check-ignore
      seen = set()
      for name in sorted(os.listdir(full)):
        if name.startswith("."):
          continue
        child_rel = os.path.join(rel, name) if rel else name
        child_full = os.path.join(full, name)
        is_dir = os.path.isdir(child_full)

        # Check if git-ignored
        check = subprocess.run(
          ["git", "check-ignore", "-q", child_rel],
          cwd=self.root, capture_output=True, timeout=5,
        )
        if check.returncode == 0:
          continue  # ignored

        entries.append({
          "name": name,
          "path": child_rel,
          "is_dir": is_dir,
        })
    except (subprocess.TimeoutExpired, OSError):
      # Fallback: just list directory
      for name in sorted(os.listdir(full)):
        if name.startswith("."):
          continue
        child_rel = os.path.join(rel, name) if rel else name
        child_full = os.path.join(full, name)
        entries.append({
          "name": name,
          "path": child_rel,
          "is_dir": os.path.isdir(child_full),
        })
    self._json({"entries": entries})

  def _serve_message(self, q: dict[str, list[str]]) -> None:
    idx_str = q.get("index", ["0"])[0]
    try:
      idx = int(idx_str)
    except ValueError:
      self._json({"error": "invalid index"}, 400)
      return
    if not self.target.messages or idx < 0 or idx >= len(self.target.messages):
      self._json({"error": "not found"}, 404)
      return
    msg = self.target.messages[idx]
    self._json({"index": msg.index, "text": msg.text, "preview": msg.preview})

  def _serve_static(self, path: str) -> None:
    from .webui import _MIME_TYPES
    rel = path.lstrip("/") or "index.html"
    dist = os.path.join(os.path.dirname(__file__), "ui", "dist")
    full = os.path.realpath(os.path.join(dist, rel))
    if not full.startswith(os.path.realpath(dist)) or not os.path.isfile(full):
      full = os.path.join(dist, "index.html")
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
    self.end_headers()
    self.wfile.write(body)


def _use_dist() -> bool:
  dist = os.path.join(os.path.dirname(__file__), "ui", "dist")
  return os.path.isdir(dist) and os.path.isfile(os.path.join(dist, "index.html"))


def _tree(root: str) -> dict:
  """File list (git-tracked) + quest badges."""
  files = (_git(root, "ls-files") or "").splitlines()
  touched: dict[str, list[str]] = {}
  base = (_git(root, "rev-parse", "--abbrev-ref", "HEAD") or "main").strip()
  now = time.time()
  merged = set(
    (_git(root, "branch", "--format=%(refname:short)", "--merged", "main") or "").split()
  )
  branches = []
  for line in (
    _git(root, "for-each-ref", "refs/heads", "--format=%(refname:short)|%(committerdate:unix)")
    or ""
  ).splitlines():
    name, ts = line.split("|")
    if name != "main" and name not in merged and (now - int(ts)) < 14 * 86400:
      branches.append(name)
  for b in branches:
    out = _git(root, "diff", "--name-only", f"main...{b}") or ""
    for f in out.splitlines():
      touched.setdefault(f, []).append(b)
  return {"files": files, "touched": touched, "branch": base}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def run_annotate(
  root: str,
  target: AnnotateTarget,
  *,
  port: int | None = None,
  open_browser: bool = True,
) -> AnnotateResult | None:
  """Start the annotation gate. Blocks until user submits or ctrl-c."""
  if port is None:
    with socket.socket() as s:
      s.bind(("127.0.0.1", 0))
      port = s.getsockname()[1]

  _AnnotateHandler.root = root
  _AnnotateHandler.target = target
  _AnnotateHandler.result = None
  _AnnotateHandler.submitted = threading.Event()

  server = ThreadingHTTPServer(("127.0.0.1", port), _AnnotateHandler)
  server.timeout = 0.5  # poll interval for checking submitted flag

  # Build URL with mode-specific params
  params = f"?annotate=1&mode={target.mode}"
  if target.diff_ref:
    params += f"&diff={target.diff_ref}"
  elif target.stdin_diff:
    params += "&diff=stdin"
  url = f"http://127.0.0.1:{port}{params}"

  print(f"mimir annotate · {url}", file=sys.stderr)
  print("annotate in browser, then submit. ctrl-c to cancel.", file=sys.stderr)

  if open_browser and os.environ.get("BROWSER") not in ("true", "false", ":"):
    webbrowser.open(url)

  try:
    # Serve until submission or interrupt
    while not _AnnotateHandler.submitted.is_set():
      server.handle_request()
  except KeyboardInterrupt:
    print("", file=sys.stderr)
    return None
  finally:
    server.server_close()

  return _AnnotateHandler.result
