---
description: Annotate the current diff in the browser
allowed-tools: Bash(mimir *)
---

## Step 1: Launch annotation gate

Run this command using the Bash tool (it blocks until the user submits in the browser — use a 600000ms timeout):

```
mimir annotate --diff HEAD $ARGUMENTS
```

The command starts a local server, opens the browser, and blocks until the user submits annotations or cancels (ctrl-c).

## Step 2: Handle the result

The command outputs a JSON object. Parse it and address the feedback:

- `annotations` — array of `{file, start_line, end_line, side, text}` comments on specific diff lines
- `side` — "old" or "new" (which side of the diff the annotation is on)
- `mode` — "diff"
- `target` — the diff ref

Address each annotation — fix the code, explain your reasoning, or discuss. If the array is empty, the user approved with no comments — acknowledge and stop.

If the command exited with no output (exit code 1), the user cancelled. Acknowledge ("Annotation cancelled.") and stop.
