"""Live smoke test of the Colab provider, on your own Colab account. Spends compute units (a T4 for
a few minutes; more with --tpu or --detached-minutes). Never run by pytest. After `colab usage`
has logged you in:

    cd box && uv run --extra dev --extra colab python -m box.tests.smoke_colab [--tpu] [--detached-minutes N]

Each step prints PASS/FAIL with its time; facts this provider assumed but could not check without a
live runtime are printed as FACT lines (contents root, TBE_RUNTIME_ADDR, token lifetime, GPU name).
Whatever happens, every runtime this script launched is terminated at the end, and the account's
runtimes are listed before and after so you can see nothing was left running.
"""

from __future__ import annotations

import argparse
import contextlib
import os
import subprocess
import sys
import time
from collections.abc import Callable, Generator

from box import sdk
from box.providers.colab import STOP_GRACE_S, Colab, ColabMachine

FAILED: list[str] = []
LAUNCHED: list[ColabMachine] = []


@contextlib.contextmanager
def step(name: str) -> Generator[None, None, None]:
    t = time.monotonic()
    try:
        yield
    except Exception as e:  # noqa: BLE001 (a smoke reports every step, then fails at the end)
        FAILED.append(name)
        print(f"FAIL {name} ({time.monotonic() - t:.1f} s): {e!r}", flush=True)
    else:
        print(f"PASS {name} ({time.monotonic() - t:.1f} s)", flush=True)


def check(cond: bool, what: str) -> None:
    if not cond:
        raise AssertionError(what)


def launch(colab: Colab, **kw: object) -> sdk.Session:
    s = sdk.launch(colab, **kw)
    assert isinstance(s.machine, ColabMachine)
    LAUNCHED.append(s.machine)
    return s


def run(s: sdk.Session, cmd: str) -> str:
    rc, out, err = s.machine.exec(cmd)
    check(rc == 0, f"`{cmd}` exited {rc}: {err.strip()}")
    return out


def facts(s: sdk.Session) -> None:
    m = s.machine
    assert isinstance(m, ColabMachine)
    print(f"FACT runtime {m.id}, accelerator {m._assignment.accelerator}")
    print(f"FACT proxy token lives {m._assignment.expires_at - time.time():.0f} s more (box refreshes it 300 s before)")
    print(f"FACT TBE_RUNTIME_ADDR={run(s, 'echo $TBE_RUNTIME_ADDR').strip()!r} (box unassigns through it)")
    print(f"FACT python {run(s, 'python3 -V').strip()}, kernel cwd {run(s, 'pwd').strip()}, user {run(s, 'whoami').strip()}")


def files(s: sdk.Session) -> None:
    """write/read go through /api/contents, assumed rooted at `/`: check against exec's view."""
    path = f"{s.machine.root}/smoke/blob.bin"
    data = os.urandom(1 << 20)
    s.machine.write(path, data)
    check(run(s, f"sha256sum {path}").split()[0] == __import__("hashlib").sha256(data).hexdigest(), "contents root is not /")
    check(s.machine.read(path) == data, "read != write")
    with contextlib.suppress(FileNotFoundError):
        s.machine.read(f"{s.machine.root}/smoke/nope")
        raise AssertionError("a missing file did not raise FileNotFoundError")
    check(len(run(s, "head -c 2000000 /dev/zero | tr '\\0' x")) == 2_000_000, "large exec output (spilled to a file)")


def stream(s: sdk.Session) -> None:
    """Machine.stream: the first chunk arrives while the command still runs (iopub push through
    Colab's proxy), exec is not held up meanwhile, and closing it kills the command."""
    go = f"{s.machine.root}/smoke/go"
    t = time.monotonic()
    with s.machine.stream(f"echo first; while [ ! -e {go} ]; do sleep 0.1; done; echo second >&2; exit 3", timeout_s=300) as st:
        chunks = iter(st)
        check(next(chunks) == ("stdout", b"first\n"), "first chunk")
        print(f"FACT first stream chunk {time.monotonic() - t:.1f} s after stream() (kernel start + cell)")
        run(s, f"touch {go}")
        check(list(chunks) == [("stderr", b"second\n")], "rest of the stream")
    check(st.rc == 3, f"stream rc {st.rc}")
    t = time.monotonic()
    with s.machine.stream("echo $$; exec sleep 999", timeout_s=300) as st:
        pid = int(next(iter(st))[1])
    print(f"FACT closing a stream took {time.monotonic() - t:.1f} s (interrupt + kernel shutdown; grace {STOP_GRACE_S} s)")
    check(s.machine.exec(f"kill -0 {pid}")[0] != 0, "a closed stream's command still runs")


def job(s: sdk.Session) -> None:
    j = s.run("echo hi; nvidia-smi -L || true; exit 3", on_exit="echo hook $BOX_EXIT_CODE > $BOX_JOB_DIR/hook", hook_budget_s=60)
    ending = j.wait()
    check(ending == sdk.Ending("exited", 3, hook_exit_code=0), f"ending {ending}")
    logs = "".join(c.text for c in j.logs() if c.stream == "stdout")
    check(logs.startswith("hi\n"), f"logs {logs!r}")
    followed = "".join(c.text for c in j.logs(follow=True) if c.stream == "stdout")  # a streamed tail (Machine.stream)
    check(followed == logs, f"followed {followed!r} != read {logs!r}")
    print(f"FACT job stdout: {logs.strip()!r}")


def refusals(colab: Colab) -> None:
    """What Colab cannot do is refused before anything is rented (no compute units spent)."""
    before = {a.endpoint for a in colab.backend.assignments()}
    for kw, words in (({"ports": (8888,)}, "terms forbid"), ({"ceiling_s": colab.max_runtime_s}, "is refused"), ({"image": "python:3.13-slim"}, "own image")):
        try:
            sdk.create(colab, gpu="T4", **kw)
        except ValueError as e:
            check(words in str(e), f"{kw}: {e}")
        else:
            raise AssertionError(f"{kw} was not refused")
    check({a.endpoint for a in colab.backend.assignments()} == before, "a refused launch rented a runtime")


def cli(*args: str) -> str:
    argv = [sys.executable, "-c", "from box.cli import main; main()", "--provider", "colab", *args]
    t = time.monotonic()
    done = subprocess.run(argv, capture_output=True, text=True, check=False, timeout=1800)
    print(f"  $ box --provider colab {' '.join(args)}  ({time.monotonic() - t:.1f} s, exit {done.returncode})")
    print("    " + (done.stdout + done.stderr).strip().replace("\n", "\n    "))
    check(done.returncode == 0, f"box {' '.join(args)} exited {done.returncode}")
    return done.stdout


def detached(colab: Colab, minutes: float) -> None:
    """Does a detached session (as `box run --detach`: idle ends it once its job is done) keep its
    runtime while nobody execs (only the supervisor's kernel is busy)? The job sleeps `minutes`; we
    only list (HTTP, no kernel) until it should be done."""
    lease_s = int(minutes * 60) + 1800
    s = launch(colab, lease_s=lease_s, ceiling_s=lease_s, idle_timeout_s=120, gpu="T4")
    s.run(f"sleep {int(minutes * 60)}; echo slept", max_duration_s=lease_s)
    left = time.monotonic()
    while not s.machine.gone():
        check(time.monotonic() - left < minutes * 60 + 600, "the detached session did not end itself 10 min after its job")
        time.sleep(60)
    lived = time.monotonic() - left
    check(lived >= minutes * 60, f"the runtime went away after {lived / 60:.1f} min, before the {minutes} min job could finish")
    print(f"FACT a detached session's runtime lived {lived / 60:.1f} min with no client activity, then unassigned itself")


def tpu(colab: Colab) -> None:
    s = launch(colab, ceiling_s=1200, gpu="TPU-v5e-1")
    try:
        out = run(s, "python3 -c 'import jax; print(jax.devices())' 2>&1 || python3 -c 'import torch_xla.core.xla_model as xm; print(xm.xla_device())'")
        print(f"FACT TPU devices: {out.strip()}")
    finally:
        s.close()  # a Receipt: the provider said the runtime is gone


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--tpu", action="store_true", help="also launch a TPU v5e-1")
    p.add_argument("--detached-minutes", type=float, default=0, help="also test a detached session's liveness (T4, this long)")
    a = p.parse_args()
    colab = Colab.from_env()
    before = colab.backend.balance()
    runtimes_before = {x.endpoint for x in colab.backend.assignments()}
    print(f"account: {before.compute_units:.2f} compute units, {len(runtimes_before)} runtime(s) assigned: {sorted(runtimes_before)}")
    started = time.monotonic()
    try:
        with step("refused before renting: ports, a ceiling past Colab's max runtime, an image"):
            refusals(colab)
        session(colab)
        with step("box run --provider colab -- echo hi (CLI end to end)"):
            check("hi" in cli("run", "--gpu", "T4", "--ceiling", "20m", "--", "echo", "hi"), "no `hi`")
        with step("box who --provider colab: nothing of ours running"):
            check(cli("who").startswith("0 running"), "box who still lists a session")
        if a.tpu:
            with step("TPU v5e-1: launch, devices, close"):
                tpu(colab)
        if a.detached_minutes:
            with step(f"detached session lives {a.detached_minutes} min unwatched, then ends itself"):
                detached(colab, a.detached_minutes)
    finally:
        cleanup(colab)
    after = colab.backend.balance()
    left = {x.endpoint for x in colab.backend.assignments()} - runtimes_before
    colab.close()  # its kernel websockets: non-daemon threads
    print(f"\n{time.monotonic() - started:.0f} s; compute units {before.compute_units:.2f} -> {after.compute_units:.2f} "
          f"(used {before.compute_units - after.compute_units:.2f}; the balance may lag)")  # fmt: skip
    print(f"runtimes left that this run created: {sorted(left) or 'none'}")
    if FAILED or left:
        sys.exit(f"FAILED: {FAILED}{' + runtimes left running' if left else ''}")
    print("ALL PASS")


def session(colab: Colab) -> None:
    s: sdk.Session | None = None
    with step("launch T4 (assign + kernels + supervisor up)"):
        s = launch(colab, ceiling_s=1200, gpu="T4")
    if s is None:
        return
    steps: list[tuple[str, Callable[[], None]]] = [
        ("facts", lambda: facts(s)),
        ("nvidia-smi", lambda: print("FACT " + run(s, "nvidia-smi --query-gpu=name,memory.total --format=csv,noheader").strip())),
        ("write + read 1 MiB, contents root, missing file, 2 MB exec output", lambda: files(s)),
        ("stream: pushed output, exec meanwhile, close kills", lambda: stream(s)),
        ("job: exit code, hook, logs, followed logs", lambda: job(s)),
        ("box who lists it (list reads its labels)", lambda: check(s.machine.id in {m.id for m in colab.list({sdk.LABEL_SESSION: s.id})}, "not listed")),
    ]
    for name, fn in steps:
        with step(name):
            fn()
    with step("close: supervisor ends, then the account says the runtime is gone (a Receipt)"):
        r = s.close()
        check(r.ended == sdk.Ended("stopped") and r.supervisor_confirmed, f"receipt {r}")
        check(s.machine.gone(), "gone() after close")
        print(f"FACT receipt: {r}")


def cleanup(colab: Colab) -> None:
    for m in LAUNCHED:
        with contextlib.suppress(Exception):
            m.terminate()
    for m in LAUNCHED:
        if m.id in {a.endpoint for a in colab.backend.assignments()}:
            print(f"WARNING: {m.id} still assigned after terminate; `colab sessions`, then stop it in the Colab UI")


if __name__ == "__main__":
    main()
