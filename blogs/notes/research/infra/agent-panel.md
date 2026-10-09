# In-page agent panel: research (2026-10-09)

Goal: the reader highlights text or code (motivating case: a proof they wrote, in prose or LaTeX — both allowed,
decided 2026-10-09), adds a comment, and Claude or Codex replies in a sidebar. Research only; nothing built.
Clones used: `/tmp/agent-panel-research/` (plannotator, pi), `/tmp/t3-auth-research/` (t3code @ c9fa1367, codex,
others, raw policy pages in `policy/`), `/tmp/bb-research/bb`. These are /tmp and may be gone.

## The references

**pi-durable** (`@earendil-works/pi-durable` v1.1.0, MIT, Mario Zechner; github.com/earendil-works/pi/tree/main/packages/durable)
- A library that runs the agent loop and writes every step (turns, tool calls, your state) to storage first, so a crashed turn resumes. Not a hosted service.
- Storage: memory, Node SQLite, JSONL, or a Cloudflare Durable Object's SQLite (`openDurableObjectSqliteStorage`, added 1.1.0 on 2026-10-07). DO backend tested only against a fake (`pi-durable.md`); no DO alarm support, so after eviction you reopen storage and call resume.
- No browser transport: read `watch()` / `watchEvents()` server-side and forward them yourself (most naturally from a DO).
- Keys come from server env via pi-ai; don't put keys in request settings (they're checkpointed). So: our key, unless we build a way for readers to supply theirs.
- "Experimental. The API changes without notice." 1.0.0 on 2026-10-01; five releases in seven days, two breaking (1.0.3, 1.1.0).
- `~/node_modules/@oh-my-pi/pi-coding-agent@15` is unrelated (can1357's oh-my-pi fork); it's the source of the 20 npm audit advisories.

**Plannotator** (github.com/backnotprop/plannotator, MIT/Apache-2.0; 0.24.2 installed locally)
- Local Bun server + React page for reviewing agent plans. Select text (fork of web-highlighter, `@plannotator/web-highlighter`, MIT), attach a comment stored with `originalText` + start/end metadata; on submit prints `{decision: approved|dismissed|annotated, feedback}`. Batch feedback, not chat.
- It also has "ask AI about the selection": `packages/ai` serves `/api/ai/session`, `/api/ai/query` (SSE), `/api/ai/abort`, `/api/ai/permission`, driving the Claude Agent SDK, pi, OpenCode or Codex. `context.ts` builds the system prompt from document + selection + annotations (close to a proof-review prompt).
- `@plannotator/ui` (npm 0.52.1, Apache-2.0) is embeddable via `configurePlannotatorUI({aiTransport})` (`AITransport` = session/query/abort/permission), but needs React 19 + Tailwind 4, ~6 MB; our page is plain TS + CodeMirror. `@plannotator/ai` is not published (404).
- Worth borrowing: the annotation data shape, the four-endpoint SSE protocol, maybe the highlighter.

**mimir annotate** (`tools/mimir/mimir/annotate.py`; command `~/dotfiles/claude/commands/annotate.md`)
- Local Python server; blocks until submit; prints `{annotations:[{file,start_line,end_line,side,text,original_text,prefix,suffix}], mode, target}`. A review gate, no live thread.
- Useful piece: anchoring by line range + selected text with ~32 chars each side survives edits — what a comment pinned to a proof paragraph needs. Comparison: `tools/mimir/notes/plannotator-comparison.md` (mimir anchors better; plannotator has the better approve/dismiss/annotate decision).
- Papercut: `~/.claude/skills/plannotator-*` and `~/dotfiles/claude/commands/annotate*.md` have similar names.

## How "use the reader's own login" works: T3 Code, bb, others

All of them run the vendor's own CLI as a child process over stdio and inherit its saved login. None touches the credentials.

**T3 Code** (pingdotgg/t3code, MIT, © T3 Tools Inc.)
- `t3` / `npx t3@latest` starts a local server that owns agent processes and serves the web UI; browser talks HTTP + WebSocket `/ws`. Desktop = Electron with the same server. Hosted app.t3.codes and phone apps reach your server over HTTPS (Tailscale or T3 Connect) (`docs/internals/overview.md`, `remote.md`).
- Claude: `@anthropic-ai/claude-agent-sdk` (`apps/server/package.json:32`), `query()` with `pathToClaudeCodeExecutable` = the user's `claude` (`apps/server/src/orchestration-v2/Adapters/ClaudeAdapterV2.ts:632,908`; `provider/Drivers/ClaudeExecutable.ts`). Shows subscription from `claude auth status` (`provider/ClaudeProvider.ts`).
- Codex: `codex app-server` (`provider/codexLaunchArgs.ts`), newline JSON-RPC over stdio (`packages/effect-codex-app-server/src/protocol.ts`). Also "Connect with ChatGPT": its own OpenAI OAuth, scope `chatgpt.tokens.use.direct` (`provider/CodexChatGptAuth.ts:527`), an official OpenAI program.
- Browser auth: `t3` prints/opens a pairing URL with the secret in the `#fragment` (`packages/shared/src/remote.ts:165`), never sent to the host; page trades it for a session token and strips it. WebSocket uses a short-lived ticket; every RPC checks a scope (`docs/internals/environment-auth.md`). Packaged server allows any origin but requires a token on every call (`apps/server/src/http.ts:238`).
- Built on Effect: vendoring means extracting a few files from a framework-heavy monorepo. Measure before committing.

**bb** (get-bb/bb; README says MIT, sparse clone had no LICENSE file — confirm; `/Applications/bb.app` v0.45.0 installed, data `~/.bb`, CLI inside the bundle at `.../app.asar.unpacked/node_modules/bb-app/dist/bb.js`, not on PATH)
- Electron shell around a Node/Hono server on `127.0.0.1:38886` (SQLite, HTTP API, `/ws`), a host daemon on 38887 that runs agents, and a web UI (`npx bb-app`). Terms: project, thread, environment, provider, automation, machine (`README.md`, `docs/system-overview.md`).
- Provider plugins ship a bridge spoken to over line JSON-RPC on stdio (`docs/provider-bridge-protocol.md`). Claude Code: Agent SDK pointed at the user's `claude` (`plugins/provider-claude-code/src/bridge/session-options.ts`). Codex: `codex app-server` (`plugins/provider-codex/src/bridge/bridge.ts`, `app-server-connection.ts`). Others via ACP, plus Pi.
- "bb uses the provider CLI you already have authenticated." Reads credentials directly only to show plan (`provider-maintenance.ts`) and, for Codex, uses `~/.codex/auth.json`'s ChatGPT token for titles and voice (`plugins/provider-codex/src/ai/`).
- Main API: no token but Origin-guarded (`apps/server/src/browser-request-guard.ts`, `server.ts:509`): any `Origin` other than bb's own -> 403; CORS same; Host checked against DNS rebinding. Non-browser loopback clients get full access. So our page can't drive it directly.
- Exception: plugin routes `/api/v1/plugins/<id>/http/*` skip the guard (`server.ts:859`), auth mode `local` / `token` (`x-bb-plugin-token` or `?token=`, from `bb plugin token <id>`; `routes/plugins.ts:220-240`) / `none`. Plugins can register WebSocket routes; browsers don't apply CORS to WebSockets, so a token-auth plugin WebSocket is reachable from any page. Model: `examples/plugins/slack-bot`; in-bb panels: `examples/plugins/thread-chat-demo`.
- `bb connect` tunnels to `<handle>.getbb.app` but needs a getbb.app owner login: not for arbitrary readers.

**Others**

| app | runs the agent | auth | local server protection |
|---|---|---|---|
| Zed ACP (agentclientprotocol.com) | editor spawns agent; JSON-RPC 2.0 stdio; Claude adapter `agentclientprotocol/claude-agent-acp` wraps the Agent SDK; Codex adapter uses app-server | `terminal` auth method runs `claude auth login` / `codex login` | no server |
| Codex app-server | stdio; also `--listen ws://IP:PORT` | ChatGPT login, device code, API key | rejects any request with an `Origin` header (403; `codex-rs/app-server-transport/src/transport/websocket.rs:89`) so browsers can't connect; won't listen beyond localhost without `--ws-auth` |
| Conductor (closed) | bundles its own claude/codex | "uses the auth tokens already saved on your machine" (conductor.build/docs/faq) | — |
| vibe-kanban | `npx @anthropic-ai/claude-code --output-format=stream-json --input-format=stream-json`; `codex app-server` | CLI login | localhost UI, Origin check, no token |
| opcode/Claudia | Tauri; `claude -p … --output-format stream-json --dangerously-skip-permissions` | CLI login | optional web mode binds 0.0.0.0, any origin, no token (`src-tauri/src/web_server.rs`): unsafe |
| Plannotator | Claude Code hook; Agent SDK or app-server | CLI login | Origin check on some routes, no token |

## Policy

Anthropic:
- Agent SDK overview (code.claude.com/docs/en/agent-sdk/overview): "Unless previously approved, Anthropic does not allow third party developers to offer claude.ai login or rate limits for their products, including agents built on the Claude Agent SDK. Use the API key authentication methods…"
- Legal and compliance (code.claude.com/docs/en/legal-and-compliance): developers "should use API key authentication … may not collect, store, or intermediate Claude.ai credentials or session tokens." Carve-out: doesn't "prevent an end user from signing in to the unmodified Claude Code binary with their own Claude subscription"; you may not "pay for, resell, or intermediate Claude usage".
- Consumer Terms §3 (eff. 2025-10-08): no automated access "except … via an Anthropic API Key or where we otherwise explicitly permit it."
- Staff: Thariq 2026-02-18 ("encourage local development and experimentation with the Agent SDK and claude -p. If you're building a business … use an API key"); Boris 2026-04-03 (subscriptions stop covering tools like OpenClaw; personal local tools wrapping the Agent SDK: "Yep"); Theo 2026-04-18 ("no clarity whatsoever"; some T3 Code users banned, probably in error).
- support.claude.com/en/articles/15036540 (updated 2026-10-07): "You can still use the Claude Agent SDK, `claude -p`, and third-party apps with your subscription limits." A planned billing change was paused 2026-06-15.

OpenAI:
- app-server is meant for third parties (learn.chatgpt.com/docs/app-server).
- "Sign in with ChatGPT plan usage" (developers.openai.com/siwc/token-sharing-open-source): own ChatGPT login, no client secret, for "open-source and locally hosted apps"; paid/remote apps waitlisted.
- Staff (Tibo 2026-09-29): ChatGPT subscriptions work in 16+ partner products, "No little rules". OpenAI ToU itself not fetched (403).

Ambiguous: "a product that only starts the reader's own unmodified, logged-in `claude`" — the carve-out arguably covers it; "offer … rate limits … built on the Agent SDK" arguably forbids it. Personal vs distributed open-source undefined. Enforcement unpredictable (block in January, cutoff in April, billing change in May paused in June). Clear: our page or relay must never touch a Claude token. Codex via existing login, or official ChatGPT sign-in as an open-source local tool, is fine. Staff quotes are thin (one-word "Yep"); some dates from secondary sources; tweets via api.fxtwitter.com mirror.

## A web page can't start local processes

Browsers sandbox pages; there's no "run this in the user's terminal". Every way in needs a prior install or command:
1. a localhost server the user started (T3, bb, an `npx` bridge);
2. a custom URL scheme (`vscode://`, `bb://`) registered by an installed app; a page link launches it behind an "Open app?" prompt;
3. a Chrome extension + native messaging host (both installed).

### Browser constraints for a localhost bridge
- Mixed content: Chrome and Firefox treat `http://127.0.0.1` as secure, so an https page may call it. Safari blocks it (WebKit bug 171934, open). Brave blocks by default.
- Permission prompt: old Private Network Access preflight never shipped. Chrome's Local Network Access prompt ("apps and services on this device"): fetch since Chrome 142, WebSocket since 147 (developer.chrome.com/blog/local-network-access; wicg.github.io/local-network-access). Firefox prompts by default since 153. Iframes need `allow="loopback-network"`.
- Untested by us in a real browser (only a curl preflight).
- Easiest path: the bridge serves the page itself on localhost: same origin, no prompt, no CORS, Safari works.

### Bridge security checklist
- Bind 127.0.0.1 only.
- Check `Host` == `127.0.0.1:PORT` (DNS rebinding; Ollama CVE-2024-28224, Jupyter `allow_remote_access`).
- Check `Origin` against an exact allowlist on every WebSocket (WebSockets ignore CORS; CVE-2025-52882, Claude Code IDE extensions' unauthenticated localhost WebSocket).
- Random per-run token delivered in a URL `#fragment` (T3 pairing), sent in a header or first WS message, never the query string.

## Options: what the reader actually does

| option | reader does | needs already | catches |
|---|---|---|---|
| API key | pastes a key once | Anthropic account | pays per token; no install; works everywhere (`anthropic-dangerous-direct-browser-access` header; SDK `dangerouslyAllowBrowser`; curl-verified preflight 400 without / 200 + `ACAO: *` with) |
| `npx` bridge serving the page | runs `npx <name>`; a localhost tab opens with the agent ready | Node; `claude` or `codex` installed + logged in | no paste (pairing link); no prompt; Safari OK; only while the terminal runs |
| `npx` bridge, page on our site | runs the bridge, keeps reading on our site, allows Chrome's local-network prompt | same | Safari can't; Brave blocks by default |
| install once, URL scheme | installs a small app once; page's "connect agent" link launches it | same | first-run install; then near zero |
| bb | install bb.app, sign in, install our plugin, paste plugin token | same | heaviest; only for bb users |
| bridge in the reader's Modal sandbox | signs in to Claude/Codex inside the sandbox once (`claude setup-token`, `codex login --device-auth`), persisted in a Modal Secret/Volume in their workspace | the Modal workspace they already connect | no install, no browser friction; highest Anthropic policy risk (hosted runtime; if our relay ever passes a Claude token it's clearly "intermediate credentials"); arguably fine for Codex |

Other server-side options (from the first pass): our relay/DO running pi-durable or a plain loop (our key or theirs); Claude Agent SDK in the reader's sandbox beside the kernel (API billing; readers can't use their subscription per the overview); Managed Agents (beta `managed-agents-2026-04-01`, list token rates + $0.08/session-hour, `max_list_cost` caps, self-hosted sandbox worker option; org API key, no documented end-user token found in bundled docs). Prices from a 2026-06-24 cache: opus-5 $5/$25, sonnet-5 $2/$10, haiku-4-5 $1/$5 per M tokens; confirm before quoting. Cache the chapter text in the prompt.

## Vendoring candidates
- T3 (MIT): Claude adapter (Agent SDK + `pathToClaudeCodeExecutable`), `codex app-server` JSON-RPC client, pairing-link + session-token flow. Effect-based: measure file count first.
- bb: Origin/Host guard (`browser-request-guard.ts`), per-plugin token, bridge protocol `thread/delta` grammar. License to confirm.
- Plannotator: four-endpoint SSE protocol, annotation shape, highlighter.
- mimir: line + quote/prefix/suffix anchoring.

## Open questions
1. Who pays for tokens: reader's key, reader's subscription via a bridge, or us?
2. Where the agent runs: browser, local bridge, our relay/DO, reader's sandbox, Managed Agents.
3. Hidden reference proof? It can't ship in the page (solutions are stripped), so it lives on a server (relay/DO/sandbox prompt). "Hint, don't reveal" is prompt-enforced only.
4. Read-only review vs edit cells and run checks (the latter ties this to the sandbox/box session work).
5. One reply per highlight vs a live thread per comment (the request reads like a thread).
