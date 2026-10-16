"""<nn-fit>'s remote backend: the widget's training (mlp.ts) in torch, on cuda if there is one.

The page bundles this file as text (esbuild's text loader), and on Train with backend "remote" sends it to the
connected kernel with the config inlined (remote.ts: remoteCode). It runs standalone too:

    uv run python web/embeds/nn-fit/remote_train.py config.json      # or the config on stdin

Config (JSON, built by remote.ts: remoteConfig): the network and optimizer state to start from, the data and
an eval grid, all sampled by the browser, so both backends train on the same points from the same weights.

    task         "regression" (MSE on y-hat) | "binary" (BCE on a logit)
    activation   "linear" | "relu" | "tanh" | "sigmoid" (hidden layers; the output unit is linear)
    sizes        [inputs, ...hidden widths, 1]
    state        {"layers": [{"w", "b"}], "adam": {"m": [{"w", "b"}], "v": [{"w", "b"}], "t"}}; w is row-major
                 (nOut, nIn), as in mlp.ts and torch.nn.Linear
    lr, dtype    Adam learning rate; "float32" | "float64"
    train, test  {"x": flat inputs (n * inputs), "y": targets}; test is the true curve (regression) or a
                 held-out sample (binary)
    grid         flat inputs to predict at, for the plot
    step, seconds          where the run starts (the widget's counters)
    max_steps, max_seconds when it stops: absolute, like the widget's budgets
    tick_seconds           at least this long between ticks

Output: one JSON object per line on stdout, flushed as it goes:

    {"kind": "start", "device": "cuda", "device_name": "Tesla T4", "torch": "2.4.1", "dtype": "float32"}
    {"kind": "tick", "step", "seconds", "loss", "accuracy", "test_loss", "test_accuracy", "pred": [...]}
    {"kind": "end", "reason": "steps" | "time" | "interrupted", "step", "seconds", "state": {...}}

A tick's metrics are for the weights after `step` steps (accuracy, test_accuracy: binary only, else null);
`pred` is y-hat (regression) or P(label 1) (binary) at each grid point. Non-finite numbers (a diverged run)
print as null. The last tick comes right before "end", and "end" carries the state to continue from. An
interrupt (Ctrl-C, a kernel interrupt: SIGINT) stops between steps and still prints the last tick and "end".
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

Task = Literal["regression", "binary"]
Activation = Literal["linear", "relu", "tanh", "sigmoid"]
StopReason = Literal["steps", "time", "interrupted"]

TASKS = ("regression", "binary")
ACTIVATIONS = ("linear", "relu", "tanh", "sigmoid")
DTYPES = {"float32": torch.float32, "float64": torch.float64}
BETA1 = 0.9  # Adam, as in mlp.ts
BETA2 = 0.999
EPS = 1e-8

# Limits: the widget's are lower (4 hidden layers of 16, 512 samples, a 128 x 128 heatmap); these leave room
# for bigger remote runs while still bounding a config that would never finish or never fit.
MAX_LAYERS = 8
MAX_WIDTH = 4096
MAX_INPUTS = 4096
MAX_POINTS = 1_000_000  # train, test or grid points
MAX_STEPS = 10**9
MAX_SECONDS = 3600.0
MIN_TICK_SECONDS = 0.05  # at most 20 ticks a second
PRED_DECIMALS = 4  # pred values print rounded: a plot needs ~3 digits, and the grid is the bulk of a tick


@dataclass(frozen=True)
class Params:
    """Weights, or anything shaped like them (Adam's m and v): one (w, b) per layer."""

    w: list[torch.Tensor]
    b: list[torch.Tensor]


@dataclass(frozen=True)
class Batch:
    x: torch.Tensor  # (n, inputs)
    y: torch.Tensor  # (n,)


@dataclass(frozen=True)
class Start:
    net: Params
    m: Params
    v: Params
    t: int  # Adam's step count (bias correction)
    step: int
    seconds: float


@dataclass(frozen=True)
class Stop:
    max_steps: int
    max_seconds: float


@dataclass(frozen=True)
class Config:
    task: Task
    activation: Activation
    lr: float
    train: Batch
    test: Batch
    grid: torch.Tensor  # (points, inputs)
    start: Start
    stop: Stop
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


def choice(raw: dict, key: str, options: tuple[str, ...]) -> str:
    value = field(raw, key, str)
    if value not in options:
        raise ValueError(f"config: {key} = {value!r}, expected one of {', '.join(options)}")
    return value


def floats(values: object, where: str, length: int, dtype: torch.dtype, device: torch.device) -> torch.Tensor:
    if not isinstance(values, list) or len(values) != length:
        got = len(values) if isinstance(values, list) else type(values).__name__
        raise ValueError(f"config: {where} must be a list of {length} numbers, got {got}")
    if not all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in values):
        raise ValueError(f"config: {where} holds something other than finite numbers")
    return torch.tensor(values, dtype=dtype, device=device)


def parse_sizes(raw: dict) -> list[int]:
    sizes = field(raw, "sizes", list)
    if not 2 <= len(sizes) <= MAX_LAYERS + 2:
        raise ValueError(f"config: sizes needs 2..{MAX_LAYERS + 2} entries, got {len(sizes)}")
    if not all(isinstance(s, int) and not isinstance(s, bool) and 1 <= s <= MAX_WIDTH for s in sizes):
        raise ValueError(f"config: sizes must be integers in 1..{MAX_WIDTH}, got {sizes}")
    if sizes[0] > MAX_INPUTS or sizes[-1] != 1:
        raise ValueError(f"config: sizes must start with 1..{MAX_INPUTS} inputs and end in 1 output, got {sizes}")
    return sizes


def parse_params(raw: object, where: str, sizes: list[int], dtype: torch.dtype, device: torch.device) -> Params:
    layers = len(sizes) - 1
    if not isinstance(raw, list) or len(raw) != layers:
        raise ValueError(f"config: {where} must list {layers} layers")
    w, b = [], []
    for i, (layer, n_in, n_out) in enumerate(zip(raw, sizes, sizes[1:], strict=False)):
        if not isinstance(layer, dict):
            raise ValueError(f"config: {where}[{i}] must be {{'w', 'b'}}")
        w.append(floats(layer.get("w"), f"{where}[{i}].w", n_in * n_out, dtype, device).reshape(n_out, n_in))
        b.append(floats(layer.get("b"), f"{where}[{i}].b", n_out, dtype, device))
    return Params(w, b)


def parse_batch(raw: dict, key: str, inputs: int, dtype: torch.dtype, device: torch.device) -> Batch:
    batch = field(raw, key, dict)
    y = batch.get("y")
    n = len(y) if isinstance(y, list) else -1
    if not 1 <= n <= MAX_POINTS:
        raise ValueError(f"config: {key}.y must list 1..{MAX_POINTS} targets")
    x = floats(batch.get("x"), f"{key}.x", n * inputs, dtype, device).reshape(n, inputs)
    return Batch(x, floats(y, f"{key}.y", n, dtype, device))


def parse_start(raw: dict, sizes: list[int], dtype: torch.dtype, device: torch.device) -> Start:
    state = field(raw, "state", dict)
    adam = state.get("adam")
    if not isinstance(adam, dict):
        raise ValueError("config: state.adam must be {'m', 'v', 't'}")
    return Start(
        net=parse_params(state.get("layers"), "state.layers", sizes, dtype, device),
        m=parse_params(adam.get("m"), "state.adam.m", sizes, dtype, device),
        v=parse_params(adam.get("v"), "state.adam.v", sizes, dtype, device),
        t=integer(adam, "t", 0, MAX_STEPS),
        step=integer(raw, "step", 0, MAX_STEPS),
        seconds=number(raw, "seconds", 0, MAX_SECONDS),
    )


def parse_config(raw: object, device: torch.device) -> Config:
    if not isinstance(raw, dict):
        raise ValueError(f"config must be a JSON object, got {type(raw).__name__}")
    sizes = parse_sizes(raw)
    dtype = DTYPES[choice(raw, "dtype", tuple(DTYPES))]
    grid = field(raw, "grid", list)
    if len(grid) % sizes[0] != 0 or len(grid) > MAX_POINTS * sizes[0]:
        raise ValueError(f"config: grid must hold whole points of {sizes[0]} inputs, at most {MAX_POINTS}")
    return Config(
        task=choice(raw, "task", TASKS),
        activation=choice(raw, "activation", ACTIVATIONS),
        lr=number(raw, "lr", 0, 10),
        train=parse_batch(raw, "train", sizes[0], dtype, device),
        test=parse_batch(raw, "test", sizes[0], dtype, device),
        grid=floats(grid, "grid", len(grid), dtype, device).reshape(-1, sizes[0]),
        start=parse_start(raw, sizes, dtype, device),
        stop=Stop(integer(raw, "max_steps", 0, MAX_STEPS), number(raw, "max_seconds", 0, MAX_SECONDS)),
        tick_seconds=number(raw, "tick_seconds", MIN_TICK_SECONDS, 60),
    )


# --- the model: mlp.ts's network, loss and Adam ---


def activate(kind: Activation, z: torch.Tensor) -> torch.Tensor:
    match kind:
        case "linear":
            return z
        case "relu":
            return torch.relu(z)
        case "tanh":
            return torch.tanh(z)
        case "sigmoid":
            return torch.sigmoid(z)


def forward(net: Params, activation: Activation, x: torch.Tensor) -> torch.Tensor:
    """The raw output unit, (n,): y-hat for regression, the logit for binary."""
    h = x
    last = len(net.w) - 1
    for i, (w, b) in enumerate(zip(net.w, net.b, strict=True)):
        z = h @ w.T + b
        h = z if i == last else activate(activation, z)
    return h[:, 0]


def mean_loss(task: Task, out: torch.Tensor, y: torch.Tensor) -> torch.Tensor:
    match task:
        case "regression":
            return ((out - y) ** 2).mean()
        case "binary":
            return F.binary_cross_entropy_with_logits(out, y)  # softplus(z) - y z, as mlp.ts


def adam_step(net: Params, m: Params, v: Params, t: int, lr: float) -> None:
    """One Adam update in place, with bias correction (mlp.ts adamStep); t counts this step."""
    c1 = 1 - BETA1**t
    c2 = 1 - BETA2**t
    with torch.no_grad():
        for p, mi, vi in zip([*net.w, *net.b], [*m.w, *m.b], [*v.w, *v.b], strict=True):
            g = p.grad
            assert g is not None, "adam_step before backward"
            mi.mul_(BETA1).add_(g, alpha=1 - BETA1)
            vi.mul_(BETA2).addcmul_(g, g, value=1 - BETA2)
            p.sub_(lr * (mi / c1) / ((vi / c2).sqrt() + EPS))
            p.grad = None


def scores(task: Task, out: torch.Tensor, y: torch.Tensor) -> tuple[float, float | None]:
    """(mean loss, accuracy): accuracy for binary only, as mlp.ts evaluate (logit > 0 means label 1)."""
    loss = mean_loss(task, out, y).item()
    if task == "regression":
        return loss, None
    return loss, ((out > 0).to(y.dtype) == y).to(torch.float64).mean().item()


# --- output ---


def finite(v: float) -> float | None:
    return v if math.isfinite(v) else None


def flat(t: torch.Tensor, decimals: int | None = None) -> list[float | None]:
    values = t.detach().to("cpu", torch.float64).flatten().tolist()
    return [finite(round(v, decimals) if decimals is not None and math.isfinite(v) else v) for v in values]


def tick(config: Config, net: Params, step: int, seconds: float) -> dict:
    with torch.no_grad():
        loss, accuracy = scores(config.task, forward(net, config.activation, config.train.x), config.train.y)
        test_loss, test_accuracy = scores(config.task, forward(net, config.activation, config.test.x), config.test.y)
        out = forward(net, config.activation, config.grid)
        pred = torch.sigmoid(out) if config.task == "binary" else out
    return {
        "kind": "tick", "step": step, "seconds": seconds,
        "loss": finite(loss), "accuracy": accuracy, "test_loss": finite(test_loss), "test_accuracy": test_accuracy,
        "pred": flat(pred, PRED_DECIMALS),
    }  # fmt: skip


def state(net: Params, m: Params, v: Params, t: int) -> dict:
    def layers(p: Params) -> list[dict]:
        return [{"w": flat(w), "b": flat(b)} for w, b in zip(p.w, p.b, strict=True)]

    return {"layers": layers(net), "adam": {"m": layers(m), "v": layers(v), "t": t}}


# --- the loop ---


@contextmanager
def interrupt_flag() -> Iterator[Callable[[], bool]]:
    """SIGINT (Ctrl-C, a Jupyter kernel interrupt) sets a flag instead of raising, so training stops between
    steps rather than inside an in-place Adam update. Off the main thread Python can't catch signals: no flag."""
    if threading.current_thread() is not threading.main_thread():
        yield lambda: False
        return
    hits: list[int] = []
    previous = signal.signal(signal.SIGINT, lambda signum, _frame: hits.append(signum))
    try:
        yield lambda: len(hits) > 0
    finally:
        signal.signal(signal.SIGINT, previous)


def train(config: Config, emit: Callable[[dict], None], clock: Callable[[], float]) -> StopReason:
    """Full-batch Adam from config.start until a budget runs out or an interrupt; emits ticks, then "end"."""
    start = config.start
    net = Params([w.clone().requires_grad_() for w in start.net.w], [b.clone().requires_grad_() for b in start.net.b])
    m = Params([w.clone() for w in start.m.w], [b.clone() for b in start.m.b])
    v = Params([w.clone() for w in start.v.w], [b.clone() for b in start.v.b])
    t, step = start.t, start.step
    began = clock()
    last_tick = began
    emit(tick(config, net, step, start.seconds))
    reason: StopReason
    with interrupt_flag() as interrupted:
        while True:
            seconds = start.seconds + clock() - began
            if interrupted():
                reason = "interrupted"
                break
            if step >= config.stop.max_steps:
                reason = "steps"
                break
            if seconds >= config.stop.max_seconds:
                reason = "time"
                break
            mean_loss(config.task, forward(net, config.activation, config.train.x), config.train.y).backward()
            t += 1
            adam_step(net, m, v, t, config.lr)
            step += 1
            if clock() - last_tick >= config.tick_seconds:
                last_tick = clock()
                emit(tick(config, net, step, start.seconds + last_tick - began))
    seconds = start.seconds + clock() - began
    emit(tick(config, net, step, seconds))
    emit({"kind": "end", "reason": reason, "step": step, "seconds": seconds, "state": state(net, m, v, t)})
    return reason


def pick_device() -> torch.device:
    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


def describe(device: torch.device, dtype: str) -> dict:
    name = torch.cuda.get_device_name(device) if device.type == "cuda" else "cpu"
    return {"kind": "start", "device": device.type, "device_name": name, "torch": torch.__version__, "dtype": dtype}


def print_line(obj: dict) -> None:
    print(json.dumps(obj, allow_nan=False, separators=(",", ":")), flush=True)


def run(config_json: str) -> StopReason:
    """The kernel entry point: parse, say where it runs, train, printing JSON lines."""
    raw = json.loads(config_json)
    device = pick_device()
    config = parse_config(raw, device)
    print_line(describe(device, raw["dtype"]))
    return train(config, print_line, time.monotonic)


def main() -> None:
    if len(sys.argv) > 2:
        sys.exit("usage: remote_train.py [config.json]   (or the config on stdin)")
    run(Path(sys.argv[1]).read_text() if len(sys.argv) == 2 else sys.stdin.read())


if __name__ == "__main__":
    main()
