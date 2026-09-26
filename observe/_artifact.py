"""Artifacts — one named, typed blob of structured data per log record.

    artifact("rollout", {"env": "CartPole-v1", "obs": [...], ...},
             mime="application/x-trajectory+json", step=42)

On disk (see DESIGN.md "Artifacts"): {ts, kind: "artifact", name, mime, payload, ...attrs}

A metric is a number; an artifact is a *structure* — a trajectory, an attention
map, a config tree — that a purpose-built renderer knows how to draw. The `mime`
is what tells a renderer whether this artifact is for it. `payload` is inline
JSON, bounded: file-backed artifacts (a PNG, a checkpoint) are deliberately
deferred, so the size assert here is the whole story on how big one can get.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from observe._record import METRIC_NAME_ATTR, STANDARD_RECORD_ATTRS

logger = logging.getLogger("observe.artifact")

# Inline payloads only. A JSONL line is read whole by every consumer (the
# tailer, DuckDB, `jq`), so an unbounded payload is an unbounded line: one
# 500 MiB artifact would take the dashboard down rather than render slowly.
# 1 MiB holds a 500-step CartPole trajectory ~40x over.
MAX_PAYLOAD_BYTES = 1024 * 1024

# Attrs the artifact record owns; a caller attr of the same name would silently
# overwrite the artifact and is a programmer error. Mirrors _metric.py.
_RESERVED_ATTRS = frozenset({"kind", "name", "mime", "payload", "ts", METRIC_NAME_ATTR})


def _check_attrs(attrs: dict[str, Any]) -> None:
    for key in attrs:
        assert key not in _RESERVED_ATTRS, f"attr {key!r} is reserved by artifact records"
        assert key not in STANDARD_RECORD_ATTRS, (
            f"attr {key!r} collides with a stdlib LogRecord field"
        )


def _serialize(name: str, payload: Any) -> str:
    """Serialize once, here, so the size assert is measured and not estimated.

    `default=` is deliberately NOT passed: `json.dumps(..., default=str)` in the
    formatter would turn an un-serializable payload into a plausible-looking
    string and ship it. An artifact whose payload is a tensor is a bug in the
    caller, and it should crash at the call site.
    """
    try:
        text = json.dumps(payload)
    except (TypeError, ValueError) as exc:
        raise AssertionError(
            f"artifact {name!r}: payload must be JSON-serializable, got {exc}"
        ) from exc
    size = len(text.encode("utf-8"))
    assert size <= MAX_PAYLOAD_BYTES, (
        f"artifact {name!r}: payload is {size} bytes, over the 1 MiB inline cap "
        f"({MAX_PAYLOAD_BYTES}); file-backed artifacts are not implemented yet"
    )
    return text


def artifact(name: str, payload: Any, *, mime: str, **attrs: Any) -> None:
    """Emit one artifact.

    Args:
        name: What this artifact is, stable across steps ("rollout"). A renderer
            keeps the latest artifact per name.
        payload: Any JSON-serializable value. Goes to disk as JSON, not a string.
        mime: The payload's type, e.g. "application/x-trajectory+json". This is
            the renderer's selector — a renderer that does not know the mime
            must leave the artifact alone rather than guess at its shape.
        **attrs: Everything else, `step` included (DESIGN.md: step is an attr).
    """
    assert isinstance(name, str), f"artifact name must be str, got {type(name).__name__}"
    assert name, "artifact name must be non-empty"
    assert isinstance(mime, str), f"artifact {name!r}: mime must be str, got {type(mime).__name__}"
    assert mime, f"artifact {name!r}: mime must be non-empty"
    _check_attrs(attrs)
    _serialize(name, payload)

    logger.info(
        name,
        extra={
            "kind": "artifact",
            METRIC_NAME_ATTR: name,
            "mime": mime,
            "payload": payload,
            **attrs,
        },
    )
