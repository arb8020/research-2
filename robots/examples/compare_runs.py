"""Compare observe run logs (jsonl): eval_reward curves and training-metric trends.

  PYTHONPATH=. robots/.venv/bin/python robots/examples/compare_runs.py runs/a.jsonl runs/b.jsonl ...

If a file holds several run_ids (restarted runs), the last one is used. Newer
logs carry no run_id; then a re-used run name appends, and for each (metric,
step) the last value wins.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

Series = dict[int, float]  # step -> value


def load_metrics(path: Path) -> dict[str, Series]:
    """name -> {step: value} for the last run_id in the file."""
    records = []
    with path.open() as f:
        for line_no, line in enumerate(f, 1):
            if not line.strip():
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as e:
                raise ValueError(f"{path}:{line_no}: bad json: {e}") from e
    metric_records = [r for r in records if r.get("kind") == "metric"]
    if not metric_records:
        raise ValueError(f"{path}: no metric records")
    last_run = metric_records[-1].get("run_id")
    out: dict[str, Series] = defaultdict(dict)
    for r in metric_records:
        if r.get("run_id") == last_run:
            out[r["name"]][int(r["step"])] = float(r["value"])
    return out


def mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else float("nan")


def frac_mean(series: Series, lo: float, hi: float) -> float:
    """Mean over the steps in the [lo, hi) fraction of the run."""
    steps = sorted(series)
    n = len(steps)
    picked = steps[int(lo * n): max(int(hi * n), int(lo * n) + 1)]
    return mean([series[s] for s in picked])


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("paths", nargs="+", type=Path)
    p.add_argument("--solved", type=float, default=500.0, help="eval_reward counted as solved")
    args = p.parse_args()

    runs = {path.stem: load_metrics(path) for path in args.paths}
    names = list(runs)
    width = max(12, *(len(n) for n in names))

    print("eval_reward by step")
    print(f"{'step':>6} " + " ".join(f"{n:>{width}}" for n in names))
    all_steps = sorted(set().union(*(r.get("eval_reward", {}).keys() for r in runs.values())))
    for step in all_steps:
        cells = [runs[n].get("eval_reward", {}).get(step) for n in names]
        print(f"{step:>6} " + " ".join(f"{c:>{width}.1f}" if c is not None else f"{'-':>{width}}" for c in cells))

    print("\nsummary")
    rows = [
        ("eval first 10%", lambda r: frac_mean(r["eval_reward"], 0.0, 0.1)),
        ("eval last 10%", lambda r: frac_mean(r["eval_reward"], 0.9, 1.0)),
        ("eval max", lambda r: max(r["eval_reward"].values())),
        (f"evals >= {args.solved:g}", lambda r: float(sum(v >= args.solved for v in r["eval_reward"].values()))),
        ("n evals", lambda r: float(len(r["eval_reward"]))),
    ]
    for metric in ("value_loss", "entropy", "train_ep_return", "advantage_mean"):
        for label, lo, hi in (("first 10%", 0.0, 0.1), ("last 10%", 0.9, 1.0)):
            rows.append((f"{metric} {label}", lambda r, m=metric, lo=lo, hi=hi: frac_mean(r[m], lo, hi) if m in r else float("nan")))
    print(f"{'':<26} " + " ".join(f"{n:>{width}}" for n in names))
    for label, fn in rows:
        print(f"{label:<26} " + " ".join(f"{fn(runs[n]):>{width}.2f}" for n in names))


if __name__ == "__main__":
    main()
