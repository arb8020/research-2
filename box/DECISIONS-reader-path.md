# Reader path: decisions (interview, 2026-10-09 night)

Source of truth for every agent working overnight. Read with `box/NOTES-sessions.md` ("Next session: the reader path")
and `worktrees/blogs-connect/blogs/HANDOFF.md`. Coding standards: `~/dotfiles/docs/synthesis/CODING_STANDARDS.md`.

## Goal (morning demo)
Open the nn-fit page (`dl/neural-nets.md`) -> header **Connect** (top right) -> paste Modal token -> pick GPU (T4) ->
connect, with boot logs in a slide-in drawer -> run an `nvidia-smi` cell on the GPU -> run `<nn-fit>` with backend
**remote** (same model/data, trained in torch on the GPU, loss curve streams into the same plot).
Proof: Playwright script + video (.webm -> .mp4) + artifact report. Demo served from `worktrees/blogs-connect`.

## Decided
1. Build directly; write design down as we go; author reviews design + code in the morning.
2. Whole box scope: `Modal(token=)`, own session id, caller labels, pinned region, `expose(port) -> Endpoint`,
   `Session.status()` + `wait()`, supervisor status + logs to durable storage. Spike uncertain parts with subagents
   concurrently; compress/rewrite later if it gets gross, but try to keep it clean.
3. **Reopened: who owns the session.** Build and compare:
   - (A) machine owns session (supervisor = truth) + plain relay (baseline),
   - (C) machine owns session + Cloudflare Durable Object in front as log fan-out / preview proxy only,
   - (B) Durable Object owns session (canonical state, log ring buffer, token-gated proxy; vmux style). Needs a Python
     service to call Modal (Modal JS SDK is Node-only, no Workers). DO holds the reader token for the session lifetime.
   Compare on: machine dies mid-run, tab reload/reattach, two tabs, idle reaping/who enforces deadline, token location,
   code weight / stateful parts / deploy needs, latency + cost. Claude picks the demo default from results.
   `wrangler dev` locally is fine; account creds in `~/research-2/cloudflare.txt` (workers free plan; also R2 S3 keys).
   NEVER print secrets; load into env vars programmatically.
4. nn-fit remote: (a) same small datasets; (b) a GPU-needing dataset (grokking/CIFAR) is a stretch.
5. Storage: a box-level storage/mount abstraction (SkyPilot `file_mounts`/`Storage` style: store = R2 | Modal Volume,
   mount vs copy). Durable status + logs is its first user.
6. Spend cap $10 Modal total, T4 or CPU only. Profile `arb8020` only (never `herdora`). Reuse one long-lived dev sandbox;
   local provider for most iteration; fresh sandboxes only when cold start / death / keep-alive is the point. Tag every
   sandbox with label `box.purpose=reader-path-dev` and sweep at the end.
7. Git: `box/reader-path` (worktrees/box-reader-path, off main), `blogs/connect` (worktrees/blogs-connect, off
   blogs/flappy), spikes in own worktrees/branches. Commit on branches; no merge, no push; old box branches untouched.
8. nvidia-smi = new scratch cell kind on `dl/neural-nets.md` (no check, no gating), runs on the connected GPU.
   Flappy cells stay on local `session.py` for now; keep cell->backend routing in one place (GPU later).
9. Connect shows only on opted-in pages; the session carries over across pages (stored in browser).
10. Providers: Modal only; RunPod visible but disabled ("soon"). Token: localStorage, "stored only in this browser",
    masked display, Sign out/forget button.
11. Logs: header pill (connecting/connected · T4 · uptime) -> menu (GPU, disconnect, sign out, details) -> slide-in
    drawer (relay steps, machine boot, live tail). UI bikesheds: Claude decides, lists them in the report.
12. Cut order if stuck (cut first -> last): (b) dataset, working DO-owns-session (keep design + partial spike in
    comparison), R2 backend, deployed worker. Never cut: Connect -> nvidia-smi -> nn-fit remote on real T4, box SDK
    changes with tests, recording, report. Never silently simplify: log every cut with reasons.

## Agent brief (every subagent)
- Stay inside your worktree/project dir. Never `npm i`/`uv init` above it (agents polluted `~` before).
  New worktrees need `npm ci` in `blogs/web` before committing under `blogs/`.
- Note as you go: judgement calls not covered here, uncertainties after executing, papercuts, frustrations.
  Return them in your final message (report files are blocked by a hook for subagents).
