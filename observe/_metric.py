"""Metric points — one gauge data point per log record.

    metric("wm_loss", 1.23, step=4)
    metrics({"wm_loss": 1.23, "pi_loss": 0.4}, step=4)   # N points, one shared ts

On disk (see DESIGN.md): {ts, kind: "metric", name, value, ...attrs}
"""

from __future__ import annotations

import logging
import math
import time
from typing import Any

from observe._record import METRIC_NAME_ATTR, STANDARD_RECORD_ATTRS

logger = logging.getLogger("observe.metric")

# Attrs the metric record owns; a caller attr of the same name would silently
# overwrite the point and is a programmer error.
_RESERVED_ATTRS = frozenset({"kind", "name", "value", "ts", METRIC_NAME_ATTR})


def _check_value(name: str, value: float) -> None:
    """A metric point must be a real, finite number."""
    assert isinstance(name, str), f"metric name must be str, got {type(name).__name__}"
    assert name, "metric name must be non-empty"
    assert not isinstance(value, bool), f"metric {name!r}: bool is not a measurement"
    assert isinstance(value, (int, float)), (
        f"metric {name!r}: value must be int|float, got {type(value).__name__}"
    )
    assert not math.isnan(value), f"metric {name!r}: NaN is not a measurement"
    assert math.isfinite(value), f"metric {name!r}: value must be finite, got {value}"


def _check_attrs(attrs: dict[str, Any]) -> None:
    for key in attrs:
        assert key not in _RESERVED_ATTRS, f"attr {key!r} is reserved by metric records"
        assert key not in STANDARD_RECORD_ATTRS, (
            f"attr {key!r} collides with a stdlib LogRecord field"
        )


def metric(name: str, value: float, **attrs: Any) -> None:
    """Emit one metric data point."""
    _check_value(name, value)
    _check_attrs(attrs)
    logger.info(
        name,
        extra={"kind": "metric", METRIC_NAME_ATTR: name, "value": float(value), **attrs},
    )


def metrics(values: dict[str, float], **attrs: Any) -> None:
    """Emit one metric point per entry, all sharing a single explicit `ts`.

    The formatter derives `ts` from record.created, which is sampled per record —
    N records would land on N microscopically different timestamps. We sample the
    clock once here and pass it as an explicit attr so the points are provably
    simultaneous (the formatter's flatten puts extras after `ts`, so this wins).
    """
    assert isinstance(values, dict), f"metrics expects a dict, got {type(values).__name__}"
    assert values, "metrics called with no values"
    _check_attrs(attrs)
    for name, value in values.items():
        _check_value(name, value)

    shared_ts = time.time()
    for name, value in values.items():
        logger.info(
            name,
            extra={
                "kind": "metric",
                METRIC_NAME_ATTR: name,
                "value": float(value),
                "ts": shared_ts,
                **attrs,
            },
        )
