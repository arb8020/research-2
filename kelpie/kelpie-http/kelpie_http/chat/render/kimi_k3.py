"""Kimi K3 renderer in the `renderers` Renderer shape (render / parse_response / stop ids /
bridge_to_next_turn). K3 ships no Jinja template: its chat format is Python (encoding_k3.py in the
checkpoint, reached through tokenizer.apply_chat_template with trust_remote_code). This is a
reimplementation of that module's build_chat_segments; tests/test_render_parity.py holds it
byte-equal to the checkpoint's own rendering.

Structural markers (<|open|>, <|close|>, <|sep|>, <|end_of_msg|>) are single special tokens; tag
names, attributes and all message text are ordinary BPE text (a user who types "<|open|>" gets
text tokens, never the control token). Tool arguments render as typed XTML arguments; an
arguments string that is not a JSON object falls back to a raw <|open|>json ...<|sep|> block.
"""

from __future__ import annotations

import json
from typing import Any

from renderers.base import (
    Message,
    ParsedResponse,
    ParsedToolCall,
    RenderedTokens,
    ToolCallParseStatus,
    ToolSpec,
)

from kelpie_http.chat.parse import kimi_k3 as fmt
from kelpie_http.chat.parse.events import (
    Event,
    ReasoningDelta,
    TextDelta,
    ToolCallArgsDelta,
    ToolCallStart,
)

OPEN, CLOSE, SEP, END_OF_MSG = "<|open|>", "<|close|>", "<|sep|>", "<|end_of_msg|>"
EOS = "[EOS]"
THINKING_EFFORTS = ("low", "high", "max")
DEFAULT_THINKING_EFFORT = "max"  # the checkpoint's apply_chat_template default


class KimiK3Renderer:
    def __init__(
        self, tokenizer: Any, *, thinking: bool = True, thinking_effort: str | None = "max"
    ) -> None:
        self._tok = tokenizer
        self.thinking = thinking
        self.thinking_effort = thinking_effort
        self._open = special_id(tokenizer, OPEN)
        self._close = special_id(tokenizer, CLOSE)
        self._sep = special_id(tokenizer, SEP)
        self._end_of_msg = special_id(tokenizer, END_OF_MSG)
        self._eos = special_id(tokenizer, EOS)

    # ---- render ------------------------------------------------------------------------------

    def render(
        self,
        messages: list[Message],
        *,
        tools: list[ToolSpec] | None = None,
        add_generation_prompt: bool = False,
    ) -> RenderedTokens:
        segments = self.segments(messages, tools=tools, add_generation_prompt=add_generation_prompt)
        ids: list[int] = []
        indices: list[int] = []
        for msg_idx, text, special in segments:
            piece = [self._special(text)] if special else self._encode(text)
            ids.extend(piece)
            indices.extend([msg_idx] * len(piece))
        return RenderedTokens(
            token_ids=ids,
            message_indices=indices,
            message_roles=[m.get("role") or "" for m in messages],
        )

    def render_ids(
        self,
        messages: list[Message],
        *,
        tools: list[ToolSpec] | None = None,
        add_generation_prompt: bool = False,
    ) -> list[int]:
        return self.render(
            messages, tools=tools, add_generation_prompt=add_generation_prompt
        ).token_ids

    def segments(
        self,
        messages: list[Message],
        *,
        tools: list[ToolSpec] | None = None,
        add_generation_prompt: bool = False,
    ) -> list[tuple[int, str, bool]]:
        """(message index or -1, text, is_control) triples; the tokenizer-independent core."""
        messages = reorder_tool_results(messages)
        out = _Segments()
        if tools:
            out.declare(-1, deep_sort(tools))
        effort = self.thinking_effort
        if self.thinking and effort is not None:
            assert effort in THINKING_EFFORTS, effort
            out.internal_system(
                -1,
                "thinking-effort",
                "`thinking_effort` guides on how much to think in your thinking channel (not "
                "including the response channel), supported values include `low`, `medium`, "
                f"`high`, and `max`.\nNow the system is invoked with `thinking_effort={effort}`.",
            )
        tool_calls: list[Any] = []
        tool_index = 0
        for i, msg in enumerate(messages):
            role = msg.get("role")
            if role == "user" or (role == "system" and not msg.get("tools")):
                attrs = [("role", role)] + ([("name", msg.get("name"))] if msg.get("name") else [])
                out.open(i, "message", attrs)
                out.text(i, content_text(msg.get("content")))
                out.close(i, "message")
                out.end_of_msg(i)
            elif role == "system":
                out.declare(i, deep_sort(msg.get("tools")), dynamic=True)
            elif role == "tool":
                tool_index += 1
                name = msg.get("tool", msg.get("name"))
                if name is None and tool_index <= len(tool_calls):
                    fn = tool_calls[tool_index - 1]
                    name = fn.get("function", fn)["name"]
                if name is None:
                    raise ValueError("Kimi K3 tool messages need a name or a matching tool_call")
                out.open(i, "message", [("role", "tool"), ("tool", name), ("index", tool_index)])
                out.text(i, content_text(msg.get("content")))
                out.close(i, "message")
                out.end_of_msg(i)
            elif role == "assistant":
                tool_calls = list(msg.get("tool_calls") or [])
                tool_index = 0
                attrs = [("role", "assistant")] + (
                    [("name", msg.get("name"))] if msg.get("name") else []
                )
                out.open(i, "message", attrs)
                self._assistant(out, i, msg)
                out.close(i, "message")
                out.end_of_msg(i)
            else:
                raise ValueError(f"unknown role {role!r} at message {i}")
        if add_generation_prompt:
            out.open(-1, "message", [("role", "assistant")])
            out.open(-1, "think" if self.thinking else "response")
        return out.items

    def _assistant(self, out: _Segments, i: int, msg: Message) -> None:
        if self.thinking:
            out.open(i, "think")
            reasoning = msg.get("reasoning_content") or msg.get("reasoning")
            if reasoning is not None and str(reasoning) != "":
                out.text(i, str(reasoning))
            out.close(i, "think")
        out.open(i, "response")
        out.text(i, content_text(msg.get("content")))
        out.close(i, "response")
        tool_calls = msg.get("tool_calls") or []
        if not tool_calls:
            return
        out.open(i, "tools")
        for index, tc in enumerate(tool_calls, start=1):
            fn = tc.get("function", tc)
            out.open(i, "call", [("tool", fn.get("name")), ("index", index)])
            args, json_block = normalize_arguments(fn.get("arguments"))
            if json_block is not None:
                out.open(i, "json", [("type", "object")])
                out.text(i, json_block)
                out.close(i, "json")
            for key, kind, text in args:
                out.open(i, "argument", [("key", key), ("type", kind)])
                out.text(i, text)
                out.close(i, "argument")
            out.close(i, "call")
        out.close(i, "tools")

    # ---- parse -------------------------------------------------------------------------------

    def parse_response(
        self, token_ids: list[int], *, tools: list[ToolSpec] | None = None
    ) -> ParsedResponse:
        del tools
        stop = set(self.get_stop_token_ids())
        ids = list(token_ids)
        for k, t in enumerate(ids):
            if t in stop:
                ids = ids[:k]
                break
        parser = fmt.KimiK3Parser(enable_thinking=self.thinking)
        events = parser.feed(self._tok.decode(ids), ids) + parser.finish()
        return parsed_response(events)

    def get_stop_token_ids(self) -> list[int]:
        return [self._end_of_msg, self._eos]

    def bridge_to_next_turn(
        self,
        previous_prompt_ids: list[int],
        previous_completion_ids: list[int],
        new_messages: list[Message],
        *,
        tools: list[ToolSpec] | None = None,
    ) -> RenderedTokens | None:
        """prev prompt + completion, closed at <|end_of_msg|> (synthesised with the message close
        if the turn was cut), then the new tool/user messages and a fresh generation prompt."""
        del tools  # declared once at the top of the conversation; never re-rendered
        if any(m.get("role") == "assistant" for m in new_messages):
            return None
        prior = list(previous_prompt_ids) + list(previous_completion_ids)
        if self._end_of_msg not in previous_completion_ids:
            prior += [self._close, *self._encode("message"), self._sep, self._end_of_msg]
        tail = self.render(new_messages, add_generation_prompt=True)
        if self.thinking and self.thinking_effort is not None:  # the preamble is not re-emitted
            tail_ids = strip_thinking_effort(self, tail.token_ids)
        else:
            tail_ids = tail.token_ids
        n_tail = len(tail_ids)
        return RenderedTokens(
            token_ids=prior + tail_ids,
            message_indices=[-1] * len(prior)
            + tail.message_indices[len(tail.token_ids) - n_tail :],
            message_roles=[m.get("role") or "" for m in new_messages],
        )

    def _special(self, text: str) -> int:
        return {OPEN: self._open, CLOSE: self._close, SEP: self._sep, END_OF_MSG: self._end_of_msg}[
            text
        ]

    def _encode(self, text: str) -> list[int]:
        if not text:
            return []
        try:
            return self._tok.encode(text, allow_special_tokens=False)  # the K3 tiktoken wrapper
        except TypeError:
            return self._tok.encode(text, add_special_tokens=False)


def strip_thinking_effort(r: KimiK3Renderer, ids: list[int]) -> list[int]:
    """Drop the leading thinking-effort system message a fresh render() prepends."""
    n_end = 0
    for k, t in enumerate(ids):
        if t == r._end_of_msg:
            n_end = k + 1
            break
    return ids[n_end:]


def parsed_response(events: list[Event]) -> ParsedResponse:
    content, reasoning, calls = [], [], []
    args: dict[int, list[str]] = {}
    names: dict[int, str] = {}
    for e in events:
        if isinstance(e, TextDelta):
            content.append(e.text)
        elif isinstance(e, ReasoningDelta):
            reasoning.append(e.text)
        elif isinstance(e, ToolCallStart):
            names[e.index] = e.name
            args[e.index] = []
        elif isinstance(e, ToolCallArgsDelta):
            args[e.index].append(e.fragment)
    for index, name in names.items():
        raw = "".join(args[index])
        calls.append(
            ParsedToolCall(
                raw=raw, name=name, arguments=json.loads(raw), status=ToolCallParseStatus.OK
            )
        )
    return ParsedResponse(
        content="".join(content).strip(),
        reasoning_content="".join(reasoning).strip() or None,
        tool_calls=calls,
    )


# ---- format helpers (mirror encoding_k3.py) --------------------------------------------------


class _Segments:
    def __init__(self) -> None:
        self.items: list[tuple[int, str, bool]] = []

    def text(self, i: int, text: str) -> None:
        if text:
            self.items.append((i, text, False))

    def control(self, i: int, tok: str) -> None:
        self.items.append((i, tok, True))

    def open(self, i: int, tag: str, attrs: list[tuple[str, Any]] | None = None) -> None:
        self.control(i, OPEN)
        self.text(i, tag)
        for key, value in attrs or []:
            self.text(i, f" {key}")
            self.text(i, '="')
            self.text(i, str(value).replace("&", "&amp;").replace('"', "&quot;"))
            self.text(i, '"')
        self.control(i, SEP)

    def close(self, i: int, tag: str) -> None:
        self.control(i, CLOSE)
        self.text(i, tag)
        self.control(i, SEP)

    def end_of_msg(self, i: int) -> None:
        self.control(i, END_OF_MSG)

    def internal_system(self, i: int, kind: str, body: str) -> None:
        self.open(i, "message", [("role", "system"), ("type", kind)])
        self.text(i, body.strip())
        self.close(i, "message")
        self.end_of_msg(i)

    def declare(self, i: int, tools: Any, *, dynamic: bool = False) -> None:
        compact = json.dumps(tools, ensure_ascii=False, separators=(",", ":"))
        if dynamic:
            body = (
                "## New Tools Available\nThe system dynamically extends the toolset via "
                "lazy-loading.\nYou have access to all existing and extended tools.\n"
                f"Here are the specs for the extended tools.\n\n```json\n{compact}\n```"
            )
        else:
            body = (
                "# Tools\nHere are the available tools, described in JSONSchema.\n\n"
                f"```json\n{compact}\n```"
            )
        self.open(i, "message", [("role", "system"), ("type", "tool-declare")])
        self.text(i, body)
        self.close(i, "message")
        self.end_of_msg(i)


def content_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    return "".join(str(p.get("text", "")) for p in content if isinstance(p, dict))


def xtml_type(value: Any) -> str:
    if isinstance(value, bool):
        return "boolean"
    if value is None:
        return "null"
    if isinstance(value, int | float):
        return "number"
    if isinstance(value, str):
        return "string"
    return "object" if isinstance(value, dict) else "array"


def normalize_arguments(arguments: Any) -> tuple[list[tuple[str, str, str]], str | None]:
    """(key, type, text) triples, or (.., raw json block) when a string is not a JSON object.
    A JSON-string argument is parsed one level deep so nested literals keep their bytes."""
    if arguments is None or arguments == "":
        return [], None
    if isinstance(arguments, dict):
        return [
            (str(k), xtml_type(v), v if isinstance(v, str) else json.dumps(v, ensure_ascii=False))
            for k, v in arguments.items()
        ], None
    assert isinstance(arguments, str), type(arguments)
    try:
        return parse_object_shallow(arguments), None
    except ValueError:
        return [], arguments


def parse_object_shallow(s: str) -> list[tuple[str, str, str]]:
    """Top-level (key, type, literal text) of a JSON object string; ValueError if not one."""
    dec = json.JSONDecoder(strict=False)
    i = skip_ws(s, 0)
    if i >= len(s) or s[i] != "{":
        raise ValueError("not a JSON object")
    i = skip_ws(s, i + 1)
    out: list[tuple[str, str, str]] = []
    if i < len(s) and s[i] == "}":
        return out
    while True:
        try:
            key, i = dec.raw_decode(s, i)
        except json.JSONDecodeError as e:
            raise ValueError(str(e)) from e
        if not isinstance(key, str):
            raise ValueError("key must be a string")
        i = skip_ws(s, i)
        if i >= len(s) or s[i] != ":":
            raise ValueError("expected ':'")
        i = skip_ws(s, i + 1)
        try:
            value, j = dec.raw_decode(s, i)
        except json.JSONDecodeError as e:
            raise ValueError(str(e)) from e
        out.append((key, xtml_type(value), value if isinstance(value, str) else s[i:j]))
        i = skip_ws(s, j)
        c = s[i] if i < len(s) else None
        i = skip_ws(s, i + 1)
        if c == "}":
            return out
        if c != ",":
            raise ValueError("expected ',' or '}'")


def skip_ws(s: str, i: int) -> int:
    while i < len(s) and s[i] in " \t\n\r":
        i += 1
    return i


def deep_sort(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: deep_sort(v) for k, v in sorted(obj.items())}
    if isinstance(obj, list):
        return [deep_sort(x) for x in obj]
    return obj


def reorder_tool_results(messages: list[Message]) -> list[Message]:
    """Each run of tool messages is sorted into the preceding assistant's tool_calls order by
    tool_call_id, and given that call's function name; an unmatched run is left as is."""
    out: list[Message] = []
    index: dict[str, tuple[int, str | None]] = {}
    i = 0
    while i < len(messages):
        m = messages[i]
        if m.get("role") == "assistant":
            index = {}
            for pos, tc in enumerate(m.get("tool_calls") or [], start=1):
                call_id = tc.get("id")
                if call_id is not None and str(call_id) not in index:
                    fn = tc.get("function", tc)
                    index[str(call_id)] = (pos, fn.get("name"))
            out.append(m)
            i += 1
            continue
        if m.get("role") != "tool":
            out.append(m)
            i += 1
            continue
        run: list[tuple[int, int, Message, str | None]] = []
        unresolved = False
        while i < len(messages) and messages[i].get("role") == "tool":
            t = messages[i]
            call_id = t.get("tool_call_id", t.get("id"))
            hit = index.get(str(call_id)) if call_id is not None else None
            if hit is None:
                unresolved = True
                run.append((0, len(run), t, None))
            else:
                run.append((hit[0], len(run), t, hit[1]))
            i += 1
        if unresolved:
            out.extend(t for _, _, t, _ in run)
            continue
        for _, _, t, name in sorted(run, key=lambda r: (r[0], r[1])):
            resolved = dict(t)
            if name is not None:
                resolved["tool"] = name
                if "name" in resolved:
                    resolved["name"] = name
            out.append(resolved)  # type: ignore[arg-type]
    return out


def special_id(tokenizer: Any, token: str) -> int:
    tid = tokenizer.convert_tokens_to_ids(token)
    assert isinstance(tid, int) and tid >= 0, (token, tid)
    return tid
