"""<nn-fit>'s grokking dataset: a + b mod p, trained on the connected kernel (remote only; torch, cuda if there).

The setup is Nanda et al. 2023, "Progress measures for grokking via mechanistic interpretability" (arXiv
2301.05217; code: github.com/mechanistic-interpretability-grokking/progress-measures-paper): p = 113, 30% of the p^2 pairs to train on, a 1-layer
transformer (d_model 128, 4 heads of 32, ReLU MLP 512, no LayerNorm) reading "a b =" and predicting the sum at
"=", full-batch AdamW (lr 1e-3, weight decay 1, betas 0.9, 0.98, 10 warmup steps), cross-entropy in float64.
The model fits the training pairs within a few hundred steps and generalises (groks) thousands of steps later
(~5k steps here; a T4 does ~240 steps/s, a laptop CPU ~40). Power et al. 2022 ("Grokking", arXiv 2201.02177)
found the effect with minibatches; this follows Nanda et al.'s full-batch setup instead (no batch sampling).
Only the "=" position's output is computed: with one layer nothing at the other positions reaches it, so this is
the same function, ~3x cheaper.

The page bundles this file as text (esbuild's text loader); grok.ts: grokCode sends it with the config inlined.
Unlike remote_train.py the weights stay on the kernel between Train presses (226k parameters plus AdamW's state
is too much to send in a JSON line): `runs`, a dict the kernel keeps, maps the page's run id to its weights.
Standalone, one run from step 0:

    uv run --with torch python web/embeds/nn-fit/grok_train.py config.json      # or the config on stdin

Config (JSON, built by grok.ts: grokConfig):

    run                    the page's id for this training run (a new id = fresh weights)
    p, train_fraction      the modulus (a prime) and the share of the p^2 pairs trained on
    split_seed, init_seed  which pairs are training pairs; the initial weights
    step, seconds          where the run is: 0, 0 starts it; otherwise it must be where the kernel's copy is
    max_steps, max_seconds when it stops: absolute, like the widget's budgets
    tick_seconds           at most this long between ticks

Output: one JSON object per line on stdout, flushed as it goes:

    {"kind": "start", "device", "device_name", "torch", "params": 226k, "train": 3831, "test": 8938, "model"}
    {"kind": "tick", "step", "seconds", "loss", "accuracy", "test_loss", "test_accuracy"}
    {"kind": "end", "reason": "steps" | "time" | "interrupted", "step", "seconds"}

A tick's metrics are for the weights after `step` steps, on the training pairs and on the rest (test). Ticks
come at log-spaced steps (each at least LOG_RATIO times the last) and at least every tick_seconds, so a log-x
plot gets points all along. Non-finite numbers print as null. The last tick comes right before "end". An
interrupt (SIGINT: a kernel interrupt, Ctrl-C) stops between steps; the run can then be continued.
"""

import json
import math
import signal
import sys
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import torch
import torch.nn.functional as F

StopReason = Literal["steps", "time", "interrupted"]

# Nanda et al. 2023 (module docstring).
D_MODEL = 128
HEADS = 4
D_MLP = 512
LR = 1e-3
WEIGHT_DECAY = 1.0
BETAS = (0.9, 0.98)
WARMUP_STEPS = 10
MODEL = f"1-layer transformer (d {D_MODEL}, {HEADS} heads, MLP {D_MLP}) · AdamW lr {LR:g}, weight decay {WEIGHT_DECAY:g}"

LOG_RATIO = 1.03  # ticks at least this far apart in log(step): ~330 points up to 20k steps
MAX_P = 257  # the eval batch is p^2 pairs
MAX_RUNS = 4  # runs kept on the kernel; the oldest goes first
MAX_STEPS = 10**9
MAX_SECONDS = 3600.0
MIN_TICK_SECONDS = 0.05


@dataclass(frozen=True)
class Config:
    run: str
    p: int
    train_fraction: float
    split_seed: int
    init_seed: int
    step: int
    seconds: float
    max_steps: int
    max_seconds: float
    tick_seconds: float


# --- parsing (the boundary: the config crossed a network) ---


def field(raw: dict, key: str, kind: type | tuple[type, ...]) -> object:
    if key not in raw:
        raise ValueError(f"config: missing {key!r}")
    value = raw[key]
    if isinstance(value, bool) or not isinstance(value, kind):
        raise ValueError(f"config: {key} must be {kind}, got {type(value).__name__}")
    return value


def number(raw: dict, key: str, lo: float, hi: float) -> float:
    value = float(field(raw, key, (int, float)))
    if not (math.isfinite(value) and lo <= value <= hi):
        raise ValueError(f"config: {key} = {value} is outside {lo}..{hi}")
    return value


def integer(raw: dict, key: str, lo: int, hi: int) -> int:
    value = field(raw, key, int)
    if not lo <= value <= hi:
        raise ValueError(f"config: {key} = {value} is outside {lo}..{hi}")
    return value


def is_prime(n: int) -> bool:
    return n >= 2 and all(n % d != 0 for d in range(2, math.isqrt(n) + 1))


def parse_config(raw: object) -> Config:
    if not isinstance(raw, dict):
        raise ValueError(f"config must be a JSON object, got {type(raw).__name__}")
    run = field(raw, "run", str)
    if not 1 <= len(run) <= 64:
        raise ValueError("config: run must be 1..64 characters")
    p = integer(raw, "p", 3, MAX_P)
    if not is_prime(p):
        raise ValueError(f"config: p = {p} is not a prime")
    return Config(
        run=run, p=p, train_fraction=number(raw, "train_fraction", 0.05, 0.95),
        split_seed=integer(raw, "split_seed", 0, 2**31), init_seed=integer(raw, "init_seed", 0, 2**31),
        step=integer(raw, "step", 0, MAX_STEPS), seconds=number(raw, "seconds", 0, MAX_SECONDS),
        max_steps=integer(raw, "max_steps", 0, MAX_STEPS), max_seconds=number(raw, "max_seconds", 0, MAX_SECONDS),
        tick_seconds=number(raw, "tick_seconds", MIN_TICK_SECONDS, 60),
    )  # fmt: skip


# --- data and model ---


@dataclass(frozen=True)
class Data:
    tokens: torch.Tensor  # (p^2, 3): a, b, "=" (token p), every pair
    labels: torch.Tensor  # (p^2,): (a + b) mod p
    train: torch.Tensor  # indices into the pairs
    test: torch.Tensor


def make_data(p: int, train_fraction: float, seed: int, device: torch.device) -> Data:
    a = torch.arange(p).repeat_interleave(p)
    b = torch.arange(p).repeat(p)
    order = torch.randperm(p * p, generator=torch.Generator().manual_seed(seed))
    cut = round(train_fraction * p * p)
    assert 0 < cut < p * p, "train_fraction leaves an empty split"
    tokens = torch.stack([a, b, torch.full_like(a, p)], dim=1)
    return Data(tokens.to(device), ((a + b) % p).to(device), order[:cut].to(device), order[cut:].to(device))


def init_params(p: int, seed: int, device: torch.device) -> dict[str, torch.Tensor]:
    """N(0, 1) / sqrt(fan-in), biases zero: like Nanda's code, which scales most weights by 1/sqrt(d_model)."""
    g = torch.Generator().manual_seed(seed)

    def randn(*shape: int, fan_in: int) -> torch.Tensor:
        return torch.randn(*shape, generator=g) / math.sqrt(fan_in)

    shapes = {
        "embed": randn(p + 1, D_MODEL, fan_in=D_MODEL), "pos": randn(3, D_MODEL, fan_in=D_MODEL),
        "qkv": randn(D_MODEL, 3 * D_MODEL, fan_in=D_MODEL), "out": randn(D_MODEL, D_MODEL, fan_in=D_MODEL),
        "mlp_in": randn(D_MODEL, D_MLP, fan_in=D_MODEL), "mlp_in_b": torch.zeros(D_MLP),
        "mlp_out": randn(D_MLP, D_MODEL, fan_in=D_MLP), "mlp_out_b": torch.zeros(D_MODEL),
        "unembed": randn(D_MODEL, p, fan_in=p + 1),
    }  # fmt: skip
    return {k: v.to(device).requires_grad_() for k, v in shapes.items()}


def logits(w: dict[str, torch.Tensor], tokens: torch.Tensor) -> torch.Tensor:
    """(n, 3) tokens -> (n, p) logits at "=": attention from "=" over a, b, "=", then the MLP, residual stream."""
    x = F.embedding(tokens, w["embed"]) + w["pos"]  # (n, 3, d); embedding's backward is ~2x faster than indexing's
    n = x.shape[0]
    head = D_MODEL // HEADS
    q, k, v = (x @ w["qkv"]).view(n, 3, 3, HEADS, head).unbind(2)  # each (n, 3, heads, head)
    attn = torch.softmax((q[:, -1:] * k).sum(-1) / math.sqrt(head), dim=1)  # "=" attends to all 3: (n, 3, heads)
    r = x[:, -1] + (attn[..., None] * v).sum(1).reshape(n, D_MODEL) @ w["out"]
    r = r + torch.relu(r @ w["mlp_in"] + w["mlp_in_b"]) @ w["mlp_out"] + w["mlp_out_b"]
    return r @ w["unembed"]


def loss_of(out: torch.Tensor, labels: torch.Tensor) -> torch.Tensor:
    return F.cross_entropy(out.to(torch.float64), labels)  # float64, as Nanda: float32 stalls near zero loss


@dataclass
class Run:
    """One training run on the kernel: what persists between Train presses."""

    data: Data
    weights: dict[str, torch.Tensor]
    opt: torch.optim.Optimizer
    sched: torch.optim.lr_scheduler.LambdaLR
    step: int


def new_run(config: Config, device: torch.device) -> Run:
    weights = init_params(config.p, config.init_seed, device)
    opt = torch.optim.AdamW(weights.values(), lr=LR, weight_decay=WEIGHT_DECAY, betas=BETAS)
    sched = torch.optim.lr_scheduler.LambdaLR(opt, lambda s: min(1.0, (s + 1) / WARMUP_STEPS))
    return Run(make_data(config.p, config.train_fraction, config.split_seed, device), weights, opt, sched, 0)


def find_run(runs: dict[str, Run], config: Config, device: torch.device) -> Run:
    """The run to continue, or a new one at step 0. A run the kernel doesn't have can't continue: it lived on
    another session, or was dropped (MAX_RUNS)."""
    run = runs.get(config.run)
    if run is None and config.step > 0:
        raise ValueError(f"run {config.run} is not on this kernel (another session, or dropped): reset the weights to start over")
    if run is not None and run.step != config.step:
        raise ValueError(f"run {config.run} is at step {run.step} on the kernel, the page says {config.step}")
    if run is not None:
        return run
    while len(runs) >= MAX_RUNS:
        del runs[next(iter(runs))]
    runs[config.run] = new_run(config, device)
    return runs[config.run]


# --- output ---


def finite(v: float) -> float | None:
    return v if math.isfinite(v) else None


def tick(run: Run, step: int, seconds: float) -> dict:
    with torch.no_grad():
        out = logits(run.weights, run.data.tokens)
        right = (out.argmax(-1) == run.data.labels).to(torch.float64)
        train, test = run.data.train, run.data.test
        loss, test_loss = loss_of(out[train], run.data.labels[train]), loss_of(out[test], run.data.labels[test])
        return {
            "kind": "tick", "step": step, "seconds": seconds,
            "loss": finite(loss.item()), "accuracy": right[train].mean().item(),
            "test_loss": finite(test_loss.item()), "test_accuracy": right[test].mean().item(),
        }  # fmt: skip


# --- the loop ---


@contextmanager
def interrupt_flag() -> Iterator[Callable[[], bool]]:
    """SIGINT sets a flag instead of raising, so training stops between steps rather than inside an AdamW
    update (as remote_train.py). Off the main thread Python can't catch signals: no flag."""
    if threading.current_thread() is not threading.main_thread():
        yield lambda: False
        return
    hits: list[int] = []
    previous = signal.signal(signal.SIGINT, lambda signum, _frame: hits.append(signum))
    try:
        yield lambda: len(hits) > 0
    finally:
        signal.signal(signal.SIGINT, previous)


def next_tick_step(step: int) -> int:
    return max(step + 1, math.ceil(step * LOG_RATIO))


def train(config: Config, run: Run, emit: Callable[[dict], None], clock: Callable[[], float]) -> StopReason:
    """Full-batch AdamW from where the run is until a budget runs out or an interrupt; emits ticks, then "end"."""
    assert run.step == config.step, "find_run hands over the run the page is at"
    began = clock()
    last_tick = began
    tick_step = next_tick_step(run.step)
    x, y = run.data.tokens[run.data.train], run.data.labels[run.data.train]
    emit(tick(run, run.step, config.seconds))
    reason: StopReason
    with interrupt_flag() as interrupted:
        while True:
            if interrupted():
                reason = "interrupted"
                break
            if run.step >= config.max_steps:
                reason = "steps"
                break
            if config.seconds + clock() - began >= config.max_seconds:
                reason = "time"
                break
            loss_of(logits(run.weights, x), y).backward()
            run.opt.step()
            run.sched.step()
            run.opt.zero_grad(set_to_none=True)
            run.step += 1
            if run.step >= tick_step or clock() - last_tick >= config.tick_seconds:
                last_tick = clock()
                tick_step = next_tick_step(run.step)
                emit(tick(run, run.step, config.seconds + last_tick - began))
    seconds = config.seconds + clock() - began
    emit(tick(run, run.step, seconds))
    emit({"kind": "end", "reason": reason, "step": run.step, "seconds": seconds})
    return reason


def describe(device: torch.device, run: Run) -> dict:
    name = torch.cuda.get_device_name(device) if device.type == "cuda" else "cpu"
    params = sum(w.numel() for w in run.weights.values())
    return {
        "kind": "start", "device": device.type, "device_name": name, "torch": torch.__version__,
        "params": params, "train": len(run.data.train), "test": len(run.data.test), "model": MODEL,
    }  # fmt: skip


def print_line(obj: dict) -> None:
    print(json.dumps(obj, allow_nan=False, separators=(",", ":")), flush=True)


def run(config_json: str, runs: dict[str, Run]) -> StopReason:
    """The kernel entry point: parse, find or start the run, say where it runs, train, printing JSON lines."""
    config = parse_config(json.loads(config_json))
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    current = find_run(runs, config, device)
    print_line(describe(device, current))
    return train(config, current, print_line, time.monotonic)


def main() -> None:
    if len(sys.argv) > 2:
        sys.exit("usage: grok_train.py [config.json]   (or the config on stdin)")
    run(Path(sys.argv[1]).read_text() if len(sys.argv) == 2 else sys.stdin.read(), {})


if __name__ == "__main__":
    main()
