"""Unit tests for `mimir annotate --last` session loading."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mimir.annotate import _load_session_messages


def _write_history(root: Path, session_id: str, rows: list[dict]) -> Path:
  hist = root / "sessions" / "cwd" / session_id / "chat_history.jsonl"
  hist.parent.mkdir(parents=True)
  hist.write_text("".join(json.dumps(row) + "\n" for row in rows))
  return hist


def test_grok_last_skips_current_turn(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
  sid = "sess-1"
  _write_history(tmp_path, sid, [
    {"type": "user", "content": [{"type": "text", "text": "first"}]},
    {"type": "assistant", "content": "hello world"},
    {"type": "user", "content": [{"type": "text", "text": "/annotate-last"}]},
    {"type": "assistant", "content": ""},
    {"type": "tool_result", "content": "noise"},
  ])
  monkeypatch.setenv("GROK_HOME", str(tmp_path))
  monkeypatch.setenv("GROK_SESSION_ID", sid)
  messages = _load_session_messages(max_messages=5)
  assert [m.text for m in messages] == ["hello world"]


def test_grok_missing_session_id_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
  monkeypatch.setenv("GROK_HOME", str(tmp_path))
  monkeypatch.setenv("GROK_SESSION_ID", "does-not-exist")
  with pytest.raises(SystemExit, match="no Grok session found"):
    _load_session_messages()
