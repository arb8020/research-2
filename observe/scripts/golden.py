"""Generate the golden JSONL fixture — the on-disk contract, byte for byte.

Deterministic by construction: the clock, the id generator and the static fields
are all pinned, so two runs produce identical bytes. The output is committed at
observe/dashboard/src/core/__fixtures__/golden.jsonl and is the single fixture
both test suites read: Python asserts the bytes still regenerate, TypeScript
asserts every line parses into the shape DESIGN.md promises.

    python3 observe/scripts/golden.py [out.jsonl]
"""

from __future__ import annotations

import logging
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from observe import _metric as metric_mod
from observe import _span as span_mod
from observe import artifact, metric, metrics, setup_logging, span
from observe._span import SpanContext

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE = REPO_ROOT / "observe/dashboard/src/core/__fixtures__/golden.jsonl"

# Pinned so the fixture is byte-stable.
BASE_TS = 1789669021.7
TICK = 0.1
STATIC_FIELDS = {
    "run_id": "goldenrun",
    "run_name": "golden",
    "git_sha": "0000000",
    "git_dirty": False,
}
PARENT_TRACE_ID = "a" * 32
PARENT_SPAN_ID = "d" * 16


def seeded_hex(n_bytes: int, counter: list[int]) -> str:
    """Deterministic stand-in for os.urandom(n).hex(): "01", "02", ... repeated.

    span() asks for 8 bytes (span_id) and, for a root span, 16 (trace_id); the
    width is whatever the caller asked for, so the ids stay well-formed.
    """
    counter[0] += 1
    return f"{counter[0]:02x}" * n_bytes


class FakeClock:
    """Monotonic fake clock: every read advances by a fixed TICK."""

    def __init__(self, start: float = BASE_TS, tick: float = TICK) -> None:
        self._now = start
        self._tick = tick

    def time(self) -> float:
        self._now += self._tick
        self._now = round(self._now, 3)
        return self._now

    def time_ns(self) -> int:
        return int(self.time() * 1_000_000_000)


@contextmanager
def pinned_world() -> Iterator[None]:
    """Freeze every source of nondeterminism the emitters touch."""
    clock = FakeClock()
    counter = [0]

    real_record_factory = logging.getLogRecordFactory()

    def factory(*args: object, **kwargs: object) -> logging.LogRecord:
        record = real_record_factory(*args, **kwargs)  # type: ignore[arg-type]
        record.created = clock.time()
        return record

    saved = (span_mod.time.time_ns, span_mod._rand_hex, metric_mod.time.time)
    logging.setLogRecordFactory(factory)
    span_mod.time.time_ns = clock.time_ns  # type: ignore[assignment]
    span_mod._rand_hex = lambda n: seeded_hex(n, counter)  # type: ignore[assignment]
    metric_mod.time.time = clock.time  # type: ignore[assignment]
    try:
        yield
    finally:
        logging.setLogRecordFactory(real_record_factory)
        span_mod.time.time_ns, span_mod._rand_hex, metric_mod.time.time = saved  # type: ignore[assignment]


def emit_all() -> None:
    """Every shape the contract allows, once."""
    log = logging.getLogger("robots.train")

    log.info("run_start", extra={"env_name": "CartPole-v1", "num_iters": 3, "lr": 0.0003})
    log.warning("slow_iteration", extra={"step": 2, "elapsed_s": 4.2})

    # One ok span with a parent, one error span (root).
    parent = SpanContext(trace_id=PARENT_TRACE_ID, span_id=PARENT_SPAN_ID)
    with span("robots.rollout", parent=parent, attributes={"step": 1}):
        pass
    try:
        with span("robots.eval", attributes={"step": 2}):
            raise ValueError("boom")
    except ValueError:
        pass

    # 2 names x 3 steps = 6 metric points, plus one stepless point = 7.
    for step in (1, 2, 3):
        metrics(
            {"wm_loss": round(1.5 - 0.1 * step, 3), "pi_loss": round(0.8 - 0.05 * step, 3)},
            step=step,
        )
    metric("wall_clock_s", 12.5)

    # One artifact: a 3-step CartPole trajectory. `obs` is len(actions) + 1 —
    # it carries the terminal observation so a renderer can draw the last frame
    # (DESIGN.md "Artifacts").
    artifact(
        "rollout",
        {
            "env": "CartPole-v1",
            "obs": [
                [0.0, 0.0, 0.0, 0.0],
                [0.01, 0.15, -0.02, -0.21],
                [0.02, 0.34, -0.06, -0.52],
                [0.04, 0.53, -0.11, -0.84],
            ],
            "actions": [1, 1, 0],
            "rewards": [1.0, 1.0, 1.0],
        },
        mime="application/x-trajectory+json",
        step=3,
    )

    log.info("run_end", extra={"iters_completed": 3})


def generate(out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()
    setup_logging(
        log_file=out,
        static_fields=STATIC_FIELDS,
        console_level=logging.CRITICAL,
    )
    try:
        with pinned_world():
            emit_all()
    finally:
        for handler in list(logging.getLogger().handlers):
            handler.close()
        logging.getLogger().handlers.clear()


def main() -> None:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else FIXTURE
    generate(out)
    print(f"wrote {out} ({len(out.read_text().splitlines())} lines)")


if __name__ == "__main__":
    main()
