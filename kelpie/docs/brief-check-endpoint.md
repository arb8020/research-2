# Brief: `scripts/check_endpoint.py` — model-behavior correctness at the endpoint

Date: 2026-09-10. Executor: sonnet, worktree `worktrees/check-endpoint`, branch `bench/check-endpoint`, off main `4c776f0`. "You are a subagent. Don't run memo." STOP and report on any ambiguity; do not pick the simpler option silently.

## What this is

`scripts/check_serve.py` proves the endpoint answers the way it did (golden strings, batched == solo). It cannot see "right shape, subtly wrong math" — an fp8 KV cache, a lossy kernel, a bad sampler. This check does: run a real downstream task against a served model and gate the score with the TensorRT-LLM hypothesis test. The pair is (reference score, candidate = our served endpoint). Model behavior, not tokens.

## Copy, don't depend

Copy these files from crucible's `crucible/verification/engines/probe/` into `kelpie-models/kelpie_models/bench/probe/` verbatim, one header line each: `# copied from crucible/verification/engines/probe/<file>.py @ <crucible sha>`. Fix imports to the new package; no other edits.

- `proxy.py` (recording reverse proxy, per-request JSONL: ttft/e2e/usage/cache tokens)
- `run.py` (`run_with_probe(target_url, command, trace_path)`: proxy up, run a client command with `{PROBE_PORT}` substituted, return trace + rc)
- `metrics.py` (`performance_report(traces)`)
- `check.py` (`check(HypothesisSpec, scores) -> CheckResult`: the trtllm one-tailed test, `threshold = ref + Φ⁻¹(α)·√(2σ²/n)`, Bonferroni helper)

Skip `diff.py`. Deps already in the tree: trio, hypercorn, httpx, starlette. `bench/__init__.py` may be empty; another branch adds `bench/correctness.py` beside it — do not touch that name.

## The script

`scripts/check_endpoint.py`, same shape and docstring style as `scripts/check_serve.py` (read it first; copy its `main`/row-filter/OK-FAIL line format). A ROW is data:

    Row(name, model, device, engine, task, reference, spec)

- `model`, `device`, `engine`: as in check_serve (`kelpie_models.models.torch.qwen3`, `"cuda"`, `{kv_blocks: ...}`).
- `task`: a `Task(command: tuple[str,...], score: Callable[[Path], float])` — the client command run through `run_with_probe` with `{PROBE_PORT}` in it, plus a function that reads the score out of what the command left on disk (a results json). Tasks are values in the file: `GSM8K_LMEVAL`, `GPQA_HARBOR`, later `KVV_TOOL_SCHEMA`.
- `reference`: a float, or `NO_REFERENCE` (run, print the score, pass; used to bootstrap a row — trtllm's `TRTLLM_ACCURACY_NO_REFERENCE`).
- `spec`: `HypothesisSpec(alpha=0.05, beta=0.2, sigma=50, n=...)` from the copied check.py; n is the task's sample count.

Runner: one subprocess per row running `kelpie serve` (via `kelpie_http.sdk.serve` or the CLI — whichever check_serve's engine path makes shortest; report which), wait for `/v1/models` to answer, `run_with_probe` around `task.command`, `task.score(trace_dir)`, `check(spec, [score])`, kill what you started, print `OK/FAIL name  score=.. threshold=.. ref=.. n=..`. Traces and the score file survive under `--out DIR` (default `./check_endpoint_out/<row>/`); cleanup never deletes evidence.

## Score sources, in order

1. **harbor** (preferred; `harbor` is on PATH, `~/.cache/harbor/datasets/gpqa-diamond` exists). Find how `harbor run` points its agent at a custom OpenAI base URL + model name (env vars or `-m`/agent config). If harbor cannot target a plain OpenAI endpoint without a container reaching the host, STOP and report what it needs; do not build a workaround.
2. **lm-eval** (`lm_eval --model local-completions --model_args base_url=http://127.0.0.1:{PROBE_PORT}/v1/completions,model=...` , task `gsm8k`, `--limit N`, `--output_path`). Add as an optional dependency group `kelpie-http[eval]`.
Get ONE of them green end to end first, then the other.

## First green row

Qwen3-0.6B on a B200 (`kelpie doctor` first). Row `qwen3_gsm8k` with `reference=NO_REFERENCE`, n=200 (`--limit 200`), then a second run with the number copied in as `reference` must pass. Report the score, the threshold, the wall time, and the probe `performance_report` summary. A gpt2 CPU row is fine as a smoke (score will be ~0; it proves plumbing, and `NO_REFERENCE` makes it pass).

## Not in scope

No lm-eval task definitions of our own. No HF-oracle greedy/logprob compare (that is a check_serve row). No perf gate. No pytest.

Commit per step, trailer `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`. `mimir breadcrumb -a check-endpoint "<msg>"` at each step and judgement call; `mimir papercut` for frictions. Report: the Row/Task definitions verbatim, the first green line verbatim, how harbor is pointed at the endpoint (or why it cannot be), judgement calls, uncertainties, papercuts.
