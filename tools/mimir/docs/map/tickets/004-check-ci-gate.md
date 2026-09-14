---
title: "mimir check: CI gate over pinned"
type: task
status: open
assignee:
blocked-by: [003]
---
## Question
`mimir check`: thin layer over quests/pinned JSON (granularity: trivially
decomposable). Exit codes grep-convention: 0 clean, 1 marker -> closed/missing
issue (the rot), 2 misconfigured. Offline/Unknown never fails. Wire into mimir's
own CI as the first consumer.
