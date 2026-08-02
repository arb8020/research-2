---
description: Annotate the last agent message in the browser
allowed-tools: Bash(mimir *)
---

## Annotations

!`PYTHONPATH=~/work/loom/worktrees/loom-sessions/packages/sessions/src mimir annotate --last`

## Your task

The output above is a JSON object with the user's annotations on your last message. Parse it and address the feedback:

- `annotations` — array of `{file, start_line, end_line, text}` comments on specific lines of your message
- `mode` — "message"
- `target` — "last"

Address each annotation. If the array is empty, the user submitted with no comments — acknowledge and stop.

If the command exited with no output (exit code 1), the user cancelled. Acknowledge ("Annotation cancelled.") and stop.
