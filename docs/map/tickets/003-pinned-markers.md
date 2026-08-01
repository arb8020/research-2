---
title: "pinned: TODO(#N) markers joined to tracker state"
type: task
status: open
assignee:
blocked-by: []
---
## Question
Parse issue refs from TODO/FIXME markers (todo scanner already finds the comments)
into a sum type; tracker declared once (config or origin inference), gh-only v1.
State via one batched gh call: Open | Closed | Unknown(reason) — Unknown never
fails anything. Watermark skew warnings, stateless: git blame time of marker vs
issue updatedAt (issue updated after marker placed; code rewritten after issue
quiet). Rumors report: markers with no ref; open issues with no marker (report,
never a gate). Read todocheck (prior art) before building.
