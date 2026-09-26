"""Parser events -> OpenAI chat-completion deltas (streaming chunks) or one assembled message
(non-streaming). Shapes mirror kelpie_http.wire; the message/delta bodies are the only thing
this module adds (content, reasoning_content, tool_calls)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from kelpie_http import wire
from kelpie_http.chat.parse.events import (
    Done,
    Event,
    ReasoningDelta,
    TextDelta,
    ToolCallArgsDelta,
    ToolCallEnd,
    ToolCallStart,
)


class ChunkStream:
    """One streaming response: turns events into `data: {...}` lines. The first chunk carries
    role=assistant; Done becomes the finish chunk, "stop" promoted to "tool_calls" when calls
    were emitted (OpenAI's rule)."""

    def __init__(self, env: wire.Envelope) -> None:
        self._env = env
        self._first = True
        self._saw_calls = False

    def chunks(self, events: list[Event]) -> list[str]:
        out: list[str] = []
        for e in events:
            delta = self._delta(e)
            if delta is None:
                continue
            if self._first:
                delta = {"role": "assistant", **delta}
                self._first = False
            out.append(self._chunk(delta, None))
        return out

    def finish(self, done: Done) -> str:
        reason = (
            "tool_calls" if self._saw_calls and done.finish_reason == "stop" else done.finish_reason
        )
        delta = {"role": "assistant"} if self._first else {}
        self._first = False
        return self._chunk(delta, reason)

    def _delta(self, e: Event) -> dict[str, Any] | None:
        if isinstance(e, TextDelta):
            return {"content": e.text}
        if isinstance(e, ReasoningDelta):
            return {"reasoning_content": e.text}
        if isinstance(e, ToolCallStart):
            self._saw_calls = True
            call = {"index": e.index, "id": e.id, "type": "function"}
            return {"tool_calls": [{**call, "function": {"name": e.name, "arguments": ""}}]}
        if isinstance(e, ToolCallArgsDelta):
            return {"tool_calls": [{"index": e.index, "function": {"arguments": e.fragment}}]}
        return None  # ToolCallEnd has no wire form; Done goes through finish()

    def _chunk(self, delta: dict[str, Any], finish_reason: str | None) -> str:
        return wire.chat_sse_chunk(self._env, delta, finish_reason)


@dataclass
class Assembled:
    content: str = ""
    reasoning_content: str | None = None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    finish_reason: str = "stop"


def assemble(events: list[Event]) -> Assembled:
    """The non-streaming message: concatenated deltas, tool calls in emitted order."""
    content: list[str] = []
    reasoning: list[str] = []
    calls: dict[int, dict[str, Any]] = {}
    args: dict[int, list[str]] = {}
    reason = "stop"
    for e in events:
        if isinstance(e, TextDelta):
            content.append(e.text)
        elif isinstance(e, ReasoningDelta):
            reasoning.append(e.text)
        elif isinstance(e, ToolCallStart):
            calls[e.index] = {"id": e.id, "type": "function", "function": {"name": e.name}}
            args[e.index] = []
        elif isinstance(e, ToolCallArgsDelta):
            args[e.index].append(e.fragment)
        elif isinstance(e, ToolCallEnd):
            pass
        elif isinstance(e, Done):
            reason = e.finish_reason
    tool_calls = []
    for index in sorted(calls):
        call = calls[index]
        call["function"]["arguments"] = "".join(args[index])
        tool_calls.append(call)
    if tool_calls and reason == "stop":
        reason = "tool_calls"
    return Assembled(
        content="".join(content),
        reasoning_content="".join(reasoning) or None,
        tool_calls=tool_calls,
        finish_reason=reason,
    )


def completion_body(env: wire.Envelope, a: Assembled, usage: dict[str, Any]) -> dict[str, Any]:
    """reasoning_content and tool_calls are present only when non-empty; content is null only
    for a tool-call message without text (docs/wire-contract.md)."""
    content = None if a.tool_calls and not a.content else a.content
    body = wire.chat_completion_object(env, content, a.finish_reason, usage)
    message = body["choices"][0]["message"]
    if a.reasoning_content is not None:
        message["reasoning_content"] = a.reasoning_content
    if a.tool_calls:
        message["tool_calls"] = a.tool_calls
    return body
