# Checked cells (flappy)

A reader edits a code cell in `rl/01-flappy.md`'s page, clicks Run, and the session runs the hidden check against it: the output streams in, the status line says pass or why it failed, a pass unlocks the next cell, later cells use the reader's latest passing version, and a reload restores the last passing code. The C cell's pass also rebuilds the play widget from the reader's env.

## Sub-features

- `cells-run` streams output into `.cell-out` and ends `.pass` or `.fail` with a one-line `.cell-status`.
- `cells-fail` reports a check failure, a sanitizer report (segfault), and a timeout (infinite loop, `--timeout 20`) without killing the session.
- `cells-gate` locks cell N (`code-cell.locked`, Run disabled, status `locked until X passes`) until N-1 passes; code stays editable.
- `cells-propagate` makes later cells use the latest *passing* upstream version; a failing upstream edit doesn't propagate.
- `cells-restore` on reload puts the last passing source back in each editor (status `passed (your last passing version, restored)`); unpassed edits are lost.
- `cells-play` swaps `<env-play>` from the reference env to the reader's passing env (caption `playing: your env (latest passing version)`).

## How to get to it (user POV)

- Open `http://127.0.0.1:<static>/01-flappy/` (from `vb launch`), scroll to the `flappy · c` cell, edit, click `Run`.
- The cell order is `flappy`, `policy`, `sample`, `logprob`, `loss`, `train`; only `flappy` is unlocked on a fresh session.

## Driving it with vb

Preconditions:

- `vb doctor` reports ok; the session's `/state` shows `passed: []` (a fresh reader). `vb drive cells` deletes this run's `.session/01-flappy/` first; it refuses if the state isn't this run's.
- `dist/01-flappy` and `dist/neural-nets` are built (verify_page.py also drives the nn-fit and link cases on neural-nets).

- **Locked on arrival.** Open the page. Run `vb drive cells` (`uv run --with playwright verify_page.py http://127.0.0.1:<static>/01-flappy/`). `page: policy locked = True` (`code-cell[name="policy"] .run` disabled).
- **Stub fails.** Click `code-cell[name="flappy"] .run` on the stub. `run flappy: ... -> FAIL` with an `AssertionError` reason in `.cell-status`; `.cell-out.fail`.
- **Solution passes.** Replace the editor contents with the hidden `solution=flappy` and Run. `run flappy: ... -> PASS | status: 'passed'`; `code-cell[name="policy"]` loses `.locked`.
- **Gating.** Run `policy` with its stub (`FAIL: NotImplementedError`), then with a working policy (PASS). `sample unlocked: True`.
- **Play widget.** After the flappy pass, `env-play iframe` src points at `<session>/wasm/<hash>/flappy.js`; caption `playing: your env (latest passing version)`.
- **Crash and hang.** Paste a null write (`volatile int *p = 0; *p = 1;`) at `// increment env by a tick` and Run: status `the sanitizer stopped your C ...; later cells keep using your last passing version`, and `policy` still passes. Paste `while (1) {}`: `killed after 20s: an infinite loop, or just too slow?`.
- **Reload.** Reload the page. `after reload: flappy editor restored to last passing = True | sample unlocked, loss locked = True`.
- **Side effect.** The drive saves `GET <session>/state` to `cells/state-after.json`; `passed` contains `flappy` and `policy`.
- **Proof.** `cells/*.png` (copied from `.evidence/verify_page/`: `1-flappy-stub-fails.png`, `2-flappy-passes.png`, `3-policy-*.png`, `4-play-your-env.png`, `5-flappy-segfault.png`, nn-fit and link-card shots), `cells/state-after.json`, `cells/transcript.txt` ending `== cells: PASS`.

## Gotchas

- verify_page.py puts code in the editor with `view.dispatch(...)` (the CodeMirror state a typed edit produces), not keystrokes; it asserts `.session/01-flappy/state.json` does not exist at start, so it only runs on a fresh reader.
- A reload restores only the last *passing* source (an open product question, HANDOFF "Page builder (5)"); don't report lost unpassed edits as a regression.
- C runs are slow on the first pass (ASan build + prod build + emcc for the play widget, ~10-20 s); the hang case waits the full `--timeout 20`. The whole drive takes ~75 s.
- session.py serves one chapter (`rl/01-flappy.md`); neural-nets and 00-plan never call it (page.ts only talks to the session when the page has `code-cell` or `env-play`).
- The page reads the session URL from `<meta name="session-url">` (baked at build) or `?session=`; a page built without `--session-url` talks to the author's `:8787`. Doctor checks the served meta.
- The flappy play iframe takes keyboard focus on load (seen headless): key presses go to the game until the reader clicks the page.
