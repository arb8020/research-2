"""Wide event spans — one structured log line per unit of work.

Usage:
    with span("box.launch", attributes={"provider": "runpod"}) as s:
        pod_id = do_launch()
        s.set_attr("pod_id", pod_id)
    # emits ONE log line at exit with all attributes flattened

Nesting: a span opened inside another span's `with` block is its child — same trace_id,
parent_span_id = the enclosing span's span_id — via a ContextVar, no argument threading.
An explicit `parent=` or `trace_id=` opts out of that and wins.

Threads: a `threading.Thread` target starts with an EMPTY context (contextvars are copied
into asyncio tasks, not into threads), so a span opened in a thread is a new root. To keep it
in the trace, pass `parent=s.context` into the thread, or start the thread with
`target=contextvars.copy_context().run, args=(fn, ...)`.
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Literal

logger = logging.getLogger(__name__)

# The two outcomes a span can have. DESIGN.md pins this set on disk:
# `status: "ok"|"error"`, with error/error_type present only when "error".
SpanStatus = Literal["ok", "error"]


def _rand_hex(n_bytes: int) -> str:
    return os.urandom(n_bytes).hex()


@dataclass(frozen=True)
class SpanContext:
    trace_id: str  # 32 hex chars (128 bits)
    span_id: str  # 16 hex chars (64 bits)


# The innermost open span in this context (thread / asyncio task); None outside any span.
# Set on span entry, reset on exit — including exit by exception.
_current: ContextVar[SpanContext | None] = ContextVar("observe_current_span", default=None)


def current_span_context() -> SpanContext | None:
    """The innermost open span here, or None. What a span with no parent= would inherit."""
    return _current.get()


@dataclass
class SpanState:
    """Mutable handle yielded inside the span. Use set_attr to build the event."""

    context: SpanContext
    _attrs: dict[str, Any] = field(default_factory=dict)

    def set_attr(self, key: str, value: Any) -> None:
        self._attrs[key] = value

    def set_attrs(self, **kwargs: Any) -> None:
        self._attrs.update(kwargs)


@dataclass(frozen=True)
class SpanRecord:
    """One completed span, exactly as it goes to disk.

    Identity (trace_id/span_id/parent_span_id), timing (start_ns/end_ns), outcome
    (status), and the attributes built up during the span. Constructed once at span
    exit; `emit_span_record` is the only consumer.
    """

    name: str
    trace_id: str
    span_id: str
    parent_span_id: str | None
    start_ns: int
    end_ns: int
    status: SpanStatus
    attributes: dict[str, Any]


def emit_span_record(record: SpanRecord) -> None:
    """THE single emitter. Every span goes through here."""
    assert len(record.trace_id) == 32, f"trace_id must be 32 hex chars, got {len(record.trace_id)}"
    assert len(record.span_id) == 16, f"span_id must be 16 hex chars, got {len(record.span_id)}"
    # Literal is erased at runtime, so the sum type is asserted at the one gate
    # every span passes through. A third status would corrupt the on-disk
    # contract silently; this turns it into a crash at the write boundary.
    assert record.status in ("ok", "error"), f"status must be ok|error, got {record.status!r}"

    duration_ms = (record.end_ns - record.start_ns) / 1_000_000

    extra = {
        "kind": "span",
        "trace_id": record.trace_id,
        "span_id": record.span_id,
        "start_time_unix_nano": record.start_ns,
        "end_time_unix_nano": record.end_ns,
        "duration_ms": round(duration_ms, 2),
        "status": record.status,
        **record.attributes,
    }
    if record.parent_span_id:
        extra["parent_span_id"] = record.parent_span_id

    logging.getLogger(record.name).info(record.name, extra=extra)


@contextmanager
def span(
    name: str,
    *,
    parent: SpanContext | None = None,
    trace_id: str | None = None,
    attributes: dict[str, Any] | None = None,
) -> Generator[SpanState, None, None]:
    """Context manager that emits a wide event span on exit.

    Args:
        name: Event name (e.g. "box.launch", "box.exec").
        parent: Parent span context for linking. Default: the enclosing span, if any.
        trace_id: Override trace ID. Given without `parent`, starts a root span in that trace
            (the enclosing span is NOT inherited).
        attributes: Initial attributes.
    """
    if parent is None and trace_id is None:
        parent = _current.get()
    tid = trace_id or (parent.trace_id if parent else _rand_hex(16))
    sid = _rand_hex(8)
    parent_sid = parent.span_id if parent else None

    state = SpanState(context=SpanContext(trace_id=tid, span_id=sid))
    if attributes:
        state.set_attrs(**attributes)

    token = _current.set(state.context)
    start_ns = time.time_ns()
    status: SpanStatus = "ok"
    try:
        yield state
    except Exception as exc:
        status = "error"
        state.set_attr("error", str(exc))
        state.set_attr("error_type", type(exc).__name__)
        raise
    finally:
        end_ns = time.time_ns()
        _current.reset(token)
        emit_span_record(
            SpanRecord(
                name=name,
                trace_id=tid,
                span_id=sid,
                parent_span_id=parent_sid,
                start_ns=start_ns,
                end_ns=end_ns,
                status=status,
                attributes=state._attrs,
            )
        )
