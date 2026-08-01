---
title: "active quests section: efforts, not branches"
type: task
status: open
assignee:
blocked-by: [001]
---
## Question
Add `active` section to quests: live branches clustered into efforts by diff overlap
(Jaccard >0.5 — stacks and v2/v3 retries collapse), 14d recency window, flag =
worktree checked out, dominant-dir location, zone-scoped `mimir quests <path>`.
Scratch dirs excluded (reuse --exclude + defaults). Unit is the effort. Uses 001's
hunk plumbing. Prototype validated 2026-07-31 on obol (104 branches -> 58 efforts).

## Field notes (2026-08-01, obol estate cleanup)

Abandoned tier EARNED (two manual runs: rover estate 33 branches, main audit 91
branches via 4 parallel subagents). Division of labor proven: mimir emits
candidate table + evidence (age, diff-stat, namespace, upstream state,
worktree/detached status); agents judge supersession (requires reading diffs vs
main content — semantic, not mechanical); humans gate the reap. Findings:
- Semantic supersession defeats patch-equivalence (landed code is an "evolved
  descendant") — mimir must never claim SUPERSEDED itself, only surface candidates.
- Namespace is evidence (decommissioned prefix e.g. rover/* = abandoned by
  construction) — support a declared-dead-prefix mechanism.
- Fleets drop real work on the floor (proxy fixes, 5k-line eval capability,
  fleet-inbox prototype found unlanded) — candidate tables are salvage tooling,
  not just hygiene.
- Squash commits that enumerate contents (obol 803e7602) make supersession
  checks cheap — worth recommending in docs.

Turn-in gaps found in use: (1) detached-HEAD worktrees not fully covered by
ancestor check (pr-review checkouts in /tmp missed); (2) "live: N worktrees, M
branches vs main" summary line is confusingly compressed — unclear semantics.
