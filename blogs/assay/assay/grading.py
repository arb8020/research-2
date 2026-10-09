"""Grading: a Grader is ordered Checks + config; grade(run, grader) -> a Grade entry, cached by (run, grader fingerprint).

    Grader("op-fp32", checks=(Check("returned", ...), Check("budget", ...)), config={"mult": 2, ...})
    grade(store, run, grader)
      for check in checks:                          in order, all reading the same stored Run
        result = check.fn(run, config)              -> Result(outcome, score, metrics, tags, notes, details)
        a required check that fails halts: every later check is recorded as skipped
        a check that promised files (`creates`) and didn't make them fails
    -> Entry("grade", key(run.key, grader.fingerprint())) with the grader snapshot inside

Regrading never re-runs anything: a changed grader (its code or its config) has a new fingerprint, so only the grade
step misses the cache. The grader fingerprint covers the source files its check functions live in, so editing a
checker makes old grades stale.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from assay.store import Entry, Store, jsonable, key_of, sha256

OUTCOMES = ("pass", "fail", "skip")
KNOWN = ("outcome", "score", "metrics", "tags", "notes", "details", "artifacts")


@dataclass(frozen=True)
class Result:
    """One check's result (smevals' shape). `artifacts` are files the check made, kept with the grade."""

    outcome: str
    score: float | None = None
    metrics: dict[str, Any] = field(default_factory=dict)
    tags: tuple[str, ...] = ()
    notes: str = ""
    details: dict[str, Any] = field(default_factory=dict)
    artifacts: dict[str, bytes] = field(default_factory=dict)

    def __post_init__(self) -> None:
        assert self.outcome in OUTCOMES, self.outcome

    def to_json(self) -> dict[str, Any]:
        return {"outcome": self.outcome, "score": self.score, "metrics": jsonable(self.metrics),
                "tags": list(self.tags), "notes": self.notes, "details": jsonable(self.details),
                "artifacts": sorted(self.artifacts)}


def result(**fields: Any) -> Result:
    """A Result from loose keys (what a check returns): unknown keys fold into details instead of being lost."""
    known = {k: v for k, v in fields.items() if k in KNOWN}
    extra = {k: v for k, v in fields.items() if k not in KNOWN}
    return Result(**{**known, "details": {**known.get("details", {}), **extra}})


def passed(**fields: Any) -> Result:
    return result(outcome="pass", score=1.0, **fields)


def failed(notes: str, **fields: Any) -> Result:
    return result(outcome="fail", score=0.0, notes=notes, **fields)


@dataclass(frozen=True)
class Check:
    name: str
    fn: Callable[[Entry, Mapping[str, Any]], Result]
    required: bool = True  # a failure halts the grader; later checks are recorded as skipped
    creates: tuple[str, ...] = ()  # artifact names this check promises to make


@dataclass(frozen=True)
class Grader:
    name: str
    checks: tuple[Check, ...]
    config: Mapping[str, Any] = field(default_factory=dict)

    def snapshot(self) -> dict[str, Any]:
        """What the grader was, stored with every grade it makes."""
        sources = sorted({inspect.getsourcefile(c.fn) or "?" for c in self.checks} | {__file__})
        return {"name": self.name, "config": dict(self.config),
                "checks": [{"name": c.name, "required": c.required, "creates": list(c.creates),
                            "fn": f"{c.fn.__module__}.{c.fn.__qualname__}"} for c in self.checks],
                "code": {Path(s).name: sha256(Path(s).read_bytes()) for s in sources}}

    def fingerprint(self) -> str:
        return key_of(self.snapshot())


def grade(store: Store, run: Entry, grader: Grader) -> Entry:
    """The grade of `run` under `grader`, from the store if this exact grader graded it before."""
    assert run.kind == "run", run.kind
    snapshot = grader.snapshot()
    parts = {"run": run.key, "grader": key_of(snapshot)}

    def build() -> tuple[dict[str, Any], dict[str, bytes]]:
        rows, artifacts = apply(run, grader)
        outcome = "fail" if any(r["outcome"] == "fail" for r in rows) else "pass"
        return {"run": run.key, "grader": snapshot, "checks": rows, "outcome": outcome,
                "summary": f"{grader.name} {outcome}"}, artifacts

    if run.path is None:  # an ephemeral run gets an ephemeral grade
        meta, _ = build()
        return Entry("grade", key_of(parts), None, {**meta, "parts": parts, "files": {}})
    return store.derive("grade", parts, build)


def apply(run: Entry, grader: Grader) -> tuple[list[dict[str, Any]], dict[str, bytes]]:
    """Run the checks in order; a required failure skips the rest (recorded, not dropped)."""
    rows: list[dict[str, Any]] = []
    artifacts: dict[str, bytes] = {}
    halted_by: str | None = None
    for check in grader.checks:
        if halted_by is not None:
            res = Result("skip", notes=f"skipped: required check {halted_by!r} failed")
        else:
            res = check.fn(run, grader.config)
            missing = [name for name in check.creates if name not in res.artifacts]
            if res.outcome != "skip" and missing:
                res = failed(f"promised {missing} but did not create them", details={"was": res.to_json()})
            if res.outcome == "fail" and check.required:
                halted_by = check.name
        artifacts.update({f"{check.name}.{name}": data for name, data in res.artifacts.items()})
        rows.append({"check": check.name, "required": check.required, **res.to_json()})
    return rows, artifacts


def first_failure(grade_entry: Entry) -> dict[str, Any] | None:
    return next((row for row in grade_entry.meta["checks"] if row["outcome"] == "fail"), None)


def verdict(grade_entry: Entry, *, blocking: bool, **fields: Any) -> dict[str, Any]:
    """A grade -> one verdict line of the run_checks contract (`fields`: op, case, dtype, chip, where?)."""
    rows = grade_entry.meta["checks"]
    bad = first_failure(grade_entry)
    metrics: dict[str, Any] = {}
    for row in rows:
        metrics.update(row["metrics"])
    out = {"kind": "verdict", **{k: v for k, v in fields.items() if k != "where"},
           "outcome": grade_entry.meta["outcome"], "score": 0.0 if bad else 1.0, "metrics": metrics,
           "notes": f"{bad['check']}: {bad['notes']}" if bad else "", "blocking": blocking,
           "run": grade_entry.meta["run"], "grade": grade_entry.key}
    if bad and fields.get("where"):
        out["where"] = fields["where"]
    return out
