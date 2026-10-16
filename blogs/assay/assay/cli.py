"""run_checks: a chapter's checks on the tree in the cwd. JSON lines on stdout; exit 0 pass, 1 fail or blocked, 2 infra.

    run_checks ch01 --op attention                   one op (repeatable); default: every op of the chapter
    run_checks ch01 --op forward --dtype fp32        dtypes (repeatable); default: every dtype the op declares
    run_checks ch01 --warn layer_norm / --warn-all   that op's (every op's) failures don't block; model level always does
    run_checks ch01 --selftest [--op X]              planted bugs + cheats must FAIL for their stated reason, correct
                                                     candidates must PASS
    run_checks ch01 --grade-only                     grade stored runs only (exit 2 if a run is missing): regrading
    run_checks ch01 --spawn                          no warm process: run in this process, spawn fresh children
    run_checks ch00 ring                             (ch00's cell as a positional: how the page invokes it today)
    run_checks report [<run id>]                     a stored session as a table (default: the latest), from the store

stdout, one JSON object per line:
    {"kind":"log","text":...}
    {"kind":"verdict","op","case","dtype","chip","outcome":"pass|fail|skip|blocked","score","metrics","notes",
     "blocking","where"?:{"file","line","region"?},"run","grade"}
    {"kind":"selftest",...}                          with --selftest
    {"kind":"summary","outcome":"pass|fail|blocked|error","counts":{...},"run":"<session id>","isolation":...}

ch01 goes through the warm process (core.py, a fork server) unless --spawn / ASSAY_SPAWN=1: this process stays stdlib-only and
copies the trusted worker's lines through, so a check does not pay torch's import.
"""

from __future__ import annotations

import argparse
import contextlib
import importlib
import json
import os
import signal
import sys
import threading
import time
import uuid
from collections import Counter
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

from assay import core

CHAPTERS = {"ch00": "assay.ch00", "ch01": "assay.ch01.suite"}
NEEDS_TORCH = {"ch01"}
EXIT = {"pass": 0, "fail": 1, "blocked": 1, "error": 2}


def parse(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="run_checks", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("chapter", choices=sorted(CHAPTERS))
    p.add_argument("cell", nargs="?", help="ch00: a cell name (same as --op)")
    p.add_argument("--op", action="append", default=[], metavar="NAME")
    p.add_argument("--dtype", action="append", default=[], metavar="D", choices=("fp32", "fp16", "bf16"))
    p.add_argument("--selftest", action="store_true")
    p.add_argument("--warn", action="append", default=[], metavar="OP")
    p.add_argument("--warn-all", action="store_true")
    p.add_argument("--grade-only", action="store_true")
    p.add_argument("--timeout", type=float, default=60.0, help="seconds per candidate call")
    p.add_argument("--spawn", action="store_true", help="no warm process (debugging)")
    args = p.parse_args(argv)
    if args.cell:
        args.op.append(args.cell)
    return args


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["report"]:
        print(report(core.Store.from_env(), argv[1] if len(argv) > 1 else None))
        return 0
    args = parse(argv)
    if args.chapter in NEEDS_TORCH and not args.spawn and os.environ.get("ASSAY_SPAWN") != "1":
        return client(argv)
    return worker(argv, out_fd=sys.stdout.fileno(), client_pid=None)


def client(argv: list[str]) -> int:
    """Hand the check to a fork of the warm process; copy its JSON lines to stdout; exit code from its summary."""
    def log(text: str) -> None:
        print(json.dumps({"kind": "log", "text": text}), flush=True)

    try:
        path = core.ensure_warm(log)
        read_end, write_end = os.pipe()
        try:
            env = {**os.environ, "ASSAY_WARM": str(path)}
            core.warm_request(path, {"kind": "trusted", "argv": argv, "cwd": os.getcwd(), "env": env,
                                  "pythonpath": str(Path(__file__).resolve().parents[1]),
                                  "client_pid": os.getpid()}, [write_end, sys.stderr.fileno()])
        finally:
            os.close(write_end)
    except (OSError, RuntimeError) as exc:
        log(f"warm process unavailable ({exc}); running without it")
        return worker(argv, out_fd=sys.stdout.fileno(), client_pid=None)
    code = EXIT["error"]  # no summary line = the worker died: infrastructure, not evidence
    with os.fdopen(read_end, "r") as stream:
        for line in stream:
            sys.stdout.write(line)
            sys.stdout.flush()
            with contextlib.suppress(ValueError):
                record = json.loads(line)
                if record.get("kind") == "summary":
                    code = EXIT.get(record.get("outcome"), 2)
    if code == EXIT["error"]:
        log("the check worker ended without a summary (it crashed: see stderr, and the warm process log in "
            f"{path.parent})")
    return code


class Emitter:
    def __init__(self, fd: int) -> None:
        self.fd = fd
        self.t0 = time.perf_counter()

    def __call__(self, record: dict[str, Any]) -> None:
        data = (json.dumps(record) + "\n").encode()
        try:
            while data:
                data = data[os.write(self.fd, data):]
        except BrokenPipeError:  # whoever reads us is gone: stop, and take our children with us
            _abandon()

    def log(self, text: str) -> None:
        self({"kind": "log", "text": f"[{time.perf_counter() - self.t0:6.2f}s] {text}"})


def worker(argv: list[str], *, out_fd: int, client_pid: int | None) -> int:
    """Run the checks here (in the trusted fork, or in-process with --spawn); returns the exit code."""
    args = parse(argv)
    emit = Emitter(out_fd)
    if client_pid is not None:
        threading.Thread(target=_watchdog, args=(client_pid,), daemon=True).start()
    else:  # in-process: a Stop (SIGTERM to our process group) must also end children that lead their own sessions
        signal.signal(signal.SIGTERM, lambda signum, frame: _abandon())
    store = core.Store.from_env()
    iso = core.isolation()
    warm = Path(os.environ["ASSAY_WARM"]) if os.environ.get("ASSAY_WARM") and client_pid else None
    emit.log(f"{args.chapter}: isolation {iso.mode} (child user {iso.user}); store {store.root}; "
             f"{'forked from the warm process' if warm else 'spawned'}")
    chapter = importlib.import_module(CHAPTERS[args.chapter])
    records: list[dict[str, Any]] = []
    try:
        for record in chapter.checks(args, store, iso, emit.log, warm):
            records.append(record)
            emit(record)
    except Exception as exc:  # noqa: BLE001 -- infrastructure: never graded, exit 2 (smevals' failed Run)
        import traceback

        emit.log(f"infrastructure error: {type(exc).__name__}: {exc}\n{traceback.format_exc()[-3000:]}")
        emit({"kind": "summary", "outcome": "error", "counts": {}, "run": None, "isolation": iso.mode})
        return EXIT["error"]
    outcome, counts = summarize(records, args.selftest)
    session = store.put("session", uuid.uuid4().hex, {
        "argv": argv, "cwd": os.getcwd(), "isolation": iso.to_json(), "outcome": outcome, "counts": counts,
        "records": [{k: r.get(k) for k in ("kind", "op", "case", "dtype", "outcome", "run", "grade", "candidate",
                                           "ok")} for r in records],
        "summary": f"{' '.join(argv)}: {outcome}"}, {})
    emit.log(f"done in {time.perf_counter() - emit.t0:.2f}s")
    emit({"kind": "summary", "outcome": outcome, "counts": counts, "run": session.key, "isolation": iso.mode})
    return EXIT[outcome]


def summarize(records: list[dict[str, Any]], selftest: bool) -> tuple[str, dict[str, int]]:
    if selftest:
        tests = [r for r in records if r["kind"] == "selftest"]
        counts = {"ok": sum(r["ok"] and not r["hole"] for r in tests), "missed": sum(not r["ok"] for r in tests),
                  "holes": sum(r["hole"] for r in tests)}
        return ("pass" if tests and not counts["missed"] else "fail"), counts
    verdicts = [r for r in records if r["kind"] == "verdict"]
    counts = dict(Counter(v["outcome"] for v in verdicts))
    counts["warn"] = sum(v["outcome"] == "fail" and not v.get("blocking", True) for v in verdicts)
    if any(v["outcome"] == "blocked" for v in verdicts):
        return "blocked", counts
    if any(v["outcome"] == "fail" and v.get("blocking", True) for v in verdicts):
        return "fail", counts
    return ("pass" if verdicts else "error"), counts


def report(store: core.Store, session: str | None) -> str:
    """One row per verdict of a stored session: what ran, what it was graded by, and why it failed."""
    if session is None:
        index = (store.root / "index.jsonl").read_text().splitlines()
        sessions = [json.loads(line) for line in index if json.loads(line)["kind"] == "session"]
        if not sessions:
            return "no sessions in the store"
        session = sessions[-1]["key"]
    entry = store.get("session", session)
    if entry is None:
        return f"no session {session} in {store.root}"
    meta = entry.meta
    out = [f"run {session}: `run_checks {' '.join(meta['argv'])}` -> {meta['outcome']} {meta['counts']} "
           f"(isolation {meta['isolation']['mode']})", "",
           "| op | case | dtype | outcome | grader | first failure | metrics |", "|---|---|---|---|---|---|---|"]
    for row in meta["records"]:
        graded = store.get("grade", row["grade"]) if row.get("grade") else None
        if graded is None:
            out.append(f"| {row.get('op')} | {row.get('case') or row.get('candidate')} | {row.get('dtype')} | "
                       f"{row.get('outcome') or ('ok' if row.get('ok') else 'MISSED')} | | | |")
            continue
        bad = core.first_failure(graded)
        metrics = {k: v for r in graded.meta["checks"] for k, v in r["metrics"].items()
                   if k in ("err", "budget", "ratio", "kl_max")}
        shown = " ".join(f"{k}={v:.3g}" if isinstance(v, float) else f"{k}={v}" for k, v in metrics.items())
        out.append(f"| {row['op']} | {row['case']} | {row['dtype']} | {graded.meta['outcome']} | "
                   f"{graded.meta['grader']['name']} | {(bad['check'] + ': ' + bad['notes'])[:80] if bad else ''} | "
                   f"{shown} |")
    return "\n".join(out)


def _watchdog(client_pid: int) -> None:
    """The client (run_checks, killed by a Stop or a timeout) is gone: kill our children and exit."""
    while core.pid_alive(client_pid):
        time.sleep(0.25)
    _abandon()


def _abandon() -> None:
    for pid in list(core.LIVE):
        core.kill_group(pid)
    os._exit(EXIT["error"])


Checks = Callable[..., Iterator[dict[str, Any]]]

if __name__ == "__main__":
    sys.exit(main())
