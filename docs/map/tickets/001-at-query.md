---
title: "--at file:line[-line]: who is here?"
type: task
status: claimed
assignee: chiraag+claude
blocked-by: []
---
## Question
Build `mimir quests --at <file>[:<line>[-<line>]]`: for each live branch/worktree
whose diff vs main intersects the range, report branch, worktree path (if any),
intersecting hunk ranges, mapped line in that version (hunk offset), and session id
when the branch encodes one. Teleport line: `$EDITOR <worktree>/<file> +<line'>`.
Plumbing (per-branch hunk intervals) is shared with active quests (002) — build it
as an honest lower layer. JSON out. Boundary tests on a fixture repo; prove on obol
(the session-ir stack over obol/cli/main.py is the live test case).
