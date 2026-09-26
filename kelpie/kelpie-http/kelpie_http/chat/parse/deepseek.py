"""DeepSeek V3.2 (DSML) tool calls. Shape of a thinking-mode assistant turn (the prompt ends in
`<think>`):

    thought</think>answer\\n\\n<｜DSML｜function_calls>\\n<｜DSML｜invoke name="f">\\n
    <｜DSML｜parameter name="k" string="true">v</｜DSML｜parameter>\\n</｜DSML｜invoke>\\n
    </｜DSML｜function_calls><｜end▁of▁sentence｜>

Reference: encoding_dsv32.parse_message_from_completion_text (non-streaming, asserts on any
deviation). This one streams: think -> content -> tools, each invoke emitted whole at its close.
Values with string="true" are strings verbatim; others are JSON."""

from __future__ import annotations

import json
import re

from kelpie_http.chat.parse import ToolCalls, partial_suffix_len
from kelpie_http.chat.parse.events import Event, ReasoningDelta, TextDelta
from kelpie_http.chat.parse.think import ThinkSplitter

DSML = "｜DSML｜"
FC_OPEN = f"<{DSML}function_calls>"
FC_CLOSE = f"</{DSML}function_calls>"
_INVOKE_RE = re.compile(
    rf'<{DSML}invoke name="(?P<name>[^"]*)">(?P<body>.*?)</{DSML}invoke>', re.DOTALL
)
_PARAM_RE = re.compile(
    rf'<{DSML}parameter name="(?P<name>[^"]*)" string="(?P<string>true|false)">'
    rf"(?P<val>.*?)</{DSML}parameter>",
    re.DOTALL,
)


class DeepSeekParser:
    def __init__(self, *, enable_thinking: bool | None = None) -> None:
        self._think = ThinkSplitter(force=enable_thinking is not False)
        self._calls = ToolCalls()
        self._buf = ""
        self._in_tools = False

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
        if not self._in_tools:
            if buf and not (buf.strip() == "" and self._calls.count):
                events.append(TextDelta(buf))
        return events + self._calls.close_if_open()

    def _content(self, text: str) -> list[Event]:
        self._buf += text
        events: list[Event] = []
        while True:
            if not self._in_tools:
                idx = self._buf.find(FC_OPEN)
                if idx == -1:
                    events.extend(self._emit_text(self._safe_prefix()))
                    return events
                events.extend(self._emit_text(self._buf[:idx].rstrip()))
                self._buf = self._buf[idx + len(FC_OPEN) :]
                self._in_tools = True
            while (m := _INVOKE_RE.search(self._buf)) is not None:
                events.extend(self._calls.whole(m["name"], decode_params(m["body"])))
                self._buf = self._buf[m.end() :]
            idx = self._buf.find(FC_CLOSE)
            if idx == -1:
                return events
            self._buf = self._buf[idx + len(FC_CLOSE) :]
            self._in_tools = False

    def _safe_prefix(self) -> str:
        """Text certain not to be the `\\n\\n` + marker that opens a tools section."""
        n = partial_suffix_len(self._buf, [FC_OPEN])
        head = self._buf[:-n] if n else self._buf
        keep = len(head) - len(head.rstrip())  # trailing whitespace may precede FC_OPEN
        cut = len(head) - keep
        emit, self._buf = self._buf[:cut], self._buf[cut:]
        return emit

    def _emit_text(self, text: str) -> list[Event]:
        if not text or (self._calls.count and not text.strip()):
            return []
        return [TextDelta(text)]


def decode_params(body: str) -> str:
    arguments: dict[str, object] = {}
    for p in _PARAM_RE.finditer(body):
        if p["string"] == "true":
            arguments[p["name"]] = p["val"]
        else:
            try:
                arguments[p["name"]] = json.loads(p["val"])
            except json.JSONDecodeError:
                arguments[p["name"]] = p["val"]
    return json.dumps(arguments, ensure_ascii=False)
