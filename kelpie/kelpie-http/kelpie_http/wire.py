"""OpenAI /v1/completions and /v1/chat/completions wire format (docs/wire-contract.md). The only
file that knows JSON/SSE shapes. Chat image parts are data: URLs only (no fetching): the bytes are
decoded here and hashed here; what they mean is the model's business (kelpie_http.vlm).

Everything on the wire goes through `dumps` (compact, UTF-8, no NaN) so the bytes are the same
whether a body is a JSON response or an SSE chunk. Ids and `created` come from a `Minting`,
injectable so a test server is deterministic."""

from __future__ import annotations

import base64
import hashlib
import json
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

DEFAULT_MAX_TOKENS = 16
DATA_URL_PREFIX = "data:"
ID_HEX_LEN = 24  # cmpl-/chatcmpl-/call_ + 24 lowercase hex chars
FINISH_REASONS = ("stop", "length", "tool_calls")  # the only values that reach the wire


def dumps(obj: Any) -> str:
    """The one JSON serialisation: compact separators, raw UTF-8 (no \\u escapes), NaN refused.
    Identical to FastAPI's JSONResponse rendering, so bodies and SSE chunks match byte for byte."""
    return json.dumps(obj, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def random_id(prefix: str) -> str:
    return prefix + uuid.uuid4().hex[:ID_HEX_LEN]


@dataclass(frozen=True)
class Minting:
    """Where ids and `created` come from. clock -> seconds since the epoch; new_id(prefix)."""

    clock: Callable[[], float] = time.time
    new_id: Callable[[str], str] = random_id

    def envelope(self, prefix: str, model: str) -> Envelope:
        return Envelope(id=self.new_id(prefix), model=model, created=int(self.clock()))


@dataclass(frozen=True)
class Envelope:
    """The (id, model, created) triple every completion object and chunk of one response shares."""

    id: str
    model: str
    created: int


@dataclass(frozen=True)
class CompletionRequest:
    prompt: str
    max_tokens: int
    temperature: float
    stream: bool
    model: str
    include_usage: bool = False  # stream_options.include_usage: a final usage-only chunk
    top_k: int = 0  # 0 = off (the whole vocabulary); see parse_top_k


def parse_request(body: Any) -> CompletionRequest:
    """Narrow a JSON body into a CompletionRequest. Raises ValueError on bad input."""
    if not isinstance(body, dict):
        raise ValueError("body must be a JSON object")
    prompt = body.get("prompt", "")
    if isinstance(prompt, list):
        if len(prompt) != 1 or not isinstance(prompt[0], str):
            raise ValueError("prompt must be a string or a single-element list of strings")
        prompt = prompt[0]
    if not isinstance(prompt, str):
        raise ValueError("prompt must be a string")
    max_tokens = body.get("max_tokens", DEFAULT_MAX_TOKENS)
    if not isinstance(max_tokens, int) or isinstance(max_tokens, bool) or max_tokens < 0:
        raise ValueError("max_tokens must be a non-negative integer")
    temperature = body.get("temperature", 1.0)
    if not isinstance(temperature, int | float) or temperature < 0:
        raise ValueError("temperature must be a non-negative number")
    if body.get("n", 1) != 1:
        raise ValueError("n must be 1")
    return CompletionRequest(
        prompt=prompt,
        max_tokens=max_tokens,
        temperature=float(temperature),
        stream=parse_bool(body, "stream"),
        model=parse_model(body),
        include_usage=parse_include_usage(body.get("stream_options")),
        top_k=parse_top_k(body),
    )


def parse_top_k(body: dict[str, Any]) -> int:
    """`top_k`: an integer, absent = 0 (off). -1 also means off (what vLLM-style clients send);
    any other negative is 400. The upper limit (vocab_size) is the engine's to check."""
    top_k = body.get("top_k", 0)
    if not isinstance(top_k, int) or isinstance(top_k, bool):
        raise ValueError("top_k must be an integer")
    if top_k == -1:
        return 0
    if top_k < 0:
        raise ValueError("top_k must be >= 0, or -1 for off")
    return top_k


def parse_include_usage(stream_options: Any) -> bool:
    if stream_options is None:
        return False
    if not isinstance(stream_options, dict):
        raise ValueError("stream_options must be an object")
    return parse_bool(stream_options, "include_usage")


def parse_bool(obj: dict[str, Any], key: str) -> bool:
    """A JSON boolean or absent (False); anything else (a string, null, 1) is 400."""
    value = obj.get(key, False)
    if not isinstance(value, bool):
        raise ValueError(f"{key} must be a boolean")
    return value


def parse_model(body: dict[str, Any]) -> str:
    """Echoed back in responses; absent means "kelpie". Never coerced (str(None) is "None")."""
    model = body.get("model", "kelpie")
    if not isinstance(model, str):
        raise ValueError("model must be a string")
    return model


def usage_object(prompt_tokens: int, completion_tokens: int, cached_tokens: int) -> dict[str, Any]:
    """OpenAI usage; cached_tokens (prompt_tokens_details) is the prefix-cache hit length."""
    assert 0 <= cached_tokens <= prompt_tokens, (cached_tokens, prompt_tokens)
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
        "prompt_tokens_details": {"cached_tokens": cached_tokens},
    }


# ---- chat completions -----------------------------------------------------------------------


@dataclass(frozen=True)
class ImagePart:
    data: bytes  # decoded image file bytes (png/jpeg/...); the model decodes the format


@dataclass(frozen=True)
class ChatMessage:
    role: str
    parts: tuple[str | ImagePart, ...]  # in order; str parts are text


@dataclass(frozen=True)
class ChatRequest:
    messages: tuple[ChatMessage, ...]
    max_tokens: int
    temperature: float
    stream: bool
    model: str
    top_k: int = 0  # 0 = off (the whole vocabulary); see parse_top_k

    @property
    def images(self) -> list[bytes]:
        return [p.data for m in self.messages for p in m.parts if isinstance(p, ImagePart)]


def parse_chat_request(body: Any) -> ChatRequest:
    """Narrow a chat-completions JSON body. content is a string or a list of
    {type: text|image_url} parts; image_url.url must be a data: URL. Raises ValueError."""
    if not isinstance(body, dict):
        raise ValueError("body must be a JSON object")
    raw = body.get("messages")
    if not isinstance(raw, list) or not raw:
        raise ValueError("messages must be a non-empty list")
    messages = tuple(parse_chat_message(m) for m in raw)
    max_tokens = body.get("max_tokens", DEFAULT_MAX_TOKENS)
    if not isinstance(max_tokens, int) or isinstance(max_tokens, bool) or max_tokens < 0:
        raise ValueError("max_tokens must be a non-negative integer")
    temperature = body.get("temperature", 1.0)
    if not isinstance(temperature, int | float) or temperature < 0:
        raise ValueError("temperature must be a non-negative number")
    if body.get("n", 1) != 1:
        raise ValueError("n must be 1")
    return ChatRequest(
        messages=messages,
        max_tokens=max_tokens,
        temperature=float(temperature),
        stream=parse_bool(body, "stream"),
        model=parse_model(body),
        top_k=parse_top_k(body),
    )


def parse_chat_message(m: Any) -> ChatMessage:
    if not isinstance(m, dict) or not isinstance(m.get("role"), str):
        raise ValueError("each message needs a string role")
    content = m.get("content")
    if content is None:  # an assistant tool-call turn: OpenAI sends content null (or omits it)
        return ChatMessage(role=m["role"], parts=())
    if isinstance(content, str):
        return ChatMessage(role=m["role"], parts=(content,))
    if not isinstance(content, list) or not content:
        raise ValueError("content must be null, a string or a non-empty list of parts")
    parts: list[str | ImagePart] = []
    for part in content:
        if not isinstance(part, dict):
            raise ValueError("content parts must be objects")
        kind = part.get("type")
        if kind == "text":
            if not isinstance(part.get("text"), str):
                raise ValueError("text part needs a string text")
            parts.append(part["text"])
        elif kind == "image_url":
            url = part.get("image_url", {})
            url = url.get("url") if isinstance(url, dict) else url
            if not isinstance(url, str):
                raise ValueError("image_url part needs image_url.url")
            parts.append(ImagePart(decode_data_url(url)))
        else:
            raise ValueError(f"unsupported content part type '{kind}'")
    return ChatMessage(role=m["role"], parts=tuple(parts))


def decode_data_url(url: str) -> bytes:
    """data:<mime>;base64,<payload> -> bytes. Only base64 data URLs are accepted."""
    if not url.startswith(DATA_URL_PREFIX) or ";base64," not in url:
        raise ValueError("image_url must be a base64 data: URL")
    payload = url.split(";base64,", 1)[1]
    try:
        return base64.b64decode(payload, validate=True)
    except ValueError as e:
        raise ValueError("image data is not valid base64") from e


def mm_hash(images: list[bytes]) -> int:
    """u64 content hash of a request's images (0 = none): first 8 bytes of sha256 over each
    image's length-prefixed bytes, so two prompts with identical placeholder ids but different
    pixels never share KV blocks."""
    if not images:
        return 0
    h = hashlib.sha256()
    for img in images:
        h.update(len(img).to_bytes(8, "big"))
        h.update(img)
    out = int.from_bytes(h.digest()[:8], "big")
    return out or 1  # 0 is reserved for "no images"


def chat_completion_object(
    env: Envelope, text: str | None, finish_reason: str, usage: dict[str, Any]
) -> dict[str, Any]:
    """text None = a message with tool calls and no content (OpenAI: content null)."""
    assert finish_reason in FINISH_REASONS, finish_reason
    return {
        "id": env.id,
        "object": "chat.completion",
        "created": env.created,
        "model": env.model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": text},
                "logprobs": None,
                "finish_reason": finish_reason,
            }
        ],
        "usage": usage,
    }


def chat_sse_chunk(env: Envelope, delta: dict[str, Any], finish_reason: str | None) -> str:
    assert finish_reason is None or finish_reason in FINISH_REASONS, finish_reason
    chunk = {
        "id": env.id,
        "object": "chat.completion.chunk",
        "created": env.created,
        "model": env.model,
        "choices": [{"index": 0, "delta": delta, "logprobs": None, "finish_reason": finish_reason}],
    }
    return sse_data(chunk)


def completion_object(
    env: Envelope, text: str, finish_reason: str, usage: dict[str, Any]
) -> dict[str, Any]:
    """usage: see usage_object."""
    assert finish_reason in FINISH_REASONS, finish_reason
    return {
        "id": env.id,
        "object": "text_completion",
        "created": env.created,
        "model": env.model,
        "choices": [{"text": text, "index": 0, "logprobs": None, "finish_reason": finish_reason}],
        "usage": usage,
    }


def sse_usage_chunk(env: Envelope, usage: dict[str, Any]) -> str:
    """The final chunk under stream_options.include_usage: empty choices, usage filled."""
    chunk = {
        "id": env.id,
        "object": "text_completion",
        "created": env.created,
        "model": env.model,
        "choices": [],
        "usage": usage,
    }
    return sse_data(chunk)


def sse_chunk(env: Envelope, text: str, finish_reason: str | None) -> str:
    assert finish_reason is None or finish_reason in FINISH_REASONS, finish_reason
    chunk = {
        "id": env.id,
        "object": "text_completion",
        "created": env.created,
        "model": env.model,
        "choices": [{"text": text, "index": 0, "logprobs": None, "finish_reason": finish_reason}],
    }
    return sse_data(chunk)


def sse_data(chunk: dict[str, Any]) -> str:
    """One SSE event: a single `data:` line, blank-line terminated (no id/event/retry fields)."""
    return "data: " + dumps(chunk) + "\n\n"


SSE_DONE = "data: [DONE]\n\n"


def error_body(message: str, error_type: str) -> dict[str, Any]:
    return {"error": {"message": message, "type": error_type, "param": None, "code": None}}


def public_finish_reason(core_reason: str) -> str:
    """Core lifecycle names -> OpenAI names (stop/length/tool_calls). A cancelled request never
    gets a body (the client is gone), so nothing else may reach here. `grammar_dead_end` maps to
    `length`: OpenAI has no "the grammar could not continue" reason, and like a length cutoff the
    client sees a truncated document rather than one that finished on its own terms (docs/
    wire-contract.md section 13); the engine-level distinction survives in `/metrics` and
    `/v1/kelpie/stats`, not on this response."""
    names = {"finished_eos": "stop", "finished_length": "length", "grammar_dead_end": "length"}
    assert core_reason in names, core_reason
    return names[core_reason]
