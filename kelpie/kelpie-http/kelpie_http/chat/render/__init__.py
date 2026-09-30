"""OpenAI chat messages + tools -> prompt token ids, per model family.

`render(messages, tools, *, reasoning_effort=None, enable_thinking=None) -> list[int]` is the
one shape the server calls. Families: Qwen3 / GLM-5 / Llama-3 via PrimeIntellect `renderers`
(hand-coded mirrors of the Jinja templates), gpt-oss via openai_harmony (the format's reference
encoder), Kimi K3 and DeepSeek V3.2 via our ports of their Python encoders (neither ships Jinja),
and `default` = the tokenizer's own apply_chat_template (SmolLM/SmolVLM and anything unknown).

Messages arrive in OpenAI wire shape and are normalised once here (`normalize_messages`): null
content -> "", content parts -> text, JSON-string tool arguments -> objects, tool results given
the function name of the call they answer. Every renderer downstream sees the same thing."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from datetime import date
from typing import Any

RenderFn = Callable[..., list[int]]
"""render(messages, tools, *, reasoning_effort=None, enable_thinking=None) -> list[int]"""

FAMILIES = ("qwen3", "gpt-oss", "kimi-k3", "deepseek-v3.2", "glm-5", "llama-3", "default")
HARMONY_EFFORTS = ("low", "medium", "high")


def make_render(family: str, tokenizer: Any) -> RenderFn:
    assert family in FAMILIES, family
    builders: dict[str, Callable[[Any], RenderFn]] = {
        "qwen3": qwen3_render,
        "gpt-oss": gpt_oss_render,
        "kimi-k3": kimi_k3_render,
        "deepseek-v3.2": deepseek_v32_render,
        "glm-5": glm5_render,
        "llama-3": llama3_render,
        "default": default_render,
    }
    return builders[family](tokenizer)


def stop_token_ids(family: str, tokenizer: Any) -> tuple[int, ...]:
    """The ids that end an assistant turn in this format (the renderer's stop set)."""
    if family == "gpt-oss":
        return tuple(int(tokenizer.convert_tokens_to_ids(t)) for t in ("<|return|>", "<|call|>"))
    if family == "default":
        ids = [tokenizer.eos_token_id]
        eou = tokenizer.convert_tokens_to_ids("<end_of_utterance>")  # SmolVLM's turn end
        if isinstance(eou, int) and eou >= 0 and eou != tokenizer.unk_token_id:
            ids.append(eou)
        return tuple(int(i) for i in ids if i is not None)
    return tuple(int(i) for i in renderer_for(family, tokenizer).get_stop_token_ids())


def renderer_for(
    family: str, tokenizer: Any, *, enable_thinking: bool | None = None, reasoning_effort=None
) -> Any:
    """A `renderers`-shaped object for the families that have one (all but gpt-oss/default)."""
    thinking = enable_thinking is not False
    if family == "qwen3":
        from renderers.configs import Qwen3RendererConfig
        from renderers.qwen3 import Qwen3Renderer

        return Qwen3Renderer(tokenizer, Qwen3RendererConfig(enable_thinking=thinking))
    if family == "glm-5":
        from renderers.configs import GLM51RendererConfig
        from renderers.glm5 import GLM51Renderer

        return GLM51Renderer(tokenizer, GLM51RendererConfig(enable_thinking=thinking))
    if family == "llama-3":
        from renderers.llama_3 import Llama3Renderer

        return Llama3Renderer(tokenizer)
    if family == "kimi-k3":
        from kelpie_http.chat.render.kimi_k3 import DEFAULT_THINKING_EFFORT, KimiK3Renderer

        return KimiK3Renderer(
            tokenizer,
            thinking=thinking,
            thinking_effort=reasoning_effort or DEFAULT_THINKING_EFFORT,
        )
    if family == "deepseek-v3.2":
        from kelpie_http.chat.render.deepseek_v32 import DeepSeekV32Renderer

        return DeepSeekV32Renderer(tokenizer, thinking=thinking)
    raise ValueError(f"no renderer object for family {family!r}")


# ---- families --------------------------------------------------------------------------------


def qwen3_render(tokenizer: Any) -> RenderFn:
    """renderers' Qwen3Renderer, except with thinking off: it then re-emits the empty
    `<think>\n\n</think>\n\n` wrapper on historical assistant turns on purpose (token-stable
    RL rollouts); serving wants the checkpoint's template, so that case is the Jinja itself."""

    def render(messages, tools, *, reasoning_effort=None, enable_thinking=None):
        del reasoning_effort  # Qwen3's template has no effort knob
        msgs = normalize_messages(messages)
        if enable_thinking is False:
            return apply(tokenizer, msgs, tools, {"enable_thinking": False})
        r = renderer_for("qwen3", tokenizer, enable_thinking=enable_thinking)
        return r.render_ids(msgs, tools=tools, add_generation_prompt=True)

    return render


def glm5_render(tokenizer: Any) -> RenderFn:
    """GLM-5.2 = the GLM-5.1 template with two token-level differences, applied here on top of
    renderers' GLM51Renderer (all four markers are single special tokens, so the edits are exact;
    tests/test_render_parity.py checks them against the checkpoint's Jinja):
    - a `<|system|>Reasoning Effort: {High|Max}` line right after `[gMASK]<sop>` whenever
      thinking is on ('high' is honoured; anything else is Max);
    - a cleared or disabled think block is `<think></think>`, never a bare `</think>`."""
    system_id = int(tokenizer.convert_tokens_to_ids("<|system|>"))
    assistant_id = int(tokenizer.convert_tokens_to_ids("<|assistant|>"))
    think_id = int(tokenizer.convert_tokens_to_ids("<think>"))
    think_end_id = int(tokenizer.convert_tokens_to_ids("</think>"))

    def render(messages, tools, *, reasoning_effort=None, enable_thinking=None):
        r = renderer_for("glm-5", tokenizer, enable_thinking=enable_thinking)
        ids = r.render_ids(normalize_messages(messages), tools=tools, add_generation_prompt=True)
        out: list[int] = []
        for k, t in enumerate(ids):
            out.append(t)
            if t == assistant_id and k + 1 < len(ids) and ids[k + 1] == think_end_id:
                out.append(think_id)
        if enable_thinking is False:
            return out
        effort = "High" if reasoning_effort == "high" else "Max"
        line = [
            system_id,
            *tokenizer.encode(f"Reasoning Effort: {effort}", add_special_tokens=False),
        ]
        return out[:2] + line + out[2:]  # after [gMASK]<sop>

    return render


def llama3_render(tokenizer: Any) -> RenderFn:
    def render(messages, tools, *, reasoning_effort=None, enable_thinking=None):
        del reasoning_effort, enable_thinking  # no reasoning channel
        r = renderer_for("llama-3", tokenizer)
        return r.render_ids(normalize_messages(messages), tools=tools, add_generation_prompt=True)

    return render


def kimi_k3_render(tokenizer: Any) -> RenderFn:
    def render(messages, tools, *, reasoning_effort=None, enable_thinking=None):
        from kelpie_http.chat.render.kimi_k3 import THINKING_EFFORTS

        if reasoning_effort is not None and reasoning_effort not in THINKING_EFFORTS:
            raise ValueError(f"Kimi K3 reasoning_effort must be one of {THINKING_EFFORTS}")
        r = renderer_for(
            "kimi-k3", tokenizer, enable_thinking=enable_thinking, reasoning_effort=reasoning_effort
        )
        return r.render_ids(normalize_messages(messages), tools=tools, add_generation_prompt=True)

    return render


def deepseek_v32_render(tokenizer: Any) -> RenderFn:
    def render(messages, tools, *, reasoning_effort=None, enable_thinking=None):
        del reasoning_effort
        r = renderer_for("deepseek-v3.2", tokenizer, enable_thinking=enable_thinking)
        return r.render_ids(normalize_messages(messages), tools=tools, add_generation_prompt=True)

    return render


def gpt_oss_render(tokenizer: Any) -> RenderFn:
    """openai_harmony's render_conversation_for_completion over our message conversion (the
    HF Jinja template is not byte-identical to harmony; harmony is what the model was trained
    on and what vLLM serves)."""
    del tokenizer  # harmony carries its own o200k encoding
    import openai_harmony as h

    enc = h.load_harmony_encoding(h.HarmonyEncodingName.HARMONY_GPT_OSS)

    def render(messages, tools, *, reasoning_effort=None, enable_thinking=None):
        del enable_thinking  # the model chooses its channels; effort is the knob
        if reasoning_effort is not None and reasoning_effort not in HARMONY_EFFORTS:
            raise ValueError(f"gpt-oss reasoning_effort must be one of {HARMONY_EFFORTS}")
        conv = harmony_conversation(normalize_messages(messages), tools, reasoning_effort)
        return list(enc.render_conversation_for_completion(conv, h.Role.ASSISTANT))

    return render


def harmony_conversation(messages: list[dict], tools, reasoning_effort: str | None) -> Any:
    import openai_harmony as h

    system = h.SystemContent.new().with_conversation_start_date(date.today().isoformat())
    if reasoning_effort is not None:
        system = system.with_reasoning_effort(h.ReasoningEffort[reasoning_effort.upper()])
    out = [h.Message.from_role_and_content(h.Role.SYSTEM, system)]
    instructions = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
    developer = h.DeveloperContent.new()
    if instructions:
        developer = developer.with_instructions(instructions)
    if tools:
        developer = developer.with_function_tools(
            [
                h.ToolDescription.new(
                    fn["name"], fn.get("description", ""), fn.get("parameters") or None
                )
                for fn in (t.get("function", t) for t in tools)
            ]
        )
    if instructions or tools:
        out.append(h.Message.from_role_and_content(h.Role.DEVELOPER, developer))
    out.extend(harmony_history(messages))
    return h.Conversation.from_messages(out)


def harmony_history(messages: list[dict]) -> list[Any]:
    """The turns after the preamble. Analysis (reasoning) is kept only for assistant turns
    after the last user message, harmony's auto_drop_analysis rule."""
    import openai_harmony as h

    out: list[Any] = []
    last_user = max((i for i, m in enumerate(messages) if m["role"] == "user"), default=-1)
    for i, m in enumerate(messages):
        role = m["role"]
        if role == "system":
            continue
        if role == "user":
            out.append(h.Message.from_role_and_content(h.Role.USER, m["content"]))
        elif role == "tool":
            author = h.Author.new(h.Role.TOOL, f"functions.{m.get('name', 'unknown')}")
            out.append(
                h.Message.from_author_and_content(author, m["content"])
                .with_recipient("assistant")
                .with_channel("commentary")
            )
        elif role == "assistant":
            out.extend(harmony_assistant(m, keep_analysis=i > last_user))
        else:
            raise ValueError(f"unknown role {role!r}")
    return out


def harmony_assistant(m: dict, *, keep_analysis: bool) -> list[Any]:
    import openai_harmony as h

    out: list[Any] = []
    reasoning = m.get("reasoning_content")
    if reasoning and keep_analysis:
        msg = h.Message.from_role_and_content(h.Role.ASSISTANT, reasoning)
        out.append(msg.with_channel("analysis"))
    if m["content"]:
        msg = h.Message.from_role_and_content(h.Role.ASSISTANT, m["content"])
        out.append(msg.with_channel("final"))
    for tc in m.get("tool_calls") or []:
        fn = tc["function"]
        args = fn["arguments"]
        text = args if isinstance(args, str) else json.dumps(args, ensure_ascii=False)
        out.append(
            h.Message.from_role_and_content(h.Role.ASSISTANT, text)
            .with_channel("commentary")
            .with_recipient(f"functions.{fn['name']}")
            .with_content_type("<|constrain|>json")
        )
    return out


def default_render(tokenizer: Any) -> RenderFn:
    """tokenizer.apply_chat_template, with the content shape the template can read."""
    template = getattr(tokenizer, "chat_template", None)
    # A template that indexes `content[0]` iterates parts (SmolVLM); Jinja would silently walk
    # a string's characters instead of raising, so the shape is decided up front.
    wants_parts = isinstance(template, str) and re.search(r"content'?\]?\[0\]", template)

    def render(messages, tools, *, reasoning_effort=None, enable_thinking=None):
        knobs = (("reasoning_effort", reasoning_effort), ("enable_thinking", enable_thinking))
        kwargs = {k: v for k, v in knobs if v is not None}
        if template is None:
            raise ValueError("this model's tokenizer has no chat template")
        msgs = normalize_messages(messages)
        if wants_parts:
            msgs = [{**m, "content": [{"type": "text", "text": m["content"]}]} for m in msgs]
        return apply(tokenizer, msgs, tools, kwargs)

    return render


def apply(tokenizer: Any, messages: list[dict], tools, kwargs: dict) -> list[int]:
    ids = tokenizer.apply_chat_template(
        messages, tools=tools or None, add_generation_prompt=True, tokenize=True, **kwargs
    )
    if hasattr(ids, "input_ids"):
        ids = ids["input_ids"]
    return [int(t) for t in ids]


# ---- normalisation ---------------------------------------------------------------------------


def normalize_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """OpenAI wire -> the message shape every renderer here accepts. Pure; copies."""
    out: list[dict[str, Any]] = []
    names: dict[str, str] = {}
    for m in messages:
        n = dict(m)
        n["content"] = content_text(m.get("content"))
        if m.get("role") == "assistant" and m.get("tool_calls"):
            calls = []
            for tc in m["tool_calls"]:
                fn = dict(tc.get("function", tc))
                fn["arguments"] = parse_arguments(fn.get("arguments"))
                call = {**tc, "type": "function", "function": fn}
                if call.get("id"):
                    names[str(call["id"])] = fn["name"]
                calls.append(call)
            n["tool_calls"] = calls
        if m.get("role") == "tool" and not n.get("name"):
            name = names.get(str(m.get("tool_call_id")))
            if name is not None:
                n["name"] = name
        if n.get("reasoning_content") is None:
            n.pop("reasoning_content", None)
        out.append(n)
    return out


def content_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            p if isinstance(p, str) else str(p.get("text", ""))
            for p in content
            if isinstance(p, str) or p.get("type") == "text"
        )
    return str(content)


def parse_arguments(arguments: Any) -> Any:
    """A JSON-object string becomes the object (what templates `tojson`); anything else as is."""
    if isinstance(arguments, str):
        try:
            obj = json.loads(arguments)
        except json.JSONDecodeError:
            return arguments
        return obj if isinstance(obj, dict) else arguments
    return {} if arguments is None else arguments
