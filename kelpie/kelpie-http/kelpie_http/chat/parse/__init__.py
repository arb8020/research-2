"""Streaming parser contract plus the helpers every format parser shares.

A Parser sees the completion as it is produced: `feed(text_delta, token_ids)` per poll (text is
the detokenized delta with stop tokens removed; token_ids are the raw new ids, stop tokens
included, for token-in formats like harmony) and `finish()` once, after the last poll. Both return
the events that became certain with that input. A parser never leaks a partial marker into a
TextDelta: it holds back any buffer suffix that could still grow into one (`partial_suffix_len`).
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Protocol

from kelpie_http.chat.parse.events import (
    Event,
    TextDelta,
    ToolCallArgsDelta,
    ToolCallEnd,
    ToolCallStart,
)


class Parser(Protocol):
    def feed(self, text_delta: str, token_ids: list[int]) -> list[Event]: ...
    def finish(self) -> list[Event]: ...


ParserFactory = Callable[..., Parser]
"""`factory(*, enable_thinking: bool | None = None) -> Parser`. Formats whose generation prompt
ends inside the think channel (GLM, K3, DeepSeek) need to know whether it did."""


class PlainParser:
    """No format: every text delta is content (a chat without a codec, e.g. the VLM image path)."""

    def __init__(self, *, enable_thinking: bool | None = None) -> None:
        del enable_thinking

    def feed(self, text_delta: str, token_ids: list[int]) -> list[Event]:
        del token_ids
        return [TextDelta(text_delta)] if text_delta else []

    def finish(self) -> list[Event]:
        return []


def partial_suffix_len(text: str, markers: list[str]) -> int:
    """Length of the longest suffix of `text` that is a proper prefix of some marker: the bytes
    to hold back because the next delta could complete the marker."""
    best = 0
    for marker in markers:
        for length in range(min(len(marker) - 1, len(text)), best, -1):
            if text.endswith(marker[:length]):
                best = length
                break
    return best


def split_holdback(text: str, markers: list[str]) -> tuple[str, str]:
    """(emit, keep): `keep` is the partial-marker suffix, `emit` everything before it."""
    n = partial_suffix_len(text, markers)
    return (text[:-n], text[-n:]) if n else (text, "")


def find_first(text: str, markers: list[str], start: int = 0) -> tuple[int, str | None]:
    """Earliest occurrence of any marker at or after `start`: (index, marker) or (-1, None)."""
    best, hit = -1, None
    for marker in markers:
        idx = text.find(marker, start)
        if idx != -1 and (best == -1 or idx < best):
            best, hit = idx, marker
    return best, hit


class ToolCalls:
    """Assigns indexes and ids; the one place tool-call events are minted."""

    def __init__(self) -> None:
        self.count = 0
        self.open: int | None = None

    def start(self, name: str) -> ToolCallStart:
        assert self.open is None, "previous tool call not ended"
        self.open = self.count
        self.count += 1
        return ToolCallStart(self.open, new_call_id(), name)

    def args(self, fragment: str) -> ToolCallArgsDelta:
        assert self.open is not None
        return ToolCallArgsDelta(self.open, fragment)

    def end(self) -> ToolCallEnd:
        assert self.open is not None
        index, self.open = self.open, None
        return ToolCallEnd(index)

    def whole(self, name: str, arguments_json: str) -> list[Event]:
        """A call that arrived complete: start, all arguments, end."""
        return [self.start(name), self.args(arguments_json), self.end()]

    def close_if_open(self) -> list[Event]:
        return [self.end()] if self.open is not None else []


def new_call_id() -> str:
    return "call_" + uuid.uuid4().hex[:24]
