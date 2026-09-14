---
title: "research: hunk annotation input format + integration seams"
type: research
status: closed
assignee:
blocked-by: []
---
## Question
Read ext/hunk (docs/, src/, AGENTS.md): how do inline AI/agent annotations enter
hunk (file format? flag? API?), what are the git-backed review + watch-mode entry
points, can an external tool feed it annotations today or does it need a patch?
Deliver: the exact interface 006 should target, or "needs upstream PR" + what to
propose.

## Resolution (2026-08-01, research subagent)

**No upstream PR needed — two stable interfaces exist today.**

1. **Target this: `--agent-context <path>` sidecar JSON** (v1). Valid on hunk
   diff/show/patch. Schema (ext/hunk/src/extension-api/types.ts:82-105): top-level
   `{version, summary?, files: [{path (required), summary?, annotations:
   [{summary (required non-empty), newRange: [start,end] 1-based ordered,
   oldRange?, rationale?, tags?, confidence?, source?, author?, id?, createdAt?}]}]}`.
   Unknown fields silently dropped. `files` array order controls review reading
   order. **Watch mode watches the sidecar itself** (watchPlan.ts:138) — rewrite the
   JSON on disk and an open `hunk diff --watch --agent-context f.json` live-reloads.
   Caveat: stdin (`-`) disables reload — write a real file.
2. Branch invocation passes ranges opaquely to git:
   `hunk diff main...branch --agent-context .mimir/hunk-annotations.json --watch`.
3. Alternative: live session daemon (`hunk session comment apply --stdin`, zod
   schema in src/session/protocolSchemas.ts) — but comments are single-line;
   sidecar preserves *ranges*. 006 should use the sidecar.

Working example: ext/hunk/examples/3-agent-review-demo/agent-context.json.
Nice-to-have upstream someday: published JSON Schema / strict mode. Not a blocker.
