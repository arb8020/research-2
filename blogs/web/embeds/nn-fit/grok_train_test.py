"""Checks for grok_train.py: the model, continuing a run across calls, ticks, interrupt, bad configs.

    cd web && npm run test:nn-fit-grok        # CPU, ~10 s

Throws (exit 1) on the first failure; prints one line per check. Grokking itself (p = 113, test accuracy past
95% after ~5k steps) takes ~2 min on a laptop CPU: remote_e2e.py --grok checks it on a real GPU.
"""

import importlib.util
import json
import math
import signal
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).parent
PROGRAM = HERE / "grok_train.py"

spec = importlib.util.spec_from_file_location("grok_train", PROGRAM)
assert spec is not None and spec.loader is not None
gt = importlib.util.module_from_spec(spec)
sys.modules["grok_train"] = gt  # dataclasses look their module up by name
spec.loader.exec_module(gt)

PARAMS_113 = 226_688  # grok.ts: grokParams(113); the page checks the "start" line against it too
SMALL = {"run": "r", "p": 23, "train_fraction": 0.5, "split_seed": 1, "init_seed": 1, "step": 0, "seconds": 0,
         "max_steps": 300, "max_seconds": 60, "tick_seconds": 60}  # fmt: skip


def check(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(f"FAIL {message}")
    print(f"ok   {message}")


def frozen_clock() -> float:
    return 0.0  # no time passes: only the log-spaced ticks come


def train(config: dict, runs: dict) -> list[dict]:
    lines: list[dict] = []
    parsed = gt.parse_config(config)
    gt.train(parsed, gt.find_run(runs, parsed, gt.torch.device("cpu")), lines.append, frozen_clock)
    return lines


def model() -> None:
    run = gt.new_run(gt.parse_config({**SMALL, "p": 113, "train_fraction": 0.3}), gt.torch.device("cpu"))
    start = gt.describe(gt.torch.device("cpu"), run)
    check(start["params"] == PARAMS_113, f"p 113: {start['params']} parameters, as grok.ts counts")
    check((start["train"], start["test"]) == (3831, 12769 - 3831), "p 113 at 30%: 3831 training pairs (round(0.3 p^2)), the rest test")
    pairs = run.data.tokens
    check(bool(((pairs[:, 0] + pairs[:, 1]) % 113 == run.data.labels).all()), "labels are (a + b) mod p")
    check(len(set(run.data.train.tolist()) | set(run.data.test.tolist())) == 113 * 113, "train and test split every pair")


def learns() -> None:
    lines = train(SMALL, {})
    ticks = [line for line in lines if line["kind"] == "tick"]
    print(f"  p 23: train {ticks[0]['accuracy']:.2f} -> {ticks[-1]['accuracy']:.2f}, test {ticks[-1]['test_accuracy']:.2f} at step {ticks[-1]['step']}")
    check(ticks[-1]["accuracy"] == 1.0, "p 23: fits every training pair within 300 steps")
    check(lines[-1] == {"kind": "end", "reason": "steps", "step": 300, "seconds": 0.0}, "the step budget ends it, at step 300")


def continues() -> None:
    """Two calls (0 -> 100 -> 200) on one runs dict are one run 0 -> 200: same weights, same metrics."""
    whole = train({**SMALL, "max_steps": 200}, {})
    runs: dict = {}
    first = train({**SMALL, "max_steps": 100}, runs)
    second = train({**SMALL, "step": 100, "max_steps": 200}, runs)
    check(first[-1]["step"] == 100 and second[0]["step"] == 100, "the second call picks up at step 100")
    at_200 = [t for t in whole if t["kind"] == "tick" and t["step"] == 200]
    check(second[-2] == at_200[-1], f"continued run equals the uninterrupted one at step 200 (loss {second[-2]['loss']:.4g})")


def refuses() -> None:
    runs: dict = {}
    train({**SMALL, "max_steps": 10}, runs)
    for config, expected in [
        ({**SMALL, "run": "other", "step": 10}, "is not on this kernel"),
        ({**SMALL, "step": 5}, "is at step 10 on the kernel, the page says 5"),
    ]:
        try:
            train(config, runs)
        except ValueError as err:
            check(expected in str(err), f"refuses: {err}")
        else:
            check(False, f"refuses: {expected}")
    for i in range(gt.MAX_RUNS + 1):
        train({**SMALL, "run": f"r{i}", "max_steps": 1}, runs)
    check(len(runs) == gt.MAX_RUNS and "r" not in runs and f"r{gt.MAX_RUNS}" in runs, f"keeps the newest {gt.MAX_RUNS} runs")


def ticks() -> None:
    lines = train({**SMALL, "max_steps": 2000}, {})
    steps = [line["step"] for line in lines if line["kind"] == "tick"]
    check(steps[:12] == list(range(12)), "ticks every step at first")
    gaps = [b / a for a, b in zip(steps[1:-2], steps[2:-1], strict=True)]
    check(all(r >= gt.LOG_RATIO - 1e-9 for r in gaps if r != 0), f"then log-spaced: {len(steps)} ticks over 2000 steps")
    check(steps[-1] == 2000 and lines[-2]["kind"] == "tick" and lines[-1]["kind"] == "end", "a last tick at the final step, right before end")


def interrupt() -> None:
    """SIGINT mid-run (a kernel interrupt): a last tick and "end" with reason "interrupted", exit 0."""
    endless = json.dumps({**SMALL, "max_steps": gt.MAX_STEPS, "tick_seconds": 0.05})
    proc = subprocess.Popen([sys.executable, str(PROGRAM)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    assert proc.stdin is not None and proc.stdout is not None
    proc.stdin.write(endless)
    proc.stdin.close()
    first = [json.loads(proc.stdout.readline()) for _ in range(2)]
    check([line["kind"] for line in first] == ["start", "tick"], f"cli: starts with start, tick (device {first[0]['device']})")
    time.sleep(0.5)
    proc.send_signal(signal.SIGINT)
    rest = [json.loads(line) for line in proc.stdout]
    code = proc.wait(timeout=10)
    end = rest[-1]
    check(code == 0, f"interrupt: exit code {code}")
    check(end["kind"] == "end" and end["reason"] == "interrupted", f"interrupt: ends with reason {end.get('reason')!r} at step {end['step']}")
    check(rest[-2]["kind"] == "tick" and rest[-2]["step"] == end["step"] and math.isfinite(rest[-2]["loss"]), "interrupt: the last tick is the final state")


def bad_configs() -> None:
    cases = [
        ({k: v for k, v in SMALL.items() if k != "run"}, "config: missing 'run'"),
        ({**SMALL, "p": 21}, "p = 21 is not a prime"),
        ({**SMALL, "p": 263}, "p = 263 is outside"),
        ({**SMALL, "train_fraction": 1}, "train_fraction = 1.0 is outside"),
        ({**SMALL, "step": 3}, "is not on this kernel"),  # a fresh process has no runs
    ]
    for bad, expected in cases:
        proc = subprocess.run([sys.executable, str(PROGRAM)], input=json.dumps(bad), capture_output=True, text=True, check=False)
        check(proc.returncode != 0 and expected in proc.stderr and proc.stdout == "", f"bad config fails before any output: {expected}")


def main() -> None:
    model()
    learns()
    continues()
    refuses()
    ticks()
    interrupt()
    bad_configs()


if __name__ == "__main__":
    main()
