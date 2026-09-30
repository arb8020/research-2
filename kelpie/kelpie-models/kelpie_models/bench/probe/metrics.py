# copied from crucible/verification/engines/probe/metrics.py @ dfb735f9a8d9
from __future__ import annotations

import json
import logging
from pathlib import Path
from statistics import fmean, quantiles
from typing import Any, Iterable

logger = logging.getLogger("crucible.verification.engines.probe.metrics")


def load_traces(path: Path) -> list[dict[str, Any]]:
    traces: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as source:
        for lineno, raw_line in enumerate(source, 1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                traces.append(json.loads(line))
            except json.JSONDecodeError as exc:
                logger.warning(
                    "probe.bad_trace_line",
                    extra={
                        "path": str(path),
                        "lineno": lineno,
                        "error": str(exc),
                    },
                )
    return traces


def performance_report(
    traces: Iterable[dict[str, Any]],
    *,
    workload: dict[str, Any] | None = None,
    accelerator_count: int = 1,
) -> dict[str, Any]:
    if accelerator_count < 1:
        msg = "accelerator_count must be at least one"
        raise ValueError(msg)

    records = list(traces)
    successful = [t for t in records if _is_successful(t)]
    ttft = [float(t["ttft_ms"]) for t in successful if t.get("ttft_ms") is not None]
    e2e = [float(t["e2e_ms"]) for t in successful if t.get("e2e_ms") is not None]

    tpot, effective_prefill = _decode_series(successful)
    wall_ms, output_tokens_per_second = _throughput(successful)
    cache_observed, cache_hit_rate = _cache_stats(successful)
    warnings = _build_warnings(ttft, tpot, cache_observed)

    decode_tokens_per_second_per_user = [
        1000 / value for value in tpot if value > 0
    ]
    return {
        "schema_version": 1,
        "semantics": "client_observed",
        "workload": workload or {},
        "accelerator_count": accelerator_count,
        "requests": {
            "total": len(records),
            "successful": len(successful),
            "failure_rate": (
                (len(records) - len(successful)) / len(records)
                if records else None
            ),
        },
        "ttft_ms": _distribution(ttft),
        "e2e_ms": _distribution(e2e),
        "tpot_ms": _distribution(tpot),
        "decode_tokens_per_second_per_user": _distribution(
            decode_tokens_per_second_per_user,
        ),
        "effective_prefill_tokens_per_second_per_request": (
            _distribution(effective_prefill)
        ),
        "output_tokens_per_second": output_tokens_per_second,
        "output_tokens_per_second_per_accelerator": (
            output_tokens_per_second / accelerator_count
            if output_tokens_per_second is not None
            else None
        ),
        "cache_hit_rate": cache_hit_rate,
        "measurement_window_ms": wall_ms if wall_ms else None,
        "warnings": warnings,
    }


def _is_successful(trace: dict[str, Any]) -> bool:
    _OK_MIN, _OK_MAX = 200, 300  # noqa: PLR2004
    return (
        _OK_MIN <= int(trace.get("status_code", 0)) < _OK_MAX
        and trace.get("error") is None
    )


def _decode_series(
    successful: list[dict[str, Any]],
) -> tuple[list[float], list[float]]:
    tpot: list[float] = []
    effective_prefill: list[float] = []
    for trace in successful:
        output_tokens = trace.get("output_tokens")
        ttft_ms = trace.get("ttft_ms")
        e2e_ms = trace.get("e2e_ms")
        if (
            trace.get("streaming")
            and output_tokens is not None
            and output_tokens > 1
            and ttft_ms is not None
            and e2e_ms is not None
            and e2e_ms >= ttft_ms
        ):
            tpot.append((e2e_ms - ttft_ms) / (output_tokens - 1))
        input_tokens = trace.get("input_tokens")
        if input_tokens is not None and ttft_ms is not None and ttft_ms > 0:
            effective_prefill.append(input_tokens * 1000 / ttft_ms)
    return tpot, effective_prefill


def _throughput(successful: list[dict[str, Any]]) -> tuple[float, float | None]:
    timed = [
        trace
        for trace in successful
        if trace.get("started_at_unix_ms") is not None
        and trace.get("ended_at_unix_ms") is not None
    ]
    wall_ms = (
        max(float(t["ended_at_unix_ms"]) for t in timed)
        - min(float(t["started_at_unix_ms"]) for t in timed)
        if timed
        else 0.0
    )
    total_output_tokens = sum(int(t.get("output_tokens") or 0) for t in timed)
    output_tokens_per_second = (
        total_output_tokens * 1000 / wall_ms if wall_ms > 0 else None
    )
    return wall_ms, output_tokens_per_second


def _cache_stats(successful: list[dict[str, Any]]) -> tuple[bool, float | None]:
    cache_observed = any(t.get("cache_read_tokens") is not None for t in successful)
    total_input_tokens = sum(int(t.get("input_tokens") or 0) for t in successful)
    cached_tokens = sum(int(t.get("cache_read_tokens") or 0) for t in successful)
    cache_hit_rate = (
        cached_tokens / total_input_tokens
        if cache_observed and total_input_tokens > 0
        else None
    )
    return cache_observed, cache_hit_rate


def _build_warnings(
    ttft: list[float], tpot: list[float], cache_observed: bool,
) -> list[str]:
    warnings = []
    _MIN_P99_SAMPLES = 100
    if len(ttft) < _MIN_P99_SAMPLES:
        warnings.append(
            "p99 estimates are low-confidence with"
            " fewer than 100 samples"
        )
    if not tpot:
        warnings.append("TPOT requires streaming traces with output token counts")
    if not cache_observed:
        warnings.append("cache hit rate was not reported by the endpoint")
    return warnings


def _distribution(values: Iterable[float]) -> dict[str, float | int | None]:
    samples = list(values)
    if not samples:
        return {
            "count": 0, "mean": None,
            "p50": None, "p95": None, "p99": None,
        }
    cuts = quantiles(samples, n=100) if len(samples) >= 2 else [samples[0]] * 99
    return {
        "count": len(samples),
        "mean": fmean(samples),
        "p50": cuts[49],
        "p95": cuts[94],
        "p99": cuts[98],
    }
