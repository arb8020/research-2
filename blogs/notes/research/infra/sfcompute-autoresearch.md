# SF Compute autoresearch

Sources: https://autoresearch.sfcompute.com/docs , https://autoresearch.sfcompute.com/llms.txt (agent-facing spec), https://autoresearch.sfcompute.com/cli.txt , https://autoresearch.sfcompute.com/changelog , https://autoresearch.sfcompute.com/about

## Distillation
- On-demand H100 (and CPU) compute "whose primary user is an agent". Formerly Givemeanode/`gman`; CLI now `autor`; env vars still `GMN_*`. Three equal interfaces: MCP server, HTTP API (`/preview`, OpenAPI 3.1), CLI. The "Research" agent feature is private preview, off by default.
- **Concepts**: Node (container on GPU/CPU with persistent encrypted disk; stop parks it and stops billing), Command (sync or detached), Job (Dockerfile/image batch run; sweeps up to 256 variants; task sets; multi-node preview), Sandbox (microVM, bake once, fork in ~10 ms, meant for RL), Mission (groups resources and spend on a private page), Artifact (~30 days, shareable).
- **Auth**: MCP via OAuth 2.1 in a browser; device code for remote machines; `gmnt_` service tokens minted by an org admin, scoped `infra`/`org` (+ read variants), 90-day default expiry. Agents can't see token-minting tools.
- **Execution constraints**: H100 and CPU shapes only. The platform owns the entrypoint (yours never runs). Only the home disk survives stop; processes don't. No SSH. Sync commands capped at 60 s (MCP) / 300 s (HTTP). **Logs are polled by offset, never streamed.** Rate limit 60 calls/min.
- Outputs: jobs write JSON/files to well-known paths captured per attempt; mid-run previews and sample series; checkpoints let interrupted attempts resume and bill only to the last checkpoint. Checks (health/success assertions) are required on MCP.
- Lifecycle: idle nodes auto-stop after 15-20 min; can hold awake; jobs default 60 min, max 12h.
- **Ports**: `expose_port` / `expose_sandbox_port` give a public HTTPS URL that passes WebSocket and SSE, can require a bearer token, expires, and dies with the node.
- No webhooks for job/command completion (only budget/idle alerts); you poll. No bring-your-own-compute.
- **Pricing**: h100-1 $3.96/hr, h100-8 $31.68/hr, batch $0.0495/GPU-min, cpu-2 $0.18/hr, sandboxes $0.046/GiB-hr running (much cheaper parked); Fridays 33% off, weekends 20% off. Prepaid only, starts at $0, everything stops at zero balance.
- Most of the report compares autoresearch to the user's own `box` tool (provider/machine/supervisor); key conflicts: platform owns the entrypoint (box's supervisor can't be it), async queued launch, per-exec HTTP round trips under the rate limit, H100-only vs box's GPU list.

## Relevance to the series
- The research was framed around `box`, not the blog; relevance here is indirect.
- Sandboxes that fork in ~10 ms and are aimed at RL are the most interesting piece for a reader-facing RL sandbox, but the report only skimmed them.
- Token-gated, expiring public ports with WS/SSE are a fit for a browser talking to a reader's running job.
- Poll-only logs and a 60/min rate limit would make live training curves in the browser awkward without our own relay.
- Prepaid, H100-only, $0 start: costly for small CPU-scale flappy runs, and per-reader auth would mean per-reader accounts or our own proxy.

## Caveats from the report
- Nothing was called or signed up for; all from docs. Sandbox/rollout sections only skimmed. HTTP API is `/preview` and may change. Unknown whether customer-planned research works when Research is disabled, and whether nodes take labels.

source: subagent file agent-a500bc00f92c8a3a1.jsonl
