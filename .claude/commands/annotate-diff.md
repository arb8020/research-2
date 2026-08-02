---
description: Annotate the current diff in the browser
allowed-tools: Bash(mimir *)
---

## Annotations

!`mimir annotate --diff HEAD $ARGUMENTS`

## Your task

The output above is a JSON object with the user's annotations on the diff. Parse it and address the feedback:

- `annotations` — array of `{file, start_line, end_line, side, text}` comments on specific diff lines
- `side` — "old" or "new" (which side of the diff the annotation is on)
- `mode` — "diff"
- `target` — the diff ref

Address each annotation — fix the code, explain your reasoning, or discuss. If the array is empty, the user approved with no comments — acknowledge and stop.

If the command exited with no output (exit code 1), the user cancelled. Acknowledge ("Annotation cancelled.") and stop.
