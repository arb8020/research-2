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

D_MODEL = 128
HEADS = 4
D_MLP = 512
LR = 1e-3
WEIGHT_DECAY = 1.0
BETAS = (0.9, 0.98)
WARMUP_STEPS = 10

LOG_RATIO = 1.03
MAX_P = 257
MAX_RUNS = 4
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


@dataclass(frozen=True)
class Data:
    tokens: torch.Tensor
    labels: torch.Tensor
    train: torch.Tensor
    test: torch.Tensor


def make_data(p: int, train_fraction: float, seed: int, device: torch.device) -> Data:
    a = torch.arange(p).repeat_interleave(p)
    b = torch.arange(p).repeat(p)
    order = torch.randperm(p * p, generator=torch.Generator().manual_seed(seed))
    cut = round(train_fraction * p * p)
    assert 0 < cut < p * p, "train_fraction leaves an empty split"
    equals_token = p
    tokens = torch.stack([a, b, torch.full_like(a, equals_token)], dim=1)
    return Data(tokens.to(device), ((a + b) % p).to(device), order[:cut].to(device), order[cut:].to(device))


def init_params(p: int, seed: int, device: torch.device) -> dict[str, torch.Tensor]:
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
    x = F.embedding(tokens, w["embed"]) + w["pos"]
    n = x.shape[0]
    head = D_MODEL // HEADS
    q, k, v = (x @ w["qkv"]).view(n, 3, 3, HEADS, head).unbind(2)
    attn = torch.softmax((q[:, -1:] * k).sum(-1) / math.sqrt(head), dim=1)
    r = x[:, -1] + (attn[..., None] * v).sum(1).reshape(n, D_MODEL) @ w["out"]
    r = r + torch.relu(r @ w["mlp_in"] + w["mlp_in_b"]) @ w["mlp_out"] + w["mlp_out_b"]
    return r @ w["unembed"]


def loss_of(out: torch.Tensor, labels: torch.Tensor) -> torch.Tensor:
    return F.cross_entropy(out.to(torch.float64), labels)


@dataclass
class Run:
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


@contextmanager
def interrupt_flag() -> Iterator[Callable[[], bool]]:
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
        "params": params, "train": len(run.data.train), "test": len(run.data.test),
    }  # fmt: skip


def print_line(obj: dict) -> None:
    print(json.dumps(obj, allow_nan=False, separators=(",", ":")), flush=True)


def run(config_json: str, runs: dict[str, Run]) -> StopReason:
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
