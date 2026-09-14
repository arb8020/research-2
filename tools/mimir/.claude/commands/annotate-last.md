---
description: Annotate the last agent message in the browser
allowed-tools: Bash(mimir *)
---

## Step 1: Launch annotation gate

Run this command using the Bash tool (it blocks until the user submits in the browser — use a 600000ms timeout):

```
PYTHONPATH=/Users/chiraagbalu/silares_stuff/obol/worktrees/obol-sessions/packages/sessions/src mimir annotate --last
```

The command starts a local server, opens the browser, and blocks until the user submits annotations or cancels (ctrl-c).

## Step 2: Handle the result

The command outputs a JSON object. Parse it and address the feedback:

- `annotations` — array of `{file, start_line, end_line, text}` comments on specific lines of your message
- `mode` — "message"
- `target` — "last"

Address each annotation. If the array is empty, the user submitted with no comments — acknowledge and stop.

If the command exited with no output (exit code 1), the user cancelled. Acknowledge ("Annotation cancelled.") and stop.
