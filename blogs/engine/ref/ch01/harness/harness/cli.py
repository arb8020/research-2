"""`run_checks ch1 [op]`: grade each op's candidate, print every non-pass, write JSONL records.

    run_checks ch1                         every op's default candidate
    run_checks ch1 layer_norm              one op
    run_checks ch1 layer_norm --candidate my_ln:layer_norm --path ~/work
    run_checks ch1 --planted               the planted bugs; exit 1 if any is NOT caught
    run_checks ch1 --warn layer_norm       that op's failures print as WARN and do not block
    run_checks ch1 --warn-all              every op-level check warns; model checks still block

Exit status: 1 if any blocking check failed (or, with --planted, any planted bug passed).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from harness.check import Policy, Record, check_candidate
from harness.registry import Op

STARTUP_TIMEOUT_S = 180.0  # the child imports torch (+ loads gpt2 for model candidates)
CALL_TIMEOUT_S = 60.0  # one call = two runs of the candidate on one case


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    from specs import ch1  # the only chapter so far

    suites = {"ch1": ch1}
    if args.chapter not in suites:
        raise SystemExit(f"unknown chapter {args.chapter!r}; have {sorted(suites)}")
    suite = suites[args.chapter]
    if args.op is not None and args.op not in suite.OPS:
        raise SystemExit(f"unknown op {args.op!r}; {args.chapter} has {sorted(suite.OPS)}")
    if args.candidate is not None and args.op is None:
        raise SystemExit("--candidate needs an op: run_checks ch1 <op> --candidate module:fn")
    unknown_warn = set(args.warn) - set(suite.OPS)
    if unknown_warn:
        raise SystemExit(f"--warn names unknown ops {sorted(unknown_warn)}")

    names = [args.op] if args.op is not None else list(suite.OPS)
    records_path = args.records or Path("records") / f"{args.chapter}-{_stamp()}.jsonl"
    records_path.parent.mkdir(parents=True, exist_ok=True)
    blocking_failures = 0
    missed_plants = []
    with records_path.open("w") as sink:
        for name in names:
            declared = suite.OPS[name]
            policy = Policy(_blocking(declared, args), STARTUP_TIMEOUT_S, args.timeout,
                            tuple(args.path))
            for qualname in _candidates(suite, name, args):
                started = time.perf_counter()
                records = check_candidate(declared, qualname, policy)
                seconds = time.perf_counter() - started
                for record in records:
                    sink.write(json.dumps(record.to_json()) + "\n")
                _print_records(records, args.verbose)
                failed = [r for r in records if r.outcome.verdict == "fail"]
                print(_summary(name, qualname, records, failed, policy, seconds, args.planted))
                blocking_failures += sum(r.outcome.blocking for r in failed)
                if args.planted and not failed:
                    missed_plants.append(qualname)
    print(f"records: {records_path}")
    if args.planted:
        print(f"planted bugs missed: {missed_plants or 'none'}")
        return 1 if missed_plants else 0
    return 1 if blocking_failures else 0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="run_checks", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("chapter")
    parser.add_argument("op", nargs="?")
    parser.add_argument("--candidate", help="'module:fn' to grade instead of the default")
    parser.add_argument("--planted", action="store_true", help="grade the planted bugs")
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


def _candidates(suite: object, name: str, args: argparse.Namespace) -> tuple[str, ...]:
    if args.candidate is not None:
        return (args.candidate,)
    if args.planted:
        return suite.PLANTED.get(name, ())  # type: ignore[attr-defined]
    return (suite.CANDIDATES[name],)  # type: ignore[attr-defined]


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
    """`layer_norm/candidates.layer_norm:layer_norm [rows=3 hidden=7 eps=1e-05 fp32]: WARN
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


def _summary(name: str, qualname: str, records: list[Record], failed: list[Record],
             policy: Policy, seconds: float, planted: bool) -> str:
    budget = [r for r in records if r.check == "budget"]
    passed_cases = sum(r.outcome.verdict == "pass" for r in budget)
    kinds = sorted({r.check for r in failed})
    if planted:
        verdict = f"CAUGHT by {', '.join(kinds)}" if failed else "MISSED (planted bug passed!)"
    elif not failed:
        verdict = "PASS"
    else:
        verdict = ("FAIL" if policy.blocking else "WARN") + f" ({', '.join(kinds)})"
    ratio = max((r.outcome.err / r.outcome.band for r in budget
                 if r.outcome.err is not None and r.outcome.band), default=0.0)
    return (f"{name:<17} {qualname:<58} {verdict:<28} cases {passed_cases}/{len(budget)} "
            f"worst err/budget {ratio:.2g}  {seconds:.1f}s")


def _stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


if __name__ == "__main__":
    sys.exit(main())
