---
title: "multi-target scan: comparative zone table"
type: task
status: open
assignee:
blocked-by: []
---
## Question
`mimir scan dir1 dir2 ...` -> one comparative table (zones named by caller, never
inferred). Columns: churn as share-of-recent-commits (NOT wall time), files-touched
recency, per-zone erosion (comparative use only), todo/ni, rot, test presence
(needs honest path-mapping — current name-match is the weakest signal). Admission
note: zone table has been hand-run twice on obol (2026-07-31); second reach = earned.
