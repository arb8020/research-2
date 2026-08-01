---
title: "emit hunk-renderable annotations (NPC symbols in terminal)"
type: task
status: open
assignee:
blocked-by: [001]
---
## Question
Have --at/quests emit annotations in whatever input format `hunk` (ext/hunk)
renders inline, so hunk becomes the first visual surface for free: "session X is
editing this hunk live", "TODO(#42) closed". Format per 007's resolution: --agent-context sidecar JSON v1, written to a real file (watch live-reloads it), ranges via newRange, source: mimir, stable ids.
