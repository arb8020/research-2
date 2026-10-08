# pi `durable` package (durable agent harness)

Source: https://github.com/earendil-works/pi/tree/main/packages/durable (`@earendil-works/pi-durable` v1.1.0, MIT, Mario Zechner)

## Distillation
- pi is a TypeScript agent-harness monorepo (LLM lib, agent core, coding CLI, TUI, `durable`). Very active (~113k stars); issues/PRs from new contributors are auto-closed.
- `durable` is "a durable agent harness": conversations, model turns, tool calls and app state are saved before being shown, and a crashed turn resumes. **Experimental; API changes without notice.** First release 2026-10-01; two breaking releases since.
- Core pieces: `Harness` (one storage + runner), `Conversation` (immutable entries, writes via `commit`), `Document` (typed JSON state scoped to storage/conversation/task), `Task` (checkpointed state machine; model calls and tool calls are tasks), `Extension` (tools, prompt sections, hooks).
- Storage backends: memory, Node SQLite, JSONL, and **Cloudflare Durable Object SQLite** (`openDurableObjectSqliteStorage(ctx.storage)`), added v1.1.0, one day old at research time and **only tested against a node:sqlite fake**, not real workerd.
- Core has no `node:` imports, so it may run in a DO; unverified. Package engines say Node ≥22.19.
- Timers are in-memory `setTimeout`, **no DO alarm integration**. Interrupted work stays pending until `harness.resume()` or the next submit; after eviction the host must reopen and resume.
- Streaming: UI reads committed state via `watch()` / `watchEvents()` (text deltas); partial output committed at most every 100 ms. **No built-in WebSocket/SSE**; you pipe it yourself.
- Context inputs: custom tools, system-prompt sections that read documents, app documents committed with transcript entries, and `submit({type:"write"})` entries that don't call the model.
- Restriction: `configure({ tools: [...] })` limits tools; `beforeTool`/`afterTool`/`beforeRequest`/`afterResponse` hooks. Nothing enforces "hint, don't solve" beyond prompt + withholding tools.
- Models via `pi-ai` (OpenAI, Anthropic, Google, Bedrock, OpenRouter, Workers AI, ...). Stream settings are written into task checkpoints, so **don't put API keys in headers/settings**; keep them in DO env or an in-memory credential store.
- One process owns a storage at a time (no cross-process locking); one DO = one owner fits. Tables are created **unprefixed** (`conversations`, `entries`, `tasks`, `documents`, ...) with no namespace option, so our own DO tables must avoid those names, or session state can live as pi documents.
- TypeBox costs ~23 MB RSS unbundled, ~4 MB tree-shaken: bundle it for DO memory limits.
- The agent ran the chat example on Node 22 with a fake provider and it worked.

## Relevance to the series
- Candidate for the in-page tutor/hint agent living in the same Durable Object as the reader's session: cell source, prose, `check()` results and sandbox logs could be fed in as documents or tools.
- Storing cell versions as pi documents would make them commit atomically with the tutor transcript.
- Risks: brand-new and churning API, untested on real workerd, no alarm-based resume across hibernation, and we build the WS relay ourselves.
- "Hint, don't solve" would be our own prompt + tool restriction + output filter.

## Caveats from the report
- Unknown whether it bundles/runs in workerd, how the scheduler behaves across DO hibernation, and whether transactions near awaited model calls stall gates.

source: subagent file agent-a7d59d8ba55d441db.jsonl
