"""The chat-completions fields the chat layer needs beyond wire.ChatRequest: the raw OpenAI
messages (tool_calls / tool_call_id survive; wire keeps only role + parts), tools, and the
reasoning knobs. Parsed here so wire.py stays the image/text parts parser."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ChatExtras:
    messages: list[dict[str, Any]]
    tools: list[dict[str, Any]] | None
    reasoning_effort: str | None
    enable_thinking: bool | None
    json_schema: dict[str, Any] | None
    """response_format json_schema/json_object as a JSON-schema dict ready for
    kelpie.grammar.compile_json_schema, or None for free-form generation. json_object is
    normalized to the trivial {"type": "object"} schema (docs/grammar-design.md section 1);
    the wire distinction between the two response_format kinds ends here."""


def parse_chat_extras(body: Any) -> ChatExtras:
    """Narrow tools / reasoning_effort / chat_template_kwargs.enable_thinking / response_format.
    ValueError on bad shapes; tool_choice other than auto/none is refused (no forced calls yet:
    docs/decisions.md "Tool calling order" step 2)."""
    assert isinstance(body, dict)
    messages = body.get("messages")
    if not isinstance(messages, list) or not all(isinstance(m, dict) for m in messages):
        raise ValueError("messages must be a list of objects")
    tools = body.get("tools")
    if tools is not None:
        if not isinstance(tools, list):
            raise ValueError("tools must be a list")
        for t in tools:
            fn = t.get("function") if isinstance(t, dict) else None
            if not isinstance(fn, dict) or not isinstance(fn.get("name"), str):
                raise ValueError("each tool needs function.name")
        tools = tools or None
    choice = body.get("tool_choice", "auto")
    if choice not in ("auto", "none"):
        raise ValueError("tool_choice must be 'auto' or 'none' (forced calls not supported)")
    if choice == "none":
        tools = None
    effort = body.get("reasoning_effort")
    if effort is not None and not isinstance(effort, str):
        raise ValueError("reasoning_effort must be a string")
    kwargs = body.get("chat_template_kwargs") or {}
    if not isinstance(kwargs, dict):
        raise ValueError("chat_template_kwargs must be an object")
    enable_thinking = kwargs.get("enable_thinking")
    if enable_thinking is not None and not isinstance(enable_thinking, bool):
        raise ValueError("chat_template_kwargs.enable_thinking must be a boolean")
    json_schema = parse_response_format(body.get("response_format"))
    return ChatExtras(messages, tools, effort, enable_thinking, json_schema)


def parse_response_format(response_format: Any) -> dict[str, Any] | None:
    """response_format: {"type": "json_schema", "json_schema": {"schema": {...}, ...}} or
    {"type": "json_object"} (OpenAI wire, docs/wire-contract.md rev 3 draft). Anything else
    (None, {"type": "text"}) is free-form: returns None. ValueError on a malformed json_schema
    body so a bad request is rejected before core.submit takes a slot (docs/grammar-design.md
    section 1: the grammar-compiling wait belongs entirely before submit)."""
    if response_format is None:
        return None
    if not isinstance(response_format, dict):
        raise ValueError("response_format must be an object")
    kind = response_format.get("type")
    if kind == "text" or kind is None:
        return None
    if kind == "json_object":
        return {"type": "object"}
    if kind == "json_schema":
        spec = response_format.get("json_schema")
        if not isinstance(spec, dict):
            raise ValueError("response_format.json_schema must be an object")
        schema = spec.get("schema")
        if not isinstance(schema, dict):
            raise ValueError("response_format.json_schema.schema must be an object")
        return schema
    raise ValueError(f"unsupported response_format.type: {kind!r}")
