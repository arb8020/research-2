# Handoff — observe dashboard (2026-09-17)

Branch `dashboard` in `worktrees/dashboard`, 3 commits ahead of `main`, not merged.
Contract and decisions: `observe/DESIGN.md`. Queued work: its **Next** section + `grep -rn "TODO(rollouts)"`.

## What exists

- **Python is a producer only.** `observe.{log via stdlib, span, metric, metrics, artifact}` →
  `runs/<name>.jsonl`, one line per event, `kind ∈ {log, span, metric, artifact}` explicit.
  `robots/train.py` emits all four; no server, no `--watch`.
- **TS dashboard** (`observe/dashboard`, Vite + React + TS strict, Bun):
  - `server/` — `bun run serve`: static `dist/`, `/runs` index, Range tail, `/query` = DuckDB
    over `runs/*.jsonl` (read-only, file access disabled, row cap, real timeout).
  - `core/` — tailer, parse-don't-validate `Event` sum type, `Panel = query + Vega-Lite spec`,
    shape check before render, discovered views (`views/*/view.ts`, `mount/append`).
  - `views/panels` — one Vega-Lite panel per metric, hover crosshair + tooltip, live refresh.
  - `views/rollout` — CartPole renderer over `application/x-trajectory+json` artifacts.
  - `app/` — paper skin (obol tokens), named themes, logs drawer (`l`), toasts.
- **Cross-language pin:** `src/core/__fixtures__/golden.jsonl`. Python regenerates it
  byte-stable (`test_golden.py`); TS parses it error-free (`golden.test.ts`). Any on-disk
  change must touch it.
- **Lint:** `ruff.toml` + `eslint.base.js` are copies of `~/dotfiles/lint/`;
  `~/dotfiles/lint/sync.sh <repo>` reports drift. No test exemptions. Import zones are
  lint-enforced (`core` ↛ `app`/`views`; `server` ↛ `app`/`views`).

## Run it

```
cd observe/dashboard && bun install && bun run build
bun run serve                                   # http://localhost:8384  (serves ../../runs)
PYTHONPATH=. robots/.venv/bin/python -m robots.train --name x --iters 200   # appears in the picker
observe/scripts/demo.sh runs/rollout-demo.jsonl # replay a finished run live
```

Gates (all green at `3c509cc`): `python3 -m pytest observe/tests`, `cd robots && uv run pytest`,
`uvx ruff check observe robots && uvx ruff format --check observe robots`,
`cd observe/dashboard && bun run typecheck && bun run lint && bun run test && bun run build`.

## Lessons this session (the expensive ones)

- **Unit tests cannot see a gray page.** Two real bugs (single-threaded server starving
  keep-alive; theme flip leaving panels empty) passed every unit test. `agent-browser`
  (`open`, `errors`, `eval`, `screenshot <selector> <abs-path> --full`) after every build is
  the cheapest gate; a Playwright smoke test against `dist/` + real server is the
  committed version (not yet written — Next #7-ish).
- **Each language's tests pinned its own half of the contract** and they disagreed
  (`span_name`). The golden fixture is the fix; keep it.
- **DuckDB:** `interrupt()` is connection-wide, `enable_external_access` is instance-wide —
  hence one instance per request (~20ms). Linear in store size; see Next #6.
- `agent-browser` papercuts: `press Escape` navigates away; bare screenshot filename is a
  selector; `document.body` in eval object literals misbehaves (use IIFE + querySelector).

## Next (in order)

1. Grid: `derivePanels(events)` into core, App owns the grid, cell = slot, `react-grid-layout`.
5. Verification script: `verify-dashboard` — scripted feature proofs via agent-browser
   (poteto-mode verification skill, not ad-hoc screenshots). Feature map: run picker,
   metric panels, log drawer, rollout playback, step picker.
2. Click a point on `eval_reward` → rollout view shows that step's episode; eval vs train
   episodes by artifact name (`TODO(rollouts)` ×3).
3. Spans view (lanes by `span_name`).
4. On-demand artifacts via trainer inbox; file-backed artifacts; store evolution.
