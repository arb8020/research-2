# Connect

A page with `<!-- page: connect -->` (today `dl/neural-nets.md`) has a Connect pill in the top-right corner. The reader pastes a Modal token, picks a GPU, and connects: a gateway boots a machine running Jupyter Server, the page attaches to its kernel, and scratch cells (and nn-fit's remote backend) run there. Locally the gateway is box's relay with `--provider local`: the same relay and contract, a real local Jupyter Server and kernel per session, no cloud, CPU only (the GPU select offers what `GET /limits` lists: just CPU).

## Sub-features

- `connect-disconnected` shows the pill `Connect`; the scratch cell's Run is disabled and `Connect to run` opens the panel.
- `connect-panel` focuses `input[name=token-id]`; Modal is selectable, RunPod disabled (`soon`); GPU select `select[name=gpu]` (the gateway's `/limits` GPUs: T4, L4, A10G, CPU; locally CPU only).
- `connect-bad-token` a token the gateway rejects ends the boot: `connect-pill[data-failed]`, panel `.connect-failure` reads `Last attempt: the machine failed to start (see Details)`.
- `connect-boot` pill `connecting…`, the Details drawer (`.connect-drawer`, `.drawer-log li`, `.drawer-follow`) streams gateway/machine steps; ends `connect-pill[data-phase=connected]`, label `CPU · 1h 29m left` (locally).
- `connect-scratch` the ```` ```python scratch ```` cell runs on the kernel (`!nvidia-smi` on a GPU), status `done (0.35s)`.
- `connect-interrupt` while a scratch cell runs, its Run button reads `Stop`; clicking it interrupts the kernel: `.cell-out.fail`, status `KeyboardInterrupt (...)`.
- `connect-reattach` a reload reattaches to the same session and kernel (same `os.getpid()`), no second `POST /sessions`; `localStorage['connect.session']` holds `{gateway, session_id, provider, gpu}`.
- `connect-end` `.connect-end` (Disconnect) ends the session (pill `data-phase=disconnected`, `connect.session` cleared); the token stays, masked (`.connect-token-mask`, `ak-…xxxx`); `.connect-forget` (Sign out) deletes `connect.token.modal`.
- `connect-modal` the real path: the page -> the box relay (Modal web endpoint or local `box/examples/notebook-gateway/relay.py`) -> a Modal sandbox running Jupyter -> the browser talks to the kernel over the sandbox tunnel directly.

## How to get to it (user POV)

- Open `/neural-nets/?gateway=<gateway URL>` (or a page built with `--gateway-url`), click `Connect` (top right) or the scratch cell's `Connect to run`.
- Paste a token (locally: any id starting `ak-` boots; any other id fails), pick a GPU, click `Connect`.
- After connecting: edit/Run the scratch cell under the nn-fit widget; the pill menu has Details, Disconnect, Sign out.

## Driving it with vb

Preconditions:

- `vb doctor` reports ok (the relay on the run's gateway port answers `GET /limits`).
- A fresh browser context (Playwright's default): no saved `connect.*` keys.

- **Connect, run, stop, reload, end.** `vb drive connect`: `MODAL_TOKEN_ID=ak-verify-blogs MODAL_TOKEN_SECRET=... uv run --with playwright verify_connect.py --gateway <ours> --page-port <free>`. Transcript lines: `bad token: 'Last attempt: the machine failed to start (see Details)'`, `connected: pill 'CPU · 1h 29m left', drawer N lines`, `stop: 'KeyboardInterrupt (...)'`, `reload: reattached to s-xxxxxxxxxxxx, same kernel (kernel pid N)`, `disconnect + sign out: token was shown as 'ak-…logs', now forgotten`, `lease ran out (20 s, ...)`, `phone (dark): ...no sideways scroll`, `axe: ... clean in classic/paper x light/dark`.
- **Proof.** `connect/1-disconnected.png` … `9-disconnected-token-saved.png`, `connect/connect.mp4` (the story as a video), phone-*.png, `connect/transcript.txt` ending `== connect: PASS`; the gateway's own log (every POST/GET, Jupyter stderr) in `logs/gateway.log`.

Modal (real GPU; not driven by `vb`; costs money). Only when a change touches the gateway contract or remote behaviour, and with the author's OK:

- **Relay.** The relay is `box/examples/notebook-gateway/relay.py` (contract `box/CONTRACT-gateway.md`; variant A: stateless relay over the box SDK, the machine owns the session): `cd box && uv run python examples/notebook-gateway/relay.py --port <free> --gpus T4 --label box.purpose=reader-path-dev`. Never reuse the author's relay on `:8790` (tmux `reader-path`).
- **Drive.** `MODAL_TOKEN_ID=... MODAL_TOKEN_SECRET=... uv run --with playwright verify_connect.py --gateway http://127.0.0.1:<relay port> --page-port <free>` (the gateway offers T4: no bad-token or lease run-out case; label `T4 · …`, `!nvidia-smi` checked). nn-fit on a T4: `remote_e2e.py --gateway URL [--case grok]`; the recorded tour: `demo_tour.py --gateway URL`.
- **Cost and teardown.** ~$0.19-0.38/h for a T4 sandbox; a first connect in a workspace builds the image (1-3 min). The harnesses Disconnect at the end (`demo_tour.py` also ends a session left by a failed run). Afterwards confirm nothing runs: `uv run --frozen --project box box who` (list) and `box kill <id>` for any sandbox you started; Modal's `idle_timeout` reaps a closed tab, but an open websocket keeps a sandbox alive.

## Gotchas

- Always pass `--page-port` to `verify_connect.py`: its default is `8012`, the author's `reader-path` page port (binding `127.0.0.1:8012` next to their `*:8012` can succeed and steal traffic). Its default `--gateway-port 8791` is free today but not reserved.
- `verify_connect.py`, `remote_e2e.py` and `demo_tour.py` rebuild `dist/neural-nets` with the default `--gateway-url` (`:8790`, the author's real relay, which reaches Modal). The page prefers `?gateway=`, so the harnesses are safe, but a hand-opened `/neural-nets/` without `?gateway=` after them would talk to the real relay. `vb drive connect` rebuilds with our gateway afterwards; doctor WARNs if it's stale.
- `verify_connect.py --gateway` takes the token from `MODAL_TOKEN_ID`/`MODAL_TOKEN_SECRET`; `vb` sets a fake `ak-` token, which the local relay boots. A gateway without T4 (local) gets the bad-token and lease run-out cases (the run-out needs `--lease-min-s` <= 20). Without `--gateway` it starts its own local relay (needs both port flags).
- `verify_connect.py` deletes `.evidence/verify_connect/` at start; `vb` copies it out after.
- Sessions outlive the relay process (the machine owns the session): `vb cleanup` ends every session in the run's machines dir through the relay (`POST /end`) before it TERMs the relay's process group, then removes the dir. A hard-killed run leaves local supervisors running until their idle timeout (5 min) or lease.
