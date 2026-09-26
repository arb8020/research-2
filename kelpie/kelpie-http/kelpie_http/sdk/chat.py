"""/v1/chat/completions over the engine.

The rendering, the tool-call parsers and the SSE assembly are the kept feature code
(`kelpie_http.chat`); this file is only what binds them to an `Engine`. Grammar
(`response_format`) and images are their own follow-up briefs -- a request asking for either
is refused here rather than half-served.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import trio
from kelpie_engine.sdk.engine import Draining, Engine, Full, TooLong
from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse
from tokenizers import Tokenizer

from kelpie_http import wire
from kelpie_http.chat import ChatCodec, Turn, sse
from kelpie_http.chat.parse.events import Done
from kelpie_http.chat.render.request import parse_chat_extras
from kelpie_http.sdk.app import (
    CLIENT_GONE_STATUS,
    POOL_FULL_STATUS,
    Detokenizer,
    cached_tokens,
    cancel_on_disconnect,
    poll_until_done,
)

NOT_YET = "structured output and images are follow-up rungs; not served by this build"


async def handle_chat(
    engine: Engine,
    waiters: dict[int, trio.Event],
    tokenizer: Tokenizer,
    chat: ChatCodec,
    minting: wire.Minting,
    request: Request,
) -> JSONResponse | StreamingResponse:
    """Render the prompt (chat template + tools), submit with the format's stop set, parse the
    output into content / reasoning / tool calls."""
    try:
        body = await request.json()
        req = wire.parse_chat_request(body)
        ids, turn = prepare(body, req, chat, minting)
    except ValueError as e:
        return JSONResponse(wire.error_body(str(e), "invalid_request_error"), status_code=400)
    try:
        request_id = engine.submit(
            ids, req.max_tokens, req.temperature, stop_token_ids=turn.stop_token_ids,
            top_k=req.top_k,
        )
        generation = engine.generation(request_id)
    except Full:
        return JSONResponse(
            wire.error_body("all request slots busy, retry later", "server_busy"),
            status_code=POOL_FULL_STATUS,
            headers={"Retry-After": "1"},
        )
    except (TooLong, Draining, ValueError) as e:  # ValueError: top_k > vocab_size, ...
        return JSONResponse(
            wire.error_body(str(e) or type(e).__name__, "invalid_request_error"), status_code=400
        )
    del tokenizer
    if req.stream:
        return StreamingResponse(
            stream_chat(engine, waiters, request, request_id, turn, generation=generation), media_type="text/event-stream"
        )
    return await collect_chat(engine, waiters, request, request_id, turn, len(ids), generation=generation)


def prepare(
    body: object, req: wire.ChatRequest, chat: ChatCodec, minting: wire.Minting
) -> tuple[list[int], Turn]:
    if req.images:
        raise ValueError(NOT_YET)
    extras = parse_chat_extras(body)
    if extras.json_schema is not None:
        raise ValueError(NOT_YET)
    ids = chat.render(
        extras.messages,
        extras.tools,
        reasoning_effort=extras.reasoning_effort,
        enable_thinking=extras.enable_thinking,
    )
    env = minting.envelope("chatcmpl-", req.model)
    return ids, chat.turn(env, enable_thinking=extras.enable_thinking)


async def collect_chat(
    engine: Engine,
    waiters: dict[int, trio.Event],
    request: Request,
    request_id: int,
    turn: Turn,
    n_prompt: int,
    *,
    generation: int,
) -> JSONResponse:
    tokens: list[int] = []
    finish = None
    async for new_tokens, reason in poll_until_done(engine, waiters, request, request_id):
        tokens.extend(new_tokens)
        finish = reason
    if finish is None:
        cancel_on_disconnect(engine, request_id, generation)
        return JSONResponse(
            wire.error_body("client disconnected", "cancelled"), status_code=CLIENT_GONE_STATUS
        )
    text = turn.decoder.decode([t for t in tokens if t not in turn.stop_token_ids])
    events = turn.parser.feed(text, tokens) + turn.parser.finish()
    events.append(Done(wire.public_finish_reason(finish)))
    usage = wire.usage_object(n_prompt, len(tokens), cached_tokens(engine, request_id))
    return JSONResponse(sse.completion_body(turn.env, sse.assemble(events), usage))


async def stream_chat(
    engine: Engine, waiters: dict[int, trio.Event], request: Request, request_id: int, turn: Turn,
    *, generation: int,
) -> AsyncIterator[str]:
    """Each poll's tokens are detokenized incrementally, fed to the format parser, and the
    events it is sure of go out as chunk deltas; the stop token never reaches the text.
    Leaving before a finish (the client went away) cancels the request so the slot is freed."""
    detok = Detokenizer(turn.decoder)
    chunks = sse.ChunkStream(turn.env)
    finish = None
    try:
        async for new_tokens, reason in poll_until_done(engine, waiters, request, request_id):
            finish = reason
            text = detok.push([t for t in new_tokens if t not in turn.stop_token_ids])
            for chunk in chunks.chunks(turn.parser.feed(text, new_tokens)):
                yield chunk
        if finish is None:
            return
        for chunk in chunks.chunks(turn.parser.feed(detok.flush(), []) + turn.parser.finish()):
            yield chunk
        yield chunks.finish(Done(wire.public_finish_reason(finish)))
        yield wire.SSE_DONE
    finally:
        if finish is None:
            cancel_on_disconnect(engine, request_id, generation)
