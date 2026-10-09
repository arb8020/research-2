# Sessions: every place we rent a machine (2026-10-09)

Research for a future "write the session code once" session. Read-only survey; nothing launched.
Paths are relative to research-2 unless absolute. Branch paths are read with `git show <branch>:<path>`.

## Summary

There are two products, not one:

- **Batch lease from a laptop CLI** (box): launch, put, run a job, follow logs, get, end. kelpie and robots use it.
- **Interactive service reached by a browser through a relay** (the blogs spikes): a kernel in a sandbox, a port tunnel,
  per-reader credentials, reattach by name. None of it uses box; each spike hand-rolls Modal create/tunnel/terminate.

The gpu-session spike's REPORT already sketches what box would need to own the second: `Machine.connect(port) -> Endpoint`,
`Provider.get_by_name`, `sdk.serve(...)`, a supervisor `--service` mode, per-reader credentials, and a lease held through
the service instead of exec.

## Inventory

| # | where | provider | shape | client | auth | teardown |
|---|---|---|---|---|---|---|
| A | `box/` (sdk.py, *_provider.py, supervisor.py, cli.py) | Modal, RunPod, Local | batch jobs; logs polled with `tail -c` over exec every 0.5 s (`sdk.py:251-266`) | laptop CLI | Modal: ambient `~/.modal.toml`, app "box" (`modal_provider.py:55`). RunPod: `RUNPOD_API_KEY` env/.env (`runpod_provider.py:109-120`) + your `~/.ssh/id_*.pub` for sshd; exec over multiplexed ssh (`:216-235`). Local: a dir, no GPU/image | client heartbeats a lease every TTL/4 (`sdk.py:129-145`); supervisor ends on deadline / lost lease / idle / stop / release; backstops: Modal sandbox `timeout` = deadline+600 capped 24 h (`modal_provider.py:62-64`), RunPod pod self-deletes with a pod-scoped key + backstop timer (`runpod_provider.py:51-93`), Local none; client terminates if not up after `boot_timeout_s` (`sdk.py:96-100`) |
| B | `kelpie/kelpie-http/kelpie_http/dev/remote.py` | Modal (+ volume `/data`), Local | batch via box SDK | laptop CLI | as box | as box; GRACE_S 1800 (`:36`) |
| C | `robots/box_run.py` | via `box.cli.make_provider` (`:23`) | batch | laptop CLI | as box | as box; never run live on a GPU since the move (`:44`) |
| D | branch `blogs/modal-spike`: `blogs/spike-modal/` (also `worktrees/blogs-modal`) | Modal CPU sandbox | interactive Jupyter Server, `encrypted_ports` + random `JUPYTER_TOKEN` (`runtime.py:46-85`) | browser via stateless relay (`relay.py` local, `relay_modal.py` = Modal web endpoint in our workspace) | reader's token; relay builds `modal.Client.from_credentials` per request, stores nothing | sandbox `timeout` (relay caps 600 s), `idle_timeout`, `/terminate`, `cleanup.py` sweep |
| E | branch `worktree-agent-a29bfb70351ac7455`: `blogs/spike-gpu-session` | Modal CPU or T4 | custom aiohttp exec-loop kernel + worker subprocess on :8080, readiness probe (`runtime.py:37-46`) | browser via `create_connect_token` (token in query string); Cloudflare DO keeps cell sources + ring buffer, rebuilds by replay | (i) `broker.py` holds reader's full token behind a DO; (ii) reader `modal deploy`s `blog_runtime.py` in their workspace | `TIMEOUT_S=600`, `IDLE_TIMEOUT_S=300`, `terminate_all` sweep (`runtime.py:19-20, 88-94`); reattach by name `s-<session>-<gpu>` via `get_or_create` (`:52-77`) |
| F | `worktrees/blogs-flappy/blogs/session.py` | none (local stand-in) | runs cells locally | browser | none | process exit |
| G | history | — | — | — | — | — |

G, history:
- Old box (`provider.py`, `providers/modal.py`, `providers/runpod.py`) deleted in b089bd0f. The old Modal provider used a fifo entrypoint (the job was the sandbox's main process; `git show b089bd0f^:box/providers/modal.py`) and had `Offering`, `Volume`, `Mount`; kelpie and robots code lived inside box.
- The SSH-box CLI was dropped by the `box/strip-ssh-boxes` merge (2d4b8442); it survives at `~/silares_stuff/kelpie/scripts/box` (outside research-2) with its own sync, setup and venv cache (c86152b6 notes the move).
- `kelpie/scripts/modal_run.py` deleted in b089bd0f.

## Duplicated vs genuinely different

Duplicated:
- Modal plumbing (`App.lookup(create_if_missing)`, `Sandbox.create(timeout, image, gpu, tags)`, terminate by id, sweep by app/tag): four copies — `box/modal_provider.py`, `spike-modal/runtime.py` + `cleanup.py`, `spike-gpu-session/runtime.py`, `kelpie/.../dev/gc.py` (volumes).
- "Hard timeout + idle + always terminate", re-derived in each.
- Provider factories: `box/cli.py:27`, `kelpie remote.py:120` (modal/local only), `box/tests/providers.py:15`.
- The follow-logs loop: robots (`box_run.py:80-105`) repeats `sdk.run_job` (`sdk.py:269-287`); kelpie's `follow` too.
- Uploading code: box put/tar vs spikes' `Image.add_local_dir`.

Genuinely different:
- Client: laptop Python vs browser. A browser can't speak Modal's gRPC (JS SDK is Node-only; api.modal.com has no CORS/grpc-web), so it needs a relay or a connect token.
- Credentials: ambient single-user (box; `Modal()` has no `client=`) vs per-reader.
- Interaction: job queue polled at 0.5 s, 2-3 execs per poll (`sdk.py:236-237` TODO) vs a long-lived service streaming over websocket/SSE at tens of ms.
- Liveness: box heartbeats via exec; a DO can't exec.
- Reattach by name vs attach by id. Readiness probe vs lease file.

## Where `Machine` (exec/write/read/terminate) fits

Fits: Modal, RunPod, Local batch; the teardown discipline; GPU names (`gpus.py`).

Doesn't fit:
- no port/endpoint primitive (no tunnel, no connect token);
- no per-tenant client/credentials;
- no get-by-name;
- the supervisor must be PID 1, which SF autoresearch forbids;
- file-polled output is too slow for interactive cells;
- the lease holder must be able to exec.

## Colab and SF autoresearch (docs only; no code touches either)

SF autoresearch (`worktrees/blogs-flappy/blogs/notes/research/infra/sfcompute-autoresearch.md`):
- CLI `autor`, env `GMN_*`; MCP, HTTP `/preview` and CLI; auth OAuth 2.1, device code, or `gmnt_` service tokens (90-day default).
- H100 and CPU only; h100-1 $3.96/h; prepaid only.
- Platform owns the entrypoint (box's supervisor can't be PID 1); no SSH; sync commands capped 60 s (MCP) / 300 s (HTTP); logs polled by offset, not streamed; 60 calls/min; idle nodes stop after 15-20 min; jobs max 12 h.
- Plus: `expose_port` gives a token-gated, expiring HTTPS URL that passes WebSocket/SSE — suits browsers.
- Sandboxes are microVMs that fork in ~10 ms (skimmed only). Unknown: whether nodes take labels.
- Prior conclusions: it "could be a box provider (H100 only; it owns the entrypoint)" (blogs HANDOFF); it can only be a provider under box, never the reverse (`blogs/notes/design-discussion.md:90`).

Colab (`.../infra/colab-architecture.md`):
- Jupyter protocol over websocket via Google's `/tun/m/` proxy, short-lived `X-Colab-Runtime-Proxy-Token` that must be refreshed.
- Allocation via beta `colaboratory.googleapis.com/v1beta` (create runtime = long-running op), known only from the VS Code extension.
- Free VMs ~12 h, Pro+ ~24 h; no kernel checkpointing.
- ToS bans SSH, proxies and "bypassing the notebook UI": likely rules it out as an exec provider. At most an interactive-kernel backend.

## Contradiction to settle first

- modal-spike: an open Jupyter websocket kept the sandbox alive until its hard timeout (418 s); idle/closed died at ~60-96 s (`.evidence/modal-spike/probe_keepalive.log`).
- gpu-session: Modal's `idle_timeout` ignored the open connect-token websocket.
- Untested guess: transport differs (`encrypted_ports` tunnel vs connect-token proxy). Settle before relying on `idle_timeout`.

## Papercuts

- `box.deadline` label is stamped before boot, so a slow boot makes it read early (`sdk.py:86-88`).
- Unpinned Modal region landed in Tokyo once (330 s boot, ~390 ms/exec); provider default is unpinned, only tests pin `region="us"` (`modal_provider.py:28`).
- Volumes aren't in box's model, so kelpie talks to Modal directly (`dev/gc.py:10`, `doctor.py:49-51, 264+`).
- Untested: RunPod's normal self-delete path (`runpod_provider.py:32-34`); robots on GPU; cross-workspace billing; the L4 hang (`modal_provider.py:126` TODO).
- Stale docs: root `NOTES-box.md` describes pre-b089bd0f; kelpie docs reference deleted `box/providers/modal.py`, `box/kelpie/` (`kelpie/docs-audit-2026-09-26.md:385`).
- spike-modal REPORT.md never written; its numbers live only in blogs HANDOFF and `.evidence/`.
- Modal tokens have no sandbox-only scope: a pasted reader token can do anything in that workspace (`vmux-modal-auth.md`).

## Decided with the author (2026-10-09)

- **One SDK, two clients.** The box Python SDK is the only way to get a session. The CLI is sugar over it (you on the laptop); the blogs relay calls the same SDK on behalf of a reader in the browser.
- **Credentials are an explicit argument everywhere**, e.g. `Modal(token=...)`, even when the value comes from `~/.modal.toml`. No ambient lookups inside providers.
- **Option 1 + (a) + (b): the machine is the session.**
  - The supervisor on the machine stays the single source of truth (jobs, logs, lease, deadline). Fail-stop: a session dies with its machine.
  - (a) Anything in front of it (a Durable Object, a relay) is only a rebuildable fan-out for live logs. It never owns the lease or deadline and never stores a reader token.
  - (b) The supervisor also writes status + logs to durable storage (Modal volume / object storage), so a dead machine is still inspectable. Recovery is an explicit "new session from what was recorded", never automatic replay.
  - Why: ~/dotfiles/docs lean this way (Goedecke "minimise stateful components", "one owner per state", "caches are state"; telos "no new daemon without a concrete failure mode"; Tiger Style fail-stop). The gaps they expose in today's box are telos "durable, inspectable authority" and structured concurrency's "awaitable terminal state", which (b) and `wait()` close.
- **Two-way door, kept open by:** sessions get their own id (not the Modal sandbox id, even if 1:1 today); every caller goes through the SDK, never supervisor files; the persisted status/log format stays small; don't promise readers "we never store your token" in prose.
- **Durable-Object-as-session (vmux style) is deferred** until a concrete failure earns it, e.g. machine loss mid-run being common and costly. It would also need idempotent job ids and storing the reader's token.

Starting scope for the box session:
```
Session                                  # own id; same API for CLI and relay
  status() -> Running | Ended(reason)
  logs(follow=True)                      # polling today; push later without API change
  wait() -> Ending                       # awaitable terminal state
+ expose(port) -> Endpoint               # NEW: token-gated URL (Modal tunnel / connect token), for kernels + previews
Provider(..., token=...)                 # NEW: explicit credentials
+ supervisor: status + logs -> durable storage   # NEW: (b)
```
First customer: `<nn-fit>` "run bigger" (streams a loss curve back; no C build, low stakes). Pick a dataset that needs a GPU (mod-arithmetic grokking or CIFAR) if the slice should also prove the GPU path. The in-browser widget stays the default.

## vmux (a friend's tool) for comparison

`vmux exec --create --gpu H100 "cmd"`; later calls by job id hit the same sandbox; a Cloudflare Durable Object per session holds canonical state + a log ring buffer + a token-gated preview proxy; `vmux claude install` gives Claude/Codex a skill to grep logs and send commands; real shell attach; runs on vmux's own Modal account with GitHub sign-in. Our gaps vs it: push streaming, preview URLs (`expose`), shell attach, an agent skill, explicit credentials. Deliberate differences: the reader's own workspace and token (not ours), and the machine (not a DO) owns the session.

## Still open

1. Has losing a machine mid-run (and its logs) actually hurt? Decides whether a DO-owned session is ever earned.
2. Colab: a backend readers connect to (free GPU), or the experience to copy?
3. SF autoresearch owns the entrypoint and is H100-only. Is a provider that supports only part of the interface acceptable?
4. The websocket keep-alive contradiction above: settle before relying on `idle_timeout` for browser sessions.
