"""GLM-5.x tool calls: `<tool_call>name<arg_key>k</arg_key><arg_value>v</arg_value>...</tool_call>`
after a <think> block the prompt opened (`<|assistant|><think>`; `<think></think>` with thinking
off). The name streams as soon as its first <arg_key> (or the close) arrives; values are typed by
JSON-parsing with a string fallback, like renderers.parse_glm without a schema."""

from __future__ import annotations

import json
import re

from kelpie_http.chat.parse import ToolCalls, split_holdback
from kelpie_http.chat.parse.events import Event, ReasoningDelta, TextDelta
from kelpie_http.chat.parse.think import ThinkSplitter

BOT = "<tool_call>"
EOT = "</tool_call>"
ARG_KEY = "<arg_key>"
_PAIR_RE = re.compile(
    r"<arg_key>(?P<k>.*?)</arg_key>\s*<arg_value>(?P<v>.*?)</arg_value>", re.DOTALL
)


class GlmParser:
    def __init__(self, *, enable_thinking: bool | None = None) -> None:
        self._think = ThinkSplitter(force=enable_thinking is not False)
        self._calls = ToolCalls()
        self._buf = ""
        self._in_call = False

    def feed(self, text_delta: str, token_ids: list[int]) -> list[Event]:
        del token_ids
        reasoning, content = self._think.feed(text_delta)
        events: list[Event] = [ReasoningDelta(reasoning)] if reasoning else []
        if content:
            events.extend(self._content(content))
        return events

    def finish(self) -> list[Event]:
        reasoning, content = self._think.finish()
        events: list[Event] = [ReasoningDelta(reasoning)] if reasoning else []
        if content:
            events.extend(self._content(content))
        buf, self._buf = self._buf, ""
        if self._in_call:
            if self._calls.open is None:  # never learned the name: drop the fragment
                return events
            events.append(self._calls.args(decode_args(buf)))
            return events + [self._calls.end()]
        return events + self._text(buf)

    def _content(self, text: str) -> list[Event]:
        self._buf += text
        events: list[Event] = []
        while True:
            if not self._in_call:
                idx = self._buf.find(BOT)
                if idx == -1:
                    emit, self._buf = split_holdback(self._buf, [BOT])
                    return events + self._text(emit)
                events.extend(self._text(self._buf[:idx]))
                self._buf = self._buf[idx + len(BOT) :]
                self._in_call = True
            end = self._buf.find(EOT)
            if self._calls.open is None:
                key = self._buf.find(ARG_KEY)
                stop = min(i for i in (key, end) if i != -1) if key != -1 or end != -1 else -1
                if stop == -1:
                    return events
                events.append(self._calls.start(self._buf[:stop].strip()))
                self._buf = self._buf[stop:]
                end = self._buf.find(EOT)
            if end == -1:
                return events
            events.append(self._calls.args(decode_args(self._buf[:end])))
            events.append(self._calls.end())
            self._buf = self._buf[end + len(EOT) :]
            self._in_call = False

    def _text(self, text: str) -> list[Event]:
        if not text or (self._calls.count and not text.strip()):
            return []
        return [TextDelta(text)]


def decode_args(body: str) -> str:
    arguments: dict[str, object] = {}
    for m in _PAIR_RE.finditer(body):
        key, raw = m["k"].strip(), m["v"].strip()
        try:
            arguments[key] = json.loads(raw)
        except json.JSONDecodeError:
            arguments[key] = raw
    return json.dumps(arguments, ensure_ascii=False)
