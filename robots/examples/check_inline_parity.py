"""Check that the inlined examples behave exactly like the robots-sdk originals.

Runs each example twice with the same args and seed: the ORIGINAL (from a git ref,
extracted with `git archive` so it imports its own robots/ modules) and the NEW
(this working tree). Each run gets its own temp cwd, so runs/<name>.jsonl don't
collide. Then compares the logged events value-for-value, ignoring fields that
differ run to run (timestamps, span ids/timing, git info, run_name), and compares
printed stdout.

Some RNGs aren't seeded by the examples themselves, so the harness pins them for
BOTH sides (it only checks original == new, not that the examples are seeded):
  cartpole_modelbased: env.action_space (collect_transitions samples random actions)
  gpt2_pretrain:       torch global RNG (no --seed flag: token_loader, generate)

  PYTHONPATH=. robots/.venv/bin/python robots/examples/check_inline_parity.py
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

VOLATILE = {
    "ts", "run_name", "git_sha", "git_dirty", "trace_id", "span_id", "parent_span_id",
    "start_time_unix_nano", "end_time_unix_nano", "duration_ms",
}

# Runs the example as __main__ after pinning RNGs the example leaves unseeded.
PINNED = """
import runpy, sys, gymnasium, torch
seed = int(sys.argv[1]); script = sys.argv[2]
torch.manual_seed(seed)
_make = gymnasium.make
def make(*a, **k):
    env = _make(*a, **k)
    env.action_space.seed(seed)
    return env
gymnasium.make = make
sys.argv = [script, *sys.argv[3:]]
runpy.run_path(script, run_name="__main__")
"""

# (name, script path relative to repo root at the base ref, args, pin unseeded RNGs?)
CASES = [
    ("cartpole_modelfree", "examples/cartpole_modelfree.py",
     ["--iters", "30", "--seed", "0"], False),
    ("cartpole_modelbased", "examples/cartpole_modelbased.py",
     ["--iters", "20", "--seed", "0", "--wm-steps", "3", "--num-imagined", "2"], True),
    ("gpt2_pretrain", "examples/gpt2_pretrain.py",
     ["--iters", "4", "--batch-size", "2", "--seq-len", "32", "--sample-every", "2"], True),
]


def run(root: Path, script: Path, args: list[str], pin: bool, cwd: Path, shakespeare: Path | None) -> tuple[list[dict], list[str]]:
    (cwd / "runs").mkdir(parents=True, exist_ok=True)
    if shakespeare is not None:
        shutil.copy(shakespeare, cwd / "runs" / "tinyshakespeare.txt")
    name = "parity"
    cmd = [sys.executable]
    cmd += ["-c", PINNED, "0", str(script)] if pin else [str(script)]
    cmd += [*args, "--name", name]
    env = {**os.environ, "PYTHONPATH": str(root)}
    p = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True)
    if p.returncode != 0:
        sys.exit(f"FAILED: {' '.join(cmd)}\n{p.stderr[-3000:]}")
    events = [json.loads(line) for line in (cwd / "runs" / f"{name}.jsonl").read_text().splitlines()]
    stripped = [{k: v for k, v in e.items() if k not in VOLATILE} for e in events]
    stdout = [line for line in p.stdout.splitlines() if not line.startswith("[")]  # drop timestamped log lines
    return stripped, stdout


def find_shakespeare(tmp: Path) -> Path:
    common = Path(subprocess.check_output(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"], cwd=REPO, text=True).strip())
    for cand in (REPO / "runs" / "tinyshakespeare.txt", common.parent / "runs" / "tinyshakespeare.txt"):
        if cand.exists():
            return cand
    import urllib.request
    dst = tmp / "tinyshakespeare.txt"
    urllib.request.urlretrieve("https://raw.githubusercontent.com/karpathy/char-rnn/master/data/tinyshakespeare/input.txt", dst)
    return dst


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--base", default="b034f2e9", help="git ref holding the original (sdk) examples")
    p.add_argument("--only", nargs="*", default=None, help="subset of case names")
    args = p.parse_args()

    tmp = Path(tempfile.mkdtemp(prefix="inline-parity-"))
    orig_root = tmp / "orig"
    orig_root.mkdir()
    archive = subprocess.run(["git", "archive", args.base, "robots", "observe", "examples"], cwd=REPO, capture_output=True, check=True)
    subprocess.run(["tar", "-x", "-C", str(orig_root)], input=archive.stdout, check=True)
    print(f"original: {args.base} extracted to {orig_root}")
    print(f"new:      {REPO} (working tree)\n")

    ok = True
    for name, orig_rel, case_args, pin in CASES:
        if args.only and name not in args.only:
            continue
        shakespeare = find_shakespeare(tmp) if name == "gpt2_pretrain" else None
        new_script = REPO / "robots" / "examples" / f"{name}.py"
        ev_o, out_o = run(orig_root, orig_root / orig_rel, case_args, pin, tmp / f"{name}-orig", shakespeare)
        ev_n, out_n = run(REPO, new_script, case_args, pin, tmp / f"{name}-new", shakespeare)
        kinds: dict[str, int] = {}
        for e in ev_o:
            kinds[e["kind"]] = kinds.get(e["kind"], 0) + 1
        same_events, same_stdout = ev_o == ev_n, out_o == out_n
        ok &= same_events and same_stdout
        status = "IDENTICAL" if same_events and same_stdout else "DIFFERENT"
        print(f"{name:22s} {status}  events={len(ev_o)} vs {len(ev_n)} {kinds}  "
              f"stdout_lines={len(out_o)} same_stdout={same_stdout}  args={' '.join(case_args)}{'  [pinned rngs]' if pin else ''}")
        if not same_events:
            for i, (a, b) in enumerate(zip(ev_o, ev_n, strict=False)):
                if a != b:
                    print(f"  first diff at event {i}:\n    orig {a}\n    new  {b}")
                    break
        last = [line for line in out_n if line.strip()][-1:]
        print(f"  last stdout: {last}")
    print("\nALL IDENTICAL" if ok else "\nMISMATCH")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
