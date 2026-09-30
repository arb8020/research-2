---
name: verify-kelpie
description: Verify a kelpie change. Use before claiming kelpie work passes; runs `kelpie doctor`, then names the proof commands for the area touched.
---

# verify-kelpie

A thin pointer: it shrinks as `kelpie check`, `kelpie bench` and `kelpie remote` land and take
these commands over. Read each script's docstring before running it. `box` below is
`uv run --frozen --project box box` from the repo root (box/cli.py).

0. Fresh worktree: `box setup --local` (xgrammar shim from the shared cache, libkelpie,
   `uv sync --frozen`; it never rewrites a uv.lock).
1. `box doctor` (= `uv run --frozen kelpie doctor` in `kelpie/kelpie-http`). Fix every FAIL
   before trusting any result below: a stale libkelpie has passed a check falsely before.
   Add `--device cuda:A100` for the arch you target, `--remote --model <hf id>` before Modal.
2. The proofs, from `kelpie/`. Laptop (CPU):
   - `cd kelpie-engine && PYTHONPATH=../.. uv run --frozen python ../scripts/check_core_loop.py`
     (add `--native --replay --seeds 4` for the Zig loop)
   - `python scripts/check_serve.py [row ...]` (CPU rows)
   GPU, through `box run` below (each docstring has its exact command):
   - `python -m scripts.smoke_run_k0 [model]`
   - `python scripts/prove_dflash.py --device cuda`
   - `python -m scripts.check_spec_teacher_forced`, `python -m scripts.prove_state_lifecycle`
   - `python -m scripts.bench_moe`, `python -m scripts.prove_moe`
3. Modal (from the repo root; `--volume kelpie-a1`, pick `--gpu`):

       box run --gpu A100-80GB --volume kelpie-a1 --timeout 2400 -- 'python -m scripts.<proof> ...'

   Long run, or one that must outlive this turn: add `--detach` (prints the sandbox id), then
   `box logs <id> -f`. `box who` lists running runs; `box kill <id>` stops one you started.
   No tmux. `kelpie/scripts/modal_run.py` still works but is deprecated.
