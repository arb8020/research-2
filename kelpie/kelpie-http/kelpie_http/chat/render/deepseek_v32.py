"""DeepSeek V3.2 renderer (DSML format). Like Kimi K3, V3.2 ships no Jinja template: the format
is encoding/encoding_dsv32.py in the checkpoint. This mirrors encode_messages(thinking_mode,
drop_thinking=True) at the string level; tokens come from the HF tokenizer, whose added tokens
(<think>, </think>, <｜User｜>, <｜Assistant｜>, <｜end▁of▁sentence｜>) are matched in text the
way the reference's own callers tokenize the rendered string. tests/test_render_parity.py holds
the string equal to the checkpoint module's output on its shipped vectors and on ours.

Assistant turn: `{reasoning}</think>{content}\\n\\n<｜DSML｜function_calls>...` then EOS.
Thinking is kept only for assistant turns after the last user message; earlier ones drop it."""

from __future__ import annotations

import copy
import json
from typing import Any

from renderers.base import Message, ParsedResponse, RenderedTokens, ToolSpec

from kelpie_http.chat.parse import deepseek as fmt
from kelpie_http.chat.render.kimi_k3 import parsed_response

BOS = "<｜begin▁of▁sentence｜>"
EOS = "<｜end▁of▁sentence｜>"
THINK, THINK_END = "<think>", "</think>"
DSML = fmt.DSML
TOOLS_SYSTEM_TEMPLATE = """## Tools

You have access to a set of tools you can use to answer the user's question.
You can invoke functions by writing a "<{d}function_calls>" block like the following as part of your reply to the user:
<{d}function_calls>
<{d}invoke name="$FUNCTION_NAME">
<{d}parameter name="$PARAMETER_NAME" string="true|false">$PARAMETER_VALUE</{d}parameter>
...
</{d}invoke>
<{d}invoke name="$FUNCTION_NAME2">
...
</{d}invoke>
</{d}function_calls>

String and scalar parameters should be specified as is without any escaping or quotes, while lists and objects should use JSON format. The "string" attribute should be set to "true" for string type parameters and "false" for other types (numbers, booleans, arrays, objects).

If the thinking_mode is enabled, then after function results you should strongly consider outputting a thinking block. Here is an example:

<{d}function_calls>
...
</{d}function_calls>

<function_results>
...
</function_results>

<think>...thinking about results</think>

Here are the functions available in JSONSchema format:
<functions>
{tool_schemas}
</functions>
"""  # noqa: E501


class DeepSeekV32Renderer:
    def __init__(self, tokenizer: Any, *, thinking: bool = True) -> None:
        self._tok = tokenizer
        self.thinking = thinking
        self._eos = tokenizer.convert_tokens_to_ids(EOS)
        assert isinstance(self._eos, int) and self._eos >= 0

    def render_text(
        self,
        messages: list[Message],
        *,
        tools: list[ToolSpec] | None = None,
        add_generation_prompt: bool = True,
    ) -> str:
        """The prompt string. tools (if any) are folded into the system message the way the
        reference expects (`messages[0]["tools"]`), inserting an empty system turn if needed."""
        msgs = [dict(m) for m in messages]
        if tools:
            if not msgs or msgs[0].get("role") != "system":
                msgs.insert(0, {"role": "system", "content": ""})
            msgs[0]["tools"] = list(tools)
        assert add_generation_prompt, "V3.2 prompts always end at the assistant opener"
        mode = "thinking" if self.thinking else "chat"
        return BOS + encode_messages(msgs, mode)  # type: ignore[arg-type]

    def render(
        self,
        messages: list[Message],
        *,
        tools: list[ToolSpec] | None = None,
        add_generation_prompt: bool = False,
    ) -> RenderedTokens:
        text = self.render_text(messages, tools=tools, add_generation_prompt=add_generation_prompt)
        ids = self._tok.encode(text, add_special_tokens=False)
        return RenderedTokens(
            token_ids=ids,
            message_indices=[-1] * len(ids),
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

    def parse_response(
        self, token_ids: list[int], *, tools: list[ToolSpec] | None = None
    ) -> ParsedResponse:
        del tools
        ids = list(token_ids)
        if self._eos in ids:
            ids = ids[: ids.index(self._eos)]
        parser = fmt.DeepSeekParser(enable_thinking=self.thinking)
        events = parser.feed(self._tok.decode(ids), ids) + parser.finish()
        return parsed_response(events)

    def get_stop_token_ids(self) -> list[int]:
        return [self._eos]

    def bridge_to_next_turn(
        self,
        previous_prompt_ids: list[int],
        previous_completion_ids: list[int],
        new_messages: list[Message],
        *,
        tools: list[ToolSpec] | None = None,
    ) -> RenderedTokens | None:
        return None  # tool results depend on the assistant's tool_calls count; re-render instead


# ---- string-level mirror of encoding_dsv32 ---------------------------------------------------


def encode_messages(messages: list[dict[str, Any]], thinking_mode: str) -> str:
    assert thinking_mode in ("chat", "thinking")
    if thinking_mode == "thinking":
        messages = drop_thinking(messages)
    last_user = last_user_index(messages)
    return "".join(
        render_message(i, messages, thinking_mode, last_user) for i in range(len(messages))
    )


def render_message(i: int, messages: list[dict[str, Any]], mode: str, last_user: int) -> str:
    msg = messages[i]
    role, content = msg.get("role"), msg.get("content")
    tools = [t["function"] for t in msg.get("tools") or []]
    if role == "system":
        out = content or ""
        if tools:
            out += "\n\n" + render_tools(tools)
        return out
    if role == "user":
        out = f"<｜User｜>{content}<｜Assistant｜>"
        return out + (THINK if i == last_user and mode == "thinking" else THINK_END)
    if role == "tool":
        return render_tool_result(i, messages, mode, last_user)
    if role == "assistant":
        tool_calls = msg.get("tool_calls") or []
        calls = ""
        if tool_calls:
            invokes = "\n".join(render_invoke(tc["function"]) for tc in tool_calls)
            calls = f"\n\n<{DSML}function_calls>\n{invokes}\n</{DSML}function_calls>"
        thinking = ""
        if mode == "thinking" and i > last_user:
            thinking = (msg.get("reasoning_content") or "") + THINK_END
        return f"{thinking}{content or ''}{calls}{EOS}"
    raise ValueError(f"unknown role {role!r}")


def render_tool_result(i: int, messages: list[dict[str, Any]], mode: str, last_user: int) -> str:
    j = i - 1
    while j >= 0 and messages[j].get("role") == "tool":
        j -= 1
    assert j >= 0 and messages[j].get("role") == "assistant", "tool result without assistant"
    order = i - j
    n_calls = len(messages[j].get("tool_calls") or [])
    assert 1 <= order <= n_calls, "tool result without a matching tool call"
    out = "\n\n<function_results>" if order == 1 else ""
    out += f"\n<result>{messages[i].get('content')}</result>"
    if order == n_calls:
        out += "\n</function_results>\n\n"
        out += THINK if i >= last_user and mode == "thinking" else THINK_END
    return out


def render_invoke(fn: dict[str, Any]) -> str:
    args = fn["arguments"]
    if isinstance(args, str):
        args = json.loads(args)
    params = "\n".join(
        f'<{DSML}parameter name="{k}" string="{"true" if isinstance(v, str) else "false"}">'
        f"{v if isinstance(v, str) else to_json(v)}</{DSML}parameter>"
        for k, v in args.items()
    )
    return f'<{DSML}invoke name="{fn["name"]}">\n{params}\n</{DSML}invoke>'


def render_tools(tools: list[dict[str, Any]]) -> str:
    return TOOLS_SYSTEM_TEMPLATE.format(d=DSML, tool_schemas="\n".join(to_json(t) for t in tools))


def to_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def last_user_index(messages: list[dict[str, Any]]) -> int:
    for i in range(len(messages) - 1, -1, -1):
        if messages[i].get("role") in ("user", "developer"):
            return i
    return -1


def drop_thinking(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    last_user = last_user_index(messages)
    out = []
    for i, m in enumerate(messages):
        if m.get("role") == "assistant" and i < last_user:
            m = copy.copy(m)
            m.pop("reasoning_content", None)
        out.append(m)
    return out
