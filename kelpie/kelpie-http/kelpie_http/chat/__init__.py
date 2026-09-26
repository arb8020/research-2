"""Chat templates and tool-call/reasoning parsers, per model family (docs/decisions.md "Tool
calling order", step 1). `resolve(model_name)` picks the family from the name -- or from
`chat_format` for a local path -- loads the HF tokenizer the family's renderer needs, and returns
a ChatCodec: prompt side `render`, output side `parser_factory` (streaming deltas -> events), and
the format's `stop_token_ids` for the engine."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from kelpie_http import wire
from kelpie_http.chat.parse import Parser, ParserFactory, PlainParser
from kelpie_http.chat.render import FAMILIES, RenderFn, make_render, stop_token_ids

__all__ = ["FAMILIES", "ChatCodec", "Parser", "Turn", "family_of", "resolve"]


@dataclass(frozen=True)
class ChatCodec:
    family: str
    tokenizer: Any  # HF tokenizer (transformers); decodes the stream for the parser
    render: RenderFn
    parser_factory: ParserFactory
    stop_token_ids: tuple[int, ...]

    def decode(self, ids: list[int]) -> str:
        return self.tokenizer.decode(ids, skip_special_tokens=False)

    def turn(self, env: wire.Envelope, *, enable_thinking: bool | None = None) -> Turn:
        parser = self.parser_factory(enable_thinking=enable_thinking)
        return Turn(env, parser, self, self.stop_token_ids)


@dataclass(frozen=True)
class Turn:
    """One chat response in flight: what stream_chat/collect_chat need beyond the core."""

    env: wire.Envelope  # id / model / created shared by every chunk of the response
    parser: Parser
    decoder: Any  # .decode(list[int]) -> str
    stop_token_ids: tuple[int, ...]  # dropped from the text (the parser still sees the ids)

    @staticmethod
    def plain(env: wire.Envelope, decoder: Any) -> Turn:
        return Turn(env, PlainParser(), decoder, ())


def resolve(model_name: str, tokenizer: Any = None, *, chat_format: str | None = None) -> ChatCodec:
    """The family normally arrives as `chat_format` -- the model module's `CHAT_FAMILY` fact,
    or the user's `--chat-format` override. `family_of` is the last-resort guess for a bare
    HF id nobody has written a model file for yet. `tokenizer` is loaded from model_name if
    None."""
    family = chat_format or family_of(model_name)
    if family is None:
        raise ValueError(
            f"cannot tell the chat format of {model_name!r}; pass --chat-format "
            f"(one of {', '.join(FAMILIES)})"
        )
    assert family in FAMILIES, family
    if tokenizer is None:
        tokenizer = load_tokenizer(model_name, family)
    return ChatCodec(
        family=family,
        tokenizer=tokenizer,
        render=make_render(family, tokenizer),
        parser_factory=parser_factory(family),
        stop_token_ids=stop_token_ids(family, tokenizer),
    )


def family_of(model_name: str) -> str | None:
    """Family from an HF id (a `@...` variant suffix is ignored). Unknown names that are not
    local paths fall back to `default` (apply_chat_template); local paths need --chat-format."""
    name = model_name.split("@", 1)[0]
    base = name.rstrip("/").rsplit("/", 1)[-1].lower()
    rules = [
        (r"^qwen3-\d", "qwen3"),
        (r"^gpt-oss", "gpt-oss"),
        (r"^kimi-k3", "kimi-k3"),
        (r"^deepseek-v3\.2", "deepseek-v3.2"),
        (r"^glm-5", "glm-5"),
        (r"^(meta-)?llama-3", "llama-3"),
    ]
    for pattern, family in rules:
        if re.match(pattern, base):
            return family
    is_local = name.startswith((".", "/", "~")) or name.count("/") != 1
    return None if is_local and base not in ("gpt2", "stub") else "default"


def parser_factory(family: str) -> ParserFactory:
    if family == "gpt-oss":
        import openai_harmony as h

        from kelpie_http.chat.parse.harmony import HarmonyParser

        enc = h.load_harmony_encoding(h.HarmonyEncodingName.HARMONY_GPT_OSS)
        return lambda **kw: HarmonyParser(enc, **kw)
    from kelpie_http.chat.parse.deepseek import DeepSeekParser
    from kelpie_http.chat.parse.glm import GlmParser
    from kelpie_http.chat.parse.hermes import HermesParser
    from kelpie_http.chat.parse.kimi_k3 import KimiK3Parser
    from kelpie_http.chat.parse.llama import LlamaParser

    factories: dict[str, ParserFactory] = {
        "qwen3": HermesParser,
        "kimi-k3": KimiK3Parser,
        "deepseek-v3.2": DeepSeekParser,
        "glm-5": GlmParser,
        "llama-3": LlamaParser,
        "default": HermesParser,  # <think> + <tool_call> JSON is the common unknown-model case
    }
    return factories[family]


def load_tokenizer(model_name: str, family: str) -> Any:
    """transformers AutoTokenizer; remote code only for Kimi K3 (its tokenizer is a tiktoken
    wrapper shipped in the checkpoint, and its chat format lives in that code)."""
    from transformers import AutoTokenizer

    name = model_name.split("@", 1)[0]
    return AutoTokenizer.from_pretrained(name, trust_remote_code=family == "kimi-k3")
