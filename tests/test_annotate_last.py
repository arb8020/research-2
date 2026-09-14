"""Session picking for `mimir annotate --last`.

The old path called obol discover() and took sources[0] — filesystem
order across every Claude project. These tests lock the replacement:
cwd/agent scoped, never another project's transcript.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from urllib.parse import quote

import pytest

from mimir.annotate import _load_session_messages, resolve_claude_log


def _clear_agent_env(monkeypatch: pytest.MonkeyPatch) -> None:
  for key in ("GROK_SESSION_ID", "GROK_AGENT", "CLAUDE_CODE_SESSION_ID", "PLANNOTATOR_CWD"):
    monkeypatch.delenv(key, raising=False)


def _write_claude(projects: Path, cwd: str, session_id: str, assistant_text: str) -> Path:
  slug = "".join(c if c.isalnum() or c == "-" else "-" for c in cwd)
  path = projects / slug / f"{session_id}.jsonl"
  path.parent.mkdir(parents=True, exist_ok=True)
  rows = [
    {"type": "user", "message": {"role": "user", "content": "hi"}},
    {
      "type": "assistant",
      "message": {"role": "assistant", "content": [{"type": "text", "text": assistant_text}]},
    },
    {"type": "user", "message": {"role": "user", "content": "/annotate-last"}},
  ]
  path.write_text("".join(json.dumps(row) + "\n" for row in rows))
  return path


def _write_grok(home: Path, cwd: Path, session_id: str, assistant_text: str) -> Path:
  hist = home / "sessions" / quote(str(cwd), safe="") / session_id / "chat_history.jsonl"
  hist.parent.mkdir(parents=True, exist_ok=True)
  rows = [
    {"type": "user", "content": "hi"},
    {"type": "assistant", "content": assistant_text},
    {"type": "user", "content": "/annotate-last"},
    {"type": "assistant", "content": ""},
    {"type": "tool_result", "content": "noise"},
  ]
  hist.write_text("".join(json.dumps(row) + "\n" for row in rows))
  return hist


def test_grok_missing_session_id_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
  _clear_agent_env(monkeypatch)
  (tmp_path / "sessions").mkdir()
  monkeypatch.setenv("GROK_HOME", str(tmp_path))
  monkeypatch.setenv("GROK_SESSION_ID", "does-not-exist")
  with pytest.raises(SystemExit, match="no Grok session found"):
    _load_session_messages()


def test_claude_prefers_this_cwd_not_other_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
  _clear_agent_env(monkeypatch)
  claude_home = tmp_path / "claude"
  projects = claude_home / "projects"
  here = tmp_path / "repo-here"
  other = tmp_path / "repo-other"
  here.mkdir()
  other.mkdir()
  _write_claude(projects, str(other), "sess-other", "WRONG PROJECT")
  time.sleep(0.02)
  _write_claude(projects, str(here), "sess-here", "RIGHT PROJECT")
  monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(claude_home))
  monkeypatch.chdir(here)

  picked = resolve_claude_log(cwd=str(here), session_id=None, projects_dir=projects)
  assert picked is not None
  assert picked.name == "sess-here.jsonl"

  messages = _load_session_messages(max_messages=5)
  assert [m.text for m in messages] == ["RIGHT PROJECT"]


def test_missing_claude_id_does_not_fall_back_to_other_project(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
  _clear_agent_env(monkeypatch)
  claude_home = tmp_path / "claude"
  projects = claude_home / "projects"
  here = tmp_path / "repo-here"
  other = tmp_path / "repo-other"
  here.mkdir()
  other.mkdir()
  _write_claude(projects, str(other), "sess-other", "WRONG PROJECT")
  monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(claude_home))
  monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "does-not-exist")
  monkeypatch.chdir(here)

  with pytest.raises(SystemExit, match="no Claude session found for does-not-exist"):
    _load_session_messages()


def test_grok_agent_does_not_open_claude(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
  _clear_agent_env(monkeypatch)
  claude_home = tmp_path / "claude"
  grok_home = tmp_path / "grok"
  here = tmp_path / "repo"
  here.mkdir()
  _write_claude(claude_home / "projects", str(here), "sess-claude", "CLAUDE TEXT")
  _write_grok(grok_home, here, "sess-grok", "GROK TEXT")
  monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(claude_home))
  monkeypatch.setenv("GROK_HOME", str(grok_home))
  monkeypatch.setenv("GROK_AGENT", "1")
  monkeypatch.setenv("GROK_SESSION_ID", "sess-grok")
  monkeypatch.chdir(here)

  messages = _load_session_messages(max_messages=5)
  assert [m.text for m in messages] == ["GROK TEXT"]


def test_grok_agent_without_session_does_not_fall_through_to_claude(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
  _clear_agent_env(monkeypatch)
  claude_home = tmp_path / "claude"
  grok_home = tmp_path / "grok"
  grok_home.mkdir()
  here = tmp_path / "repo"
  here.mkdir()
  _write_claude(claude_home / "projects", str(here), "sess-claude", "CLAUDE TEXT")
  monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(claude_home))
  monkeypatch.setenv("GROK_HOME", str(grok_home))
  monkeypatch.setenv("GROK_AGENT", "1")
  monkeypatch.chdir(here)

  with pytest.raises(SystemExit, match="no Grok session found"):
    _load_session_messages()


def test_grok_skips_current_turn(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
  _clear_agent_env(monkeypatch)
  grok_home = tmp_path / "grok"
  here = tmp_path / "repo"
  here.mkdir()
  _write_grok(grok_home, here, "sess-1", "hello world")
  monkeypatch.setenv("GROK_HOME", str(grok_home))
  monkeypatch.setenv("GROK_SESSION_ID", "sess-1")
  monkeypatch.chdir(here)
  messages = _load_session_messages(max_messages=5)
  assert [m.text for m in messages] == ["hello world"]


def test_no_env_uses_cwd_not_global_newest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
  _clear_agent_env(monkeypatch)
  claude_home = tmp_path / "claude"
  projects = claude_home / "projects"
  here = tmp_path / "repo-here"
  other = tmp_path / "repo-other"
  here.mkdir()
  other.mkdir()
  older = _write_claude(projects, str(here), "sess-here", "HERE")
  newer = _write_claude(projects, str(other), "sess-other", "OTHER")
  os.utime(older, (1, 1))
  os.utime(newer, (9_999_999_999, 9_999_999_999))
  monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(claude_home))
  monkeypatch.setenv("GROK_HOME", str(tmp_path / "empty-grok"))
  monkeypatch.chdir(here)

  messages = _load_session_messages(max_messages=5)
  assert [m.text for m in messages] == ["HERE"]
