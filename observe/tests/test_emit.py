"""The on-disk contract: every line has an explicit kind, metrics are point-shaped."""

from __future__ import annotations

import contextvars
import io
import json
import logging
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

from observe import artifact, metric, metrics, setup_logging
from observe._artifact import MAX_PAYLOAD_BYTES
from observe._log import ConsoleFormatter
from observe._span import SpanContext, SpanRecord, current_span_context, emit_span_record, span


def read_lines(path: Path) -> list[dict]:
    lines = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    for obj in lines:
        assert "ts" in obj, f"line without ts: {obj}"
        assert "kind" in obj, f"line without kind: {obj}"
    return lines


@pytest.fixture
def run_file(tmp_path: Path) -> Iterator[Path]:
    """A configured logger writing to a fresh JSONL, torn down after the test."""
    path = tmp_path / "run.jsonl"
    setup_logging(
        log_file=path,
        static_fields={"run_id": "abc123", "run_name": "t"},
        console_level=logging.CRITICAL,
    )
    yield path
    for handler in list(logging.getLogger().handlers):
        handler.close()
    logging.getLogger().handlers.clear()


def test_plain_log_line_gets_kind_log(run_file: Path) -> None:
    logging.getLogger("t").info("run_start", extra={"env_name": "CartPole-v1"})
    (line,) = read_lines(run_file)
    assert line["kind"] == "log"
    assert line["event"] == "run_start"
    assert line["env_name"] == "CartPole-v1"
    assert line["run_id"] == "abc123"


def test_metric_line_shape(run_file: Path) -> None:
    metric("eval_reward", 42.5, step=10)
    (line,) = read_lines(run_file)
    assert line["kind"] == "metric"
    assert line["name"] == "eval_reward"
    assert line["value"] == 42.5
    assert line["step"] == 10
    for log_only in ("level", "event", "logger"):
        assert log_only not in line, f"{log_only} is a log-only field"


def test_metrics_emits_one_line_per_value_sharing_ts(run_file: Path) -> None:
    metrics({"wm_loss": 1.5, "pi_loss": 0.25}, step=3)
    lines = read_lines(run_file)
    assert len(lines) == 2
    assert {line["name"] for line in lines} == {"wm_loss", "pi_loss"}
    assert {line["kind"] for line in lines} == {"metric"}
    assert all(line["step"] == 3 for line in lines)
    assert len({line["ts"] for line in lines}) == 1, "metrics points must share one ts"


def test_metric_rejects_non_measurements(run_file: Path) -> None:
    with pytest.raises(AssertionError):
        metric("flag", True)  # bool is not a measurement
    with pytest.raises(AssertionError):
        metric("loss", float("nan"))
    with pytest.raises(AssertionError):
        metric("loss", float("inf"))
    with pytest.raises(AssertionError):
        metric("loss", "1.0")  # type: ignore[arg-type]
    assert not run_file.exists() or read_lines(run_file) == []


def test_metric_rejects_reserved_attr(run_file: Path) -> None:
    with pytest.raises(AssertionError):
        metric("loss", 1.0, ts=2.0)
    with pytest.raises(AssertionError):
        metrics({"loss": 1.0}, name="other")


def test_metrics_rejects_empty(run_file: Path) -> None:
    with pytest.raises(AssertionError):
        metrics({})


SPAN_FIELDS = {
    "ts",
    "kind",
    "span_name",
    "run_id",
    "run_name",
    "trace_id",
    "span_id",
    "start_time_unix_nano",
    "end_time_unix_nano",
    "duration_ms",
    "status",
    "parent_span_id",  # always present; null means root span
}


def test_span_line_field_set_is_pinned(run_file: Path) -> None:
    """The on-disk span shape. Adding/removing a field here is a contract change."""
    with span("robots.rollout", attributes={"step": 7}):
        pass
    (line,) = read_lines(run_file)
    assert set(line) == SPAN_FIELDS | {"step"}, "span field set drifted"
    assert line["kind"] == "span"
    assert line["span_name"] == "robots.rollout"
    assert line["status"] == "ok"
    assert line["step"] == 7
    assert len(line["trace_id"]) == 32
    assert len(line["span_id"]) == 16
    assert line["parent_span_id"] is None, "no parent -> present and null"
    for log_only in ("level", "event", "logger"):
        assert log_only not in line, f"{log_only} is a log-only field"
    assert isinstance(line["start_time_unix_nano"], int)
    assert line["end_time_unix_nano"] >= line["start_time_unix_nano"]


def test_span_error_status_and_parent(run_file: Path) -> None:
    parent = SpanContext(trace_id="a" * 32, span_id="b" * 16)
    with pytest.raises(ValueError, match="boom"), span("robots.eval", parent=parent):
        raise ValueError("boom")
    (line,) = read_lines(run_file)
    assert set(line) == SPAN_FIELDS | {"error", "error_type"}
    assert line["status"] == "error"
    assert line["trace_id"] == "a" * 32, "trace_id inherits from parent"
    assert line["parent_span_id"] == "b" * 16
    assert line["error"] == "boom"
    assert line["error_type"] == "ValueError"


def by_name(lines: list[dict]) -> dict[str, dict]:
    return {line["span_name"]: line for line in lines}


def test_nested_spans_share_trace_and_link_to_enclosing(run_file: Path) -> None:
    with span("outer") as outer, span("mid") as mid:
        with span("inner") as inner:
            assert current_span_context() == inner.context
        assert current_span_context() == mid.context, "inner exit restores mid"
    assert current_span_context() is None, "outermost exit restores no-span"
    lines = by_name(read_lines(run_file))
    assert {line["trace_id"] for line in lines.values()} == {outer.context.trace_id}
    assert lines["outer"]["parent_span_id"] is None
    assert lines["mid"]["parent_span_id"] == outer.context.span_id
    assert lines["inner"]["parent_span_id"] == mid.context.span_id
    assert lines["inner"]["span_id"] == inner.context.span_id


def test_current_span_reset_when_child_raises(run_file: Path) -> None:
    with span("outer") as outer:
        with pytest.raises(ValueError), span("child"):
            raise ValueError("boom")
        assert current_span_context() == outer.context
        with span("sibling"):
            pass
    assert current_span_context() is None
    lines = by_name(read_lines(run_file))
    assert lines["child"]["status"] == "error"
    assert lines["sibling"]["parent_span_id"] == outer.context.span_id


def test_explicit_parent_and_trace_id_win_over_enclosing(run_file: Path) -> None:
    other = SpanContext(trace_id="a" * 32, span_id="b" * 16)
    with span("outer") as outer:
        with span("adopted", parent=other) as adopted, span("grandchild"):
            pass
        with span("new_root", trace_id="c" * 32):
            pass
    lines = by_name(read_lines(run_file))
    assert lines["adopted"]["trace_id"] == "a" * 32
    assert lines["adopted"]["parent_span_id"] == "b" * 16
    assert lines["grandchild"]["trace_id"] == "a" * 32, "children follow the explicit parent"
    assert lines["grandchild"]["parent_span_id"] == adopted.context.span_id
    assert lines["new_root"]["trace_id"] == "c" * 32
    assert lines["new_root"]["parent_span_id"] is None, "trace_id alone starts a root, not a child"
    assert lines["outer"]["trace_id"] == outer.context.trace_id != "a" * 32


def test_thread_does_not_inherit_enclosing_span(run_file: Path) -> None:
    """Pinned so the documented behaviour cannot drift: threads start with an empty context."""

    def work(name: str, parent: SpanContext | None = None) -> None:
        with span(name, parent=parent):
            pass

    with span("outer") as outer:
        for t in (
            threading.Thread(target=work, args=("bare",)),
            threading.Thread(target=work, args=("passed", outer.context)),
            threading.Thread(target=contextvars.copy_context().run, args=(work, "copied")),
        ):
            t.start()
            t.join()
    lines = by_name(read_lines(run_file))
    assert lines["bare"]["parent_span_id"] is None
    assert lines["bare"]["trace_id"] != outer.context.trace_id
    for name in ("passed", "copied"):
        assert lines[name]["parent_span_id"] == outer.context.span_id, name
        assert lines[name]["trace_id"] == outer.context.trace_id, name


def test_console_hides_span_identity_and_nanos_jsonl_keeps_them(run_file: Path) -> None:
    buf = io.StringIO()
    console = logging.StreamHandler(buf)
    console.setFormatter(ConsoleFormatter())
    logging.getLogger().addHandler(console)
    with span("box.exec", attributes={"cmd": "ls"}):
        pass
    err = buf.getvalue()
    assert "box.exec" in err and "duration_ms=" in err and "cmd=ls" in err and "status=ok" in err
    for hidden in ("trace_id", "span_id", "start_time_unix_nano", "end_time_unix_nano", "kind="):
        assert hidden not in err, f"{hidden} leaked to console: {err}"
    (line,) = read_lines(run_file)
    assert set(line) >= SPAN_FIELDS, "JSONL keeps every field the console hides"


def test_emit_span_record_rejects_malformed_ids() -> None:
    bad_trace = SpanRecord(
        name="x",
        trace_id="short",
        span_id="b" * 16,
        parent_span_id=None,
        start_ns=0,
        end_ns=1,
        status="ok",
        attributes={},
    )
    with pytest.raises(AssertionError):
        emit_span_record(bad_trace)


def test_emit_span_record_rejects_unknown_status() -> None:
    """`status` is a sum type: "okay" is not a near-miss, it is a contract violation.

    Literal is erased at runtime, so the emitter asserts the set. A third status
    reaching disk would break every reader's exhaustive switch silently.
    """
    typo = SpanRecord(
        name="x",
        trace_id="a" * 32,
        span_id="b" * 16,
        parent_span_id=None,
        start_ns=0,
        end_ns=1,
        status="okay",  # type: ignore[arg-type]
        attributes={},
    )
    with pytest.raises(AssertionError, match="status must be ok\\|error"):
        emit_span_record(typo)


# ---------------------------------------------------------------- artifacts


def test_artifact_line_shape(run_file: Path) -> None:
    """The on-disk artifact shape: {ts, kind, name, mime, payload} + static + attrs."""
    payload = {"env": "CartPole-v1", "obs": [[0.0, 0.0, 0.0, 0.0]], "actions": [], "rewards": []}
    artifact("rollout", payload, mime="application/x-trajectory+json", step=10)
    (line,) = read_lines(run_file)
    assert set(line) == {"ts", "kind", "name", "mime", "payload", "run_id", "run_name", "step"}
    assert line["kind"] == "artifact"
    assert line["name"] == "rollout"
    assert line["mime"] == "application/x-trajectory+json"
    assert line["payload"] == payload, "payload is a JSON object, not a string"
    assert line["step"] == 10
    for log_only in ("level", "event", "logger"):
        assert log_only not in line, f"{log_only} is a log-only field"


def test_artifact_rejects_empty_name_and_mime(run_file: Path) -> None:
    with pytest.raises(AssertionError, match="name must be non-empty"):
        artifact("", {"a": 1}, mime="application/json")
    with pytest.raises(AssertionError, match="mime must be non-empty"):
        artifact("x", {"a": 1}, mime="")


def test_artifact_rejects_unserializable_payload(run_file: Path) -> None:
    """A payload that cannot round-trip through JSON is a crash, not a str() fallback."""
    with pytest.raises(AssertionError, match="JSON-serializable"):
        artifact("x", {"tensor": object()}, mime="application/json")


def test_artifact_rejects_oversized_payload(run_file: Path) -> None:
    """Inline payloads are bounded at 1 MiB; file-backed artifacts are deferred."""
    huge = {"blob": "x" * (MAX_PAYLOAD_BYTES + 1)}
    with pytest.raises(AssertionError, match="payload is .* bytes, over the 1 MiB"):
        artifact("big", huge, mime="application/json")


def test_artifact_rejects_reserved_attr(run_file: Path) -> None:
    """`kind`/`ts` reach **attrs and are caught here.

    `name`, `mime` and `payload` are real parameters, so Python's own
    "multiple values for argument" TypeError catches those before we do —
    equally loud, one layer earlier.
    """
    for reserved in ("kind", "ts"):
        with pytest.raises(AssertionError, match="reserved"):
            artifact("x", {"a": 1}, mime="application/json", **{reserved: "clobber"})
    with pytest.raises(TypeError, match="multiple values"):
        artifact("x", {"a": 1}, mime="application/json", name="clobber")
