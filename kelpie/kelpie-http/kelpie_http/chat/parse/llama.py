"""Llama-3.x tool calls: the whole assistant body is one JSON object
`{"name": ..., "parameters": {...}}` (optionally behind <|python_tag|>), or plain text. There is
no delimiter, so a body that opens with `{` is buffered until the end and decided there; anything
else streams as text. No reasoning channel."""

from __future__ import annotations

import json

from kelpie_http.chat.parse import ToolCalls
from kelpie_http.chat.parse.events import Event, TextDelta

PYTHON_TAG = "<|python_tag|>"


class LlamaParser:
    def __init__(self, *, enable_thinking: bool | None = None) -> None:
        del enable_thinking
        self._calls = ToolCalls()
        self._buf = ""
        self._mode = "start"  # start (undecided) | text | json

    def feed(self, text_delta: str, token_ids: list[int]) -> list[Event]:
        del token_ids
        self._buf += text_delta
        if self._mode == "start":
            head = self._buf.lstrip()
            if not head or PYTHON_TAG.startswith(head):
                return []
            if head.startswith(PYTHON_TAG):
                head = head[len(PYTHON_TAG) :].lstrip()
                if not head:
                    return []
            self._mode = "json" if head.startswith("{") else "text"
            self._buf = head if self._mode == "json" else self._buf
        if self._mode == "text":
            out, self._buf = self._buf, ""
            return [TextDelta(out)]
        return []

    def finish(self) -> list[Event]:
        buf, self._buf = self._buf, ""
        if not buf:
            return []
        if self._mode == "json":
            call = parse_call(buf)
            if call is not None:
                return self._calls.whole(*call)
        return [TextDelta(buf)]


def parse_call(text: str) -> tuple[str, str] | None:
    try:
        obj = json.loads(text.strip())
    except json.JSONDecodeError:
        return None
    if not isinstance(obj, dict) or not obj.get("name"):
        return None
    args = obj.get("parameters", obj.get("arguments", {}))
    return str(obj["name"]), args if isinstance(args, str) else json.dumps(args, ensure_ascii=False)
