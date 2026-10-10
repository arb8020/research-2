# engine chapter 1: handoff (2026-10-09, session 2)

Start here next session. Decisions of record: `blogs/notes/ch01-design-2026-10-09.md`. Everything below is on
branch `engine/ch01` (worktree `worktrees/engine-ch01`), not merged to `blogs/engine` or `main`.

## state

The chapter 1 page works end to end: locally against `connect_dev.py`, and live on a Modal T4 through the box relay
pinned at `box/lease@42c05b12` (`--image blogs/engine/kernel.Dockerfile --volume /ws=blogs-ws`).

- `blogs/engine/ch01-forward.md`: 7 region cells over one `gpt2.py` (linear, gelu, layer_norm, attention, block,
  forward, generate). Prose is placeholder (wip banner). Cells run in any order; stubs raise NotImplementedError
  pointing at their cell. Per-cell read-only reference toggle (no copy; closes on edit). Shift/Cmd-Enter runs a
  cell; Tab opens completion; long lines wrap.
- `gpt2.py` (ref/ch01/{files,start}): scaling-book letters (TDNH), shape suffixes, einops einsum/reduce, 80 cols,
  given `load()` with named weight layouts.
- `blogs/assay`: the check core (our smevals: core.py + cli.py; ch00.py; ch01/{ops,run,suite}.py). Warm fork
  server; child runs as `nobody` when root; trusted code uploaded to `_blogs/` and sha256-verified per check.
- Correctness for ch01 is SIMPLE: per-op allclose vs fp64 truth (one atol/rtol per dtype, `TOL` in
  assay/ch01/suite.py), inputs offset from zero; model level fp32 per-position KL < 1e-7 + top-k smoke. bf16 is a
  visible SKIP on T4.
- `blogs/engine/correctness.md`: Claude-written stub explainer (wip banner, `<!-- claude: -->` comments). The
  author rewrites it.
- `blogs/workspace.py` (was ws.py), oxlint replaced ESLint in blogs/web (+4 vendored anti-slop guards, `cause`).

Proof at the end of the session: `ref.py verify ch00` / `verify ch01` pass, assay pytest 27 passed. Modal story
(edit before connect, pass, planted exact-GELU fail, reference regions pass, reload, restore from Volume) passed on a
T4: evidence in `blogs/.evidence/modal-ch01/` (gitignored, local only).

## run it

```text
# local (from worktrees/engine-ch01/blogs)
uv run build_page.py engine/ch01-forward.md --gateway-url http://127.0.0.1:8795
uv run --project assay python connect_dev.py --port 8795 --root /tmp/ch01-root --persist /tmp/ch01-persist
python3 -m http.server 8015 -d dist --bind 127.0.0.1   # /ch01-forward/?gateway=http://127.0.0.1:8795, token ak-...

# checks without a page
uv run ref.py verify ch01
cd engine/ref/ch01/files && PYTHONPATH=../../../../assay ../../../../assay/.venv/bin/python -P -m assay.cli ch01 --op attention

# Modal (real relay, your token from ~/.modal.toml)
git archive 42c05b12 box pyproject.toml observe | tar -x -C /tmp/box-42c05b12   # from the repo root
cd /tmp/box-42c05b12/box && uv sync --extra dev
uv run python -m box.gateway.relay --port 8791 --image <abs>/blogs/engine/kernel.Dockerfile --volume /ws=blogs-ws
uv run --with playwright verify_modal_ch01.py --relay http://localhost:8791   # from blogs/
```

Timings (T4): cold image build ~2.6 min (once per reader workspace and image change), warm connect ~10 s, first
check of a cell 12–20 s (fp64 truth on T4 + warm process start), re-runs ~2 s.

## deferred (with evidence)

- Principled tolerances for the kernel chapters: BLAS-style ratio for contractions, Monte Carlo arithmetic + a
  TRT-LLM-style hypothesis test for composite ops, TOML graders. Prototype (CPU, T4, L4; liger/fla/SDPA held out):
  `blogs/notes/evidence/tolerance-2026-10-09/` (README.md, gpu/README_gpu.md). Findings: holds on GPU; MCA σ is
  device-independent (compute on CPU, cache); "fp32 internal math" is too strict for fused attention (P is rounded);
  split-K reduced-precision reduction can't be graded, only pinned by setting the flag.
- Before moving the relay pin past 42c05b12: accept `status.started_at = null` in blogs/web/connect/gateway.ts.
  Don't upgrade the relay while readers have live sessions (newer relays find Jupyter by name).
- Rest of `blogs/lease` (length picker, Extend, fake-relay lease tests): the box team merges it; it must also fix
  `connect_dev --attach-kernel`, which still uses the old deadline.
- Dotfiles lint proposal (oxlint base + anti-slop): `/private/tmp/dotfiles-lint-proposal-2026-10-09/lint/` (tmp:
  re-generate from blogs/web/.oxlintrc.json + oxlint.base.json + lint/anti-slop if it's gone).
- Schema library for boundary parsing (anti-slop's no-runtime-typeof direction): separate decision.

## open / check next session

- Possible trust gap: on the T4 run, checks deleted a `_blogs/tree/__pycache__` someone wrote. If `_blogs/tree` is
  writable by `nobody` (umask), the child could plant bytecode. Find the writer; make `_blogs` root-owned 0755.
- Block check drops layer 11 (HF's own fp32 block 11 misses the fp32 atol); forward's KL covers it.
- Exact-GELU margin under allclose is thin (3.07x on CPU, 1.43x on T4 rows).
- First checks in a fresh sandbox are slow (Volume-backed store reads).
- Cell header crowded at narrow widths.
- The user still owes: chapter 1 prose, the correctness page rewrite, Colab smoke run (`box/tests/smoke_colab`), the
  flappy focus check, and which of the ~25 unrelated worktrees can go.
- Merge `engine/ch01` into `blogs/engine` once reverified.
