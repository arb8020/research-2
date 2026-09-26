"""Rung 3: HTTP over a running `Engine`.

Handlers only submit / poll / cancel. There is no Core, no Ticker and no Stepper between this
file and the engine: the Zig loop is already stepping by the time `serve` gets here, and every
attribute these routes reach for is one of the engine's public members.

Fan-out lives here, not in the engine: the engine only exposes `step_fd`, the fd its Zig step
thread writes one byte to per commit (the boundary is a file descriptor; the kernel does the
waiting, no framework in between). This module owns the one Python-side piece of bookkeeping the
engine cannot -- a `request_id -> trio.Event` map -- because only the caller's own event loop
knows what "wake a waiter" means. One reader task per engine, started from the Starlette lifespan
(there is no nursery reachable from `create_app` otherwise -- `serve.py`'s nursery exists only
after `trio.run` starts, well after this module has built the app object), loops:
`await trio.lowlevel.wait_readable(engine.step_fd)`, drains `next_commit()` until it returns
None, and sets a fresh `trio.Event` per advanced request_id. Request handlers await their own
event with a short timeout as the safety net only -- progress is signalled by the reader task,
not polled for.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

import trio
from kelpie_engine.sdk.engine import Draining, Engine, Full, TooLong
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Route
from tokenizers import Tokenizer

from kelpie_http import wire
from kelpie_http.chat import ChatCodec

POLL_TIMEOUT_S = 0.05  # safety net only; progress is signalled by the reader task
POOL_FULL_STATUS = 429  # OpenAI clients retry on 429
UNHEALTHY_STATUS = 503
CLIENT_GONE_STATUS = 499
HEALTH_STEP_WINDOW_S = 5.0  # a busy engine must have committed a step this recently
READER_CHUNK_BYTES = 4096  # step_fd is a byte-per-commit pipe; drain it in chunks, not one byte

Endpoint = Callable[[Request], Awaitable[Response]]


def create_app(engine: Engine, tokenizer_id: str, chat: ChatCodec | None = None) -> Starlette:
    """The OpenAI surface over one engine. `chat` is the chat codec for /v1/chat/completions;
    None serves completions only."""
    tokenizer = Tokenizer.from_pretrained(tokenizer_id)
    minting = wire.Minting()
    waiters: dict[int, trio.Event] = {}

    async def completions(request: Request) -> Response:
        try:
            req = wire.parse_request(await request.json())
        except ValueError as e:
            return JSONResponse(wire.error_body(str(e), "invalid_request_error"), status_code=400)
        prompt_ids = tokenizer.encode(req.prompt).ids
        try:
            request_id = engine.submit(prompt_ids, req.max_tokens, req.temperature, top_k=req.top_k)
            generation = engine.generation(request_id)
        except Full:
            return JSONResponse(
                wire.error_body("all request slots busy, retry later", "server_busy"),
                status_code=POOL_FULL_STATUS,
                headers={"Retry-After": "1"},
            )
        except (TooLong, Draining, ValueError) as e:  # ValueError: top_k > vocab_size, ...
            return JSONResponse(
                wire.error_body(str(e) or type(e).__name__, "invalid_request_error"),
                status_code=400,
            )
        env = minting.envelope("cmpl-", req.model)
        if req.stream:
            return StreamingResponse(
                stream_completion(engine, waiters, tokenizer, request, request_id, env, generation=generation),
                media_type="text/event-stream",
            )
        return await collect_completion(
            engine, waiters, tokenizer, request, request_id, env, len(prompt_ids), generation=generation
        )

    routes = [
        Route("/v1/completions", completions, methods=["POST"]),
        *_reporting_routes(engine, tokenizer_id),
        *_config_routes(engine),
    ]
    if chat is not None:
        routes.append(
            Route(
                "/v1/chat/completions",
                _chat(engine, waiters, tokenizer, chat, minting),
                methods=["POST"],
            )
        )
    return Starlette(routes=routes, lifespan=_lifespan(engine, waiters))


def _lifespan(engine: Engine, waiters: dict[int, trio.Event]) -> Callable[[Starlette], object]:
    """One reader task for this engine's step_fd, running for the app's whole lifetime."""

    @asynccontextmanager
    async def lifespan(_app: Starlette) -> AsyncIterator[None]:
        async with trio.open_nursery() as nursery:
            nursery.start_soon(read_commits, engine, waiters)
            yield
            nursery.cancel_scope.cancel()

    return lifespan


async def read_commits(engine: Engine, waiters: dict[int, trio.Event]) -> None:
    """Block on step_fd, then drain every pending commit record and wake what it advanced. The
    step pipe writes one byte per record, so a burst of steps between wakes costs one pass, not
    one per step."""
    while True:
        await trio.lowlevel.wait_readable(engine.step_fd)
        if not os.read(engine.step_fd, READER_CHUNK_BYTES):
            return  # write end closed: the engine is going away
        while (record := engine.next_commit()) is not None:
            for request_id in record.advanced:
                event = waiters.pop(request_id, None)
                if event is not None:
                    event.set()


def _reporting_routes(engine: Engine, tokenizer_id: str) -> list[Route]:
    async def health(_: Request) -> Response:
        body = health_body(engine)
        return JSONResponse(body, status_code=200 if body["ok"] else UNHEALTHY_STATUS)

    async def models(_: Request) -> Response:
        return JSONResponse({"object": "list", "data": [{"id": tokenizer_id, "object": "model"}]})

    return [Route("/health", health), Route("/v1/models", models)]


def _config_routes(engine: Engine) -> list[Route]:
    async def get_config(_: Request) -> Response:
        config = engine.live_config()
        return JSONResponse(
            {
                "order": config.order,
                "reserve_ratio": config.reserve_ratio,
                "max_batch_tokens": config.max_batch_tokens,
                "max_batch_reqs": config.max_batch_reqs,
                "prefix_cache": config.prefix_cache,
            }
        )

    async def set_config(request: Request) -> Response:
        try:
            apply_step = engine.set(**await request.json())
        except (AssertionError, ValueError, TypeError) as e:
            return JSONResponse(wire.error_body(str(e), "invalid_request_error"), status_code=400)
        return JSONResponse({"apply_step": apply_step})

    return [
        Route("/v1/kelpie/config", get_config),
        Route("/v1/kelpie/config", set_config, methods=["POST"]),
    ]


def _chat(
    engine: Engine,
    waiters: dict[int, trio.Event],
    tokenizer: Tokenizer,
    chat: ChatCodec,
    minting: wire.Minting,
) -> Endpoint:
    async def chat_completions(request: Request) -> Response:
        from kelpie_http.sdk.chat import handle_chat

        return await handle_chat(engine, waiters, tokenizer, chat, minting, request)

    return chat_completions


async def collect_completion(  # noqa: PLR0913, PLR0917
    engine: Engine,
    waiters: dict[int, trio.Event],
    tokenizer: Tokenizer,
    request: Request,
    request_id: int,
    env: wire.Envelope,
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
    usage = wire.usage_object(n_prompt, len(tokens), cached_tokens(engine, request_id))
    return JSONResponse(
        wire.completion_object(
            env, tokenizer.decode(tokens), wire.public_finish_reason(finish), usage
        )
    )


async def stream_completion(
    engine: Engine,
    waiters: dict[int, trio.Event],
    tokenizer: Tokenizer,
    request: Request,
    request_id: int,
    env: wire.Envelope,
    *,
    generation: int,
) -> AsyncIterator[str]:
    """Cancel on exit: a generator abandoned mid-stream must not leave the slot generating."""
    detok = Detokenizer(tokenizer)
    finish = None
    try:
        async for new_tokens, reason in poll_until_done(engine, waiters, request, request_id):
            finish = reason
            if text := detok.push(new_tokens):
                yield wire.sse_chunk(env, text, None)
        if finish is None:
            return
        yield wire.sse_chunk(env, detok.flush(), wire.public_finish_reason(finish))
        yield wire.SSE_DONE
    finally:
        if finish is None:
            cancel_on_disconnect(engine, request_id, generation)


async def poll_until_done(
    engine: Engine, waiters: dict[int, trio.Event], request: Request, request_id: int
) -> AsyncIterator[tuple[list[int], str | None]]:
    """Yield (new_tokens, finish_reason) per poll; stops early (finish None) on disconnect.

    Register the wait event BEFORE poll, so a commit can never slip between the two unseen: a
    commit after the register sets the event, so the wait below is only ever for a real future
    step."""
    while True:
        event = trio.Event()
        waiters[request_id] = event
        if await request.is_disconnected():
            del waiters[request_id]
            return
        engine.raise_error()
        result = engine.poll(request_id)
        if result.finished:
            yield result.new_tokens, result.reason
            return
        if result.new_tokens:
            yield result.new_tokens, None
        with trio.move_on_after(POLL_TIMEOUT_S):
            await event.wait()


def cancel_on_disconnect(engine: Engine, request_id: int, generation: int) -> bool:
    """Cancel exactly the request this handler submitted (design-multigpu section 8 B2): the
    handler does not know whether its request already finished, was polled and released, and
    its id handed to someone else -- a plain cancel would then kill that stranger. With the
    generation recorded at submit, such a stale cancel is a no-op. -> whether one was queued."""
    return engine.cancel(request_id, generation)


def cached_tokens(engine: Engine, request_id: int) -> int:
    """Prefix-cache hit length for the response's usage. The core knows it, so it is read from
    the core rather than carried at 0 through the Python path."""
    stats = engine.request_stats(request_id)
    return max(0, int(stats.n_prompt) - int(stats.n_chunks))


def health_body(engine: Engine) -> dict[str, object]:
    alive, busy = engine.alive(), engine.has_work()
    since = engine.since_last_step_s()
    stepping = since is not None and since <= HEALTH_STEP_WINDOW_S
    ok = alive and (not busy or stepping)
    reason = None if ok else ("loop dead" if not alive else "loop stalled")
    return {"ok": ok, "reason": reason, "alive": alive, "busy": busy, "since_last_step_s": since}


class Detokenizer:
    """Emit text only once it no longer ends in a partial UTF-8 sequence (the U+FFFD marker)."""

    def __init__(self, tokenizer: Tokenizer) -> None:
        self.tokenizer = tokenizer
        self.tokens: list[int] = []
        self.emitted = 0

    def push(self, new_tokens: list[int]) -> str:
        self.tokens.extend(new_tokens)
        text = self.tokenizer.decode(self.tokens)
        if text.endswith("�"):
            return ""
        out, self.emitted = text[self.emitted :], len(text)
        return out

    def flush(self) -> str:
        return self.tokenizer.decode(self.tokens)[self.emitted :]
