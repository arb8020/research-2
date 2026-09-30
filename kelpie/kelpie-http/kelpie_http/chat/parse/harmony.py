"""gpt-oss (harmony): token-in over openai_harmony's StreamableParser. Channels map to events:
analysis -> reasoning, final -> text, commentary to=functions.<name> -> a tool call whose body
streams as arguments, commentary without recipient -> text (preamble). Text deltas from the
detokenizer are ignored; harmony decodes its own."""

from __future__ import annotations

from openai_harmony import HarmonyEncoding, Role, StreamableParser

from kelpie_http.chat.parse import ToolCalls
from kelpie_http.chat.parse.events import Event, ReasoningDelta, TextDelta

FUNCTIONS = "functions."


class HarmonyParser:
    def __init__(self, encoding: HarmonyEncoding, *, enable_thinking: bool | None = None) -> None:
        del enable_thinking  # the model picks its channels; nothing to force
        self._sp = StreamableParser(encoding, role=Role.ASSISTANT, strict=False)
        self._calls = ToolCalls()
        self._n_messages = 0
        self._in_call = False

    def feed(self, text_delta: str, token_ids: list[int]) -> list[Event]:
        del text_delta
        events: list[Event] = []
        for tid in token_ids:
            self._sp.process(tid)
            events.extend(self._after_token())
        return events

    def finish(self) -> list[Event]:
        return self._calls.close_if_open()

    def _after_token(self) -> list[Event]:
        events: list[Event] = []
        delta = self._sp.last_content_delta
        if delta:
            recipient = self._sp.current_recipient or ""
            if recipient.startswith(FUNCTIONS):
                if not self._in_call:
                    events.append(self._calls.start(recipient[len(FUNCTIONS) :]))
                    self._in_call = True
                events.append(self._calls.args(delta))
            elif self._sp.current_channel == "analysis":
                events.append(ReasoningDelta(delta))
            else:
                events.append(TextDelta(delta))
        if len(self._sp.messages) > self._n_messages:  # a message closed (<|end|> / <|call|>)
            self._n_messages = len(self._sp.messages)
            if self._in_call:
                events.append(self._calls.end())
                self._in_call = False
        return events
