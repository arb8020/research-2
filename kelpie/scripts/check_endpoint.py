#!/usr/bin/env python3
"""The endpoint check: does the served model get a downstream TASK right? One line per row.

    python scripts/check_endpoint.py                  # every row
    python scripts/check_endpoint.py qwen3_gsm8k       # only rows whose name matches

`scripts/check_serve.py` proves the endpoint answers the way it did (golden strings, batched ==
solo). It cannot see "right shape, subtly wrong math" -- an fp8 KV cache, a lossy kernel, a bad
sampler. This file runs a real downstream task against a served model and gates the score with
the TensorRT-LLM hypothesis test. The pair is (reference score, candidate = our served
endpoint). Model behavior, not tokens.

A ROW is data:

    Row(name, model, device, engine, task, reference, gate)

`model`, `device`, `engine` are as in check_serve (`kelpie_models.models.torch.qwen3`, `"cuda"`,
`{kv_blocks: ...}`). `task` is a `Task(command, score)`: the client command run through
`run_with_probe` (kelpie_models.bench.probe.run), with `{PROBE_PORT}` substituted for the
recording proxy's port, plus a function that reads the score out of whatever the command left
on disk. `reference` is a float, or `NO_REFERENCE` (run, print the score, pass -- bootstraps a
row, mirrors trtllm's `TRTLLM_ACCURACY_NO_REFERENCE`). `gate` is a `Gate`: the hypothesis-test
parameters other than the reference mean itself, which the runner folds in at check time
(`kelpie_models.bench.probe.check.HypothesisSpec(reference_mean=row.reference, **asdict(gate))`).

HOW IT RUNS: one subprocess per row running `kelpie serve` (the kelpie-http CLI) for real, over
a real TCP port -- not `httpx.ASGITransport` like check_serve, because the task's client command
(harbor's containerized agent, or lm-eval as a separate process) needs an actual socket to
connect to, possibly from outside this machine. The runner waits for `/v1/models` to answer,
then runs `task.command` under `run_with_probe`, which fronts the server with a recording
reverse proxy and returns the trace path + return code. `task.score(out_dir)` reads the number
back off whatever the command wrote to `--out DIR`; `check(spec, [score])` gates it. Traces and
the score file survive under `--out DIR` (default `./check_endpoint_out/<row>/`) -- cleanup
kills the server, never deletes evidence.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import socket
import subprocess
import sys
import time
import traceback
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

NO_REFERENCE = "no-reference"  # bootstrap sentinel: run, print the score, pass


@dataclass(frozen=True)
class Task:
    """One downstream job: the client command (through `run_with_probe`, `{PROBE_PORT}`
    substituted for the recording proxy) and how to read a score off what it left on disk."""

    command: tuple[str, ...]
    score: Callable[[Path], float]
    describe: str = ""  # human-readable note on how the command targets the endpoint


@dataclass(frozen=True)
class Gate:
    """The TensorRT-LLM hypothesis-test parameters other than the reference mean, which lives
    on the Row instead (`kelpie_models.bench.probe.check.HypothesisSpec` bundles the two, but a
    Row's reference is sometimes `NO_REFERENCE` -- unknown until the row's first run)."""

    sigma: float
    sample_count: int
    alpha: float = 0.05
    beta: float = 0.2
    higher_is_better: bool = True


@dataclass(frozen=True)
class Row:
    """One check: this model, on this device, scored on this task against this reference."""

    name: str
    model: str  # dotted module path, as in check_serve
    device: str
    engine: dict[str, Any]
    task: Task
    reference: float | str  # a float, or NO_REFERENCE
    gate: Gate


def gsm8k_lmeval_command(
    limit: int, tokenizer: str, num_fewshot: int = 5
) -> tuple[str, ...]:
    """`lm-eval run` against the endpoint's `/v1/completions`, base_url pointed at the probe.

    `model=` is the name the request body carries (the server ignores it: one model per
    process); `tokenizer=` is a real HF id so lm-eval's huggingface tokenizer backend can
    count/encode tokens locally -- the two are unrelated to `local-completions` and must not
    be the same string. `tokenized_requests=False` sends the prompt as a plain string:
    kelpie_http.sdk.chat's /v1/completions rejects a tokenized (int-list) prompt with 400
    "prompt must be a string or a single-element list of strings". `num_fewshot` defaults to
    the task's own 5-shot, but gpt2's max_seq_len (1024, HF n_positions) is too small for a
    5-shot gsm8k prompt plus 256 generated tokens -- 400 "TooLong"; the smoke row overrides it
    to 0."""
    return (
        "uv",
        "run",
        "--project",
        "kelpie-http",
        "--extra",
        "eval",
        "lm_eval",
        "run",
        "--model",
        "local-completions",
        "--model_args",
        (
            f"base_url=http://127.0.0.1:{{PROBE_PORT}}/v1/completions,"
            f"model=endpoint,tokenizer={tokenizer},num_concurrent=8,max_retries=3,"
            f"tokenized_requests=False"
        ),
        "--tasks",
        "gsm8k",
        "--num_fewshot",
        str(num_fewshot),
        "--limit",
        str(limit),
        "--output_path",
        "{OUT_DIR}/lm_eval",
    )


def gsm8k_score(out_dir: Path) -> float:
    """`exact_match,flexible-extract` for the gsm8k task out of lm-eval's `--output_path`
    results json -- gsm8k's own metric_list runs both a `strict-match` regex (the literal
    "#### N" line) and a `flexible-extract` filter (the last number anywhere in the
    completion); flexible-extract is what upstream leaderboards report and what a base model
    without the exact prompt-trained format needs to score above zero."""
    results_dir = out_dir / "lm_eval"
    candidates = sorted(results_dir.glob("**/results_*.json"))
    assert candidates, f"no lm-eval results_*.json under {results_dir}"
    with open(candidates[-1]) as handle:
        payload = json.load(handle)
    metrics = payload["results"]["gsm8k"]
    return float(metrics["exact_match,flexible-extract"])


GSM8K_DESCRIBE = (
    "lm-eval's local-completions model hits {PROBE_PORT} (the recording proxy in front of "
    "the real server) directly over base_url=; no container, no extra network reachability "
    "needed beyond localhost"
)


def gsm8k_lmeval(limit: int, tokenizer: str, num_fewshot: int = 5) -> Task:
    """A gsm8k `Task` for a model whose real HF checkpoint is `tokenizer` (lm-eval needs it to
    tokenize locally; the server itself is asked for by `model=endpoint`, not by this id)."""
    return Task(
        command=gsm8k_lmeval_command(
            limit=limit, tokenizer=tokenizer, num_fewshot=num_fewshot
        ),
        score=gsm8k_score,
        describe=GSM8K_DESCRIBE,
    )


def gpqa_harbor_command() -> tuple[str, ...]:
    """`harbor run` against gpqa-diamond, agent pointed at the endpoint over an OpenAI-shaped
    base URL. See GPQA_HARBOR.describe for how the agent's container reaches the probe."""
    return (
        "harbor",
        "run",
        "--path",
        str(Path.home() / ".cache/harbor/datasets/gpqa-diamond"),
        "--agent",
        "claude-code",
        "--model",
        "openai/qwen3",
        "--ae",
        "OPENAI_BASE_URL=http://{PROBE_HOST}:{PROBE_PORT}/v1",
        "--ae",
        "OPENAI_API_KEY=unused",
        "--allow-agent-host",
        "{PROBE_HOST}",
        "--jobs-dir",
        "{OUT_DIR}/harbor",
        "--disable-verification",  # placeholder until the row is exercised; see brief
        "--yes",
    )


def gpqa_score(out_dir: Path) -> float:
    raise NotImplementedError(
        "GPQA_HARBOR is not exercised yet; see docs/brief-check-endpoint.md"
    )


GPQA_HARBOR = Task(
    command=gpqa_harbor_command(),
    score=gpqa_score,
    describe=(
        "harbor's docker environment sandboxes the agent phase; OPENAI_BASE_URL/OPENAI_API_KEY "
        "reach the agent via --ae (harbor/agents/model_connection.py resolves them for any "
        "openai/<model> name), and --allow-agent-host opens egress from the container to the "
        "box running `kelpie serve` (harbor/environments/capabilities.py: network_allowlist). "
        "{PROBE_HOST} must be the box's routable IP, not 127.0.0.1 -- the proxy binds "
        "127.0.0.1 today, which a container cannot reach; not fixed here (see report)."
    ),
)


ROWS: tuple[Row, ...] = (
    Row(
        name="gpt2_smoke",
        model="kelpie_models.models.torch.gpt2",
        device="cpu",
        # gsm8k's few-shot prompt is long; check_serve's kv_blocks=64 is sized for a single
        # short Ask and 400s "TooLong" here.
        engine={"kv_blocks": 1024, "max_batch_tokens": 4096},
        task=gsm8k_lmeval(limit=20, tokenizer="openai-community/gpt2", num_fewshot=0),
        reference=NO_REFERENCE,  # gpt2 is not going to solve grade-school math; proves plumbing
        gate=Gate(sigma=50, sample_count=20),
    ),
    Row(
        name="qwen3_gsm8k",
        model="kelpie_models.models.torch.qwen3",
        device="cuda",
        # 5-shot gsm8k prompts run long (~1-2k tokens) and lm-eval sends num_concurrent=8 at
        # once; max_batch_tokens=4096 crashed the Zig step loop mid-run ("launch failed:
        # status=1 step=2 shape=4107 n_reqs=1" -- a single request's tokens already exceeded
        # it, past whatever check should have 400'd it cleanly instead). 8192 is the ceiling:
        # buckets.zig's BUCKETS ladder tops out there and kelpie_create asserts
        # max_batch_tokens <= 8192 (16384 panics at startup, "reached unreachable code" in
        # buckets.bucket). See the report.
        engine={"kv_blocks": 8192, "max_batch_tokens": 8192},
        task=gsm8k_lmeval(limit=200, tokenizer="Qwen/Qwen3-0.6B"),
        reference=NO_REFERENCE,  # first run bootstraps the row; copy the score in as reference
        gate=Gate(sigma=50, sample_count=200),
    ),
)


# ---- the runner ------------------------------------------------------------------------------


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("names", nargs="*")
    parser.add_argument("--out", default=os.path.join(ROOT, "check_endpoint_out"))
    args = parser.parse_args(argv[1:])
    wanted = set(args.names)
    rows = [r for r in ROWS if not wanted or r.name in wanted]
    if wanted and not rows:
        print(f"no row named {sorted(wanted)}; rows: {[r.name for r in ROWS]}")
        return 2
    worst = 0
    for row in rows:
        out_dir = Path(args.out) / row.name
        out_dir.mkdir(parents=True, exist_ok=True)
        started = time.monotonic()
        try:
            ok, detail = run_row(row, out_dir)
        except Exception:  # noqa: BLE001 -- a crashed row is a FAILED row, with its traceback
            traceback.print_exc()
            ok, detail = False, "raised"
        took = time.monotonic() - started
        print(f"{'OK  ' if ok else 'FAIL'} {row.name:16s} {took:6.1f}s  {detail}")
        worst = worst or (0 if ok else 1)
    return worst


def run_row(row: Row, out_dir: Path) -> tuple[bool, str]:
    port = free_port()
    server = start_server(row, port, out_dir / "server.log")
    try:
        try:
            wait_for_models(port, timeout_s=1200.0 if row.device != "cpu" else 180.0)
        except TimeoutError as exc:
            return False, f"{exc}; server.log tail: {log_tail(server.log_path)}"
        trace_path = out_dir / "trace.jsonl"
        result = run_task(row, port, out_dir, trace_path)
        if result["returncode"] != 0:
            tail = (result["stderr"] or result["stdout"]).strip().splitlines()[-5:]
            return False, f"task command rc={result['returncode']}: {' / '.join(tail)}"
        score = row.task.score(out_dir)
        report = performance_summary(trace_path)
        return gate(row, score, report)
    finally:
        stop_server(server)


def log_tail(path: Path, lines: int = 15) -> str:
    if not path.exists():
        return "(no server.log)"
    content = path.read_text(errors="replace").strip().splitlines()
    return " / ".join(content[-lines:])


def run_task(row: Row, port: int, out_dir: Path, trace_path: Path) -> dict[str, Any]:
    """`row.task.command` through `run_with_probe`, run in a fresh interpreter (trio.run cannot
    nest inside whatever loop is driving this one -- there is none here, but the probe's own
    subprocess needs its own asyncio-free trio run, so this goes through a one-shot script)."""
    import trio
    from kelpie_models.bench.probe.run import run_with_probe

    command = [
        arg.replace("{OUT_DIR}", str(out_dir)).replace("{PROBE_HOST}", "127.0.0.1")
        for arg in row.task.command
    ]

    async def go() -> dict[str, Any]:
        return await run_with_probe(
            target_url=f"http://127.0.0.1:{port}",
            command=command,
            trace_path=trace_path,
        )

    return trio.run(go)


def performance_summary(trace_path: Path) -> dict[str, Any]:
    from kelpie_models.bench.probe.metrics import load_traces, performance_report

    if not trace_path.exists():
        return {}
    return performance_report(load_traces(trace_path))


def gate(row: Row, score: float, report: dict[str, Any]) -> tuple[bool, str]:
    perf = summarize_perf(report)
    if row.reference == NO_REFERENCE:
        return True, f"score={score:.4f} (no reference; copy into the row){perf}"
    from kelpie_models.bench.probe.check import HypothesisSpec
    from kelpie_models.bench.probe.check import check as check_fn

    spec = HypothesisSpec(reference_mean=float(row.reference), **asdict(row.gate))
    result = check_fn(spec, [score])
    detail = (
        f"score={result.observed_mean:.4f} threshold={result.threshold:.4f} "
        f"ref={spec.reference_mean:.4f} n={spec.sample_count}{perf}"
    )
    return result.passed, detail


def summarize_perf(report: dict[str, Any]) -> str:
    if not report:
        return ""
    e2e = report.get("e2e_ms") or {}
    otps = report.get("output_tokens_per_second")
    return f"  e2e_p50={e2e.get('p50')}ms otps={otps}"


# ---- serving ------------------------------------------------------------------------------


@dataclass(frozen=True)
class Server:
    process: subprocess.Popen
    port: int
    log_path: Path
    log_file: Any  # the open handle `process.stdout` writes into; closed in stop_server


def start_server(row: Row, port: int, log_path: Path) -> Server:
    """`kelpie serve` for real, on `port`, in its own process (ops.bind runs once per process,
    same constraint as check_serve). stdout+stderr go to `log_path` (survives under --out DIR,
    same as a trace) so a startup failure -- a crash, a hang loading the checkpoint -- is
    diagnosable instead of a bare "connection refused". `--kernel` overrides in `row.engine`
    are not supported here; `row.engine` maps 1:1 onto `kelpie serve`'s flags below."""
    argv = [
        "uv",
        "run",
        "--project",
        "kelpie-http",
        "kelpie",
        "--model",
        row.model,
        "--device",
        row.device,
        "--port",
        str(port),
        # serve's --capture defaults to None -> capture=True on cuda (sdk/run.py: `capture if
        # capture is not None else device.startswith("cuda")`), which imports
        # kelpie_models.sdk.captured.Captured -- a module that does not exist in this tree
        # (ModuleNotFoundError at startup, not exercised by check_serve.py since every one of
        # its rows is device="cpu"). --no-capture until that module lands; see the report.
        "--no-capture",
    ]
    for flag, key in (
        ("--kv-blocks", "kv_blocks"),
        ("--max-batch-tokens", "max_batch_tokens"),
        ("--max-requests", "max_requests"),
    ):
        if key in row.engine:
            argv += [flag, str(row.engine[key])]
    log_file = open(log_path, "w")  # noqa: SIM115 -- closed in stop_server, lifetime is Server's
    process = subprocess.Popen(
        argv,
        cwd=ROOT,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        text=True,
        start_new_session=True,  # so stop_server can kill the whole process group
    )
    return Server(process=process, port=port, log_path=log_path, log_file=log_file)


def stop_server(server: Server) -> None:
    if server.process.poll() is None:
        os.killpg(os.getpgid(server.process.pid), signal.SIGTERM)
        try:
            server.process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            os.killpg(os.getpgid(server.process.pid), signal.SIGKILL)
            server.process.wait(timeout=15)
    server.log_file.close()


def wait_for_models(port: int, timeout_s: float) -> None:
    url = f"http://127.0.0.1:{port}/v1/models"
    deadline = time.monotonic() + timeout_s
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2.0) as resp:
                if resp.status == 200:
                    return
        except (urllib.error.URLError, ConnectionError, TimeoutError) as exc:
            last_error = exc
        time.sleep(1.0)
    raise TimeoutError(f"{url} did not answer within {timeout_s}s: {last_error}")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


if __name__ == "__main__":
    sys.exit(main(sys.argv))
