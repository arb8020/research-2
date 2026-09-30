"""The parser -> wire event vocabulary. A parser turns a model's raw completion (text deltas or
token ids) into these; sse.py turns them into OpenAI chunk deltas. Nothing here knows a format."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TextDelta:
    text: str


@dataclass(frozen=True)
class ReasoningDelta:
    text: str


@dataclass(frozen=True)
class ToolCallStart:
    index: int
    id: str
    name: str


@dataclass(frozen=True)
class ToolCallArgsDelta:
    index: int
    fragment: str  # a piece of the arguments JSON string, in order


@dataclass(frozen=True)
class ToolCallEnd:
    index: int


@dataclass(frozen=True)
class Done:
    finish_reason: str  # "stop" | "length"; sse.py promotes "stop" to "tool_calls" when calls ran


Event = TextDelta | ReasoningDelta | ToolCallStart | ToolCallArgsDelta | ToolCallEnd | Done
