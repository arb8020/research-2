"""Logging setup — console + JSONL formatters over stdlib logging."""

from __future__ import annotations

import json
import logging
import logging.handlers
import time
from pathlib import Path
from typing import Any

from observe._record import METRIC_NAME_ATTR, STANDARD_RECORD_ATTRS

_MAX_DISPLAY_LEN = 120

# Machine fields a human reading the console does not act on: span identity (it links lines in
# the JSONL, where it is always kept) and raw nanos (duration_ms says the same thing readably).
# `kind` too — a span line is recognisable by duration_ms, a metric by value.
CONSOLE_HIDDEN = frozenset({
    "kind", "trace_id", "span_id", "parent_span_id", "start_time_unix_nano", "end_time_unix_nano",
})  # fmt: skip


class ConsoleFormatter(logging.Formatter):
    """Human-readable: [HH:MM:SS] LEVEL: message  [key=val, key=val]

    Lossy on purpose: CONSOLE_HIDDEN fields are dropped here and kept in the JSONL."""

    def format(self, record: logging.LogRecord) -> str:
        ts = time.strftime("%H:%M:%S", time.localtime(record.created))
        level = record.levelname

        # Allow human_message override for machine-friendly event names
        msg = getattr(record, "human_message", None) or record.getMessage()

        # Collect extra= kwargs. METRIC_NAME_ATTR is already the message.
        extras = {
            k: v
            for k, v in record.__dict__.items()
            if k not in STANDARD_RECORD_ATTRS
            and k not in ("human_message", METRIC_NAME_ATTR)
            and k not in CONSOLE_HIDDEN
        }

        if extras:
            parts = []
            for k, v in extras.items():
                s = str(v)
                if len(s) > _MAX_DISPLAY_LEN:
                    s = s[:_MAX_DISPLAY_LEN] + "…"
                parts.append(f"{k}={s}")
            extra_str = "  [" + ", ".join(parts) + "]"
        else:
            extra_str = ""

        return f"[{ts}] {level}: {msg}{extra_str}"


class JsonlFormatter(logging.Formatter):
    """One JSON line per record. Flattens extra= kwargs to top level."""

    def __init__(self, static_fields: dict[str, Any] | None = None) -> None:
        super().__init__()
        self._static = static_fields or {}

    def format(self, record: logging.LogRecord) -> str:
        """Emit exactly the DESIGN.md field set for this record's kind.

        The ONLY place that branches on `kind`. Per kind we build the fixed
        fields, then layer static_fields and attrs on top. `level`/`event`/
        `logger` are log-only — a metric or span carrying them would be a
        contract violation that the TS parser folds into `attrs`.
        """
        attrs: dict[str, Any] = {}
        for key, value in record.__dict__.items():
            if key in STANDARD_RECORD_ATTRS or key == "human_message":
                continue
            # `name` is stdlib-reserved on a LogRecord (it is the logger name),
            # so metric() smuggles the point name through METRIC_NAME_ATTR and
            # it is renamed here, at the on-disk boundary.
            attrs["name" if key == METRIC_NAME_ATTR else key] = value

        kind = attrs.pop("kind", "log")
        message = record.getMessage()
        obj: dict[str, Any]

        if kind == "log":
            obj = {
                "ts": record.created,
                "kind": "log",
                "level": record.levelname,
                "event": message,
                "logger": record.name,
            }
        elif kind == "metric":
            obj = {
                "ts": record.created,
                "kind": "metric",
                "name": attrs.pop("name", message),
                "value": attrs.pop("value"),
            }
        elif kind == "artifact":
            # `payload` stays a Python object here so json.dumps writes it as a
            # nested JSON value. _artifact.artifact() has already proved it
            # serializes and fits the size cap, so the `default=str` fallback
            # below can never reach it.
            obj = {
                "ts": record.created,
                "kind": "artifact",
                "name": attrs.pop("name", message),
                "mime": attrs.pop("mime"),
                "payload": attrs.pop("payload"),
            }
        elif kind == "span":
            # parent_span_id is always present; JSON null means "root span"
            # (parse.ts requireNullableString requires the key).
            obj = {
                "ts": record.created,
                "kind": "span",
                "span_name": message,
                "trace_id": attrs.pop("trace_id"),
                "span_id": attrs.pop("span_id"),
                "parent_span_id": attrs.pop("parent_span_id", None),
                "start_time_unix_nano": attrs.pop("start_time_unix_nano"),
                "end_time_unix_nano": attrs.pop("end_time_unix_nano"),
                "duration_ms": attrs.pop("duration_ms"),
                "status": attrs.pop("status"),
            }
            for optional in ("error", "error_type"):
                if optional in attrs:
                    obj[optional] = attrs.pop(optional)
        else:
            raise AssertionError(f"unknown kind {kind!r} on record {message!r}")

        # static_fields are attrs (DESIGN.md): stamped on every line, never fixed.
        obj.update(self._static)
        obj.update(attrs)

        if record.exc_info and record.exc_info[1]:
            obj["exception"] = str(record.exc_info[1])
            obj["exception_type"] = type(record.exc_info[1]).__name__

        return json.dumps(obj, default=str)


# Noisy loggers to silence
_QUIET_LOGGERS = (
    "paramiko",
    "httpx",
    "httpcore",
    "urllib3",
    "requests",
    "asyncio",
)


def setup_logging(
    *,
    level: int = logging.DEBUG,
    console_level: int = logging.INFO,
    log_file: str | Path | None = None,
    static_fields: dict[str, Any] | None = None,
) -> None:
    """Configure logging with console + optional JSONL file output.

    Args:
        level: Root logger level.
        console_level: Console handler level.
        log_file: Path to JSONL log file (rotating, 100MB, 5 backups).
        static_fields: Fields injected into every JSONL line (e.g. service name).
    """
    root = logging.getLogger()
    root.setLevel(level)

    # Clear existing handlers
    root.handlers.clear()

    # Console
    console = logging.StreamHandler()
    console.setLevel(console_level)
    console.setFormatter(ConsoleFormatter())
    root.addHandler(console)

    # JSONL file
    if log_file:
        path = Path(log_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            path,
            maxBytes=100_000_000,  # 100MB
            backupCount=5,
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(JsonlFormatter(static_fields=static_fields))
        root.addHandler(file_handler)

    # Silence noisy libraries
    for name in _QUIET_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)
