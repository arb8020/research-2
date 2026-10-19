# Connect

A page with `<!-- page: connect -->` (today `dl/neural-nets.md`) has a Connect pill in the top-right corner. The reader pastes a Modal token, picks a GPU, and connects: a gateway boots a machine running Jupyter Server, the page attaches to its kernel, and scratch cells (and nn-fit's remote backend) run there. Locally the gateway is `connect_dev.py`: the same HTTP contract, a real local Jupyter Server and kernel, no cloud, and a `nvidia-smi` that prints a table labelled FAKE.

## Sub-features

- `connect-disconnected` shows the pill `Connect`; the scratch cell's Run is disabled and `Connect to run` opens the panel.
- `connect-panel` focuses `input[name=token-id]`; Modal is selectable, RunPod disabled (`soon`); GPU select `select[name=gpu]` (none, T4, L4, A10G).
- `connect-bad-token` a token the gateway rejects ends the boot: `connect-pill[data-failed]`, panel `.connect-failure` reads `Last attempt: the machine failed to start (see Details)`.
- `connect-boot` pill `connecting…`, the Details drawer (`.connect-drawer`, `.drawer-log li`, `.drawer-follow`) streams gateway/machine steps; ends `connect-pill[data-phase=connected]`, label `T4 · <1m`.
- `connect-scratch` the ```` ```python scratch ```` cell runs on the kernel (`!nvidia-smi`), status `done (0.35s)`.
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

- `vb doctor` reports ok (connect_dev.py on the run's gateway port answers `GET /sessions/none` with 404).
- A fresh browser context (Playwright's default): no saved `connect.*` keys.

- **Bad token.** Run `vb drive connect` (step 1: `pages.py bad-token`). Fill `not-a-modal-token` / `nope`, click `.connect-go`. `connect-pill[data-failed]`; reopening the pill shows `failed to start` in `.connect-failure`. Screenshots `connect/bad-token-panel.png`, `connect/bad-token-failed.png`.
- **Connect, run, stop, reload, end.** Same drive, step 2: `MODAL_TOKEN_ID=ak-verify-blogs MODAL_TOKEN_SECRET=... uv run --with playwright verify_connect.py --gateway <ours> --page-port <free>`. Transcript lines: `connected: pill 'T4 · <1m', drawer N lines`, `nvidia-smi: 'done (...)', 13 lines (FAKE)`, `stop: 'KeyboardInterrupt (...)'`, `reload: reattached to fake-xxxx, same kernel (kernel pid N)`, `disconnect + sign out: token was shown as 'ak-…logs', now forgotten`, `phone (dark): ...no sideways scroll`, `axe: ... clean in classic/paper x light/dark`.
- **Proof.** `connect/1-disconnected.png` … `9-disconnected-token-saved.png`, `connect/connect.mp4` (the story as a video), phone-*.png, `connect/transcript.txt` ending `== connect: PASS`; the gateway's own log (every POST/GET, Jupyter stderr) in `logs/gateway.log`.

Modal (real GPU; not driven by `vb`; costs money). Only when a change touches the gateway contract or remote behaviour, and with the author's OK:

- **Relay.** The relay is `box/examples/notebook-gateway/relay.py` (contract `box/CONTRACT-gateway.md`; variant A: stateless relay over the box SDK, the machine owns the session): `cd box && uv run python examples/notebook-gateway/relay.py --port <free> --gpus T4 --label box.purpose=reader-path-dev`. Never reuse the author's relay on `:8790` (tmux `reader-path`).
- **Drive.** `MODAL_TOKEN_ID=... MODAL_TOKEN_SECRET=... uv run --with playwright verify_connect.py --gateway http://127.0.0.1:<relay port> --page-port <free>` (no bad-token case; label `T4 · <1m`, nvidia-smi without FAKE). nn-fit on a T4: `remote_e2e.py --gateway URL [--case grok]`; the recorded tour: `demo_tour.py --gateway URL`.
- **Cost and teardown.** ~$0.19-0.38/h for a T4 sandbox; a first connect in a workspace builds the image (1-3 min). The harnesses Disconnect at the end (`demo_tour.py` also ends a session left by a failed run). Afterwards confirm nothing runs: `uv run --frozen --project box box who` (list) and `box kill <id>` for any sandbox you started; Modal's `idle_timeout` reaps a closed tab, but an open websocket keeps a sandbox alive.

## Gotchas

- Always pass `--page-port` to `verify_connect.py`: its default is `8012`, the author's `reader-path` page port (binding `127.0.0.1:8012` next to their `*:8012` can succeed and steal traffic). Its default `--gateway-port 8791` is free today but not reserved.
- `verify_connect.py`, `remote_e2e.py` and `demo_tour.py` rebuild `dist/neural-nets` with the default `--gateway-url` (`:8790`, the author's real relay, which reaches Modal). The page prefers `?gateway=`, so the harnesses are safe, but a hand-opened `/neural-nets/` without `?gateway=` after them would talk to the real relay. `vb drive connect` rebuilds with our gateway afterwards; doctor WARNs if it's stale.
- `verify_connect.py --gateway` skips its own bad-token case and takes the token from `MODAL_TOKEN_ID`/`MODAL_TOKEN_SECRET`; `vb` sets a fake `ak-` token, which connect_dev boots. Without `--gateway` it starts its own connect_dev (needs both port flags).
- `verify_connect.py` deletes `.evidence/verify_connect/` at start; `vb` copies it out after.
- connect_dev.py holds at most 32 sessions; restart it (`vb cleanup && vb launch`) after many runs. Ended sessions stop their Jupyter Server; `vb cleanup` TERMs connect_dev's whole process group, which ends the rest.
- The FAKE nvidia-smi table says `Tesla T4` whatever GPU was picked; the label in the pill is the picked GPU.
- Each Jupyter Server root dir is a temp dir removed when its session ends; a hard-killed connect_dev can orphan Jupyter servers (two from older runs were seen on 2026-10-09, not started by `vb`; leave others' processes alone).
