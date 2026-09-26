"""Hermes / Qwen3 tool calls: `<tool_call>\\n{"name": ..., "arguments": {...}}\\n</tool_call>`,
optionally after a <think> block. Shape of SGLang's qwen25 detector: text before the first
<tool_call> streams with the partial-marker suffix held back; inside a block the name is emitted
as soon as it parses and the arguments object streams as raw JSON text (so the client receives
exactly the bytes the model wrote, no re-serialisation); `</tool_call>` closes the call."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from kelpie_http.chat.parse import ToolCalls, split_holdback
from kelpie_http.chat.parse.events import Event, ReasoningDelta, TextDelta
from kelpie_http.chat.parse.think import ThinkSplitter

BOT = "<tool_call>"
EOT = "</tool_call>"
_NAME_RE = re.compile(r'"name"\s*:\s*"((?:[^"\\]|\\.)*)"')
_ARGS_RE = re.compile(r'"arguments"\s*:\s*')


class HermesParser:
    def __init__(self, *, enable_thinking: bool | None = None) -> None:
        del enable_thinking  # Qwen3 emits its own <think>; the splitter detects it either way
        self._think = ThinkSplitter()
        self._calls = ToolCalls()
        self._buf = ""
        self._call: _Call | None = None

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
        if self._call is None:
            events.extend(self._text(self._buf))  # a held partial "<tool_ca" was plain text
        else:
            events.extend(self._call.close(self._buf, self._calls, closed=False))
        self._buf = ""
        return events

    def _content(self, text: str) -> list[Event]:
        self._buf += text
        events: list[Event] = []
        while True:
            if self._call is None:
                idx = self._buf.find(BOT)
                if idx == -1:
                    emit, self._buf = split_holdback(self._buf, [BOT])
                    events.extend(self._text(emit))
                    return events
                events.extend(self._text(self._buf[:idx]))
                self._buf = self._buf[idx + len(BOT) :]
                self._call = _Call()
            idx = self._buf.find(EOT)
            if idx == -1:
                block, _ = split_holdback(self._buf, [EOT])
                events.extend(self._call.stream(block, self._calls))
                return events
            events.extend(self._call.close(self._buf[:idx], self._calls, closed=True))
            self._buf = self._buf[idx + len(EOT) :]
            self._call = None

    def _text(self, text: str) -> list[Event]:
        if not text or (self._calls.count and not text.strip()):
            return []  # "\n" between tool calls is a separator, not content
        return [TextDelta(text)]


@dataclass
class _Call:
    """One <tool_call> block as it grows. `block` is always the full text since <tool_call>."""

    started: bool = False
    args_pos: int | None = None  # index in block where the arguments object starts
    sent: int = 0  # chars of the arguments object already emitted
    done_args: bool = False
    _events: list[Event] = field(default_factory=list)

    def stream(self, block: str, calls: ToolCalls) -> list[Event]:
        events: list[Event] = []
        if not self.started:
            name = _NAME_RE.search(block)
            args = _ARGS_RE.search(block)
            if name is None or (args is not None and args.start() < name.start()):
                return events  # arguments before name: buffer until the block closes
            events.append(calls.start(json.loads('"' + name.group(1) + '"')))
            self.started = True
        if self.args_pos is None:
            args = _ARGS_RE.search(block)
            if args is None or args.end() >= len(block):
                return events
            if block[args.end()] != "{":
                self.args_pos = -1  # scalar/string arguments: emit whole at close
                return events
            self.args_pos = args.end()
        if self.args_pos < 0 or self.done_args:
            return events
        end = json_object_end(block, self.args_pos)
        upto = len(block) if end == -1 else end
        if upto > self.args_pos + self.sent:
            events.append(calls.args(block[self.args_pos + self.sent : upto]))
            self.sent = upto - self.args_pos
        self.done_args = end != -1
        return events

    def close(self, block: str, calls: ToolCalls, *, closed: bool) -> list[Event]:
        events = self.stream(block, calls) if closed else []
        parsed = parse_call(block)
        if parsed is None:
            if self.started:
                return events + [calls.end()]
            return events + ([TextDelta(BOT + block + EOT)] if closed else [])
        name, arguments = parsed
        if not self.started:
            return events + calls.whole(name, arguments)
        if self.args_pos is not None and self.args_pos < 0:
            events.append(calls.args(arguments))
        elif not self.done_args and closed and self.args_pos is None:
            events.append(calls.args(arguments))
        return events + [calls.end()]


def parse_call(block: str) -> tuple[str, str] | None:
    """(name, arguments JSON string) from a complete block, or None if it is not a tool call."""
    try:
        obj = json.loads(block.strip())
    except json.JSONDecodeError:
        return None
    if not isinstance(obj, dict) or not obj.get("name"):
        return None
    args = obj.get("arguments", obj.get("parameters", {}))
    return str(obj["name"]), args if isinstance(args, str) else json.dumps(args, ensure_ascii=False)


def json_object_end(text: str, start: int) -> int:
    """Index one past the `}` closing the object that opens at `start`, or -1 if incomplete."""
    assert text[start] == "{", text[start:]
    depth, in_str, esc = 0, False, False
    for i in range(start, len(text)):
        c = text[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c in "{[":
            depth += 1
        elif c in "}]":
            depth -= 1
            if depth == 0:
                return i + 1
    return -1
