"""Kimi K3 XTML channels, streamed. A K3 assistant turn after the generation prompt
(`<|open|>message role="assistant"<|sep|><|open|>think<|sep|>`) looks like

    thought<|close|>think<|sep|><|open|>response<|sep|>answer<|close|>response<|sep|>
    <|open|>tools<|sep|><|open|>call tool="f" index="1"<|sep|>
      <|open|>argument key="k" type="string"<|sep|>v<|close|>argument<|sep|><|close|>call<|sep|>
    <|close|>tools<|sep|><|close|>message<|sep|><|end_of_msg|>

Port of the sgl_jax KimiK3Detector + KimiK3 reasoning detector, merged into one state machine:
think -> content -> tools. Channel markers never reach the client; partial markers are held back;
each tool call is emitted whole once its `<|close|>call<|sep|>` arrives (K3 emits arguments as
typed XTML, so there is no raw-JSON prefix worth streaming)."""

from __future__ import annotations

import json
import re

from kelpie_http.chat.parse import ToolCalls, find_first, partial_suffix_len
from kelpie_http.chat.parse.events import Event, ReasoningDelta, TextDelta

THINK_OPEN = "<|open|>think<|sep|>"
THINK_CLOSE = "<|close|>think<|sep|>"
RESPONSE_OPEN = "<|open|>response<|sep|>"
RESPONSE_CLOSE = "<|close|>response<|sep|>"
TOOLS_OPEN = "<|open|>tools<|sep|>"
TOOLS_CLOSE = "<|close|>tools<|sep|>"
MESSAGE_CLOSE = "<|close|>message<|sep|>"
CONTENT_MARKERS = [RESPONSE_OPEN, RESPONSE_CLOSE, MESSAGE_CLOSE]

_CALL_RE = re.compile(
    r"<\|open\|>call\s+(?P<attrs>(?:(?!<\|sep\|>).)*?)<\|sep\|>(?P<body>.*?)<\|close\|>call<\|sep\|>",
    re.DOTALL,
)
_ARG_RE = re.compile(
    r"<\|open\|>argument\s+(?P<attrs>(?:(?!<\|sep\|>).)*?)<\|sep\|>"
    r"(?P<val>.*?)<\|close\|>argument<\|sep\|>",
    re.DOTALL,
)
_JSON_RE = re.compile(
    r"<\|open\|>json\s+(?:(?!<\|sep\|>).)*?<\|sep\|>(?P<val>.*?)<\|close\|>json<\|sep\|>", re.DOTALL
)
_ATTR_RE = re.compile(r'(?P<k>\w+)="(?P<v>[^"]*)"')


class KimiK3Parser:
    def __init__(self, *, enable_thinking: bool | None = None) -> None:
        # The generation prompt opens the think channel unless thinking was disabled, in which
        # case it opens the response channel instead.
        self._state = "content" if enable_thinking is False else "think"
        self._calls = ToolCalls()
        self._buf = ""

    def feed(self, text_delta: str, token_ids: list[int]) -> list[Event]:
        del token_ids
        self._buf += text_delta
        events: list[Event] = []
        while True:  # each state consumes what it can; stop once nothing moves
            before = (self._state, len(self._buf))
            events.extend(getattr(self, "_" + self._state)())
            if (self._state, len(self._buf)) == before:
                return events

    def finish(self) -> list[Event]:
        """Flush; a marker the stream was cut inside (max_tokens mid-tag) is dropped."""
        buf, self._buf = self._buf, ""
        if self._state == "think":
            text = drop_partial_marker(buf, [THINK_CLOSE, TOOLS_OPEN, RESPONSE_OPEN])
            return [ReasoningDelta(text)] if text else []
        if self._state == "content":
            text = clean_content(drop_partial_marker(buf, [*CONTENT_MARKERS, TOOLS_OPEN]))
            return [TextDelta(text)] if text else []
        return self._calls.close_if_open()  # tools: an unfinished call is dropped, not leaked

    def _think(self) -> list[Event]:
        idx, marker = find_first(self._buf, [THINK_CLOSE, TOOLS_OPEN, RESPONSE_OPEN])
        if idx == -1:
            n = partial_suffix_len(self._buf, [THINK_CLOSE, TOOLS_OPEN, RESPONSE_OPEN])
            emit, self._buf = (self._buf[:-n], self._buf[-n:]) if n else (self._buf, "")
            return [ReasoningDelta(emit)] if emit else []
        reasoning = self._buf[:idx]
        self._buf = (
            self._buf[idx + len(THINK_CLOSE) :] if marker == THINK_CLOSE else self._buf[idx:]
        )
        self._state = "content"
        return [ReasoningDelta(reasoning)] if reasoning else []

    def _content(self) -> list[Event]:
        idx = self._buf.find(TOOLS_OPEN)
        if idx == -1:
            n = partial_suffix_len(self._buf, [*CONTENT_MARKERS, TOOLS_OPEN])
            emit, self._buf = (self._buf[:-n], self._buf[-n:]) if n else (self._buf, "")
            text = clean_content(emit)
            return [TextDelta(text)] if text else []
        text = clean_content(self._buf[:idx])
        self._buf = self._buf[idx + len(TOOLS_OPEN) :]
        self._state = "tools"
        return [TextDelta(text)] if text else []

    def _tools(self) -> list[Event]:
        events: list[Event] = []
        while (m := _CALL_RE.search(self._buf)) is not None:
            call = decode_call(m["attrs"], m["body"])
            if call is not None:
                events.extend(self._calls.whole(*call))
            self._buf = self._buf[m.end() :]
        idx = self._buf.find(TOOLS_CLOSE)
        if idx != -1 and _CALL_RE.search(self._buf) is None:
            self._buf = self._buf[idx + len(TOOLS_CLOSE) :]
            self._state = "content"
        return events


def decode_call(attrs: str, body: str) -> tuple[str, str] | None:
    """(tool name, arguments JSON) from one call block; None when the block names no tool."""
    name = parse_attrs(attrs).get("tool", "")
    if not name:
        return None
    json_block = _JSON_RE.search(body)
    if json_block is not None:
        return name, json_block["val"]
    arguments: dict[str, object] = {}
    for arg in _ARG_RE.finditer(body):
        a = parse_attrs(arg["attrs"])
        key, kind, raw = a.get("key", ""), a.get("type", "string"), arg["val"]
        if kind == "string":
            arguments[key] = raw
        else:
            try:
                arguments[key] = json.loads(raw)
            except json.JSONDecodeError:
                arguments[key] = raw
    return name, json.dumps(arguments, ensure_ascii=False)


def parse_attrs(attrs: str) -> dict[str, str]:
    return {
        m["k"]: m["v"].replace("&quot;", '"').replace("&amp;", "&")
        for m in _ATTR_RE.finditer(attrs)
    }


def clean_content(text: str) -> str:
    for marker in CONTENT_MARKERS:
        text = text.replace(marker, "")
    return text


def drop_partial_marker(text: str, markers: list[str]) -> str:
    n = partial_suffix_len(text, markers)
    return text[:-n] if n else text
