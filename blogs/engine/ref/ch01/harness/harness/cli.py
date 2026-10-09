"""`run_checks ch1 [op]`: grade each op's candidate, print every non-pass, write JSONL records.

    run_checks ch1                         every op's default candidate
    run_checks ch1 layer_norm              one op
    run_checks ch1 layer_norm --candidate my_ln:layer_norm --path ~/work
    run_checks ch1 --warn layer_norm       that op's failures print as WARN and do not block
    run_checks ch1 --warn-all              every op-level check warns; model checks still block
    run_checks ch1 --selftest [op]         planted bugs + adversarial candidates must all FAIL,
                                           each for its stated reason

Exit status: 1 if any blocking check failed; with --selftest, 1 if any self-test was not
caught (or was caught for a different reason than it states).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType

from harness.check import MustFail, Policy, Record, check_candidate
from harness.registry import Op

STARTUP_TIMEOUT_S = 180.0  # the child imports torch (+ loads gpt2 for model candidates)
CALL_TIMEOUT_S = 60.0  # one call = two runs of the candidate on one case


@dataclass(frozen=True)
class Job:
    """One (op, candidate) to grade; `must_fail` is set for a self-test."""

    op: str
    candidate: str
    call_timeout: float
    must_fail: MustFail | None


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    suite = _suite(args)
    jobs = _jobs(suite, args)
    records_path = args.records or Path("records") / f"{args.chapter}-{_stamp()}.jsonl"
    records_path.parent.mkdir(parents=True, exist_ok=True)
    blocking_failures = 0
    selftest_misses = []
    with records_path.open("w") as sink:
        for job in jobs:
            declared = suite.OPS[job.op]
            policy = Policy(_blocking(declared, args), STARTUP_TIMEOUT_S, job.call_timeout,
                            tuple(args.path))
            started = time.perf_counter()
            records = check_candidate(declared, job.candidate, policy)
            seconds = time.perf_counter() - started
            for record in records:
                sink.write(json.dumps(record.to_json()) + "\n")
            _print_records(records, args.verbose)
            print(_summary(job, records, policy, seconds))
            failed = [r for r in records if r.outcome.verdict == "fail"]
            blocking_failures += sum(r.outcome.blocking for r in failed)
            if job.must_fail is not None and not job.must_fail.caught(records):
                selftest_misses.append(job.candidate)
    print(f"records: {records_path}")
    if args.selftest:
        print(f"self-tests not caught as stated: {selftest_misses or 'none'}")
        return 1 if selftest_misses else 0
    return 1 if blocking_failures else 0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="run_checks", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("chapter")
    parser.add_argument("op", nargs="?")
    parser.add_argument("--candidate", help="'module:fn' to grade instead of the default")
    parser.add_argument("--selftest", action="store_true",
                        help="grade the planted bugs and adversarial candidates")
    parser.add_argument("--warn", action="append", default=[], metavar="OP",
                        help="this op's failures warn instead of blocking (repeatable)")
    parser.add_argument("--warn-all", action="store_true",
                        help="every op-level check warns; model-level checks still block")
    parser.add_argument("--path", action="append", default=[], metavar="DIR",
                        help="extra import root for candidate modules (repeatable)")
    parser.add_argument("--records", type=Path, help="JSONL output (default records/<ch>-<ts>)")
    parser.add_argument("--timeout", type=float, default=CALL_TIMEOUT_S,
                        help="seconds per candidate call")
    parser.add_argument("-v", "--verbose", action="store_true", help="print passing cases too")
    return parser.parse_args(argv)


def _suite(args: argparse.Namespace) -> ModuleType:
    """The chapter's suite module, after checking every name the command line gave."""
    from specs import ch1  # the only chapter so far

    suites = {"ch1": ch1}
    if args.chapter not in suites:
        raise SystemExit(f"unknown chapter {args.chapter!r}; have {sorted(suites)}")
    suite = suites[args.chapter]
    if args.op is not None and args.op not in suite.OPS:
        raise SystemExit(f"unknown op {args.op!r}; {args.chapter} has {sorted(suite.OPS)}")
    if args.candidate is not None and args.op is None:
        raise SystemExit("--candidate needs an op: run_checks ch1 <op> --candidate module:fn")
    if args.candidate is not None and args.selftest:
        raise SystemExit("--candidate and --selftest are exclusive")
    unknown_warn = set(args.warn) - set(suite.OPS)
    if unknown_warn:
        raise SystemExit(f"--warn names unknown ops {sorted(unknown_warn)}")
    return suite


def _jobs(suite: ModuleType, args: argparse.Namespace) -> list[Job]:
    names = [args.op] if args.op is not None else list(suite.OPS)
    if args.selftest:
        return [Job(test.op, test.candidate, test.call_timeout, test) for test in suite.SELFTEST
                if test.op in names]
    if args.candidate is not None:
        return [Job(args.op, args.candidate, args.timeout, None)]
    return [Job(name, suite.CANDIDATES[name], args.timeout, None) for name in names]


def _blocking(declared: Op, args: argparse.Namespace) -> bool:
    """Model checks always block; otherwise --warn/--warn-all turn blocking off, else the op's
    own default."""
    if declared.model:
        return True
    if args.warn_all or declared.name in args.warn:
        return False
    return declared.blocking


def _print_records(records: list[Record], verbose: bool) -> None:
    for record in records:
        if record.outcome.verdict == "pass" and not verbose:
            continue
        print("  " + _line(record))


def _line(record: Record) -> str:
    """`layer_norm/candidates.x:layer_norm [budget: rows=3 hidden=7 eps=1e-05 fp32]: WARN
    (blocking off) err 3e-02 > budget 1e-04`."""
    outcome = record.outcome
    if outcome.verdict == "pass":
        label = "PASS"
    else:
        label = "FAIL" if outcome.blocking else "WARN (blocking off)"
    numbers = (f" err {outcome.err:.2e} <= budget {outcome.band:.2e}"
               if outcome.verdict == "pass" and outcome.err is not None else "")
    reason = f" {outcome.reason}" if outcome.reason else ""
    return f"{record.op}/{record.candidate} [{record.check}: {record.case}]: {label}{numbers}{reason}"


def _summary(job: Job, records: list[Record], policy: Policy, seconds: float) -> str:
    budget = [r for r in records if r.check == "budget"]
    passed_cases = sum(r.outcome.verdict == "pass" for r in budget)
    failed = [r for r in records if r.outcome.verdict == "fail"]
    kinds = ", ".join(sorted({r.check for r in failed}))
    if job.must_fail is not None:
        verdict = (f"CAUGHT ({job.must_fail.caught_by!r})" if job.must_fail.caught(records)
                   else f"NOT CAUGHT as {job.must_fail.caught_by!r}")
    elif not failed:
        verdict = "PASS"
    else:
        verdict = ("FAIL" if policy.blocking else "WARN") + f" ({kinds})"
    graded = [r.outcome for r in budget if r.outcome.err is not None and r.outcome.band]
    # NaN err sorts as the worst: it is a failure no finite error beats
    worst_case = max(graded, key=lambda o: o.err / o.band if o.err == o.err else float("inf"),
                     default=None)
    worst = ("worst err -" if worst_case is None else
             f"worst err {worst_case.err:.2g} vs budget {worst_case.band:.2g}")
    return (f"{job.op:<17} {job.candidate:<58} {verdict:<44} "
            f"cases {passed_cases}/{len(budget)}  {worst}  {seconds:.1f}s")


def _stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


if __name__ == "__main__":
    sys.exit(main())
