"""Checks for remote_train.py: parity with mlp.ts, resume, interrupt, tick rate, bad configs.

    cd web && npm run test:nn-fit-remote      # builds parity.ts for node, then runs this with its path

Throws (exit 1) on the first failure; prints one line per check, plus the parity table.
Parity: parity.ts trains the widget's default datasets with mlp.ts and prints the configs the page would send
(same data, same initial weights); here torch trains the same configs and compares loss traces: float64 equal
to rounding at first, then both dtypes converging comparably (thresholds below).
"""

import importlib.util
import json
import math
import signal
import statistics
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

HERE = Path(__file__).parent
PROGRAM = HERE / "remote_train.py"

spec = importlib.util.spec_from_file_location("remote_train", PROGRAM)
assert spec is not None and spec.loader is not None
rt = importlib.util.module_from_spec(spec)
sys.modules["remote_train"] = rt  # dataclasses look their module up by name
spec.loader.exec_module(rt)

# float64 does mlp.ts's arithmetic up to summation order, so the two agree to rounding for a while (at least
# 175 steps on these cases); then the rounding differences grow (chaotically), and so do float32's. So:
EXACT_STEPS = 100  # float64: the training loss equals mlp.ts's to EXACT_REL for this many steps
EXACT_REL = 1e-12
# Converging comparably, float32 and float64 alike, measured on the training-loss trace:
CONVERGED = 1e-3  # steps until the loss first drops below this (from ~0.2 on the wave, ~0.7 on the spiral)...
STEPS_REL = 0.1  # ...within 10% of mlp.ts's
TAIL = 200  # median loss over the last TAIL steps (the final value alone is spiky: Adam at lr 0.03)...
TAIL_FACTOR = 1.5  # ...within this factor of mlp.ts's
# Spiral held-out accuracy (500 points): within this many points of each other.
ACCURACY_POINTS = 25


def check(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(f"FAIL {message}")
    print(f"ok   {message}")


def train(config: dict, clock: Callable[[], float] = time.monotonic) -> list[dict]:
    lines: list[dict] = []
    rt.train(rt.parse_config(config, rt.pick_device()), lines.append, clock)
    return lines


def loss_trace(config: dict) -> list[float]:
    """The training loss after every step, 0..max_steps: a clock that jumps past tick_seconds on every read
    makes the program tick after each step."""
    now = [0.0]

    def clock() -> float:
        now[0] += config["tick_seconds"] * 2
        return now[0]

    ticks = [line for line in train({**config, "max_seconds": rt.MAX_SECONDS}, clock) if line["kind"] == "tick"]
    trace = {t["step"]: t["loss"] for t in ticks}
    assert sorted(trace) == list(range(config["max_steps"] + 1)), "expected a tick after every step"
    return [trace[k] for k in range(config["max_steps"] + 1)]


def rel(a: float, b: float) -> float:
    return abs(a - b) / max(abs(a), abs(b), 1e-300)


def first_below(trace: list[float], level: float) -> int:
    return next((k for k, v in enumerate(trace) if v < level), len(trace))


def parity(report: dict) -> None:
    steps = report["steps"]
    print(f"\nparity: {steps} full-batch Adam steps (lr 0.03), same data and initial weights; training-loss trace")
    print(f"  {'':<27}{f'steps to loss < {CONVERGED:g}':^24}{f'median loss, last {TAIL} steps':^36}{'held-out accuracy':^18}")
    print(f"  {'case':<22}{'seed':>5}{'mlp.ts':>8}{'f64':>8}{'f32':>8}{'mlp.ts':>12}{'f64':>12}{'f32':>12}{'mlp.ts':>9}{'f32':>9}")
    for r in report["results"]:
        b = r["browser"]
        mine, f64, f32 = b["trace"], loss_trace(r["config"]["float64"]), loss_trace(r["config"]["float32"])
        last32 = train(r["config"]["float32"])[-2]  # the final tick, for the test metrics (the last line is "end")
        reach = [first_below(t, CONVERGED) for t in (mine, f64, f32)]
        tail = [statistics.median(t[-TAIL:]) for t in (mine, f64, f32)]
        binary = b["testAccuracy"] is not None
        acc = f"{b['testAccuracy']:>9.1%}{last32['test_accuracy']:>9.1%}" if binary else ""
        print(f"  {r['name']:<22}{r['seed']:>5}{reach[0]:>8}{reach[1]:>8}{reach[2]:>8}{tail[0]:>12.3e}{tail[1]:>12.3e}{tail[2]:>12.3e}{acc}")
        where = f"{r['name']} seed {r['seed']}"
        worst = max(rel(f64[k], mine[k]) for k in range(EXACT_STEPS + 1))
        check(worst < EXACT_REL, f"{where}: float64 equals mlp.ts for {EXACT_STEPS} steps (worst rel {worst:.0e})")
        for name, k, t in (("float64", reach[1], tail[1]), ("float32", reach[2], tail[2])):
            check(abs(k - reach[0]) <= STEPS_REL * reach[0], f"{where}: {name} reaches {CONVERGED:g} in {k} steps (mlp.ts {reach[0]})")
            check(1 / TAIL_FACTOR < t / tail[0] < TAIL_FACTOR, f"{where}: {name} tail median {t / tail[0]:.2f}x mlp.ts's")
        if binary:
            gap = abs(last32["test_accuracy"] - b["testAccuracy"]) * len(r["config"]["float32"]["test"]["y"])
            check(gap <= ACCURACY_POINTS, f"{where}: float32 held-out accuracy within {ACCURACY_POINTS} points ({gap:.0f})")


def resume(config: dict) -> None:
    """Two halves, the second started from the first's "end" state, land where one straight run does."""
    half = config["max_steps"] // 2
    straight = train(config)
    first = train({**config, "max_steps": half})
    end = first[-1]
    second = train({**config, "state": end["state"], "step": end["step"], "seconds": 0})
    a, b = straight[-2]["loss"], second[-2]["loss"]
    check(second[-1]["step"] == config["max_steps"], f"resume: second half ends at step {config['max_steps']}")
    check(a == b, f"resume: {half} + {half} steps == {2 * half} steps, bit for bit in float64 ({a:.6e} vs {b:.6e})")


def tick_rate(config: dict) -> None:
    seconds = 1.0
    start = time.monotonic()
    lines = train({**config, "max_steps": rt.MAX_STEPS, "max_seconds": seconds, "tick_seconds": 0.1})
    took = time.monotonic() - start
    ticks = [line for line in lines if line["kind"] == "tick"]
    check(lines[-1]["reason"] == "time", f"time budget: stopped by time after {lines[-1]['step']} steps")
    # One at the start, at most one per tick_seconds, one at the end.
    check(len(ticks) <= seconds / 0.1 + 2, f"tick rate: {len(ticks)} ticks in {took:.2f} s with tick_seconds 0.1")
    check(all(len(t["pred"]) == len(config["grid"]) // config["sizes"][0] for t in ticks), "every tick predicts the whole grid")


def interrupt(config: dict) -> None:
    """SIGINT mid-run (what a kernel interrupt sends): a final tick and "end" with reason "interrupted", exit 0."""
    endless = json.dumps({**config, "max_steps": rt.MAX_STEPS, "max_seconds": 60})
    proc = subprocess.Popen([sys.executable, str(PROGRAM)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    assert proc.stdin is not None and proc.stdout is not None
    proc.stdin.write(endless)
    proc.stdin.close()
    first = [json.loads(proc.stdout.readline()) for _ in range(2)]  # start, tick at step 0
    check([line["kind"] for line in first] == ["start", "tick"], f"cli: starts with start, tick (device {first[0]['device']})")
    time.sleep(0.5)
    proc.send_signal(signal.SIGINT)
    rest = [json.loads(line) for line in proc.stdout]
    code = proc.wait(timeout=10)
    end = rest[-1]
    check(code == 0, f"interrupt: exit code {code}")
    check(end["kind"] == "end" and end["reason"] == "interrupted", f"interrupt: ends with reason {end.get('reason')!r} at step {end['step']}")
    check(rest[-2]["kind"] == "tick" and rest[-2]["step"] == end["step"], "interrupt: the last tick is the final state")
    check(all(math.isfinite(v) for layer in end["state"]["layers"] for v in layer["w"]), "interrupt: the end state is whole")


def bad_configs(config: dict) -> None:
    cases = [
        ({k: v for k, v in config.items() if k != "lr"}, "config: missing 'lr'"),
        ({**config, "activation": "gelu"}, "activation = 'gelu'"),
        ({**config, "max_seconds": 1e9}, "max_seconds = 1000000000.0 is outside"),
        ({**config, "train": {"x": config["train"]["x"][:-1], "y": config["train"]["y"]}}, "train.x must be a list of"),
        ({**config, "sizes": [*config["sizes"][:-1], 2]}, "end in 1 output"),
    ]
    for bad, expected in cases:
        proc = subprocess.run([sys.executable, str(PROGRAM)], input=json.dumps(bad), capture_output=True, text=True, check=False)
        check(proc.returncode != 0 and expected in proc.stderr and proc.stdout == "", f"bad config fails before any output: {expected}")


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: remote_train_test.py build/nn-fit-parity.mjs   (npm run test:nn-fit-remote builds it)")
    report = json.loads(subprocess.run(["node", sys.argv[1]], capture_output=True, text=True, check=True).stdout)
    parity(report)
    config = report["results"][0]["config"]
    print()
    resume({**config["float64"], "max_steps": 400})
    tick_rate(config["float32"])
    interrupt(config["float32"])
    bad_configs(config["float32"])


if __name__ == "__main__":
    main()
