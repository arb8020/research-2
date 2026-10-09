from __future__ import annotations

import argparse
import contextlib
import json
import re
import subprocess
import sys
import time
from collections.abc import Generator
from pathlib import Path

from box import sdk
from box.providers.modal import Modal, ModalToken, ModalVolumeStore

PROFILE = "arb8020"
NAME = "overnight-demo"
LABELS = {"box.purpose": "lease-e2e"}
RECORD_VOLUME = "box-sessions"
LINES, EVERY_S = 80, 3
JOB = f'for i in $(seq 1 {LINES}); do echo "overnight line $i of {LINES} at $(date +%H:%M:%S)"; sleep {EVERY_S}; done'
FOLLOW_B_S = 20.0
LINE = re.compile(r"^overnight line (\d+) of \d+ at ", re.M)
T0 = time.time()


def header(text: str) -> None:
    print(f"\n==== {text}  [{time.strftime('%H:%M:%S')}]", flush=True)


def say(text: str) -> None:
    print(f"  {text}", flush=True)


def check(ok: bool, what: str) -> None:
    say(f"{'PASS' if ok else 'FAIL'}: {what}")
    if not ok:
        sys.exit(1)


@contextlib.contextmanager
def modal() -> Generator[tuple[Modal, ModalVolumeStore]]:
    with Modal(token=ModalToken.from_profile(PROFILE), region="us") as provider:
        yield provider, ModalVolumeStore(RECORD_VOLUME, provider=provider)


def left(lease: sdk.Lease) -> str:
    return f"{(min(lease.until, lease.ceiling) - time.time()) / 60:.1f} min"


def numbers(text: str) -> list[int]:
    return [int(n) for n in LINE.findall(text)]


def phase_a(state: Path) -> None:
    header("A (the VPS): create a detached session, start the job, exit")
    with modal() as (provider, store):
        t = time.monotonic()
        s = sdk.launch(provider, name=NAME, lease_s=15 * 60, ceiling_s=60 * 60, idle_timeout_s=5 * 60, labels=LABELS, record=store)
        say(f"session {s.id} ({s.name}) on {s.machine.id}: up in {time.monotonic() - t:.0f} s; record {store.uri}")
        status = s.status()
        check(isinstance(status, sdk.Running), f"status after launch: {status}")
        job = s.run(JOB, max_duration_s=10 * 60)
        say(f"job {job.id}: {LINES} lines, one every {EVERY_S} s")
        state.write_text(json.dumps({"session_id": s.id, "job_id": job.id}))
    say("A exits now; the provider's client is closed, the session is not")


def phase_b(state: Path) -> None:
    header("B (next morning): attach by name, status, follow ~20 s, stop, extend")
    st = json.loads(state.read_text())
    with modal() as (provider, store):
        s = sdk.attach(provider, name=NAME, record=store)
        check(s.id == st["session_id"], f"attach(name={NAME!r}) found session {s.id} (A made {st['session_id']})")
        status = s.status()
        check(isinstance(status, sdk.Running), f"status: {type(status).__name__}, lease until {time.strftime('%H:%M:%S', time.localtime(status.lease.until))}, {left(status.lease)} left")
        job = next(j for j in s.jobs() if j.id == st["job_id"])
        say(f"job {job.id}: {type(job.status()).__name__}")
        text, cursor, t = "", (0, 0), time.monotonic()
        logs = job.logs(follow=True)
        for chunk in logs:
            if chunk.stream == "stdout":
                for line in chunk.text.splitlines():
                    say(f"| {line}")
            text, cursor = text + (chunk.text if chunk.stream == "stdout" else ""), chunk.end
            if time.monotonic() - t > FOLLOW_B_S:
                break
        logs.close()
        got = numbers(text)
        check(got == list(range(1, len(got) + 1)) and len(got) > 0, f"followed {time.monotonic() - t:.0f} s: lines 1..{len(got)}, stopped at cursor {cursor}")
        before = status.lease
        lease = s.extend(time.time() + 20 * 60)
        check(lease.until > before.until and lease.ceiling == before.ceiling, f"extend(now + 20 min): until {before.until:.0f} -> {lease.until:.0f}, {left(lease)} left, ceiling unchanged")
        state.write_text(json.dumps({**st, "cursor": cursor, "b_text": text}))
    say("B exits")


def phase_c(state: Path) -> None:  # noqa: PLR0915
    header("C: attach again, follow from B's cursor to the end, close, read the record")
    st = json.loads(state.read_text())
    cursor = tuple(st["cursor"])
    with modal() as (provider, store):
        s = sdk.attach(provider, name=NAME, record=store)
        check(s.id == st["session_id"], f"attach(name={NAME!r}) -> {s.id}")
        job = next(j for j in s.jobs() if j.id == st["job_id"])
        say(f"following {job.id} from cursor {cursor}")
        text, t = "", time.monotonic()
        for chunk in job.logs(after=cursor, follow=True):
            if chunk.stream == "stdout":
                text += chunk.text
                for line in chunk.text.splitlines():
                    say(f"| {line}")
        ending = job.wait()
        check(ending.reason == "exited" and ending.exit_code == 0, f"job done after {time.monotonic() - t:.0f} s more: {ending}")
        joined = numbers(st["b_text"] + text)
        dupes = sorted({n for n in joined if joined.count(n) > 1})
        missing = sorted(set(range(1, LINES + 1)) - set(joined))
        check(joined == list(range(1, LINES + 1)), f"B ({len(numbers(st['b_text']))} lines) + C ({len(numbers(text))} lines) = 1..{LINES} in order; duplicated {dupes}, missing {missing}")

        header("C: close() -> Receipt")
        t = time.monotonic()
        receipt = s.close()
        say(f"{receipt}")
        check(receipt.session_id == s.id and receipt.supervisor_confirmed and receipt.ended.reason == "stopped",
              f"receipt in {time.monotonic() - t:.1f} s: ended {receipt.ended.reason}, supervisor_confirmed, machine gone at {time.strftime('%H:%M:%S', time.localtime(receipt.machine_gone_at))}")  # fmt: skip
        live = provider.list({sdk.LABEL_SESSION: s.id})
        check(not live, f"provider.list for the session: {len(live)} live machines")

        header("C: read_record() after the machine is gone (no machine, just the store)")
        r = sdk.read_record(store, s.id)
        say(f"machine {r.machine_id}, labels box.purpose={r.labels.get('box.purpose')} box.name={r.labels.get(sdk.LABEL_NAME)}")
        check(r.ended == sdk.Ended("stopped"), f"status: {r.ended}")
        check(r.jobs() == [st["job_id"]] and isinstance(r.job_status(st["job_id"]), sdk.Done), f"job {st['job_id']}: {r.job_status(st['job_id'])}")
        recorded = "".join(c.text for c in r.logs(st["job_id"]) if c.stream == "stdout")
        for line in recorded.splitlines()[-3:]:
            say(f"| {line}")
        check(recorded == st["b_text"] + text, f"recorded stdout ({len(recorded)} bytes) == what B and C followed, byte for byte")
        audit = r.lease_audit()
        for e in audit:
            say(f"lease {e.op:<7} until {time.strftime('%H:%M:%S', time.localtime(e.until))}  at {time.strftime('%H:%M:%S', time.localtime(e.at))}  from {e.host} pid {e.pid} (x{e.n})")
        ops = [e.op for e in audit]
        check(ops[:2] == ["create", "extend"] and len({e.pid for e in audit[:2]}) == 2, f"lease audit: {ops} (create and extend from different processes)")
        check(r.receipt == receipt, f"record's receipt == close()'s: {r.receipt}")
        again = sdk.attach(provider, session_id=s.id, record=store)
        check(again.status() == sdk.Ended("stopped"), f"attach(session_id, record=store) after it is gone: {again.status()} (machine {type(again.machine).__name__})")


def driver(out: Path, gap_s: float) -> int:
    out.mkdir(parents=True, exist_ok=True)
    state, log = out / "state.json", out / "overnight.log"
    timings = []
    with log.open("w") as f:
        for phase, wait_s in (("a", gap_s), ("b", 5.0), ("c", 0.0)):
            t = time.monotonic()
            proc = subprocess.Popen([sys.executable, __file__, phase, "--state", str(state)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            for line in proc.stdout:  # MUST KILL: proc.stdout is Optional (was type: ignore[union-attr]); assert it before iterating
                sys.stdout.write(line)
                sys.stdout.flush()
                f.write(line)
                f.flush()
            rc = proc.wait()
            timings.append(f"{phase.upper()} pid {proc.pid}: exit {rc} in {time.monotonic() - t:.0f} s")
            if rc != 0:
                break
            if wait_s:
                msg = f"\n.... {phase.upper()} has exited; waiting {wait_s:.0f} s before the next process"
                print(msg, flush=True)
                f.write(msg + "\n")
                time.sleep(wait_s)
        summary = "\n==== summary\n" + "\n".join(f"  {t}" for t in timings) + f"\n  total {time.time() - T0:.0f} s\n  log {log}\n"
        print(summary, flush=True)
        f.write(summary)
    return rc


def main() -> None:
    ap = argparse.ArgumentParser(description="Three processes share one detached Modal session: create (a), attach and extend (b), follow, close and read the record (c).", formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("phase", nargs="?", choices=["a", "b", "c"], help="one phase (default: run all three as separate processes)")
    ap.add_argument("--state", type=Path, help="(a phase) the file the phases share")
    ap.add_argument("--out", type=Path, default=Path.home() / ".cache" / "box" / "overnight" / time.strftime("%Y%m%d-%H%M%S"))
    ap.add_argument("--gap-s", type=float, default=45.0, help="between A exiting and B starting")
    a = ap.parse_args()
    if a.phase is None:
        sys.exit(driver(a.out, a.gap_s))
    assert a.state is not None, "a phase needs --state"
    {"a": phase_a, "b": phase_b, "c": phase_c}[a.phase](a.state)


if __name__ == "__main__":
    main()
