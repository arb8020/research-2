# mimir annotate vs plannotator: agent-side control flow

Compared 2026-08-11. Both tools solve the same problem (agent blocks on
human annotation of a document/plan) with the same architecture (local
server, browser UI, JSON on stdout). The interesting difference is how
the agent harness drives the call.

## plannotator (Gemini CLI / OpenCode)

Gemini's command TOML uses `!{plannotator annotate {{args}}}` — a
prompt-time shell interpolation. The CLI runs and blocks *before the LLM
sees the turn*. Its stdout lands inline in the prompt, and the
surrounding text tells the model the three-way branch:

```
approved  → "Acknowledged." Stop.
dismissed → "Session closed." Stop.
annotated → Address the feedback.
```

One LLM turn total: the model sees the result and acts on it in the same
generation.

OpenCode commands are stubs — OpenCode doesn't have `!{}` interpolation,
so the wrappers are basically empty description-only frontmatter.

## mimir annotate (Claude Code)

The `/annotate` skill tells the agent to call
`Bash(mimir annotate ..., timeout=600000)` explicitly. The agent spends
one turn making the tool call, then a second turn reading the JSON and
acting on it. Two LLM turns total.

The JSON is an array of line-anchored annotations
(`{file, start_line, end_line, text}`) — no built-in approve/dismiss
enum. The skill text says "if the array is empty, the user submitted with
no comments — acknowledge and stop." Agent infers approval from
empty-array.

## What plannotator does better (for the plan-annotation case)

1. **Approve gate as a first-class primitive.** The three-way
   `approved | dismissed | annotated` enum is the right abstraction.
   Mimir encodes "approved" as "empty annotations array" which is
   implicit and fragile.

2. **One fewer LLM round-trip.** Prompt-time interpolation (`!{}`) means
   the blocking wait + result parsing happen in a single model turn.
   Mimir's explicit Bash call costs an extra turn. Doesn't matter much
   (human wait dominates) but it's cleaner.

3. **Agent-side wrappers are done for you.** The Gemini TOML handles the
   three-way branch so every agent integration doesn't re-implement it.

## What mimir does better

1. **Harness-agnostic.** "Run a command, parse JSON" works in any agent
   harness. `!{}` is Gemini CLI-specific.

2. **Richer annotation model.** Line-anchored annotations with file/line
   ranges vs plannotator's feedback blob. Better for code review and
   diff annotation.

3. **More modes.** `--diff`, `--last` (annotate agent's own messages),
   codebase tree browsing, `@` context queries.

## If we want to converge

The minimal changes to get plannotator's wins in mimir:

- Add `--gate` flag to `mimir annotate` that adds an Approve button and
  emits `{"decision": "approved|dismissed|annotated", ...}` instead of
  (or wrapping) the current annotations array.
- Update the `/annotate` Claude Code skill to handle the three-way
  decision explicitly.
- Consider whether prompt-time interpolation is worth pursuing in Claude
  Code (probably not — it's a harness feature request, not a mimir
  change).
