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
