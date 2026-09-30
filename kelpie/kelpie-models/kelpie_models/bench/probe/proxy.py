# copied from crucible/verification/engines/probe/proxy.py @ dfb735f9a8d9
from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from collections.abc import AsyncGenerator
from typing import Any

import httpx
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response, StreamingResponse
from starlette.routing import Route

logger = logging.getLogger("crucible.verification.engines.probe.proxy")

_SCHEMA_VERSION = 2

_SENSITIVE_HEADERS = frozenset({
    "authorization", "x-api-key", "api-key",
    "cookie", "set-cookie", "proxy-authorization",
})


@dataclass
class _RequestContext:
    request_id: str
    request: Request
    request_body: Any
    upstream_resp: httpx.Response
    client: httpx.AsyncClient
    t_start: float
    started_at_unix_ms: float


class ProbeProxy:
    def __init__(
        self,
        target: str,
        output: Path,
        *,
        upstream_timeout_s: float | None = None,
    ) -> None:
        self.target = target.rstrip("/")
        self.output = output
        self.upstream_timeout_s = upstream_timeout_s
        logger.info(
            "probe.proxy_init",
            extra={"target": self.target, "output": str(self.output)},
        )

    def starlette(self) -> Starlette:
        return Starlette(routes=[
            Route(
                "/{path:path}", self._handle,
                methods=["GET", "POST", "PUT", "DELETE",
                         "PATCH", "OPTIONS"],
            ),
        ])

    async def _handle(self, request: Request) -> Response:
        request_id = uuid.uuid4().hex
        request_body_raw = await request.body()
        request_body = _parse_request_body(request_body_raw)
        is_streaming = (
            isinstance(request_body, dict)
            and request_body.get("stream", False)
        )

        # Probe is observational infrastructure. By default it must not impose
        # a shorter request lifetime than the client it is observing. This is
        # especially important for cold-compiling inference engines, where a
        # healthy non-streaming response can legitimately take several minutes.
        client = httpx.AsyncClient(timeout=self.upstream_timeout_s)
        t_start = time.monotonic()
        started_at_unix_ms = time.time_ns() / 1_000_000

        try:
            upstream_resp = await self._send_upstream(
                client, request, request_body_raw, is_streaming,
            )
        except httpx.HTTPError as exc:
            return await self._handle_upstream_error(
                exc, client, request, request_id,
                request_body, is_streaming,
                t_start, started_at_unix_ms,
            )

        ctx = _RequestContext(
            request_id=request_id,
            request=request, request_body=request_body,
            upstream_resp=upstream_resp, client=client,
            t_start=t_start,
            started_at_unix_ms=started_at_unix_ms,
        )
        if is_streaming:
            return await self._handle_streaming(ctx)
        else:
            return await self._handle_non_streaming(ctx)

    async def _send_upstream(
        self, client: httpx.AsyncClient, request: Request,
        request_body_raw: bytes, is_streaming: bool,
    ) -> httpx.Response:
        path = request.url.path
        query = str(request.url.query) if request.url.query else None
        upstream_url = f"{self.target}{path}"
        if query:
            upstream_url += f"?{query}"

        fwd_headers = dict(request.headers)
        fwd_headers.pop("host", None)
        fwd_headers.pop("accept-encoding", None)

        upstream_req = client.build_request(
            request.method, upstream_url,
            headers=fwd_headers, content=request_body_raw,
        )
        return await client.send(upstream_req, stream=is_streaming)

    async def _handle_upstream_error(  # noqa: PLR0913, PLR0917
        self, exc: httpx.HTTPError, client: httpx.AsyncClient,
        request: Request, request_id: str, request_body: Any,
        is_streaming: bool, t_start: float, started_at_unix_ms: float,
    ) -> Response:
        await client.aclose()
        logger.exception(
            "probe.upstream_error",
            extra={"request_id": request_id, "error": str(exc)},
        )
        elapsed_ms = round((time.monotonic() - t_start) * 1000, 2)
        trace = {
            "request_id": request_id,
            "timestamp": _unix_ms_to_iso8601(started_at_unix_ms),
            "started_at_unix_ms": started_at_unix_ms,
            "ended_at_unix_ms": started_at_unix_ms + elapsed_ms,
            "method": request.method,
            "path": request.url.path,
            "request_headers": _sanitize_headers(dict(request.headers)),
            "request_body": request_body,
            "response_body": None,
            "ttft_ms": None,
            "e2e_ms": elapsed_ms,
            "input_tokens": None,
            "output_tokens": None,
            "cache_read_tokens": None,
            "status_code": 502,
            "streaming": is_streaming,
            "chunk_count": None,
            "error": str(exc),
        }
        _append_trace_jsonl_line(self.output, trace)
        err_body = json.dumps({
            "error": {
                "message": f"upstream error: {exc}",
                "type": "proxy_error",
            },
        })
        return Response(err_body, status_code=502, media_type="application/json")

    async def _handle_non_streaming(
        self, ctx: _RequestContext,
    ) -> Response:
        try:
            body_bytes = await ctx.upstream_resp.aread()
        finally:
            await ctx.upstream_resp.aclose()
            await ctx.client.aclose()

        e2e_ms = round(
            (time.monotonic() - ctx.t_start) * 1000, 2,
        )

        response_body: Any = None
        try:
            response_body = json.loads(body_bytes)
        except (json.JSONDecodeError, ValueError):
            response_body = body_bytes.decode(
                "utf-8", errors="replace",
            )

        usage = (
            _extract_usage(response_body)
            if isinstance(response_body, dict)
            else {}
        )

        trace = {
            "request_id": ctx.request_id,
            "timestamp": _unix_ms_to_iso8601(ctx.started_at_unix_ms),
            "started_at_unix_ms": ctx.started_at_unix_ms,
            "ended_at_unix_ms": ctx.started_at_unix_ms + e2e_ms,
            "method": ctx.request.method,
            "path": ctx.request.url.path,
            "request_headers": _sanitize_headers(
                dict(ctx.request.headers),
            ),
            "request_body": ctx.request_body,
            "response_body": response_body,
            "ttft_ms": None,
            "e2e_ms": e2e_ms,
            **usage,
            "status_code": ctx.upstream_resp.status_code,
            "streaming": False,
            "chunk_count": None,
        }
        _append_trace_jsonl_line(self.output, trace)
        logger.info(
            "probe.request_recorded",
            extra={
                "request_id": ctx.request_id,
                "path": ctx.request.url.path,
                "streaming": False,
                "e2e_ms": e2e_ms,
            },
        )

        resp_headers = dict(ctx.upstream_resp.headers)
        resp_headers.pop("transfer-encoding", None)
        resp_headers.pop("content-encoding", None)
        return Response(
            body_bytes,
            status_code=ctx.upstream_resp.status_code,
            headers=resp_headers,
        )

    async def _handle_streaming(
        self, ctx: _RequestContext,
    ) -> StreamingResponse:
        resp_headers = dict(ctx.upstream_resp.headers)
        resp_headers.pop("content-length", None)
        return StreamingResponse(
            _stream_and_record(ctx, self.output),
            status_code=ctx.upstream_resp.status_code,
            headers=resp_headers,
            media_type="text/event-stream",
        )


async def _stream_and_record(
    ctx: _RequestContext, output: Path,
) -> AsyncGenerator[bytes, None]:
    accumulated_raw: list[bytes] = []
    chunk_count = 0
    ttft_ms: float | None = None
    first_data_seen = False
    last_sse_data: str | None = None

    try:
        async for raw_chunk in ctx.upstream_resp.aiter_bytes():
            now = time.monotonic()
            chunk_count += 1
            if not first_data_seen:
                data = _parse_sse_data(raw_chunk)
                if data is not None:
                    first_data_seen = True
                    ttft_ms = round(
                        (now - ctx.t_start) * 1000, 2,
                    )
            data = _parse_sse_data(raw_chunk)
            if data is not None:
                last_sse_data = data
            accumulated_raw.append(raw_chunk)
            yield raw_chunk
    finally:
        await ctx.upstream_resp.aclose()
        await ctx.client.aclose()

        e2e_ms = round(
            (time.monotonic() - ctx.t_start) * 1000, 2,
        )
        response_body = b"".join(
            accumulated_raw,
        ).decode("utf-8", errors="replace")

        usage = _extract_streaming_usage(last_sse_data)
        trace = {
            "request_id": ctx.request_id,
            "timestamp": _unix_ms_to_iso8601(ctx.started_at_unix_ms),
            "started_at_unix_ms": ctx.started_at_unix_ms,
            "ended_at_unix_ms": ctx.started_at_unix_ms + e2e_ms,
            "method": ctx.request.method,
            "path": ctx.request.url.path,
            "request_headers": _sanitize_headers(
                dict(ctx.request.headers),
            ),
            "request_body": ctx.request_body,
            "response_body": response_body,
            "ttft_ms": ttft_ms,
            "e2e_ms": e2e_ms,
            **usage,
            "status_code": ctx.upstream_resp.status_code,
            "streaming": True,
            "chunk_count": chunk_count,
        }
        _append_trace_jsonl_line(output, trace)
        logger.info(
            "probe.request_recorded",
            extra={
                "request_id": ctx.request_id,
                "path": ctx.request.url.path,
                "streaming": True,
                "chunk_count": chunk_count,
                "ttft_ms": ttft_ms,
                "e2e_ms": e2e_ms,
            },
        )


def _parse_request_body(raw: bytes) -> Any:
    try:
        return json.loads(raw) if raw else None
    except (json.JSONDecodeError, ValueError):
        return raw.decode("utf-8", errors="replace")


def _extract_streaming_usage(
    last_sse_data: str | None,
) -> dict[str, int | None]:
    if last_sse_data is None:
        return {}
    try:
        parsed = json.loads(last_sse_data)
        if isinstance(parsed, dict):
            return _extract_usage(parsed)
    except (json.JSONDecodeError, ValueError):
        pass
    return {}


def _append_trace_jsonl_line(path: Path, trace: dict[str, Any]) -> dict[str, Any]:
    trace["v"] = _SCHEMA_VERSION
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(trace, default=str, sort_keys=True) + "\n")
    return trace


def _sanitize_headers(headers: dict[str, str]) -> dict[str, str]:
    return {k: v for k, v in headers.items() if k.lower() not in _SENSITIVE_HEADERS}


def _extract_usage(body: dict[str, Any]) -> dict[str, int | None]:
    usage = body.get("usage") or {}
    return {
        "input_tokens": usage.get("prompt_tokens") or usage.get("input_tokens"),
        "output_tokens": usage.get("completion_tokens") or usage.get("output_tokens"),
        "cache_read_tokens": (
            usage.get("cache_read_input_tokens")
            or (usage.get("prompt_tokens_details") or {}).get("cached_tokens")
        ),
    }


def _unix_ms_to_iso8601(unix_ms: float) -> str:
    return time.strftime(
        "%Y-%m-%dT%H:%M:%S", time.gmtime(unix_ms / 1000),
    )


def _parse_sse_data(raw: bytes) -> str | None:
    text = raw.decode("utf-8", errors="replace")
    for line in text.splitlines():
        if line.startswith("data: "):
            payload = line[6:].strip()
            if payload == "[DONE]":
                return None
            return payload
    return None
