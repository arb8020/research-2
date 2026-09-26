# Review: bench/check-endpoint (sonnet review, checked by fable) — 2026-09-10

Branch: `bench/check-endpoint`, 4 commits off `4c776f0`, worktree `worktrees/check-endpoint`. Unmerged.
Green: `gpt2_smoke` CPU row end to end. `qwen3_gsm8k` blocked by engine bugs (handoff).

## Verified clean
- Probe files diffed against crucible: only the header line and one import path differ.
- `check(spec, [score])` call matches the copied `HypothesisSpec` (reference folded from `Gate`).
- Server lifecycle: `try/finally` -> SIGTERM process group, 15s, SIGKILL; evidence dir never deleted.
- `{PROBE_PORT}` substitution is inside `run_with_probe`; pre-substituting `{OUT_DIR}`/`{PROBE_HOST}` is right.

## Needs the user's decision
1. **Where `bench/probe` lives.** Brief said `kelpie-models/bench/probe/`; that pulls trio/hypercorn/httpx/
   starlette into kelpie-models (`pyproject.toml:12-15`) for a reverse proxy that has nothing to do with
   forwards. kelpie-http already has those deps. Move to `kelpie_http/bench/`? (`bench/correctness.py`
   from kernels-build stays in kelpie-models — it is torch-only.)
2. **`mimir audit` is red on the copied probe bodies** (ruff format, UP035, complexity). Exempt
   `bench/probe/` from the gate, or edit crucible's code and drop "verbatim".
3. **`NO_REFERENCE` prints OK at score 0.0.** By design for bootstrap, but the first qwen3 run must be
   read by a person; nothing flags "suspiciously low". Add a `floor` to `Gate` (OK only if score >= floor
   even with no reference)?

## Fix at merge
- `check_endpoint.py:150` `gsm8k_score` takes `sorted(candidates)[-1]` over `lm_eval/**/results_*.json`;
  a stale evidence dir can win. Read the results path lm-eval reports for this run, or clear the row's
  `lm_eval/` subdir before the run (evidence = traces + results of this run, not older runs).
- Four bare `dict[str, Any]` in the new script without site comments (rule 20); `otps`/`e2e` undefined
  abbreviations in the OK line (rule 17).
- `--no-capture` block and the `max_batch_tokens` comment narrate engine bugs (rule 21): one-line pointer
  to the handoff, delete when the bugs are fixed.
- `GPQA_HARBOR` binds the proxy on 127.0.0.1; a container cannot reach it. Bind on the host IP when the
  row is exercised (not 0.0.0.0 silently).

## CUDA (B200) before merge (after qwen3 rms_norm fix + Captured restored)
    kelpie doctor
    python scripts/check_endpoint.py qwen3_gsm8k --out check_endpoint_out   # bootstrap; copy score into the row
    python scripts/check_endpoint.py qwen3_gsm8k --out check_endpoint_out   # must pass the gate
    python scripts/check_endpoint.py gpt2_smoke
    scripts/test
