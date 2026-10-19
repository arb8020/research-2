# blogs verification map

This directory is the maintained source for verifying what readers and the author see in blogs/. Read this index before driving, then use the matching feature file as the recipe. `vb` is `.claude/skills/verify-blogs/vb`, run from `blogs/`.

## Baseline preconditions

- `vb setup` has run in this checkout (`web/node_modules` present; Playwright Chromium installed).
- `vb launch` started this run's own session.py, static server and local relay on free ports, and printed `ready.`.
- `vb doctor` reports `doctor: ok`: right branch, our processes alive and owning their ports, the served pages built for our session and gateway.
- Never drive the author's long-running instances (tmux `blogs` :8787/:8010, `reader-path` :8790/:8012, `blogs-nnfit` :8060).
- The session starts as a fresh reader (`/state` shows `passed: []`); `vb drive cells` resets this run's reader state itself.

## Driving conventions

- Drive through `vb drive <feature>`; it runs doctor first, tees every command into `<evidence>/<feature>/transcript.txt`, and kills anything the harness left running.
- Prefer the repo's own harnesses (`verify_page.py`, `verify_connect.py`, `web/embeds/nn-fit/remote_e2e.py`); `pages.py` holds only the cases they don't cover.
- Selectors are the page's own handles: custom elements (`code-cell[name=X]`, `scratch-cell`, `env-play[cell=X]`, `connect-pill[data-phase]`, `page-link`, `nn-fit`, `embed-carousel`), their classes (`.run`, `.cell-out.pass|.fail`, `.cell-status`, `.connect-go`), form names (`input[name=token-id]`), roles and ARIA names (`note "under construction"`, `button "Next slide"`).
- Always open Connect pages with `?gateway=<our gateway>`.
- Every C or Python cell runs through the page's Run button against the session; never POST `/run` directly as proof.

## Proof and skip reporting

- Capture the action and the resulting state: a screenshot after each step that changes state, plus the status text in the transcript.
- Check side effects next to what's visible: session `/state` after cells, the gateway log after Connect, the built HTML after a build.
- Record the feature and entry point with every artifact (the feature dir name and the transcript do this).
- A path not driven (e.g. Modal) is reported as not driven, with the prerequisite (token, relay branch, cost approval); never as verified through the local gateway.
- Evidence lives in `blogs/.evidence/verify-blogs/<run id>/` and survives `vb cleanup`.

## Feature entry contract

Each feature file starts with an H1 title and one paragraph describing the user-visible behavior. It then uses exactly four H2 sections in this order.

1. `Sub-features` lists short IDs with one line for each behavior.
2. `How to get to it (user POV)` lists every user entry point.
3. `Driving it with vb` starts with `Preconditions:` and uses labeled bullets that pair each user action with an exact command and observable result.
4. `Gotchas` lists traps that can waste or invalidate a verification run.

Keep implementation details out of the map. Name only user paths, stable handles, required state, commands, and observable proof. The file name is the `vb drive` feature name (`nn-fit-remote` lives in embeds.md).

## Features

- [Build pages](./build.md) covers `build_page.py` one chapter and `--all`, wip banners, todo placeholders, `[[links]]`, excerpts, the hidden-block leak check, and build failures (fixtures).
- [Engine plan page](./plan.md) covers `engine/00-plan.md`: builds, banner, heading ids, no session traffic.
- [Checked cells](./cells.md) covers flappy's cells against session.py: run, pass/fail, crash/hang, gating, propagation, reload restore, the play widget rebuilt from the reader's env.
- [Embeds and widgets](./embeds.md) covers the carousel, the flappy play widget (reference env), nn-fit in the browser and on a Connect kernel (`nn-fit-remote`).
- [Page links](./links.md) covers the `[[page#heading]]` hover card, Escape, click navigation.
- [Connect](./connect.md) covers the Connect pill against the local relay (bad token, boot drawer, scratch cell, Stop, reload reattach, disconnect, sign out) and how the real Modal path is reached.

## Known upcoming features (not mapped yet)

- **Workspace-backed file cells** (branch `blogs/workspace-cells`: changes page.ts, kernel.ts, check.py). Once merged, a maintain pass adds a feature file and a `vb drive` recipe for them.
- **Chapter 1 of the inference-engine series** (`engine/`, per `engine/00-plan.md`: gpt2 forward with the correctness machinery). Once it has cells, map it like [cells](./cells.md).
