# vmux and Modal auth (running on a user's behalf)

Sources: https://vmux.sdan.io/ (CLI `vmux-cli` 0.6.2 on PyPI), https://modal.com/docs/sdk/py/latest/Client , https://modal.com/docs/guide/service-users , https://modal.com/docs/guide/rbac , https://modal.com/docs/guide/budgets , https://modal.com/docs/guide/sandbox-resources , https://modal.com/docs/guide/sandbox-snapshots , https://modal.com/docs/guide/sandbox-networking , https://modal.com/docs/guide/restricted-access , https://modal.com/partners

## Distillation
- **vmux never takes Modal credentials.** Login is a GitHub OAuth device flow (scope `read:user`); the raw GitHub token is stored in plain text in `~/.vmux/config.toml` and sent as a bearer token to vmux's server. Everything runs on vmux's own Modal account, billed by vmux ("Free for the holidays, then $2/mo"). Server is private.
- vmux user secrets live in the OS keychain locally and are sent in plain text per run; the server turns them into Modal secrets.
- vmux advertises one Durable Object per session that "outlives the sandbox", a SQLite exec ledger with checkpoints/replay, CPU on Cloudflare Containers (~8s cold start, 168h max) and GPU on Modal (~30s cold start, 3h max). Inferred: the Worker reaches Modal via a Python Modal app, not the JS SDK.
- **Modal tokens**: workspace-scoped id/secret pairs, optional expiry. Service users and RBAC are Team/Enterprise only; roles are per environment (Contributor/Viewer/No Access). **No sandbox-only permission.**
- **Spend caps**: workspace budgets on all plans (environment budgets Team/Enterprise), dashboard-only, no API, no per-token or per-GPU cap.
- **Modal third-party OAuth exists but is undocumented**: `Client.from_oauth_credentials(refresh_token, oauth_client_id, oauth_client_secret)` in the Python SDK, "for managing Modal on behalf of third-party users"; JS and Go SDKs also support it. No public info on how to get a client, scopes, consent screen or token lifetimes. Looks partner-only; ask Modal.
- The `modal token new` browser flow is a hidden internal API; relying on it would be fragile.
- **Modal's JS SDK does not run in Cloudflare Workers/DOs** (gRPC over HTTP/2 fails). A known workaround runs the Modal-facing code in a Cloudflare Container behind a DO. Modal's gRPC API "is not considered a public API", and browsers can't speak it, so a server must see the token.
- Sandboxes: reattach by id or name; 5 min default lifetime, up to 24h, optional idle timeout. GPU sandboxes need gVisor and **can be preempted**.
- Snapshots: filesystem snapshots kept 30 days; memory snapshots alpha, 7 days, **cannot be used with GPUs**; no API to list snapshots.
- **Sandbox Connect Tokens** give an authenticated HTTP/WebSocket URL into a sandbox port (usable from a Worker), with an unspoofable `X-Verified-User-Data` header. Creating the token still needs gRPC.
- GPU sandbox cold start: no Modal number; only vmux's ~30s claim.
- **ToS**: Modal's SaaS agreement bans letting third parties have "direct access to or use of the Service". Offering a product built on Modal (as vmux does) seems normal; handing readers raw Modal access may not be. Ask Modal.
- BYO-credential patterns elsewhere (from a sub-subagent): HF has real "Sign in with HF" OAuth with compute scopes; Cloudflare has self-serve OAuth clients since June 2026; Vercel Connect keeps refresh tokens server-side and hands out short-lived ones; Fused, Mastra and LangChain just take pasted Modal id/secret. For storing per-user tokens: DO storage is encrypted at rest, and Web Crypto in Workers supports envelope encryption (master key in a Worker secret, wrapped per-user keys, ciphertext in the DO).

## Relevance to the series
- Running everything on our own Modal account is the vmux model and avoids reader auth entirely, but needs a ToS check and our own abuse/spend control (Modal budgets are workspace-wide, dashboard-only).
- BYO Modal is possible via pasted tokens, but tokens are full-environment access (no sandbox-only scope). OAuth would be nicer but is not publicly available.
- Our planned Cloudflare DO cannot call Modal directly; it needs a Python/Container hop. Connect Tokens could let the browser or DO talk to a running sandbox over plain HTTP/WS once created.
- Preemptible GPU sandboxes and no GPU memory snapshots mean GPU-stage chapters need checkpointing to files, not snapshot-restore.
- Unknown GPU cold start (~30s per vmux) shapes UX for the "run on GPU" cells.

## Caveats from the report
- vmux's server was never seen; "vmux's own Modal account" is inferred from client code. Q3 (BYO patterns) was done by a subagent and only the Modal OAuth claim was spot-checked. Unknown: who can get Modal OAuth clients, whether filesystem snapshots work with GPUs, real GPU cold starts.

source: subagent file agent-a86b511b3ccd90327.jsonl (BYO-credential detail from its child agent-a23252cede318172c.jsonl)
