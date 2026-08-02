---
description: Open files or diffs in the browser for annotation, return feedback
allowed-tools: Bash(mimir *)
---

## Annotations

!`mimir annotate $ARGUMENTS`

## Your task

The output above is a JSON object with the user's annotations. Parse it and address the feedback:

- `annotations` — array of `{file, start_line, end_line, text}` comments on specific code locations
- `mode` — "browse" (files), "diff" (branch diff), or "message" (last agent message)
- `target` — what was annotated

Address each annotation. If the array is empty, the user submitted with no comments — acknowledge and stop.

If the command exited with no output (exit code 1), the user cancelled. Acknowledge ("Annotation cancelled.") and stop.
