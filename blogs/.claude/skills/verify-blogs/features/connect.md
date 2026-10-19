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

- **Fast tier.** `vb drive connect` (`uv run --with playwright replay.py fast`, ~15 s). Recorded streams (`fixtures/replay/*.jsonl`) replayed into the built pages with the gateway, the SSE stream and the kernel stubbed at the network boundary: bad token, connect with the drawer, Stop, reload reattach, disconnect + sign out, the session-length form, extend, run-out, every ended reason's message, a status without `lease_until`, phone/dark, axe; workspace cells (queued run, compile-error link, pass, reload, Stop, Python); ch01's shared doc; nn-fit remote runs.
- **Slow tier.** `vb drive slow` (`replay.py slow`, ~40 s): one local relay (`--lease-default-s 20 --ceiling-s 35`), one CPU session, the same flows for real, then the lease runs out; asserts cleanup and diffs the streams against the fixtures (`replay.py slow --record` re-records).
- **Proof.** Transcript lines `ok   ...`; screenshots and the slow tier's recording in `.evidence/replay/`.

Modal (real GPU; not driven by `vb`; costs money). Only when a change touches the gateway contract or remote behaviour, and with the author's OK:

- **Relay.** The relay is `box/examples/notebook-gateway/relay.py` (contract `box/CONTRACT-gateway.md`; variant A: stateless relay over the box SDK, the machine owns the session): `cd box && uv run python examples/notebook-gateway/relay.py --port <free> --gpus T4 --label box.purpose=reader-path-dev`. Never reuse the author's relay on `:8790` (tmux `reader-path`).
- **Drive.** `MODAL_TOKEN_ID=... MODAL_TOKEN_SECRET=... uv run --with playwright replay.py slow --gateway http://127.0.0.1:<relay port>` (start the relay with `--lease-min-s 2 --lease-default-s 20 --lease-max-s 60 --ceiling-s 60 --idle-timeout-s 60`; T4: `!nvidia-smi` and grokking checked); the recorded tour: `demo_tour.py --gateway URL`; ch01 on a T4: `verify_modal_ch01.py`.
- **Cost and teardown.** ~$0.19-0.38/h for a T4 sandbox; a first connect in a workspace builds the image (1-3 min). The harnesses Disconnect at the end (`demo_tour.py` also ends a session left by a failed run). Afterwards confirm nothing runs: `uv run --frozen --project box box who` (list) and `box kill <id>` for any sandbox you started; Modal's `idle_timeout` reaps a closed tab, but an open websocket keeps a sandbox alive.

## Gotchas

- `replay.py` and `demo_tour.py` rebuild `dist/neural-nets` with the default `--gateway-url` (`:8790`, the author's real relay). The page prefers `?gateway=`, so the harnesses are safe, but a hand-opened `/neural-nets/` without `?gateway=` after them would talk to the real relay. `vb drive connect` rebuilds with our gateway afterwards; doctor WARNs if it's stale.
- Sessions outlive the relay process (the machine owns the session): `vb cleanup` ends every session in the run's machines dir through the relay (`POST /end`) before it TERMs the relay's process group, then removes the dir. A hard-killed run leaves local supervisors running until their idle timeout (5 min) or lease.
